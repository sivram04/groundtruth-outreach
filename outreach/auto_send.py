"""Stage 3+: the scheduled, no-click send - the one exception to "a human clicks every send".

A Gmail draft that already passed the full review-and-create gate (``job_draft.create`` or the
founder's own edited draft, ``job_draft.create_edited``) sits as ``CREATED`` until a human clicks
Approve-and-send in the console, or until this job runs and sends it for them, up to the same
daily cap that already limits draft creation. Nothing here writes a draft or chooses its words;
it only decides WHEN an already-approved draft leaves, and how many leave today.

Guards, each re-checked here (a drip can span days, so a draft approved yesterday is re-checked
against today's call log and suppression list, not yesterday's):
  * ``ENABLE_AUTO_SEND`` must be set, independently of the console's own ``ENABLE_SEND`` (both
    flags must be on; this module calls the same sanctioned ``outreach.send`` path, so the
    no-send test's "only the console imports send.py" rule is widened to name this module too).
  * a recorded call outcome (STOP/HOLD) blocks the send, exactly as it blocks a create.
  * the recipient must not be on the Suppression list (an unreadable list blocks, never guesses).
  * the daily cap counts TODAY's sends (New York), separate from the cap on draft creation, so a
    full day of creating drafts does not by itself empty tomorrow's send allowance.
  * ``outreach.send.send_created_draft``'s own guards (reservation, at-most-once, CREATED only)
    still apply unchanged; this module only decides which lead to call it for, in order.
"""

import os
from datetime import datetime
from zoneinfo import ZoneInfo

from outreach import calls, job_draft, send, suppression
from outreach.sheet import LEAD_TABS, SYSTEM_COLUMNS, Tab, _api


class AutoSendBlocked(Exception):
    """Auto-send could not run; no email was sent."""


def _sent_today(tabs, today):
    count = 0
    for tab in tabs:
        for _, lead in tab.rows:
            if (lead.get("Draft status") or "").upper() != "SENT":
                continue
            stamp = (lead.get("Sent at") or "").strip()
            if not stamp:
                continue
            try:
                when = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
            except ValueError:
                continue
            count += when.astimezone(ZoneInfo("America/New_York")).date() == today
    return count


def _candidates(tabs):
    """Lead IDs with a created, unsent Gmail draft, oldest draft action first."""
    rows = []
    for tab in tabs:
        for _, lead in tab.rows:
            if (lead.get("Draft status") or "").upper() != "CREATED":
                continue
            if not (lead.get("Draft ID") or "").strip():
                continue
            rows.append((lead.get("Draft action at") or "", lead["Lead ID"]))
    rows.sort(key=lambda pair: pair[0])
    return [lead_id for _, lead_id in rows]


def run(*, api=None, gmail=None, now=None, sent_by="auto-send (daily cap)"):
    """Send as many already-created drafts as today's cap still allows, oldest first.

    Returns ``{"sent": [...], "skipped": [...], "remaining_cap": n}``. Never raises for an
    individual lead's guard failure - those are reported in ``skipped`` so one bad row cannot
    stop the rest of the run; only a whole-run precondition (the flag, or the settings) raises.
    """
    if os.environ.get("ENABLE_AUTO_SEND") != "true":
        raise AutoSendBlocked("auto-send is disabled (ENABLE_AUTO_SEND is not set)")
    settings = job_draft.load_settings()
    try:
        cap = int(settings["daily_cap"])
    except (KeyError, TypeError, ValueError):
        raise AutoSendBlocked("daily cap is missing or invalid") from None

    api = api or _api()
    tabs = [Tab(api, name, SYSTEM_COLUMNS) for name in LEAD_TABS]
    today = datetime.now(ZoneInfo("America/New_York")).date()
    remaining = max(0, cap - _sent_today(tabs, today))

    sent, skipped = [], []
    for lead_id in _candidates(tabs):
        if remaining <= 0:
            skipped.append({"lead_id": lead_id, "reason": "the daily send cap is reached"})
            continue
        try:
            effect = job_draft._call_effect(api, lead_id)
        except job_draft.DraftBlocked as exc:
            skipped.append({"lead_id": lead_id, "reason": str(exc)})
            continue
        if calls.blocks_outreach(effect):
            skipped.append({"lead_id": lead_id,
                            "reason": f"a recorded call outcome ({effect.lower()}) blocks this send"})
            continue
        _, _, lead = send._find(api, lead_id)
        suppressed = job_draft._suppressed(api, lead.get("BEST EMAIL", ""))
        if suppressed is None:
            skipped.append({"lead_id": lead_id, "reason": "the suppression list could not be read"})
            continue
        if suppressed:
            skipped.append({"lead_id": lead_id, "reason": "this recipient is on the suppression list"})
            continue
        try:
            result = send.send_created_draft(lead_id, sent_by=sent_by, api=api, gmail=gmail, now=now)
        except send.SendBlocked as exc:
            skipped.append({"lead_id": lead_id, "reason": str(exc)})
            continue
        sent.append(result)
        remaining -= 1

    return {"sent": sent, "skipped": skipped, "remaining_cap": remaining}
