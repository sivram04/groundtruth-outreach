"""Stage 5 pass test: one tracked draft to the founder's own other inbox.

The founder sends it, opens it there and clicks its link; the hits must come back as OPEN and
CLICK events for the lead TEST. It is never addressed to a lead: an address that any lead row
lists, or a company domain one does, is refused, and so is an address on Suppression. It is a
draft only; the founder presses Send.

    ENABLE_GMAIL_DRAFTS=true python -m outreach.tracking_check --to you@example.com
"""

import argparse
import hashlib
import json
import os
import re
from datetime import datetime, timezone

from outreach import drafting, followup, gmail_drafts, job_draft, sequence, suppression, sync, tracking
from outreach.sheet import Store
from outreach.tracking_job import TEST_LEAD

SUBJECT = "Lakshyaa tracking test"
BODY = ("This is a test of the outreach email tracking. No reply is needed.\n\n"
        "Please open this email, then click the link below.\n\n{website}")


class CheckBlocked(ValueError):
    """The test draft cannot be made; nothing was written."""


def real_wording(settings, handbook):
    """(subject, body) as a real outreach email reads, for a spam-folder check: the handbook's
    own follow-up 1 words and the founder's signature, postal address and opt-out line, under the
    handbook's own subject. Nothing here is written for the test (founder, 2026-09-28)."""
    body, problems = followup.render(1, handbook["text"], settings, "there")
    subject = str(settings.get("subject_template", "")).replace(
        "[PRODUCT_NAME]", str(settings.get("product_name", "")).strip())
    if not subject.strip() or drafting.TOKEN.search(subject):
        problems = problems + ["the settings give no usable subject_template"]
    if problems:
        raise CheckBlocked("the real wording cannot be made: " + "; ".join(problems))
    return subject, body


def create(to, *, store=None, gmail=None, settings=None, secret=None, now=None, real=False,
           handbook=None, drive=None):
    """One tracked test draft. `real` uses the words a real outreach email would carry instead
    of the plain test note, so the test also shows which folder real outreach lands in."""
    if os.environ.get("ENABLE_GMAIL_DRAFTS") != "true":
        raise CheckBlocked("Gmail draft creation is disabled")
    to = (to or "").strip().lower()
    if not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", to):
        raise CheckBlocked("that is not an email address")
    settings = job_draft.load_settings() if settings is None else settings
    sender = str(settings.get("sender_email", "")).strip().lower()
    if not sender or to == sender:
        raise CheckBlocked("the test goes to another inbox of yours, not the sending mailbox")
    website = str(settings.get("sender_website", "")).strip()
    if not tracking.allowed(website):
        raise CheckBlocked("the sender website is not an https link the tracker may lead to")
    store = store or Store()
    index = sync.LeadIndex(store.leads())
    if index.by_address.get(to) or index.by_domain.get(sync.company_domain(to)):
        raise CheckBlocked("that address, or its company, is a lead: the test goes to your own inbox")
    try:
        entries = store.suppression()
    except suppression.Unreadable as exc:
        raise CheckBlocked("no test can be drafted: " + exc.reason) from exc
    if sync.on_list(entries, to):
        raise CheckBlocked("the address, or its whole domain, is on the Suppression list")
    now = now or datetime.now(timezone.utc)
    action = hashlib.sha256(f"test:{to}:{now.isoformat()}".encode()).hexdigest()[:32]
    subject, body = SUBJECT, BODY.format(website=website)
    if real:
        book, why = job_draft._handbook(settings, handbook, drive)
        if not book:
            raise CheckBlocked(why)
        subject, body = real_wording(settings, book)
    html = tracking.tracked_html(body, action, secret or tracking.key())
    gmail = gmail or gmail_drafts.client()
    mailbox = gmail.users().getProfile(userId="me").execute().get("emailAddress", "").lower()
    if mailbox != sender:
        raise CheckBlocked("the signed-in mailbox is not the configured sender")
    draft = gmail_drafts.create(gmail, to=to, from_address=sender, subject=subject, body=body,
                                action_id=action, html=html)
    wording = "real email wording" if real else "test note"
    event = sync._event(TEST_LEAD, sequence.DRAFTED, "TEST", now, to, "DRAFT",
                        draft.get("message", {}).get("threadId", ""), "",
                        f"tracking test draft {draft.get('id', '')}, {sequence.TRACKED}, {wording}",
                        key=f"test:{action}")
    event["Recorded at (UTC)"] = now.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    store.append_events([event])
    return {"draft_id": draft.get("id"), "action": action, "to": to, "subject": subject}


def main():
    parser = argparse.ArgumentParser(description="Make one tracked test draft to your own inbox")
    parser.add_argument("--to", required=True, help="another inbox of yours, never a lead")
    parser.add_argument("--real", action="store_true",
                        help="the words a real outreach email carries, from the Drive handbook")
    args = parser.parse_args()
    print(json.dumps(create(args.to, real=args.real), indent=2))


if __name__ == "__main__":
    main()
