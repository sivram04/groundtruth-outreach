"""The one place the system sends an email. Nothing else in ``outreach/`` may send.

A send happens only here, for a draft this system already created and the founder has read, and
only through one of two sanctioned callers: the console's human-clicked "Approve and send", or
``outreach/auto_send.py`` (the scheduled, cap-limited drip of drafts already approved and
created - founder decision 2026-10-08). No other worker or scheduled job imports this module, so
the rest of the automation can create drafts but can never send. One approval sends exactly one
email; a lead already sent (or in flight) is refused, so a repeated click or a repeated scheduled
run never sends twice.

This is the single sanctioned exception to the "the system never sends email" rule. The no-send
test (``tests/test_no_send.py``) permits a send call in this file and nowhere else, and a separate
test holds that only the console and ``auto_send.py`` reach it.
"""

import os
from datetime import datetime, timezone

from outreach import gmail_drafts
from outreach.sheet import LEAD_TABS, SHEET_ID, SYSTEM_COLUMNS, Tab, _api


class SendBlocked(Exception):
    """A send could not safely proceed; no email was sent."""


def _find(api, lead_id, sheet_id=SHEET_ID, lead_tabs=LEAD_TABS):
    for name in lead_tabs:
        tab = Tab(api, name, SYSTEM_COLUMNS, sheet_id)
        for row, lead in tab.rows:
            if lead.get("Lead ID") == lead_id:
                return tab, row, lead
    raise SendBlocked(f"no lead {lead_id}")


def _set_status(api, lead_id, *, expect, cells, sheet_id=SHEET_ID, lead_tabs=LEAD_TABS):
    """Re-read the lead and write ``cells`` only while its Draft status still equals ``expect``.

    Returns True when the write landed, False when the row changed underneath (optimistic
    concurrency, like every other system write) so the caller never assumes a write it did not make.
    """
    tab, row, lead = _find(api, lead_id, sheet_id, lead_tabs)
    if (lead.get("Draft status") or "").upper() != expect:
        return False
    outcome = tab.write({row: cells})
    return outcome["written"] == 1 and not outcome["skipped"]


def send_created_draft(lead_id, *, sent_by, api=None, gmail=None, now=None, sheet_id=SHEET_ID,
                       lead_tabs=LEAD_TABS):
    """Send the Gmail draft already created for ``lead_id``, on a human's approval.

    Guards (any failure sends nothing): the send flag must be on; an approver must be named; the
    lead must have a CREATED draft with a Draft ID; and the lead must not already be sent or in
    flight. The lead is marked in flight BEFORE the send, so a lost response or a second click
    cannot send a second email. Returns the sent message id and thread id.
    """
    if os.environ.get("ENABLE_SEND") != "true":
        raise SendBlocked("sending is disabled (ENABLE_SEND is not set)")
    if not (sent_by or "").strip():
        raise SendBlocked("a send must name the person who approved it")
    api = api or _api()
    _, _, lead = _find(api, lead_id, sheet_id, lead_tabs)

    status = (lead.get("Draft status") or "").upper()
    if status in ("SENT", "SENDING") or (lead.get("Sent at") or "").strip():
        raise SendBlocked("this lead has already been sent")
    if status != "CREATED" or not (lead.get("Draft ID") or "").strip():
        raise SendBlocked("no created draft to send for this lead")
    draft_id = lead["Draft ID"].strip()

    # Reserve the send BEFORE touching Gmail. If this does not land, another request already has it
    # (or the row changed) and we must not send: at most one email leaves per created draft.
    if not _set_status(api, lead_id, expect="CREATED", cells={"Draft status": "SENDING"},
                       sheet_id=sheet_id, lead_tabs=lead_tabs):
        raise SendBlocked("the draft could not be reserved for sending; nothing was sent")

    gmail = gmail or gmail_drafts.client()
    sent = gmail.users().drafts().send(userId="me", body={"id": draft_id}).execute()
    message_id, thread_id = sent.get("id", ""), sent.get("threadId", "")

    stamp = (now or datetime.now(timezone.utc)).isoformat()
    recorded = _set_status(api, lead_id, expect="SENDING",
                           cells={"Draft status": "SENT", "Sent at": stamp},
                           sheet_id=sheet_id, lead_tabs=lead_tabs)
    # The email is out either way. If the record did not land, say so rather than claim a clean
    # state; the reservation (SENDING) still blocks a second send until it is reconciled.
    return {"lead_id": lead_id, "sent": True, "message_id": message_id,
            "thread_id": thread_id, "recorded": recorded, "sent_by": sent_by}
