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

from outreach import gmail_drafts, job_draft, sequence, sync, tracking
from outreach.sheet import Store
from outreach.tracking_job import TEST_LEAD

SUBJECT = "Lakshyaa tracking test"
BODY = ("This is a test of the outreach email tracking. No reply is needed.\n\n"
        "Please open this email, then click the link below.\n\n{website}")


class CheckBlocked(ValueError):
    """The test draft cannot be made; nothing was written."""


def create(to, *, store=None, gmail=None, settings=None, secret=None, now=None):
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
    entries = store.suppression()
    if entries is None or sync.on_list(entries, to):
        raise CheckBlocked("the address is on Suppression, or Suppression cannot be read")
    now = now or datetime.now(timezone.utc)
    action = hashlib.sha256(f"test:{to}:{now.isoformat()}".encode()).hexdigest()[:32]
    body = BODY.format(website=website)
    html = tracking.tracked_html(body, action, secret or tracking.key())
    gmail = gmail or gmail_drafts.client()
    mailbox = gmail.users().getProfile(userId="me").execute().get("emailAddress", "").lower()
    if mailbox != sender:
        raise CheckBlocked("the signed-in mailbox is not the configured sender")
    draft = gmail_drafts.create(gmail, to=to, from_address=sender, subject=SUBJECT, body=body,
                                action_id=action, html=html)
    event = sync._event(TEST_LEAD, sequence.DRAFTED, "TEST", now, to, "DRAFT",
                        draft.get("message", {}).get("threadId", ""), "",
                        f"tracking test draft {draft.get('id', '')}, {sequence.TRACKED}",
                        key=f"test:{action}")
    event["Recorded at (UTC)"] = now.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    store.append_events([event])
    return {"draft_id": draft.get("id"), "action": action, "to": to}


def main():
    parser = argparse.ArgumentParser(description="Make one tracked test draft to your own inbox")
    parser.add_argument("--to", required=True, help="another inbox of yours, never a lead")
    print(json.dumps(create(parser.parse_args().to), indent=2))


if __name__ == "__main__":
    main()
