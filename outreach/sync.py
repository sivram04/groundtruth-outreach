"""Stage 4 sync: what happened in Gmail after each email, recorded in the Sheet.

Reads the mailbox, never writes to it, and records for each lead:
  SENT        the founder sent the lead an email: one of this system's drafts, or one written
              by hand
  REPLIED     the lead wrote back
  AUTO_REPLY  an automatic answer such as out of office; it stops nothing
  OPT_OUT     the lead asked not to be written to again
  BOUNCED     a delivery failure (DELAYED is a temporary one and stops nothing)
  DRAFTED     an initial draft this system created, taken from the lead row

A message is tied to a lead only when that is certain:
  DRAFT    it is in the thread of this system's initial draft for the lead
  ADDRESS  its address is written on exactly one lead's row
  THREAD   it is in a thread already tied to one lead
A match on the company's domain alone (DOMAIN), or on more than one lead (SEVERAL), is recorded
but is uncertain: it starts no follow-up and the lead reads REVIEW_NEEDED. A personal mailbox
(gmail.com and the like) is never matched by its domain. A message from a lead before anyone
emailed them is not outreach and is not recorded.

Writes, in this order so the part that protects people lands first: bounced and opted-out
addresses to Suppression (the address only, never the whole domain), new rows to the append-only
Events tab, the lead's summary columns, and a Runs row carrying the cursor. Suppression and the
summaries are worked out again from the whole Events history on every run, so a run that stops
half-way is completed by the next one.

    python -m outreach.sync --dry-run      # read everything, print what would be written
    python -m outreach.sync                # write it
"""

import argparse
import json
from collections import Counter, defaultdict
from datetime import datetime, time, timedelta, timezone

from outreach import checks, gmail_drafts, job_draft, mailbox, sequence
from outreach.business_days import NEW_YORK, new_york_date
from outreach.gmail_drafts import ACTION_HEADER
from outreach.sheet import SYNC_COLUMNS, Store, now_utc

SYNC_START = "2026-09-21"  # the day before the first outreach emails (14 sent by hand, 2026-09-22)
OVERLAP = timedelta(days=2)  # each run re-reads two days before the last one stopped
# On a ten-minute schedule most runs find nothing. Such a run writes no Runs row unless the last
# one is this old, so the Runs tab gains a row when something happened and four a day otherwise.
# Six hours is this system's choice: it bounds how much mail a quiet run re-reads (the cursor
# moves only with a Runs row), and it is not a founder decision.
QUIET_RUNS_ROW_EVERY = timedelta(hours=6)
ADDRESS_COLUMNS = ("BEST EMAIL", "Their email", "Finance email", "Emails we already had")
RANK = {"DRAFT": 4, "ADDRESS": 3, "THREAD": 2, "DOMAIN": 1, "SEVERAL": 0}


class SyncBlocked(RuntimeError):
    """Sync cannot run safely; nothing was written."""


def lead_addresses(row):
    text = " ".join(row.get(column, "") for column in ADDRESS_COLUMNS)
    return {address.lower() for address in checks.EMAIL_IN_TEXT.findall(text)}


def company_domain(address):
    """The company part of an address, or '' for a personal mailbox."""
    base = checks.base_domain(checks.domain_of_email(address))
    return "" if base in checks.PERSONAL_MAIL else base


class LeadIndex:
    """Which lead an address, a domain or a thread belongs to."""

    def __init__(self, rows):
        self.rows = rows
        self.by_address, self.by_domain = defaultdict(set), defaultdict(set)
        for lead_id, row in rows.items():
            for address in lead_addresses(row):
                self.by_address[address].add(lead_id)
                if company_domain(address):
                    self.by_domain[company_domain(address)].add(lead_id)
            site = checks.site_domain(row.get("Website", ""))
            if site and checks.base_domain(site) not in checks.PERSONAL_MAIL:
                self.by_domain[checks.base_domain(site)].add(lead_id)
        self.draft_threads = {row["Draft thread ID"]: lead_id for lead_id, row in rows.items()
                              if row.get("Draft thread ID")}
        self.draft_actions = {row["Draft action"]: lead_id for lead_id, row in rows.items()
                              if row.get("Draft action")}
        self.sent_to = defaultdict(set)  # address -> leads emailed at it
        self.threads = {}  # thread -> [(lead, match)]; one entry once a certain match exists
        self.thread_address = {}  # thread -> the address its first recorded email went to

    def learn(self, event):
        """Remember a recorded send, so later replies and bounces find their lead."""
        lead_id, address, thread, match = (event["Lead ID"], event["Address"], event["Thread ID"],
                                           event["Match"])
        if address:
            self.sent_to[address].add(lead_id)
        if not thread:
            return
        current = self.threads.setdefault(thread, [])
        if any(m in sequence.CONFIDENT for _, m in current):
            return
        if match in sequence.CONFIDENT:
            self.threads[thread] = [(lead_id, match)]
        elif (lead_id, match) not in current:
            current.append((lead_id, match))
        self.thread_address.setdefault(thread, address)

    def _in_thread(self, thread):
        return [(lead_id, "THREAD" if match in sequence.CONFIDENT else match)
                for lead_id, match in self.threads.get(thread, [])]

    def _by(self, index, key, single):
        leads = sorted(index.get(key, set())) if key else []
        return [(lead_id, single if len(leads) == 1 else "SEVERAL") for lead_id in leads]

    def match_sent(self, recipient, thread, action):
        lead_id = self.draft_threads.get(thread) or (self.draft_actions.get(action) if action else None)
        if lead_id:
            return [(lead_id, "DRAFT")]
        return (self._by(self.by_address, recipient, "ADDRESS") or self._in_thread(thread)
                or self._by(self.by_domain, company_domain(recipient), "DOMAIN"))

    def match_received(self, sender, thread):
        return (self._in_thread(thread) or self._by(self.by_address, sender, "ADDRESS")
                or self._by(self.by_domain, company_domain(sender), "DOMAIN"))

    def match_bounce(self, failed, in_text, thread):
        """[(lead, match, address that failed)] for a delivery notice."""
        emailed = [a for a in failed if a in self.sent_to] or [a for a in in_text if a in self.sent_to]
        if self.threads.get(thread):
            out = []
            for lead_id, match in self._in_thread(thread):
                address = next((a for a in emailed if lead_id in self.sent_to[a]),
                               self.thread_address.get(thread, ""))
                out.append((lead_id, match, address))
            return out
        out = []
        for address in emailed:
            leads = sorted(self.sent_to[address])
            out += [(lead_id, "ADDRESS" if len(leads) == 1 else "SEVERAL", address) for lead_id in leads]
        return out


def _event(lead_id, kind, step, at, address, match, thread, message_id, detail, key=None):
    return {"Recorded at (UTC)": "", "Lead ID": lead_id, "Event": kind, "Step": step,
            sequence.OCCURRED: at.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "Address": address, "Match": match, "Detail": detail, "Thread ID": thread,
            "Gmail message ID": message_id,
            "Event key": key or f"msg:{message_id}:{lead_id}:{kind}"}


def _stamp(text):
    try:
        moment = datetime.fromisoformat((text or "").replace("Z", "+00:00"))
    except ValueError:
        return None
    return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)


def _emailed_before(events, at):
    return any(e["Event"] == sequence.SENT and sequence.when(e) <= at for e in events)


def unique(events):
    """Each event once, by its key. Two runs at the same moment could both append the same
    event; reading it twice would make it look like two emails."""
    seen, out = set(), []
    for event in events:
        if event.get("Event key") not in seen:
            seen.add(event.get("Event key"))
            out.append(event)
    return out


def plan(gmail, index, events, *, since, sender):
    """New events from the mailbox since `since`. Returns (new events, all events by lead,
    messages read). Messages already in Events are not read again."""
    known = {e["Event key"] for e in events}
    seen = {e["Gmail message ID"] for e in events if e.get("Gmail message ID")}
    by_lead = defaultdict(list)
    for event in events:
        by_lead[event["Lead ID"]].append(event)
        if event["Event"] == sequence.SENT:
            index.learn(event)
    new = []

    def add(event):
        if event["Event key"] in known:
            return
        known.add(event["Event key"])
        new.append(event)
        by_lead[event["Lead ID"]].append(event)
        if event["Event"] == sequence.SENT:
            index.learn(event)

    # This system's own initial drafts, from the lead rows that record them.
    for lead_id, row in sorted(index.rows.items()):
        drafted = _stamp(row.get("Drafted at"))
        if row.get("Draft status") == "CREATED" and row.get("Draft action") and drafted:
            add(_event(lead_id, sequence.DRAFTED, sequence.INITIAL, drafted,
                       row.get("BEST EMAIL", "").strip().lower(), "DRAFT",
                       row.get("Draft thread ID", ""), "", f"draft {row.get('Draft ID', '')}",
                       key=f"draft:{row['Draft action']}"))

    messages = [m for m in (mailbox.get(gmail, message_id)
                            for message_id in mailbox.list_ids(gmail, since)
                            if message_id not in seen) if m]
    messages.sort(key=lambda m: (int(m.get("internalDate", 0)), m["id"]))
    for message in messages:
        at, thread = mailbox.moment(message), message.get("threadId", "")
        if mailbox.is_sent(message):
            best = {}
            for recipient in mailbox.recipients(message):
                if recipient == sender:
                    continue
                for lead_id, match in index.match_sent(recipient, thread,
                                                       mailbox.header(message, ACTION_HEADER)):
                    if lead_id not in best or RANK[match] > RANK[best[lead_id][1]]:
                        best[lead_id] = (recipient, match)
            subject = " ".join(mailbox.header(message, "Subject").split())[:80]
            for lead_id, (address, match) in sorted(best.items()):
                step = (sequence.step_for_send(by_lead[lead_id], thread, at)
                        if match in sequence.CONFIDENT else sequence.UNCONFIRMED)
                add(_event(lead_id, sequence.SENT, step, at, address, match, thread,
                           message["id"], f'subject "{subject}"'))
        elif mailbox.is_bounce_notice(message):
            full = mailbox.get(gmail, message["id"], full=True) or message
            kind, failed, in_text, detail = mailbox.bounce(full)
            for lead_id, match, address in index.match_bounce(failed, in_text, thread):
                if _emailed_before(by_lead[lead_id], at):
                    add(_event(lead_id, kind, "", at, address, match, thread, message["id"], detail))
        else:
            sender_address = mailbox.from_address(message)
            if not sender_address or sender_address == sender:
                continue
            matches = [(lead_id, match) for lead_id, match in
                       index.match_received(sender_address, thread)
                       if _emailed_before(by_lead[lead_id], at)]
            if not matches:
                continue
            full = mailbox.get(gmail, message["id"], full=True) or message
            kind, detail = mailbox.received_kind(full)
            for lead_id, match in matches:
                add(_event(lead_id, kind, "", at, sender_address, match, thread, message["id"],
                           detail))
    return new, by_lead, len(messages)


def on_list(entries, address):
    """True when an address, or its whole domain, is on the Suppression list."""
    address = (address or "").strip().lower()
    if not address:
        return False
    domain = address.rpartition("@")[2]
    for entry in entries:
        value = (entry.get("Address or domain") or "").strip().lower()
        if value and (value == address or ("@" not in value.lstrip("@") and value.lstrip("@") == domain)):
            return True
    return False


def lead_suppressed(entries, row, events):
    """Whether the address a follow-up would go to is on Suppression (or its whole domain is).

    That is the address of the running sequence, not every address the lead ever had: after
    one address bounced, a new one may be written to."""
    running = sequence.current_sequence(events)
    return on_list(entries, running["address"] if running else row.get("BEST EMAIL", ""))


def suppression_rows(events, entries, stamp):
    """Suppression rows still missing for bounced and opted-out addresses in `events`.

    A request to stop covers the address that asked and the address the thread was sent to.
    Never a whole domain: one person's no is not their company's.
    """
    sent_in_thread = defaultdict(set)
    for event in events:
        if event["Event"] == sequence.SENT and event["Thread ID"]:
            sent_in_thread[(event["Lead ID"], event["Thread ID"])].add(event["Address"])
    listed, rows = list(entries), []
    for event in sorted(events, key=sequence._order):
        if event["Event"] not in (sequence.OPT_OUT, sequence.BOUNCED):
            continue
        targets = [event["Address"]]
        if event["Event"] == sequence.OPT_OUT:
            targets += sorted(sent_in_thread[(event["Lead ID"], event["Thread ID"])])
        reason = (f"opted out: {event['Detail']}" if event["Event"] == sequence.OPT_OUT
                  else f"bounced: {event['Detail']}")
        for address in targets:
            if address and not on_list(listed, address):
                row = {"Address or domain": address, "Reason": reason, "Added at": stamp,
                       "Source": f"sync: lead {event['Lead ID']}, Gmail message "
                                 f"{event['Gmail message ID']}"}
                rows.append(row)
                listed.append(row)
    return rows


def drafts_gone(gmail, index, by_lead):
    """Which of this system's unsent drafts are no longer in Gmail: {lead: {kind: bool}}."""
    gone = {}
    for lead_id, row in sorted(index.rows.items()):
        sends = [e for e in by_lead.get(lead_id, []) if e["Event"] == sequence.SENT]
        flags = {}
        if row.get("Draft status") == "CREATED" and row.get("Draft ID") and not sends:
            flags["initial"] = not mailbox.draft_exists(gmail, row["Draft ID"])
        step = row.get("Follow-up step", "")
        if (row.get("Follow-up status") == "CREATED" and row.get("Follow-up draft ID")
                and not any(e["Step"] == f"FOLLOWUP_{step}" for e in sends)):
            flags["followup"] = not mailbox.draft_exists(gmail, row["Follow-up draft ID"])
        if flags:
            gone[lead_id] = flags
    return gone


def summaries(rows, by_lead, entries, today, gone=None):
    """The summary columns that differ from what the lead row shows now: {lead: {column: value}}."""
    gone = gone or {}
    updates = {}
    for lead_id, row in sorted(rows.items()):
        events = by_lead.get(lead_id, [])
        if not events and not any(row.get(column) for column in SYNC_COLUMNS):
            continue
        state = sequence.lead_state(row, events, suppressed=lead_suppressed(entries, row, events),
                                    today=today, draft_gone=gone.get(lead_id))
        changed = {column: value for column, value in state["cells"].items()
                   if row.get(column, "") != value}
        if changed:
            updates[lead_id] = changed
    return updates


def start_of(settings):
    day = datetime.fromisoformat(str(settings.get("sync_start_date") or SYNC_START)).date()
    return datetime.combine(day, time(0, 0), NEW_YORK).astimezone(timezone.utc)


def _iso(moment):
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def run(where="local", *, dry_run=False, store=None, gmail=None, settings=None, now=None):
    now = now or datetime.now(timezone.utc)
    settings = job_draft.load_settings() if settings is None else settings
    store = store or Store()
    gmail = gmail or gmail_drafts.client()
    address = gmail.users().getProfile(userId="me").execute().get("emailAddress", "").lower()
    expected = str(settings.get("sender_email", "")).strip().lower()
    if expected and address != expected:
        raise SyncBlocked(f"the signed-in mailbox {address} is not the configured sender {expected}")

    start = start_of(settings)
    cursor = store.last_cursor()
    since = max(start, cursor - OVERLAP) if cursor else start
    index = LeadIndex(store.leads())
    events = unique(store.events())
    entries = store.suppression()
    new, by_lead, read = plan(gmail, index, events, since=since, sender=address)
    gone = drafts_gone(gmail, index, by_lead)
    stamp = now_utc()
    suppress = suppression_rows(events + new, entries or [], stamp)
    updates = summaries(index.rows, by_lead, (entries or []) + suppress, new_york_date(now), gone)
    report = {"dry_run": dry_run, "mailbox": address, "read_since": _iso(since),
              "messages_read": read, "new_events": dict(Counter(e["Event"] for e in new)),
              "events": new, "suppression": suppress, "lead_updates": updates, "cursor": _iso(now)}
    if dry_run:
        return report
    if not (new or suppress or updates) and cursor and now - cursor < QUIET_RUNS_ROW_EVERY:
        # Nothing happened: the Sheet is left alone. The cursor stays where it was, so the next
        # run reads a little more mail again, and skips what it has already recorded.
        report.update(written=0, skipped=[], runs_row=False)
        return report

    for event in new:
        event["Recorded at (UTC)"] = stamp
    store.append_suppression(suppress)
    store.append_events(new)
    written, skipped = store.write_leads(updates, SYNC_COLUMNS)
    counts = ", ".join(f"{kind} {n}" for kind, n in sorted(report["new_events"].items())) or "none"
    detail = (f"read {read} messages since {_iso(since)}; new events: {counts}; "
              f"suppressed {len(suppress)}; lead rows updated {written}")
    if skipped:
        detail += f"; skipped {len(skipped)} rows that changed during the run: " + "; ".join(skipped[:5])
    store.run_row("sync", where, "PARTIAL" if skipped else "OK", f"{detail}; cursor {_iso(now)}")
    report.update(written=written, skipped=skipped, runs_row=True)
    return report


def main():
    parser = argparse.ArgumentParser(description="Record what happened in Gmail; never sends")
    parser.add_argument("--dry-run", action="store_true", help="read only; print what would change")
    args = parser.parse_args()
    print(json.dumps(run(dry_run=args.dry_run), indent=2, default=str))


if __name__ == "__main__":
    main()
