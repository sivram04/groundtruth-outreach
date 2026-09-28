"""Stage 5: queued tracker hits become OPEN and CLICK events, and each lead's counts.

Every genuine hit is recorded with the moment it happened, even one before the email was sent
(the founder looking at the draft). Whether it counts is decided when the lead's figures are
worked out (`sequence.tracking_cells`), because sync may record the send a few minutes after a
hit arrives: deciding here would lose those hits.

A hit is tied to a lead through its draft ID: the lead rows (`Draft action`, `Follow-up
action`) and the drafted events in Events (`draft:`, `followup:`, and `test:` for the pass-test
draft, lead TEST). A hit for no known draft is still recorded, with no lead, rather than lost.

Not recorded again: a hit already recorded (the queue may deliver twice), and a hit for the same
draft, kind and link within a minute of one already recorded (image caches and scanners fire in
bursts; a minute is this system's choice). A hit whose signature fails is dropped. Queue messages
are acknowledged only after the Sheet has them, so a failed run loses nothing.

    python -m outreach.tracking_job     # run once
"""

import json
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone

from outreach import pubsub, sequence, sync, tracking
from outreach.sheet import TRACKING_COLUMNS, Store

TEST_LEAD = "TEST"
BURST = timedelta(minutes=1)
PULL_ROUNDS = 5  # pulls per run; a pull returns at most 100 hits


def actions(rows, events):
    """{draft ID: (lead, step)} from the lead rows and the drafted events."""
    found = {}
    for lead_id, row in rows.items():
        if row.get("Draft action"):
            found[row["Draft action"]] = (lead_id, sequence.INITIAL)
        step = row.get("Follow-up step", "")
        if row.get("Follow-up action") and step in ("1", "2"):
            found[row["Follow-up action"]] = (lead_id, sequence.FOLLOWUPS[int(step) - 1])
    for event in events:
        kind, _, action = event.get("Event key", "").partition(":")
        if kind == "draft":
            found.setdefault(action, (event["Lead ID"], sequence.INITIAL))
        elif kind == "followup":
            found.setdefault(action, (event["Lead ID"], event["Step"]))
        elif kind == "test":
            found.setdefault(action, (TEST_LEAD, "TEST"))
    return found


def client(agent):
    """What the mail program says it is, where that says something useful."""
    agent = agent or ""
    if "GoogleImageProxy" in agent:
        return "Google image proxy"
    if "YahooMailProxy" in agent:
        return "Yahoo image proxy"
    if "Microsoft Outlook" in agent or "ms-office" in agent.lower():
        return "Outlook"
    return ""


def _burst_key(event):
    parts = event["Detail"].split(", ")
    return (parts[0], event["Event"], next((p for p in parts if p.startswith("link ")), ""))


def hit_event(hit, payload, lead_id, step):
    kind = sequence.OPEN if payload["k"] == tracking.OPEN else sequence.CLICK
    detail = [f"draft {payload['a']}"]
    if kind == sequence.CLICK:
        detail.append(f"link {payload['l']}")
    if hit.get("method") == "HEAD":
        detail.append(sequence.HEAD)
    if client(hit.get("agent")):
        detail.append(client(hit.get("agent")))
    at = datetime.fromisoformat(hit["at"].replace("Z", "+00:00"))
    return sync._event(lead_id, kind, step, at, "", "TRACKER", "", "", ", ".join(detail),
                       key=f"hit:{hit['hit']}")


def plan(messages, secret, rows, events):
    """(new events, dropped count) for pulled messages [(ack id, data)]."""
    known = {e["Event key"] for e in events}
    drafts = actions(rows, events)
    recent = defaultdict(list)  # burst key -> times recorded
    for event in events:
        if event["Event"] in (sequence.OPEN, sequence.CLICK):
            recent[_burst_key(event)].append(sequence.when(event))
    new, dropped = [], 0
    hits = [data for _, data in messages]
    for hit in sorted((h for h in hits if isinstance(h, dict)), key=lambda h: str(h.get("at", ""))):
        payload = tracking.verify(str(hit.get("token", "")), secret)
        if not payload or not hit.get("hit") or not hit.get("at"):
            dropped += 1
            continue
        lead_id, step = drafts.get(payload["a"], ("", ""))
        try:
            event = hit_event(hit, payload, lead_id, step)
        except ValueError:
            dropped += 1
            continue
        if event["Event key"] in known:
            continue
        at, key = sequence.when(event), _burst_key(event)
        if any(abs(at - earlier) < BURST for earlier in recent[key]):
            continue
        known.add(event["Event key"])
        recent[key].append(at)
        new.append(event)
    dropped += sum(1 for h in hits if not isinstance(h, dict))
    return new, dropped


def run(where="local", *, store=None, queue=None, secret=None, now=None):
    now = now or datetime.now(timezone.utc)
    queue = queue or pubsub.Queue()
    messages = []
    for _ in range(PULL_ROUNDS):
        batch = queue.pull(100)
        if not batch:
            break
        messages += batch
    report = {"pulled": len(messages), "recorded": {}, "dropped": 0, "lead_updates": {}}
    if not messages:
        return report
    secret = secret or tracking.key()
    store = store or Store()
    rows, events = store.leads(), sync.unique(store.events())
    new, dropped = plan(messages, secret, rows, events)
    by_lead = defaultdict(list)
    for event in events + new:
        by_lead[event["Lead ID"]].append(event)
    touched = {e["Lead ID"] for e in new if e["Lead ID"] in rows}
    updates = {}
    for lead_id in sorted(touched):
        cells = sequence.tracking_cells(by_lead[lead_id])
        changed = {c: v for c, v in cells.items() if rows[lead_id].get(c, "") != v}
        if changed:
            updates[lead_id] = changed
    stamp = now.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    for event in new:
        event["Recorded at (UTC)"] = stamp
    store.append_events(new)
    written, skipped = store.write_leads(updates, TRACKING_COLUMNS) if updates else (0, [])
    queue.ack([ack for ack, _ in messages])
    report.update(recorded=dict(Counter(e["Event"] for e in new)), dropped=dropped,
                  lead_updates=updates, written=written, skipped=skipped)
    if new or dropped:
        counts = ", ".join(f"{k} {n}" for k, n in sorted(report["recorded"].items())) or "none"
        store.run_row("tracking", where, "PARTIAL" if skipped else "OK",
                      f"pulled {len(messages)} hits; recorded: {counts}; dropped {dropped}; "
                      f"lead rows updated {written}")
    return report


if __name__ == "__main__":
    print(json.dumps(run(), indent=2, default=str))
