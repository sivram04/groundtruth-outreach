"""Stage 3: explicit, unscheduled initial-email preview and guarded Gmail draft creation.

No automatic lead selection or send operation exists. An operator supplies 1–4 Lead IDs
for preview and the exact approved preview hash for each requested Gmail draft.
"""

import argparse
import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from outreach import drafting, gmail_drafts
from outreach.sheet import DRAFT_COLUMNS, LEAD_TABS, SHEET_ID, SYSTEM_COLUMNS, Tab, _api

MAX_PILOT = 4
CONFIG_PATH = Path(__file__).resolve().parent.parent / ".secrets" / "pilot_handbook.json"


class DraftBlocked(ValueError):
    """A missing fact, changed lead, or uncertain previous action requires review."""


def load_settings(path=CONFIG_PATH):
    if os.environ.get("OUTREACH_HANDBOOK_JSON"):
        return json.loads(os.environ["OUTREACH_HANDBOOK_JSON"])
    return json.loads(Path(path).read_text(encoding="utf-8")) if Path(path).exists() else {}


def _records(api, tab_name, header_row=1):
    values = api.values().get(spreadsheetId=SHEET_ID, range=f"'{tab_name}'").execute().get("values", [])
    if len(values) < header_row:
        return []
    header = values[header_row - 1]
    return [{name: row[i] if i < len(row) else "" for i, name in enumerate(header) if name}
            for row in values[header_row:]]


def _suppressed(api, email):
    """An absent or unreadable Suppression tab is unknown, never an empty list."""
    try:
        values = api.values().get(spreadsheetId=SHEET_ID, range="'Suppression'").execute().get("values", [])
    except Exception:
        return None
    if not values or not any(h in values[0] for h in ("Address or domain", "Address", "Domain")):
        return None
    header = values[0]
    rows = [{name: row[i] if i < len(row) else "" for i, name in enumerate(header) if name}
            for row in values[1:]]
    address = email.strip().lower()
    domain = address.rpartition("@")[2]
    for row in rows:
        value = (row.get("Address or domain") or row.get("Address") or row.get("Domain") or "").lower().strip()
        if value == address or value.lstrip("@") == domain:
            return True
    return False


def _read(api, ids):
    if not 1 <= len(ids) <= MAX_PILOT or len(set(ids)) != len(ids):
        raise DraftBlocked("supply one to four distinct Lead IDs")
    tabs = [Tab(api, name, SYSTEM_COLUMNS) for name in LEAD_TABS]
    matches = [(tab, row, lead) for tab in tabs for row, lead in tab.rows
               if lead.get("Lead ID") in ids]
    if len(matches) != len(ids) or {lead.get("Lead ID") for _, _, lead in matches} != set(ids):
        raise DraftBlocked("a Lead ID is missing or duplicated")
    facts = _records(api, "Research")
    return tabs, matches, facts


def previews(ids, *, settings=None, api=None, fixture=None):
    settings = load_settings() if settings is None else settings
    if fixture is not None:
        if not 1 <= len(ids) <= MAX_PILOT or len(set(ids)) != len(ids):
            raise DraftBlocked("supply one to four distinct Lead IDs")
        leads = {lead["Lead ID"]: lead for lead in fixture["leads"]}
        if not set(ids) <= leads.keys():
            raise DraftBlocked("fixture is missing a requested Lead ID")
        return [drafting.preview(leads[lead_id], fixture["research"], settings,
                                suppressed=fixture.get("suppressed", {}).get(lead_id, None),
                                subject_template=settings.get("subject_template"))
                for lead_id in ids]
    api = api or _api()
    _, matches, facts = _read(api, ids)
    by_id = {lead["Lead ID"]: lead for _, _, lead in matches}
    return [drafting.preview(by_id[lead_id], facts, settings,
                            suppressed=_suppressed(api, by_id[lead_id].get("BEST EMAIL", "")),
                            subject_template=settings.get("subject_template"))
            for lead_id in ids]


def _actions_today(tabs):
    today = datetime.now(ZoneInfo("America/New_York")).date()
    count = 0
    for tab in tabs:
        for _, lead in tab.rows:
            if lead.get("Draft status") not in {"RESERVED", "CREATED"}:
                continue
            try:
                stamp = datetime.fromisoformat(lead["Draft action at"].replace("Z", "+00:00"))
                count += stamp.astimezone(ZoneInfo("America/New_York")).date() == today
            except (ValueError, KeyError):
                raise DraftBlocked("a draft action has no usable timestamp")
    return count


def create(lead_id, approved_hash, *, settings=None, api=None, gmail=None):
    """Reserve in Sheets, create one Gmail draft, then finalize the Sheet row.

    A failed/uncertain create leaves RESERVED. No second create is attempted for that
    action, even if Gmail search cannot find it. A human must reconcile it.
    """
    if os.environ.get("ENABLE_GMAIL_DRAFTS") != "true":
        raise DraftBlocked("Gmail draft creation is disabled")
    if not approved_hash:
        raise DraftBlocked("the founder's approved preview hash is required")
    settings = load_settings() if settings is None else settings
    api = api or _api()
    tabs, matches, facts = _read(api, [lead_id])
    tab, row, lead = matches[0]
    result = drafting.preview(lead, facts, settings,
                             suppressed=_suppressed(api, lead.get("BEST EMAIL", "")),
                             subject_template=settings.get("subject_template"))
    if result["blockers"]:
        raise DraftBlocked("; ".join(result["blockers"]))
    if result["preview_hash"] != approved_hash:
        raise DraftBlocked("the approved hash does not match the current preview")
    if _actions_today(tabs) >= int(settings["daily_cap"]):
        raise DraftBlocked("the daily draft cap is reached")

    gmail = gmail or gmail_drafts.client()
    mailbox = gmail.users().getProfile(userId="me").execute().get("emailAddress", "")
    if mailbox.lower() != settings["sender_email"].lower():
        raise DraftBlocked("the signed-in Gmail mailbox does not match the configured sender")
    if gmail_drafts.prior_sends(gmail, result["to"]):
        raise DraftBlocked("a prior sent message exists for this recipient")
    if gmail_drafts.existing_drafts(gmail, result["to"]):
        raise DraftBlocked("a Gmail draft already exists for this recipient")

    action_id = hashlib.sha256(("initial:" + approved_hash).encode()).hexdigest()[:32]
    tab.ensure_columns(DRAFT_COLUMNS)
    reserved = tab.write({row: {"Draft action": action_id,
                                "Draft action at": datetime.now(timezone.utc).isoformat(),
                                "Draft status": "RESERVED", "Draft hash": approved_hash}})
    if reserved["written"] != 1 or reserved["skipped"]:
        raise DraftBlocked("lead changed before reservation; no Gmail write attempted")

    # A create exception may still mean Gmail committed. Leave RESERVED for reconciliation.
    draft = gmail_drafts.create(gmail, to=result["to"], from_address=settings["sender_email"],
                                subject=result["subject"], body=result["body"],
                                action_id=action_id)
    draft_id = draft.get("id")
    if not draft_id:
        raise DraftBlocked("Gmail did not return a draft ID; action remains RESERVED")
    fresh = Tab(api, tab.name, SYSTEM_COLUMNS)
    match = [(r, v) for r, v in fresh.rows if v.get("Lead ID") == lead_id]
    if len(match) != 1 or match[0][1].get("Draft action") != action_id:
        raise DraftBlocked("draft exists in Gmail but Sheet reservation changed; reconcile manually")
    finalized = fresh.write({match[0][0]: {"Draft status": "CREATED", "Draft ID": draft_id,
                                         "Drafted at": datetime.now(timezone.utc).isoformat()}})
    if finalized["written"] != 1 or finalized["skipped"]:
        raise DraftBlocked("draft exists in Gmail but Sheet finalization failed; reconcile manually")
    return {"lead_id": lead_id, "draft_id": draft_id, "action_id": action_id,
            "status": "CREATED"}


def reconcile(lead_id, *, api=None, gmail=None):
    """Find one reserved Gmail draft; never attempt to create a replacement."""
    if os.environ.get("ENABLE_GMAIL_DRAFTS") != "true":
        raise DraftBlocked("Gmail draft reconciliation is disabled")
    api = api or _api()
    _, matches, _ = _read(api, [lead_id])
    tab, row, lead = matches[0]
    if lead.get("Draft status") != "RESERVED" or not lead.get("Draft action"):
        raise DraftBlocked("lead has no reserved draft action")
    gmail = gmail or gmail_drafts.client()
    found = gmail_drafts.drafts_for_action(gmail, lead["Draft action"])
    if len(found) != 1:
        return {"lead_id": lead_id, "status": "UNRESOLVED", "matching_drafts": len(found)}
    draft_id = found[0]["id"]
    outcome = tab.write({row: {"Draft status": "CREATED", "Draft ID": draft_id,
                               "Drafted at": datetime.now(timezone.utc).isoformat()}})
    if outcome["written"] != 1 or outcome["skipped"]:
        raise DraftBlocked("reservation changed before reconciliation")
    return {"lead_id": lead_id, "status": "CREATED", "draft_id": draft_id}


def main():
    parser = argparse.ArgumentParser(description="Preview initial outreach drafts; never sends")
    parser.add_argument("--ids", required=True, help="one to four comma-separated Lead IDs")
    parser.add_argument("--fixture", type=Path, help="offline fixture; no Google access")
    parser.add_argument("--settings", type=Path, help="local handbook settings JSON")
    args = parser.parse_args()
    settings = (json.loads(args.settings.read_text(encoding="utf-8")) if args.settings
                else load_settings())
    fixture = json.loads(args.fixture.read_text(encoding="utf-8")) if args.fixture else None
    print(json.dumps(previews(args.ids.split(","), settings=settings, fixture=fixture), indent=2))


if __name__ == "__main__":
    main()
