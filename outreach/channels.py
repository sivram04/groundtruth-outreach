"""How a lead can be reached, worked out from its row alone.

Every lead is one of three channels, so the rest of the system can show the right next action and
keep phone-only leads usable:

- EMAIL: a usable email address is on the row. The existing research/draft/review path applies.
- CALL: no email, but a phone number. There is no email to draft; the next action is a call.
- COMPANY_ONLY: neither an email nor a phone. The lead is a company we cannot yet reach; it needs a
  contact found (enrichment) before anything else.

This module reads the row and nothing else: it never invents a contact, never sends and never writes.
It is used by the importer (to classify a fresh list) and by the console model (to show the next
action), so the two always agree.
"""

import re

EMAIL = "EMAIL"
CALL = "CALL"
COMPANY_ONLY = "COMPANY_ONLY"

# The row headers a phone can live under. The founder's own columns vary, so several spellings are
# accepted; matching is case-insensitive on the trimmed header.
PHONE_HEADERS = ("phone", "phone number", "best phone", "telephone", "tel", "mobile", "cell",
                 "cell phone", "contact number")
EMAIL_HEADERS = ("best email", "email", "their email", "email address")

_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_DIGITS = re.compile(r"\d")


def _first(row, headers):
    """The first non-empty value among `headers`, matched case-insensitively; '' if none."""
    lowered = {str(key).strip().lower(): value for key, value in row.items()}
    for header in headers:
        value = str(lowered.get(header, "") or "").strip()
        if value:
            return value
    return ""


def email_of(row):
    """The lead's email if the row carries one that looks like an address, else ''."""
    value = _first(row, EMAIL_HEADERS)
    return value if _EMAIL.match(value) else ""


def phone_of(row):
    """The lead's phone if the row carries one with enough digits to dial, else ''."""
    value = _first(row, PHONE_HEADERS)
    return value if len(_DIGITS.findall(value)) >= 7 else ""


def channel_of(row):
    """EMAIL, CALL or COMPANY_ONLY for one lead row."""
    if email_of(row):
        return EMAIL
    if phone_of(row):
        return CALL
    return COMPANY_ONLY


def next_action(channel, company):
    """The next action for a lead that has not been emailed, by channel.

    EMAIL leads flow through the existing draft/review path, so they get no call/enrich action here
    ('' - the draft flow shows readiness instead). CALL and COMPANY_ONLY leads, which have no email to
    draft, get a plain instruction so they stay usable and are never a dead end."""
    name = (str(company or "").strip() or "this company")
    if channel == CALL:
        return f"Call {name}: no email is on file. Record the call outcome after."
    if channel == COMPANY_ONLY:
        return f"Find a contact for {name}: there is no email or phone yet."
    return ""
