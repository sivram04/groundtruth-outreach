"""The Drafts tab: each ready lead's first email, written and checked, waiting for the founder.

`prepare` takes the leads ready for a first draft (the drafting step's own checks, and never
emailed), has the pipeline write each one's email (the Drive handbook, the company's own
quotes, Gemini, then every check in `drafting`), and keeps one row per lead in the Drafts tab:
who it goes to, the subject, the words, the quote it opens with and the page it is on, and where
it stands:

  READY    every check passes; the row carries the approval hash sending will require
  WAITING  the words pass every check, but the founder has not approved the offer wording, so
           no approval hash exists; the words are kept so they can be read and approved
  HELD     it cannot be written as it stands; the row says why

Nothing here sends or makes a Gmail draft. A lead that already has a row is left as it is
unless `refresh` asks for it to be written again.

    HANDBOOK_DOC_ID=... python -m outreach.drafts --dry-run      # who would be written
    HANDBOOK_DOC_ID=... python -m outreach.drafts --limit 30     # write their rows
"""

import argparse
import json
from datetime import datetime, timezone

from outreach import drafting, gemini, job_draft, sequence, sync
from outreach.sheet import Store

READY, WAITING, HELD = "READY", "WAITING", "HELD"
OFFER_NOT_APPROVED = "founder has not approved the offer wording"
NAME_NOT_ON_SITE = "was not found on its own site"
FIRST_EMAIL = "First email"
DEFAULT_LIMIT = 30  # Gemini writes one email per lead; this bounds a run's cost and time
MAX_LIMIT = 100


class DraftsBlocked(RuntimeError):
    """Drafts cannot be prepared safely; nothing was written."""


def first_draft_blockers(row, events, entries):
    """Why a lead may not have a first draft: the drafting step's own lead checks, and never
    emailed (by hand or by this system). `entries` None (Suppression unreadable) blocks it."""
    address = row.get("BEST EMAIL", "").strip()
    blockers = drafting.lead_blockers(row, None if entries is None else sync.on_list(entries, address))
    if any(e.get("Event") == sequence.SENT for e in events):
        blockers.append("already emailed")
    return blockers


def _reviewable(blocker):
    """A blocker that still lets the founder read the words: the offer approval itself, and
    the company name not found on the company's own site, which the founder checks by eye."""
    return blocker == OFFER_NOT_APPROVED or NAME_NOT_ON_SITE in blocker


def written_row(lead, preview, settings, facts, *, suppressed, handbook, now):
    """The Drafts row for one written preview.

    While the offer is not approved the pipeline withholds the words; if that approval (or a
    name to check) is all that stands in the way, the same approved sentences are put together
    once more as they would read once approved, only to be read here. That second pass calls no
    model and its hash is thrown away: a row with no approval hash can never be sent."""
    blockers = list(preview.get("blockers") or [])
    body, subject = preview.get("body") or "", preview.get("subject") or ""
    if preview.get("preview_hash") and not blockers:
        status = READY
    elif preview.get("written") and blockers and all(_reviewable(b) for b in blockers):
        shown = drafting.preview(lead, facts, {**settings, "offer_approved": True},
                                 suppressed=suppressed, handbook=handbook,
                                 written=preview["written"],
                                 company=preview.get("company_name_used"))
        leftover = [b for b in shown["blockers"] if not _reviewable(b)]
        if leftover or shown["body"] == drafting.WITHHELD:
            status, blockers = HELD, blockers + leftover
            body = ""
        else:
            status, body, subject = WAITING, shown["body"], shown["subject"]
    else:
        status, body = HELD, ""
    evidence = preview.get("evidence") or {}
    return {
        "Lead ID": lead["Lead ID"], "Email": FIRST_EMAIL, "To": preview.get("to", ""),
        "Company": preview.get("company_name_used") or lead.get("Company", ""),
        "Subject": subject, "Body": body if body != drafting.WITHHELD else "",
        "Opening quote": evidence.get("quote", ""), "Quote page": evidence.get("url", ""),
        # One reason a line: a reason may itself contain "; ".
        "Status": status, "Why": "\n".join(dict.fromkeys(blockers)),
        "Approval hash": preview.get("preview_hash") or "" if status == READY else "",
        "Handbook hash": preview.get("handbook_hash", ""),
        "Written": json.dumps(preview["written"], sort_keys=True) if preview.get("written") else "",
        "Prepared at (UTC)": now.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
    }


def plan(store):
    """(leads ready for a first draft in Lead ID order, the Drafts tab as {Lead ID: sheet row})."""
    leads = store.leads()
    entries = store.suppression()
    if entries is None:
        raise DraftsBlocked("the Suppression tab cannot be read, so no lead can be called ready")
    by_lead = {}
    for event in sync.unique(store.events()):
        by_lead.setdefault(event.get("Lead ID", ""), []).append(event)
    ready = [row for lead_id, row in sorted(leads.items())
             if not first_draft_blockers(row, by_lead.get(lead_id, []), entries)]
    existing = {}
    for number, row in store.drafts():
        if row.get("Email", FIRST_EMAIL) == FIRST_EMAIL:
            existing.setdefault(row["Lead ID"], number)
    return ready, existing, entries


def prepare(store=None, *, settings=None, handbook=None, drive=None, model=None, now=None,
            limit=DEFAULT_LIMIT, refresh=False, dry_run=False, pages=None):
    """Write the Drafts rows of up to `limit` ready leads. Returns what was done, by lead."""
    if not 1 <= int(limit) <= MAX_LIMIT:
        raise DraftsBlocked(f"a run writes between 1 and {MAX_LIMIT} drafts")
    settings = job_draft.load_settings() if settings is None else settings
    if not settings:
        raise DraftsBlocked("the drafting settings cannot be read")
    store = store or Store()
    ready, existing, entries = plan(store)
    todo = [row for row in ready if refresh or row["Lead ID"] not in existing][:int(limit)]
    report = {"ready": len(ready), "already_drafted": len([r for r in ready if r["Lead ID"] in existing]),
              "to_write": [row["Lead ID"] for row in todo], "dry_run": dry_run, "written": {}}
    if dry_run or not todo:
        return report
    book, why = job_draft._handbook(settings, handbook, drive)
    if not book:
        raise DraftsBlocked(why)
    facts = (store.table("Research") or ([], []))[1]
    now = now or datetime.now(timezone.utc)
    model = model or gemini.generate_json
    new, replace = [], {}
    for lead in todo:
        suppressed = sync.on_list(entries, lead.get("BEST EMAIL", ""))
        preview = job_draft.written_preview(
            lead, facts, settings, book, suppressed=suppressed, model=model,
            pages=None if pages is None else pages.get(lead["Lead ID"], ""))
        row = written_row(lead, preview, settings, facts, suppressed=suppressed, handbook=book,
                          now=now)
        if lead["Lead ID"] in existing:
            replace[existing[lead["Lead ID"]]] = row
        else:
            new.append(row)
        report["written"][lead["Lead ID"]] = {"status": row["Status"], "why": row["Why"]}
    store.write_drafts(new, replace)
    counts = {status: sum(1 for r in report["written"].values() if r["status"] == status)
              for status in (READY, WAITING, HELD)}
    store.run_row("drafts", "local", "OK", f"wrote {len(report['written'])} drafts: " +
                  ", ".join(f"{k} {v}" for k, v in counts.items()))
    return report


def main():
    parser = argparse.ArgumentParser(description="Write ready leads' first emails into the Drafts "
                                                 "tab; never sends")
    parser.add_argument("--limit", type=int, default=DEFAULT_LIMIT)
    parser.add_argument("--refresh", action="store_true", help="write leads that already have a row again")
    parser.add_argument("--dry-run", action="store_true", help="only say who would be written")
    args = parser.parse_args()
    print(json.dumps(prepare(limit=args.limit, refresh=args.refresh, dry_run=args.dry_run), indent=2))


if __name__ == "__main__":
    main()
