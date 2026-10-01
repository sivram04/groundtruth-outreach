"""A post-call email candidate for the founder to inspect, edit or discard.

This is separate from the initial email (`drafting`/`job_draft`) and from the scheduled follow-up
sequence (`followup`). It never sends, never creates a Gmail draft, never writes to the Sheet, and it is
not persisted: it is composed on demand from already-saved facts so the founder can read it beside its
evidence and decide what to do by hand.

What it is grounded in: the saved call outcome and note (`outreach/calls.py`), the company's own evidence
on the lead row (the cited offering quote), the handbook-approved offer (the product name and CTA from
settings), and tied to the current Drive handbook's content hash. The handbook has no post-call template,
so the wording is composed here per outcome, never drawn from a model.

Rules, by the founder's direction:
  * A candidate is offered only for NO_ANSWER, INTERESTED and CALLBACK. DO_NOT_CONTACT, NOT_INTERESTED and
    WRONG_NUMBER get none.
  * After NO_ANSWER the wording never claims a conversation happened.
  * No wording ever invents what the recipient said.
  * A CALLBACK uses only the callback time the founder recorded, never an inferred one.
  * A lead with no email address gets no candidate (a phone-only lead keeps its task and history).
"""

import re

from outreach import calls, drafting
from outreach.business_days import NEW_YORK

# The call outcomes that warrant a post-call outreach candidate.
CANDIDATE_OUTCOMES = (calls.NO_ANSWER, calls.INTERESTED, calls.CALLBACK)

_EVIDENCE = re.compile(r'^\s*[""“]?(?P<quote>.+?)[""”]?\s*\((?P<url>[^)]+)\)\s*$', re.S)


def eligible_outcome(outcome):
    return outcome in CANDIDATE_OUTCOMES


def latest_call(events):
    """The most recent recorded OUTCOME as {outcome, note, callback_at, called_at}, or None.

    `callback_at` is the recorded callback time and only for a CALLBACK (never inferred for anything else)."""
    last = None
    for event in sorted(events, key=calls._order):
        if event.get("Kind") == "OUTCOME":
            last = event
    if last is None:
        return None
    outcome = last.get("Outcome", "")
    return {
        "outcome": outcome,
        "note": last.get("Note", ""),
        "callback_at": last.get("Due", "") if outcome == calls.CALLBACK else "",
        "called_at": last.get("Called at (UTC)", ""),
    }


def _evidence(lead):
    """The company's own cited words from the lead row's Offerings evidence (quote, url), or None."""
    raw = str(lead.get("Offerings evidence", "")).strip()
    match = _EVIDENCE.match(raw)
    if not match:
        return None
    quote = match.group("quote").strip().strip('"').strip("“”").strip()
    url = match.group("url").strip()
    return {"quote": quote, "url": url} if quote and url else None


def _callback_text(callback_at):
    when = calls._parse(callback_at)
    return when.astimezone(NEW_YORK).strftime("%Y-%m-%d %H:%M ET") if when else ""


def _sender_values(settings):
    values = {key: str(settings.get(key.lower(), "")).strip() for key in drafting.SIGNATURE_FIELDS}
    values["SENDER_PHONE"] = str(settings.get("sender_phone", "")).strip()
    return values


def offer_configured(settings):
    """Whether the handbook-approved offer fields a candidate needs are present (non-placeholder)."""
    values = _sender_values(settings)
    return all(values[key] for key in drafting.SIGNATURE_FIELDS)


def candidate(lead, call, settings, *, handbook):
    """A post-call email candidate for review, or raise `NotEligible` with a reason.

    `call` is a `latest_call(...)` dict. `handbook` is the current Drive handbook (its content hash ties the
    candidate to a version); a candidate is never built without it. Composes the subject, body and the
    evidence to show; sends and persists nothing."""
    outcome = call.get("outcome", "")
    if not eligible_outcome(outcome):
        raise NotEligible("outcome_not_eligible")
    email = str(lead.get("BEST EMAIL", "")).strip()
    if not email:
        raise NotEligible("no_email")
    if handbook is None:
        raise NotEligible("handbook_unavailable")
    if not offer_configured(settings):
        raise NotEligible("offer_not_configured")

    values = _sender_values(settings)
    first = drafting.verified_first_name(lead)
    product = values["PRODUCT_NAME"]
    company = str(lead.get("Company", "")).strip() or "your company"
    evidence = _evidence(lead)
    cta = str(settings.get("cta_question", "")).strip()
    callback_text = _callback_text(call.get("callback_at", "")) if outcome == calls.CALLBACK else ""

    # The one line that references the company uses the company's OWN words (verbatim, from its site), so
    # nothing is invented. It is included only when that evidence exists.
    evidence_line = (f'On your site you describe your work as "{evidence["quote"]}" — that is just the kind '
                     f'of contractor {product} is built to help.') if evidence else ""

    paragraphs = []
    if outcome == calls.NO_ANSWER:
        # Never claim a conversation happened.
        paragraphs.append(f"I tried to reach you by phone today but could not get through.")
        if evidence_line:
            paragraphs.append(evidence_line)
        paragraphs.append(f"I would still welcome the chance to show you how {product} could help {company}.")
        paragraphs.append(cta or "Is there a better time to reach you?")
        subject = f"Tried to reach you — {product}"
    elif outcome == calls.INTERESTED:
        paragraphs.append(f"Thank you for taking the time to speak with me today, and for your interest in "
                          f"{product}.")
        if evidence_line:
            paragraphs.append(evidence_line)
        paragraphs.append(f"I would love to set up a short next step so you can see how it could help "
                          f"{company}.")
        paragraphs.append(cta or "Would a brief call next week suit you?")
        subject = f"Following up after our call — {product}"
    else:  # CALLBACK
        paragraphs.append("Thanks for the call today.")
        if callback_text:
            paragraphs.append(f"I have a note to follow up with you at {callback_text}.")
        if evidence_line:
            paragraphs.append(evidence_line)
        paragraphs.append(cta or "Does that still work for you?")
        subject = f"Following up — {product}"

    body = "\n\n".join([f"Hi {first},", *[p for p in paragraphs if p], drafting.sign_off(values)])
    return {
        "outcome": outcome,
        "to": email,
        "subject": subject,
        "body": body,
        "evidence": evidence,
        "note": call.get("note", ""),
        "callback_at": call.get("callback_at", ""),
        "callback_text": callback_text,
        "handbook_hash": str(handbook.get("content_hash", "")),
        "handbook_name": str(handbook.get("name", "")),
    }


class NotEligible(Exception):
    """No post-call candidate should be offered; `reason` says why (for the UI to explain)."""

    def __init__(self, reason):
        super().__init__(reason)
        self.reason = reason
