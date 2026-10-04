"""A reply-draft candidate for the founder to inspect, edit or discard, after a lead writes back.

This is #6 in the MVP plan (reply drafting + booking link). It is built exactly like
`outreach/post_call.py`: it never sends, never creates a Gmail draft, never writes to the Sheet, and it
is not persisted. It is composed on demand from already-saved facts so the founder can read a suggested
reply beside its evidence and decide what to do by hand (edit it, paste it into the thread in Gmail, or
discard it).

What it is grounded in: the recorded inbound event that shows the lead replied (`outreach/sync.py`
events), the company's own cited words on the lead row (the offering quote), the offer the founder
approved in settings (the product name and CTA), and an optional booking link from settings. The reply
is composed here in code - the handbook has no reply template and its text is not read; the current Drive
handbook's name and content hash are recorded only so the candidate is tied to a handbook version.

Rules, kept deliberately conservative:
  * A candidate is offered only when the lead's most recent inbound is a genuine REPLIED (the lead wrote
    back). An AUTO_REPLY (out-of-office) is not a reply. An OPT_OUT or a BOUNCED anywhere in the thread
    blocks a candidate outright - a lead who asked not to be written to, or whose address failed, gets
    none.
  * The wording NEVER quotes, paraphrases or guesses what the lead said. We did not parse their message;
    we only know that they replied. So the reply acknowledges the reply, offers a next step, and says
    nothing about its contents.
  * The effective call decision is honoured: a STOP (sticky do-not-contact, or not-interested) blocks a
    candidate even after a reply; a HOLD does not (a reply is the founder handling the lead by hand).
  * A lead on the Suppression list gets no candidate.
  * The founder must have approved and configured the offer wording before it is shown.
  * A lead with no email address gets no candidate.
  * The booking link is included only when it is a real, non-placeholder URL in settings; otherwise the
    CTA falls back to the approved question, then to a neutral ask. A booking link is never invented.
  * The candidate carries the thread id and the inbound message id so a reply draft can later be created
    in the original thread (that draft step is separate and still review-gated; nothing here sends).
"""

import hashlib
import os
import re

from outreach import calls, drafting, gmail_drafts, sequence

# Inbound events that mean "the lead wrote back" vs ones that must block a reply candidate.
REPLY_EVENT = sequence.REPLIED
BLOCKING_EVENTS = (sequence.OPT_OUT, sequence.BOUNCED)

_EVIDENCE = re.compile(r'^\s*[""“]?(?P<quote>.+?)[""”]?\s*\((?P<url>[^)]+)\)\s*$', re.S)
# A booking link must look like a real http(s) URL and not be a left-in placeholder.
_PLACEHOLDER = re.compile(r"\[[^\]]*\]|example\.com|your[-_]?link|booking[-_]?link|tbd", re.I)


def booking_link(settings):
    """The founder's booking URL from settings, or "" when none is set or it is a placeholder."""
    raw = str((settings or {}).get("booking_link", "")).strip()
    if not raw or _PLACEHOLDER.search(raw):
        return ""
    if not re.match(r"^https?://", raw, re.I):
        return ""
    return raw


def latest_inbound(events):
    """The lead's most recent genuine inbound reply as {thread, message_id, occurred, address}, or None.

    Returns None when the most recent inbound-or-blocking event is an OPT_OUT or a BOUNCED (so a reply
    that came before an opt-out never resurfaces a candidate), and None when there is no REPLIED at all.
    AUTO_REPLY is ignored entirely - it is not the lead writing back."""
    considered = [e for e in events
                  if e.get("Event") in (REPLY_EVENT, *BLOCKING_EVENTS)]
    if not considered:
        return None
    considered.sort(key=lambda e: str(e.get(sequence.OCCURRED, "")))
    last = considered[-1]
    if last.get("Event") in BLOCKING_EVENTS:
        return None
    return {
        "thread": last.get("Thread ID", ""),
        "message_id": last.get("Gmail message ID", ""),
        "occurred": last.get(sequence.OCCURRED, ""),
        "address": last.get("Address", ""),
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


def _sender_values(settings):
    values = {key: str(settings.get(key.lower(), "")).strip() for key in drafting.SIGNATURE_FIELDS}
    values["SENDER_PHONE"] = str(settings.get("sender_phone", "")).strip()
    return values


def offer_configured(settings):
    values = _sender_values(settings)
    return all(values[key] for key in drafting.SIGNATURE_FIELDS)


def offer_approved(settings):
    return settings.get("offer_approved") is True


class NotEligible(Exception):
    """No reply candidate should be offered; `reason` says why (for the UI to explain)."""

    def __init__(self, reason):
        super().__init__(reason)
        self.reason = reason


class ReplyBlocked(Exception):
    """An in-thread reply draft cannot be created; `reason` says why. Nothing was written."""

    def __init__(self, reason):
        super().__init__(reason)
        self.reason = reason


MAX_SUBJECT = 300
MAX_BODY = 20000


def reply_action_id(lead_id, thread, message_id):
    """A stable action id for a reply in one thread, so a repeat on the same inbound is the same action."""
    return hashlib.sha256(f"reply:{lead_id}:{thread}:{message_id}".encode()).hexdigest()[:32]


def _thread_has_draft(gmail, thread):
    """Whether a Gmail draft already sits in this thread (so a reply draft is not created twice)."""
    listed = gmail.users().drafts().list(userId="me").execute().get("drafts", [])
    return any((d.get("message") or {}).get("threadId", "") == thread for d in listed)


def create(lead, inbound, subject, body, *, settings, gmail, effect=calls.CONTINUE, suppressed=False):
    """Create ONE in-thread Gmail reply draft from the founder's reviewed (possibly edited) subject and
    body. DRAFT ONLY - it never sends; the founder presses Send in Gmail. Raises `ReplyBlocked` and writes
    nothing on any failure.

    The candidate's guards are re-checked here at the write boundary (not trusted from when the candidate
    was shown): a call STOP, suppression, no email, or no inbound reply all refuse. `ENABLE_GMAIL_DRAFTS`
    must be "true" (the same hard env gate the initial-email path uses), so the flag alone never creates a
    draft. No tracking is added to a reply. The draft is filed in the inbound reply's own thread; a thread
    that already holds a draft is refused, so a repeat does not create a second one."""
    if os.environ.get("ENABLE_GMAIL_DRAFTS") != "true":
        raise ReplyBlocked("drafts_disabled")
    if not inbound:
        raise ReplyBlocked("no_reply")
    if suppressed:
        raise ReplyBlocked("suppressed")
    if effect == calls.STOP:
        raise ReplyBlocked("call_stop")
    to = str(lead.get("BEST EMAIL", "")).strip()
    if not to:
        raise ReplyBlocked("no_email")
    thread = str(inbound.get("thread", "")).strip()
    if not thread:
        raise ReplyBlocked("no_thread")
    subject = str(subject or "").strip()
    body = str(body or "").strip()
    if not subject or not body:
        raise ReplyBlocked("empty")
    if len(subject) > MAX_SUBJECT or len(body) > MAX_BODY:
        raise ReplyBlocked("too_long")
    sender = str(settings.get("sender_email", "")).strip()
    if not sender:
        raise ReplyBlocked("no_sender")
    mailbox = str(gmail.users().getProfile(userId="me").execute().get("emailAddress", "")).strip().lower()
    if mailbox != sender.lower():
        raise ReplyBlocked("mailbox_mismatch")
    if _thread_has_draft(gmail, thread):
        raise ReplyBlocked("draft_exists")
    action_id = reply_action_id(lead.get("Lead ID", ""), thread, inbound.get("message_id", ""))
    draft = gmail_drafts.create(gmail, to=to, from_address=sender, subject=subject, body=body,
                                action_id=action_id, thread_id=thread)
    draft_id = draft.get("id")
    if not draft_id:
        raise ReplyBlocked("no_draft_id")
    return {"draft_id": draft_id, "action_id": action_id, "to": to,
            "thread_id": draft.get("message", {}).get("threadId", thread)}


def candidate(lead, inbound, settings, *, handbook, effect=calls.CONTINUE, suppressed=False):
    """A reply-draft candidate for review, or raise `NotEligible` with a reason.

    `inbound` is a `latest_inbound(...)` dict (the recorded reply). `effect` is the lead's effective call
    decision (`calls.outreach_effect` over its call events): a STOP blocks a candidate. `suppressed` is
    whether the lead is on the Suppression list. `handbook` ties the candidate to a handbook version (its
    text is not read). Composes the subject, body, booking link and evidence to show; sends and persists
    nothing, and never states what the lead's reply said."""
    if not inbound:
        raise NotEligible("no_reply")
    if suppressed:
        raise NotEligible("suppressed")
    if effect == calls.STOP:
        raise NotEligible("call_stop")
    email = str(lead.get("BEST EMAIL", "")).strip()
    if not email:
        raise NotEligible("no_email")
    if handbook is None:
        raise NotEligible("handbook_unavailable")
    if not offer_configured(settings):
        raise NotEligible("offer_not_configured")
    if not offer_approved(settings):
        raise NotEligible("offer_not_approved")

    values = _sender_values(settings)
    first = drafting.verified_first_name(lead)
    product = values["PRODUCT_NAME"]
    company = str(lead.get("Company", "")).strip() or "your company"
    evidence = _evidence(lead)
    link = booking_link(settings)
    cta_question = str(settings.get("cta_question", "")).strip()

    # The only line that references the company uses its OWN words (verbatim, from its site); nothing is
    # invented, and nothing refers to what the lead wrote back.
    evidence_line = (f'On your site you describe your work as "{evidence["quote"]}" — that is just the '
                     f'kind of contractor {product} is built to help.') if evidence else ""

    paragraphs = ["Thank you for getting back to me."]
    if evidence_line:
        paragraphs.append(evidence_line)
    paragraphs.append(f"I would welcome the chance to show you how {product} could help {company}.")
    if link:
        paragraphs.append(f"If it is easier, you can book a time that suits you here: {link}")
    else:
        paragraphs.append(cta_question or "Would a short call in the next week or two suit you?")

    body = "\n\n".join([f"Hi {first},", *[p for p in paragraphs if p], drafting.sign_off(values)])
    subject = f"Re: {product}"
    return {
        "to": email,
        "subject": subject,
        "body": body,
        "booking_link": link,
        "evidence": evidence,
        "thread_id": inbound.get("thread", ""),
        "in_reply_to": inbound.get("message_id", ""),
        "replied_at": inbound.get("occurred", ""),
        "handbook_hash": str(handbook.get("content_hash", "")),
        "handbook_name": str(handbook.get("name", "")),
    }
