"""Stage 4 follow-up drafts, in the founder's own words from the Drive handbook.

The wording is the handbook's "Follow-up 1" and "Follow-up 2" templates, filled with the offer
values written in the same document ("[NEXT_WEEK_ACTION]: ..."). No model writes or rewrites
them. The greeting, signature, postal address and opt-out line are added here, exactly as for
the initial email. A follow-up goes into the thread of the email it follows, to the address that
email actually went to, under the same subject.

Founder decisions, 2026-09-28:
- only a sequence whose initial email was one of this system's drafts gets follow-up drafts;
  a thread the founder started by hand gets a reminder in Next action and never a draft;
- the follow-up wording is approved once per handbook version: `followup_approved_handbook_hash`
  in the settings must equal the Drive document's current content hash, so any edit to the
  document withdraws the approval until the founder reads the wording and approves it again.

Every guard of the initial draft still applies: ENABLE_GMAIL_DRAFTS, the offer approval, one
daily cap shared with initial drafts, the signed-in mailbox, a reservation in the Sheet before
the Gmail write, no retry after an uncertain result, and no draft where one already sits in the
thread. Nothing here sends.

    python -m outreach.followup --preview     # both follow-ups as they would read, and the hash
    python -m outreach.followup --dry-run     # which leads are due, and what blocks drafting
"""

import argparse
import hashlib
import json
import os
import re
from collections import defaultdict
from datetime import datetime, timezone

from outreach import drafting, gmail_drafts, job_draft, mailbox, sequence, sync
from outreach.business_days import new_york_date
from outreach.sheet import FOLLOWUP_COLUMNS, Store

APPROVAL_KEY = "followup_approved_handbook_hash"
# A heading line, as Markdown or as a Google Doc exports it: "## Follow-up 1", "Follow-up 2".
HEADING = re.compile(r"^\s*#*\s*follow[\s-]*up\s*([12])\s*(?:[-–—:(].{0,40})?$", re.I)
GREETING = re.compile(r"^\s*Hi \[FIRST_NAME\],?\s*$")
SIGN_OFF = re.compile(r"^\s*Best,?\s*$")
VALUE = re.compile(r"^\s*\[(INTENDED_USE|NEXT_WEEK_ACTION|CTA_QUESTION)\]\s*:\s*(\S.*?)\s*$")
PLACEHOLDER_ONLY = re.compile(r"^\s*\[[A-Z_]+\]\s*$")


class FollowupBlocked(ValueError):
    """A guard is not met; nothing was written to Gmail."""


def offer_values(text):
    """The offer values the handbook itself states, and any it states twice differently."""
    seen = defaultdict(list)
    for line in text.replace("\r\n", "\n").split("\n"):
        found = VALUE.match(line)
        if found:
            seen[found.group(1)].append(found.group(2))
    values = {key: found[0] for key, found in seen.items() if len(set(found)) == 1}
    problems = [f"the handbook gives [{key}] more than one value"
                for key, found in seen.items() if len(set(found)) > 1]
    return values, problems


def _paragraphs(lines):
    """Lines between the greeting and "Best," as paragraphs. A blank line ends a paragraph, a
    line holding only a placeholder is a paragraph of its own, and a paragraph wrapped over
    several lines is joined back into one."""
    paragraphs, current = [], []

    def close():
        if current:
            paragraphs.append(" ".join(current))
            current.clear()

    for line in lines:
        text = line.strip().rstrip("\\").strip()
        if not text:
            close()
        elif PLACEHOLDER_ONLY.match(text):
            close()
            paragraphs.append(text)
        else:
            current.append(text)
    close()
    return paragraphs


def templates(text):
    """{1: [paragraphs], 2: [paragraphs]} from the handbook, and what is missing from it."""
    lines = text.replace("\r\n", "\n").split("\n")
    heads = [(i, int(found.group(1))) for i, line in enumerate(lines)
             if (found := HEADING.match(line))]
    out, problems = {}, []
    for step in (1, 2):
        at = [i for i, s in heads if s == step]
        if len(at) != 1:
            problems.append(f'the handbook has {len(at)} "Follow-up {step}" headings; it needs one')
            continue
        end = min([i for i, _ in heads if i > at[0]] + [len(lines)])
        section = lines[at[0] + 1:end]
        greeting = next((i for i, line in enumerate(section) if GREETING.match(line)), None)
        if greeting is None:
            problems.append(f'follow-up {step} has no "Hi [FIRST_NAME]," line')
            continue
        sign_off = next((i for i, line in enumerate(section)
                         if i > greeting and SIGN_OFF.match(line)), None)
        if sign_off is None:
            problems.append(f'follow-up {step} has no "Best," line')
            continue
        out[step] = _paragraphs(section[greeting + 1:sign_off])
        if not out[step]:
            problems.append(f'follow-up {step} has nothing between the greeting and "Best,"')
    return out, problems


def render(step, handbook_text, settings, first_name):
    """(body, problems) for follow-up `step`. A body exists only when nothing is missing."""
    parts, problems = templates(handbook_text)
    values, conflicts = offer_values(handbook_text)
    problems = problems + conflicts
    identity = {key: str(settings.get(key.lower(), "")).strip() for key in drafting.SIGNATURE_FIELDS}
    for key, value in identity.items():
        if not value or drafting.TOKEN.search(value):
            problems.append(f"settings field {key} is missing")
    if identity["POSTAL_ADDRESS"] and len(identity["POSTAL_ADDRESS"]) < 10:
        problems.append("postal address is too short")
    phone = str(settings.get("sender_phone", "")).strip()
    if phone and not drafting.PHONE.fullmatch(phone):
        problems.append("sender phone is invalid")
    if any("\n" in v or "\r" in v for v in [*identity.values(), phone, first_name]):
        problems.append("a signature field or the first name spans lines")
    if step not in parts:
        return None, problems or [f"follow-up {step} is missing from the handbook"]
    fill = {**values, "PRODUCT_NAME": identity["PRODUCT_NAME"]}
    middle = []
    for paragraph in parts[step]:
        for key, value in fill.items():
            paragraph = paragraph.replace(f"[{key}]", value)
        middle.append(paragraph)
    unfilled = sorted(set(drafting.TOKEN.findall(" ".join(middle))))
    if unfilled:
        problems.append("the handbook's follow-up leaves unfilled: " + ", ".join(unfilled))
    if problems:
        return None, problems
    body = "\n\n".join([f"Hi {first_name},", *middle,
                        drafting.sign_off({**identity, "SENDER_PHONE": phone})])
    if len(body) > 2500:
        return None, ["the follow-up exceeds the length limit"]
    return body, []


def preview(*, settings=None, handbook=None, drive=None):
    """Both follow-ups as they would read, and the handbook hash that approving them binds to."""
    settings = job_draft.load_settings() if settings is None else settings
    book, why = job_draft._handbook(settings, handbook, drive)
    if not book:
        return {"approved": False, "problems": [why], "followups": {}}
    out = {"handbook_document": book["document_id"], "handbook_hash": book["content_hash"],
           "handbook_modified": book.get("modified", ""),
           "approved": settings.get(APPROVAL_KEY) == book["content_hash"], "followups": {}}
    for step in (1, 2):
        body, problems = render(step, book["text"], settings, "<first name>")
        out["followups"][str(step)] = {"body": body, "problems": problems}
    ready = all(not f["problems"] for f in out["followups"].values())
    if ready and not out["approved"]:
        out["to_approve"] = (f'After reading both, set "{APPROVAL_KEY}": "{book["content_hash"]}" '
                             f"in the settings. Any edit to the handbook withdraws it.")
    return out


def gates(settings, book, why=None):
    """What stops any follow-up draft from being created now."""
    problems = [why] if why else []
    if os.environ.get("ENABLE_GMAIL_DRAFTS") != "true":
        problems.append("Gmail draft creation is disabled")
    if settings.get("offer_approved") is not True:
        problems.append("founder has not approved the offer wording")
    if book and settings.get(APPROVAL_KEY) != book["content_hash"]:
        problems.append("the follow-up wording is not approved for the handbook as it stands now")
    try:
        cap = int(settings.get("daily_cap", 0))
    except (TypeError, ValueError):
        cap = 0
    if not 1 <= cap <= 30:
        problems.append("daily cap must be between 1 and 30")
    if not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", str(settings.get("sender_email", "")).strip()):
        problems.append("sender email is missing or invalid")
    return problems


def actions_today(rows, today):
    """Initial and follow-up draft actions taken today (New York): one cap covers both."""
    count = 0
    for row in rows:
        for status, stamp in (("Draft status", "Draft action at"),
                              ("Follow-up status", "Follow-up action at")):
            if row.get(status) not in ("RESERVED", "CREATED"):
                continue
            moment = sync._stamp(row.get(stamp))
            if moment is None:
                raise FollowupBlocked("a draft action has no usable timestamp")
            count += new_york_date(moment) == today
    return count


def due_now(leads, events, entries, today):
    """[(item, state)] for sequences this system started whose next follow-up is due by today,
    and the same for those due later."""
    by_lead = defaultdict(list)
    for event in events:
        by_lead[event["Lead ID"]].append(event)
    due, later = [], []
    for lead_id, row in sorted(leads.items()):
        mine = by_lead.get(lead_id, [])
        state = sequence.lead_state(row, mine, suppressed=sync.lead_suppressed(entries, row, mine),
                                    today=today)
        if not state["due"] or state["sequence"]["origin"] != sequence.SYSTEM:
            continue
        item = {"lead_id": lead_id, "step": state["due"]["step"],
                "due": state["due"]["date"].isoformat(), "to": state["due"]["address"]}
        (due if state["due"]["date"] <= today else later).append((item, state))
    return due, later


def run(where="local", *, dry_run=True, store=None, gmail=None, settings=None, handbook=None,
        drive=None, now=None):
    now = now or datetime.now(timezone.utc)
    today = new_york_date(now)
    settings = job_draft.load_settings() if settings is None else settings
    store = store or Store()
    leads, events, entries = store.leads(), sync.unique(store.events()), store.suppression()
    report = {"dry_run": dry_run, "today": today.isoformat(), "due": [], "later": [],
              "created": [], "blocked": [], "gates": []}
    if entries is None:
        report["gates"] = ["the Suppression tab is missing or unreadable"]
        return report
    due, later = due_now(leads, events, entries, today)
    report["due"], report["later"] = [i for i, _ in due], [i for i, _ in later]
    book, why = job_draft._handbook(settings, handbook, drive)
    report["gates"] = gates(settings, book, why)
    if dry_run or not due:
        return report
    if report["gates"]:
        report["blocked"] = [{**item, "why": report["gates"]} for item, _ in due]
        store.run_row("followup", where, "BLOCKED", "; ".join(report["gates"])[:500])
        return report

    gmail = gmail or gmail_drafts.client()
    address = gmail.users().getProfile(userId="me").execute().get("emailAddress", "").lower()
    if address != str(settings["sender_email"]).strip().lower():
        report["blocked"] = [{**item, "why": ["the signed-in Gmail mailbox is not the sender"]}
                             for item, _ in due]
        store.run_row("followup", where, "BLOCKED", "signed-in mailbox is not the sender")
        return report
    remaining = int(settings["daily_cap"]) - actions_today(leads.values(), today)
    for item, state in due:
        if remaining <= 0:
            report["blocked"].append({**item, "why": ["the daily draft cap is reached"]})
            continue
        try:
            report["created"].append(_create(store, gmail, item, state, leads[item["lead_id"]],
                                             book, settings, now))
            remaining -= 1
        except FollowupBlocked as exc:
            report["blocked"].append({**item, "why": [str(exc)]})
    detail = f"due {len(due)}, drafted {len(report['created'])}, blocked {len(report['blocked'])}"
    store.run_row("followup", where, "OK" if not report["blocked"] else "PARTIAL", detail)
    return report


def _create(store, gmail, item, state, row, book, settings, now):
    """One follow-up draft: fresh checks against Gmail, reserve in the Sheet, create, finalize."""
    lead_id, step = item["lead_id"], state["due"]["step"]
    thread_id, address = state["due"]["thread"], state["due"]["address"]
    everything = mailbox.thread(gmail, thread_id).get("messages", [])
    if (any("DRAFT" in m.get("labelIds", []) for m in everything)
            or mailbox.drafts_in_thread(gmail, thread_id)):
        raise FollowupBlocked("a draft already sits in this thread")
    messages = [m for m in everything if "DRAFT" not in m.get("labelIds", [])]
    if not messages:
        raise FollowupBlocked("the thread is no longer in Gmail")
    last = messages[-1]
    if last["id"] != state["due"]["after_message"] or not mailbox.is_sent(last):
        raise FollowupBlocked("the thread changed since the last sync; run sync first")
    if not all(mailbox.is_sent(m) for m in messages):
        raise FollowupBlocked("the thread holds a message from someone else")
    first = messages[0]
    if address not in mailbox.recipients(first):
        raise FollowupBlocked("the address is not a recipient of the thread's first email")
    subject = " ".join(mailbox.header(first, "Subject").split())
    if not subject:
        raise FollowupBlocked("the thread's first email has no subject")
    reply_to = mailbox.header(last, "Message-ID").strip()
    if not reply_to:
        raise FollowupBlocked("the last email has no Message-ID to answer")
    references = " ".join((mailbox.header(last, "References") + " " + reply_to).split())
    first_name = (drafting.verified_first_name(row)
                  if address == row.get("BEST EMAIL", "").strip().lower() else "there")
    body, problems = render(step, book["text"], settings, first_name)
    if problems:
        raise FollowupBlocked("; ".join(problems))
    action_id = hashlib.sha256(
        f"followup:{lead_id}:{step}:{thread_id}:{last['id']}".encode()).hexdigest()[:32]

    tab, number, fresh = store.fresh_lead(lead_id)
    if any(fresh.get(c, "") != row.get(c, "") for c in FOLLOWUP_COLUMNS):
        raise FollowupBlocked("the lead's follow-up columns changed during the run")
    tab.ensure_columns(FOLLOWUP_COLUMNS)
    reserved = tab.write({number: {"Follow-up step": str(step), "Follow-up action": action_id,
                                   "Follow-up action at": now.isoformat(),
                                   "Follow-up status": "RESERVED", "Follow-up draft ID": ""}})
    if reserved["written"] != 1 or reserved["skipped"]:
        raise FollowupBlocked("the lead changed before the reservation; Gmail was not touched")

    # An exception here may still mean Gmail made the draft: the reservation stays for review.
    draft = gmail_drafts.create(gmail, to=address, from_address=settings["sender_email"],
                                subject=subject, body=body, action_id=action_id,
                                thread_id=thread_id, in_reply_to=reply_to, references=references)
    draft_id = draft.get("id")
    if not draft_id:
        raise FollowupBlocked("Gmail returned no draft ID; the action stays RESERVED")
    return _finalize(store, lead_id, action_id, draft_id, step, thread_id, address, item, now)


def _finalize(store, lead_id, action_id, draft_id, step, thread_id, address, item, now):
    tab, number, fresh = store.fresh_lead(lead_id)
    if fresh.get("Follow-up action") != action_id:
        raise FollowupBlocked("the draft is in Gmail but the Sheet reservation changed; reconcile")
    done = tab.write({number: {"Follow-up status": "CREATED", "Follow-up draft ID": draft_id}})
    if done["written"] != 1 or done["skipped"]:
        raise FollowupBlocked("the draft is in Gmail but the Sheet was not updated; reconcile")
    event = sync._event(lead_id, sequence.FOLLOWUP_DRAFTED, sequence.FOLLOWUPS[step - 1], now,
                        address, "DRAFT", thread_id, "", f"draft {draft_id}",
                        key=f"followup:{action_id}")
    event["Recorded at (UTC)"] = now.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    store.append_events([event])
    return {**item, "draft_id": draft_id, "action_id": action_id}


def reconcile(lead_id, *, store=None, gmail=None, now=None):
    """Settle a RESERVED follow-up by finding its draft. Never creates a replacement."""
    if os.environ.get("ENABLE_GMAIL_DRAFTS") != "true":
        raise FollowupBlocked("Gmail draft reconciliation is disabled")
    now = now or datetime.now(timezone.utc)
    store = store or Store()
    _, _, row = store.fresh_lead(lead_id)
    if row.get("Follow-up status") != "RESERVED" or not row.get("Follow-up action"):
        raise FollowupBlocked("the lead has no reserved follow-up")
    gmail = gmail or gmail_drafts.client()
    found = gmail_drafts.drafts_for_action(gmail, row["Follow-up action"])
    if len(found) != 1:
        return {"lead_id": lead_id, "status": "UNRESOLVED", "matching_drafts": len(found)}
    draft = found[0]
    step = int(row.get("Follow-up step") or 0)
    if step not in (1, 2):
        raise FollowupBlocked("the reserved follow-up has no step")
    thread_id = draft.get("message", {}).get("threadId", "")
    item = {"lead_id": lead_id, "step": step}
    _finalize(store, lead_id, row["Follow-up action"], draft["id"], step, thread_id,
              row.get("Sent to", ""), item, now)
    return {"lead_id": lead_id, "status": "CREATED", "draft_id": draft["id"]}


def main():
    parser = argparse.ArgumentParser(description="Prepare follow-up drafts; never sends")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--preview", action="store_true", help="both follow-ups and the hash to approve")
    mode.add_argument("--dry-run", action="store_true", help="who is due, and what blocks drafting")
    args = parser.parse_args()
    result = preview() if args.preview else run(dry_run=True)
    print(json.dumps(result, indent=2, default=str))


if __name__ == "__main__":
    main()
