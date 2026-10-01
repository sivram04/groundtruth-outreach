"""Interpret a short typed note about a call into a proposed outcome for the founder to confirm.

Deterministic and read-only: it never writes and never calls a model. The general assistant's answer path
stays read-only and separate; this is an explicit, confirmed action. Nothing is saved here - the console
writes only when the founder confirms, through the existing call-outcome route (so submission identity, task
scheduling and the STOP/HOLD and sticky do-not-contact rules are reused unchanged).

Two safety rules are built in:
  * A callback time is never inferred from prose. If the note means a callback and no explicit date/time has
    been supplied, the proposal asks for one.
  * When the person or company matches more than one lead, the proposal hands the choice back to the founder.
"""

import re
import uuid
from datetime import date, timezone

from outreach import calls
from outreach.business_days import NEW_YORK

# Outcome phrases, most decisive first: a stop or a wrong number wins over a softer reading of the same note.
_OUTCOME_PHRASES = [
    (calls.DO_NOT_CONTACT, ("do not contact", "don't contact", "dont contact", "do-not-contact",
                            "opt out", "opted out", "opt-out", "unsubscribe", "take me off", "remove me",
                            "take them off", "stop contacting")),
    (calls.NOT_INTERESTED, ("not interested", "no interest", "not keen", "no thanks", "not a fit",
                            "said no", "declined")),
    (calls.WRONG_NUMBER, ("wrong number", "wrong no", "bad number", "not their number")),
    (calls.CALLBACK, ("call back", "callback", "call me back", "ring back", "wants a call back",
                      "reschedule", "call them back")),
    (calls.INTERESTED, ("interested", "keen", "wants a demo", "wants to talk", "wants more",
                        "send more", "follow up with info")),
    (calls.NO_ANSWER, ("no answer", "no pickup", "no pick up", "didn't answer", "didnt answer",
                       "didn't pick up", "left a voicemail", "left vm", "voicemail", "rang out",
                       "no response", "could not reach", "couldn't reach", "couldnt reach")),
]

# Words that do not help identify a company (legal suffixes and generic nouns).
_STOP_WORDS = {"inc", "llc", "llp", "lp", "corp", "corporation", "co", "company", "ltd", "limited",
               "group", "services", "service", "the", "and", "of", "at", "to", "a", "an"}


def detect_outcome(note):
    """The call outcome the note describes, or None when none is recognised."""
    text = f" {note.lower()} "
    for outcome, phrases in _OUTCOME_PHRASES:
        if any(f" {p} " in text or text.strip().endswith(p) or text.strip().startswith(p) or p in text
               for p in phrases):
            return outcome
    return None


def _norm(value):
    return re.sub(r"[^a-z0-9 ]", " ", str(value or "").lower())


def _significant(words):
    return [w for w in words if len(w) > 2 and w not in _STOP_WORDS]


def match_leads(leads, note):
    """Lead IDs whose company or contact name appears in the note. Over-matching is safe: several matches
    become a 'choose' prompt rather than a guess."""
    tokens = set(_norm(note).split())
    hits = []
    for lead_id, row in leads.items():
        company_words = _significant(_norm(row.get("Company", "")).split())
        contact_words = _significant(_norm(row.get("Decision maker", "")).split())
        if any(w in tokens for w in company_words) or any(w in tokens for w in contact_words):
            hits.append(lead_id)
    return sorted(hits)


def _lead_view(lead_id, row):
    from outreach import channels
    return {"lead_id": lead_id, "company": row.get("Company", ""),
            "contact": row.get("Decision maker", ""), "email": channels.email_of(row),
            "phone": channels.phone_of(row)}


def _due_text(outcome, now, *, rule, callback_at):
    due, kind = calls.next_due(outcome, now.astimezone(NEW_YORK).isoformat(),
                               no_answer_business_days=rule, callback_at=callback_at)
    if not due:
        return "", ""
    if kind == "DATE":
        try:
            return due, date.fromisoformat(due).strftime("%a %Y-%m-%d")
        except ValueError:
            return due, due
    when = calls._parse(due)
    return due, (when.astimezone(NEW_YORK).strftime("%Y-%m-%d %H:%M ET") if when else due)


def interpret(note, leads, *, now, rule=calls.DEFAULT_NO_ANSWER_BUSINESS_DAYS, chosen_lead_id=None,
              callback_at=None):
    """A proposal for the founder to confirm, as a dict with a `status`:

      unclear_outcome - no recognised outcome; no_lead - nothing matched; choose_lead - several matched
      (`leads` listed); need_time - a callback with no explicit date/time; ready - everything needed, with
      the lead, outcome, saved note, resulting due date and the email effect to show before confirming.

    Reads only; writes nothing. A callback time is taken only from `callback_at` (supplied explicitly by the
    founder), never parsed from the note."""
    note = str(note or "").strip()
    outcome = detect_outcome(note)
    if outcome is None:
        return {"status": "unclear_outcome"}

    if chosen_lead_id:
        if chosen_lead_id not in leads:
            return {"status": "no_lead"}
        matched = [chosen_lead_id]
    else:
        matched = match_leads(leads, note)
    if not matched:
        return {"status": "no_lead"}
    if len(matched) > 1:
        return {"status": "choose_lead", "outcome": outcome, "note": note,
                "leads": [_lead_view(lid, leads[lid]) for lid in matched]}

    lead_id = matched[0]
    callback_at = str(callback_at or "").strip() or None
    if outcome == calls.CALLBACK and not callback_at:
        return {"status": "need_time", "outcome": outcome, "note": note,
                "lead": _lead_view(lead_id, leads[lead_id])}

    due, due_text = _due_text(outcome, now, rule=rule, callback_at=callback_at)
    # The call time is pinned to this interpretation so the date previewed is the date saved: the confirm
    # posts this `called_at`, and the outcome route computes the same due from it - a preview before New York
    # midnight and a confirm after it can no longer disagree.
    called_at = now.astimezone(timezone.utc).isoformat()
    return {
        "status": "ready",
        "lead": _lead_view(lead_id, leads[lead_id]),
        "outcome": outcome,
        "note": note,
        "called_at": called_at,
        "callback_at": callback_at or "",
        "due": due,
        "due_text": due_text,
        "effect": calls.email_effect(outcome),
        "do_not_contact": outcome == calls.DO_NOT_CONTACT,
        "submission_id": f"chat-{uuid.uuid4().hex[:16]}",
    }
