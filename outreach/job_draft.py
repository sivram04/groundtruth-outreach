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

from outreach import (drafting, gemini, gmail_drafts, handbook_drive, research, review,
                      suppression, tracking, writer)
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
    """Whether the address is suppressed, or None when the list cannot be read: never a guess.

    `drafting.preview` treats None as unknown and blocks on it. The tab is read through the one
    contract in `outreach/suppression.py`, the same one the Store uses, so this reader and that
    one accept the same headers and refuse the same rows."""
    try:
        values = api.values().get(spreadsheetId=SHEET_ID,
                                  range="'Suppression'").execute().get("values", [])
        entries = suppression.of_values(values)
    except Exception:
        return None
    return suppression.covers(entries, email)


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


def _handbook(settings, handbook=None, drive=None):
    """The Drive document, or the reason there is none. Never a local substitute."""
    if handbook is not None:
        return handbook, None
    try:
        return handbook_drive.load(settings, drive=drive), None
    except handbook_drive.HandbookUnavailable as exc:
        return None, f"handbook unavailable: {exc}"


def _blocked(lead, options, blockers, handbook=None):
    """A preview shaped like any other, with no hash, when writing could not even start."""
    return {"lead_id": lead.get("Lead ID", ""), "company": lead.get("Company", ""),
            "to": lead.get("BEST EMAIL", "").strip().lower(), "subject": "", "body": "",
            "evidence": None, "evidence_options": options, "selected_quote_id": None,
            "handbook_hash": (handbook or {}).get("content_hash", ""),
            "preview_date": datetime.now(ZoneInfo("America/New_York")).date().isoformat(),
            "blockers": blockers, "preview_hash": None}


def site_text(lead):
    """The company's own pages, used only to confirm how it writes its name. Never quoted."""
    try:
        pages, _ = research.read_site(lead.get("Website", ""))
    except Exception:
        return ""
    return " ".join(text for _, text in pages)


def written_preview(lead, facts, settings, handbook, *, suppressed, model, quote_id=None,
                    pages=None, review_store=None):
    """Gemini writes; `drafting` decides whether the result may ever become a draft.

    No approval hash is issued for a candidate that has no valid human evidence review: this is the
    hash-producing path for previews and the Drafts tab, so the gate lives here (the action
    boundary in `create` rechecks separately). An unreviewed but otherwise-approvable candidate
    keeps its words and is held for review, exactly as the offer-not-approved case is."""
    company, verified = drafting.verified_company_name(
        lead.get("Company", ""), site_text(lead) if pages is None else pages)
    options = drafting.opening_options(drafting.supported_quotes(lead, facts), company)
    if quote_id:
        # An explicit choice overrides the ranking, but must still be a current usable quote.
        usable = [o for o in options if o["usable"] and o["quote_id"] == quote_id]
        if not usable:
            return _blocked(lead, options,
                            ["the selected quote is not a current, usable quote"], handbook)
        selection = []
    else:
        # Normal path: the code picks the opening, so only that quote reaches the model.
        chosen, selection = drafting.choose_opening(options)
        if not chosen:
            why = sorted({r for item in selection for r in item["reasons"]})
            return _blocked(lead, options, ["no quote is good enough to open with: "
                                            + ("; ".join(why) if why else "none available")],
                            handbook)
        usable = [chosen]
    try:
        draft, problems = writer.compose(handbook["text"], company, usable, model)
    except Exception as exc:  # a model or network failure must not produce a draft
        return _blocked(lead, options,
                        [f"the writer failed: {type(exc).__name__}: {exc}"[:180]], handbook)
    if draft is None:
        return _blocked(lead, options, problems, handbook)
    result = drafting.preview(lead, facts, settings, suppressed=suppressed,
                              handbook=handbook, written=draft, company=company)
    result["company_name_used"] = company
    result["selection"] = selection
    result["chosen_automatically"] = not quote_id
    if not verified:
        result["blockers"].append(
            f'the company name "{company}" was not found on its own site; check it')
        result["preview_hash"] = None
    return _gate_hash(result, handbook, settings, review_store)


def _gate_hash(result, handbook, settings, review_store):
    """Turn a preview's raw content digest into an approval hash only when this candidate has a
    valid human evidence review; otherwise `preview_hash` stays None and the candidate is held.

    `drafting._finish` computes a digest over the candidate's content for anyone who renders a
    preview (an *internal candidate digest*). It only becomes an *actionable approval token* -
    something `create` will accept - once a review exists. Every preview path that could expose a
    hash routes through here, so no supported CLI or API path exposes an approval token without a
    review; `create` rechecks at the action boundary as well."""
    if result.get("preview_hash"):
        store = review_store or review.default_store()
        fingerprint = review.candidate_fingerprint(result, handbook, settings)
        if not review.is_reviewed(store, result.get("lead_id", ""), fingerprint,
                                  reviewers=review.allowed_reviewers(settings)):
            result["preview_hash"] = None
            result["blockers"].append(review.AWAITING_BLOCKER)
    return result


def previews(ids, *, settings=None, api=None, fixture=None, quote_choices=None,
             write=False, model=None, drive=None, handbook=None, review_store=None):
    settings = load_settings() if settings is None else settings
    quote_choices = quote_choices or {}
    if fixture is not None:
        if not 1 <= len(ids) <= MAX_PILOT or len(set(ids)) != len(ids):
            raise DraftBlocked("supply one to four distinct Lead IDs")
        leads = {lead["Lead ID"]: lead for lead in fixture["leads"]}
        if not set(ids) <= leads.keys():
            raise DraftBlocked("fixture is missing a requested Lead ID")
        if write:
            book, why = _handbook(settings, handbook, drive)
            return [(written_preview(leads[i], fixture["research"], settings, book,
                                     suppressed=fixture.get("suppressed", {}).get(i, None),
                                     model=model or gemini.generate_json,
                                     quote_id=quote_choices.get(i), pages=fixture.get("pages", ""),
                                     review_store=review_store)
                     if book else _blocked(leads[i], [], [why]))
                    for i in ids]
        return [_gate_hash(drafting.preview(leads[lead_id], fixture["research"], settings,
                                            suppressed=fixture.get("suppressed", {}).get(lead_id, None),
                                            subject_template=settings.get("subject_template"),
                                            selected_quote_id=quote_choices.get(lead_id)),
                           None, settings, review_store)
                for lead_id in ids]
    api = api or _api()
    _, matches, facts = _read(api, ids)
    by_id = {lead["Lead ID"]: lead for _, _, lead in matches}
    if write:
        book, why = _handbook(settings, handbook, drive)
        return [(written_preview(by_id[i], facts, settings, book,
                                 suppressed=_suppressed(api, by_id[i].get("BEST EMAIL", "")),
                                 model=model or gemini.generate_json,
                                 quote_id=quote_choices.get(i), review_store=review_store)
                 if book else _blocked(by_id[i], [], [why]))
                for i in ids]
    return [_gate_hash(drafting.preview(by_id[lead_id], facts, settings,
                                        suppressed=_suppressed(api, by_id[lead_id].get("BEST EMAIL", "")),
                                        subject_template=settings.get("subject_template"),
                                        selected_quote_id=quote_choices.get(lead_id)),
                       None, settings, review_store)
            for lead_id in ids]


def _actions_today(tabs):
    """Draft actions taken today (New York). One daily cap covers initial and follow-up drafts."""
    today = datetime.now(ZoneInfo("America/New_York")).date()
    count = 0
    for tab in tabs:
        for _, lead in tab.rows:
            for status, stamp_column in (("Draft status", "Draft action at"),
                                         ("Follow-up status", "Follow-up action at")):
                if lead.get(status) not in {"RESERVED", "CREATED"}:
                    continue
                try:
                    stamp = datetime.fromisoformat(lead[stamp_column].replace("Z", "+00:00"))
                    count += stamp.astimezone(ZoneInfo("America/New_York")).date() == today
                except (ValueError, KeyError):
                    raise DraftBlocked("a draft action has no usable timestamp")
    return count


def _revalidated(lead, facts, written, settings, handbook=None, drive=None, pages=None):
    """Re-judge an approved written draft against the live handbook, quotes and company name.

    The company name is re-derived from the company's own site exactly as the preview did, so
    the rebuilt copy and its hash match what the founder approved.
    """
    book, why = _handbook(settings, handbook, drive)
    if not book:
        raise DraftBlocked(why)
    company, verified = drafting.verified_company_name(
        lead.get("Company", ""), site_text(lead) if pages is None else pages)
    if not verified:
        raise DraftBlocked(f'the company name "{company}" is no longer confirmed on its own site')
    options = drafting.opening_options(drafting.supported_quotes(lead, facts), company)
    rebuilt, problems = writer.revalidate(book["text"], company,
                                          [o for o in options if o["usable"]], written)
    if rebuilt is None:
        raise DraftBlocked("; ".join(problems))
    if any(rebuilt[k] != written.get(k) for k in ("subject", "company", "product", "ask")):
        raise DraftBlocked("the approved wording no longer passes its own checks")
    return book, rebuilt, company


def create(lead_id, approved_hash, *, written=None, settings=None, api=None,
           gmail=None, drive=None, handbook=None, pages=None, review_store=None):
    """Reserve in Sheets, create one Gmail draft, then finalize the Sheet row.

    A failed/uncertain create leaves RESERVED. No second create is attempted for that
    action, even if Gmail search cannot find it. A human must reconcile it.

    This is the only path that turns a model-written, grounded-claim draft into a Gmail draft,
    and the HTTP `create` route calls it, so the human evidence-review gate lives here — not in
    the console UI, which a direct API call would bypass. A valid, current, confirmed review of
    this exact candidate is required (`outreach/review.py`), rechecked against the rebuilt
    candidate at this boundary.
    """
    if os.environ.get("ENABLE_GMAIL_DRAFTS") != "true":
        raise DraftBlocked("Gmail draft creation is disabled")
    if not approved_hash:
        raise DraftBlocked("the founder's approved preview hash is required")
    if not isinstance(written, dict) or not written.get("sentences"):
        raise DraftBlocked("a Drive-handbook written draft is required")
    settings = load_settings() if settings is None else settings
    api = api or _api()
    tabs, matches, facts = _read(api, [lead_id])
    tab, row, lead = matches[0]
    book, rebuilt, company = _revalidated(lead, facts, written, settings, handbook, drive, pages)
    result = drafting.preview(lead, facts, settings,
                             suppressed=_suppressed(api, lead.get("BEST EMAIL", "")),
                             handbook=book, written=rebuilt, company=company)
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

    # The review recheck is the LAST gate before any write, to narrow the window in which a
    # revocation or edit could slip past. It re-reads the store and recomputes the fingerprint from
    # `result`, and every write below uses that same `result` object - so the draft that is created
    # is exactly the candidate that was just checked. The window is NOT closed: a rejection or edit
    # landing after this line and before the Gmail write is not caught (see docs); drafting is
    # disabled anyway, and a half-done create leaves a RESERVED row for reconciliation.
    try:
        review.enforce(result, book, settings, store=review_store or review.default_store())
    except review.ReviewInvalid as exc:
        raise DraftBlocked(f"human evidence review required ({exc.reason}): {exc}") from None

    action_id = hashlib.sha256(("initial:" + approved_hash).encode()).hexdigest()[:32]
    # Stage 5: tracking only when the founder has switched it on, and never an untracked
    # draft in its place when the signing key cannot be read.
    html = None
    if settings.get("tracking_enabled") is True:
        try:
            html = tracking.tracked_html(result["body"], action_id, tracking.key())
        except tracking.TrackingUnavailable as exc:
            raise DraftBlocked(f"tracking is on but {exc}") from None
    tab.ensure_columns(DRAFT_COLUMNS)
    reserved = tab.write({row: {"Draft action": action_id,
                                "Draft action at": datetime.now(timezone.utc).isoformat(),
                                "Draft status": "RESERVED", "Draft hash": approved_hash,
                                "Draft quote ID": result["selected_quote_id"],
                                "Draft tracked": "yes" if html else ""}})
    if reserved["written"] != 1 or reserved["skipped"]:
        raise DraftBlocked("lead changed before reservation; no Gmail write attempted")

    # A create exception may still mean Gmail committed. Leave RESERVED for reconciliation.
    draft = gmail_drafts.create(gmail, to=result["to"], from_address=settings["sender_email"],
                                subject=result["subject"], body=result["body"],
                                action_id=action_id, html=html)
    draft_id = draft.get("id")
    if not draft_id:
        raise DraftBlocked("Gmail did not return a draft ID; action remains RESERVED")
    fresh = Tab(api, tab.name, SYSTEM_COLUMNS)
    match = [(r, v) for r, v in fresh.rows if v.get("Lead ID") == lead_id]
    if len(match) != 1 or match[0][1].get("Draft action") != action_id:
        raise DraftBlocked("draft exists in Gmail but Sheet reservation changed; reconcile manually")
    # The draft's thread lets sync tie the founder's send to this action for certain (stage 4).
    finalized = fresh.write({match[0][0]: {"Draft status": "CREATED", "Draft ID": draft_id,
                                         "Draft thread ID": draft.get("message", {}).get("threadId", ""),
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
                               "Draft thread ID": found[0].get("message", {}).get("threadId", ""),
                               "Drafted at": datetime.now(timezone.utc).isoformat()}})
    if outcome["written"] != 1 or outcome["skipped"]:
        raise DraftBlocked("reservation changed before reconciliation")
    return {"lead_id": lead_id, "status": "CREATED", "draft_id": draft_id}


def main():
    parser = argparse.ArgumentParser(description="Preview initial outreach drafts; never sends")
    parser.add_argument("--ids", required=True, help="one to four comma-separated Lead IDs")
    parser.add_argument("--fixture", type=Path, help="offline fixture; no Google access")
    parser.add_argument("--settings", type=Path, help="local handbook settings JSON")
    parser.add_argument("--quote-choice", action="append", default=[],
                        help="select verified opening: LEAD_ID=QUOTE_ID; repeat per lead")
    parser.add_argument("--write", action="store_true",
                        help="Gemini writes from the Drive handbook instead of the fixed template")
    parser.add_argument("--handbook", type=Path,
                        help="offline handbook text for a synthetic run; never used in production")
    args = parser.parse_args()
    settings = (json.loads(args.settings.read_text(encoding="utf-8")) if args.settings
                else load_settings())
    fixture = json.loads(args.fixture.read_text(encoding="utf-8")) if args.fixture else None
    choices = {}
    for item in args.quote_choice:
        lead_id, sep, quote_id = item.partition("=")
        if not sep or not lead_id or not quote_id or lead_id in choices:
            parser.error("each --quote-choice must be a unique LEAD_ID=QUOTE_ID")
        choices[lead_id] = quote_id
    book = None
    if args.handbook:
        if not args.fixture:
            parser.error("--handbook is for synthetic runs only; use it with --fixture")
        text = args.handbook.read_text(encoding="utf-8")
        book = {"text": text, "document_id": f"local:{args.handbook.name}", "source": "local",
                "content_hash": hashlib.sha256(text.encode()).hexdigest(), "version": "local"}
    print(json.dumps(previews(args.ids.split(","), settings=settings, fixture=fixture,
                              quote_choices=choices, write=args.write, handbook=book), indent=2))


if __name__ == "__main__":
    main()
