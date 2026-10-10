"""Company/sender identity fields (name, title, email, phone, website, postal address, product
name, daily cap) and a few optional links (booking, survey, a doc/case-study to cite), stored
durably so they can be set from the chat assistant instead of only by hand-editing the
``outreach-settings`` secret with ``gcloud``.

The links are stored here, by the same chat flow, but using them in outbound copy is a separate
decision per link: ``booking_link`` is already read by ``outreach/reply.py`` for the reply CTA.
``survey_link`` and ``doc_link`` are stored and can be set, but nothing reads them yet - storing a
link is not the same as deciding where, when, and under what condition it may appear in an email,
and that needs its own grounding decision (this system never states a fact or offers a link the
founder did not deliberately put there for that purpose).

Stored the same way the playbook is (``outreach/handbook_store.py``): an append-only ``Company``
tab on the leads Sheet, one field per row, latest row for a given field wins. This needs no new
secret or permission - the console already writes the Sheet with the founder's own OAuth, and
``outreach-settings`` stays the base/fallback for any field never set this way.

``overrides`` is only ever consulted where a caller has a live Sheets client to hand it
(``outreach/console.py``'s ``_chosen_settings``), exactly like the playbook resolver - so a path
that supplies its own settings dict (tests, fixtures, the synthetic CLI run) never reads the
store and is unaffected by it.
"""

import re
from datetime import datetime, timezone

from outreach.drafting import PHONE, TOKEN, _host
from outreach.reply import _PLACEHOLDER as _LINK_PLACEHOLDER
from outreach.sheet import SHEET_ID, _api, ensure_tab

TAB = "Company"
HEADER = ["Set at (UTC)", "Set by", "Field", "Value"]

# (settings key, what the assistant calls it when asking). Order is the order the guided chat
# flow asks in. sender_phone is deliberately not here: it is optional, so it is never "missing"
# and never auto-asked - set it only by naming it explicitly ("phone: ...").
FIELD_ORDER = [
    ("sender_name", "your name, as the sender"),
    ("founder_title", "your title"),
    ("sender_email", "the email address you send from"),
    ("sender_website", "your website"),
    ("postal_address", "your postal address (required so the opt-out line is truthful)"),
    ("product_name", "the product name to use in the email"),
    ("daily_cap", "how many emails to send per day (1-30)"),
]
# Optional links: never auto-asked (not in FIELD_ORDER), set only by naming them explicitly.
OPTIONAL_LINKS = {
    "booking_link": "your booking/scheduling link",
    "survey_link": "your survey link",
    "doc_link": "a doc or case-study link to cite",
}
LABELS = dict(FIELD_ORDER) | {"sender_phone": "your phone number"} | OPTIONAL_LINKS

ALIASES = {
    "name": "sender_name", "sender name": "sender_name", "your name": "sender_name",
    "title": "founder_title", "founder title": "founder_title", "your title": "founder_title",
    "email": "sender_email", "sender email": "sender_email",
    "phone": "sender_phone", "sender phone": "sender_phone", "phone number": "sender_phone",
    "website": "sender_website", "sender website": "sender_website",
    "address": "postal_address", "postal address": "postal_address",
    "product": "product_name", "product name": "product_name",
    "cap": "daily_cap", "daily cap": "daily_cap",
    "booking link": "booking_link", "booking": "booking_link", "scheduling link": "booking_link",
    "survey": "survey_link", "survey link": "survey_link",
    "doc": "doc_link", "doc link": "doc_link", "document link": "doc_link",
    "case study": "doc_link", "case study link": "doc_link",
}


class InvalidField(ValueError):
    """A proposed value for a company field is not usable; ``field`` names which one."""

    def __init__(self, field, reason):
        super().__init__(reason)
        self.field = field


def missing(value):
    """True when a stored field is empty or still a bracket placeholder (e.g. ``[SENDER_NAME]``)."""
    value = (value or "").strip()
    return not value or bool(TOKEN.fullmatch(value))


def next_missing(settings):
    """The first required field (in ``FIELD_ORDER``) ``settings`` does not yet have, or None."""
    for key, label in FIELD_ORDER:
        if missing(settings.get(key, "")):
            return key, label
    return None


def validate(field, raw):
    """Clean and check one field's proposed value. Raises `InvalidField`; never guesses or fills in."""
    value = " ".join((raw or "").strip().split())  # one line, collapsed whitespace
    if field == "sender_phone" and value.lower() in ("skip", "none", "no", "n/a", "-"):
        return ""
    if not value:
        raise InvalidField(field, "that can't be empty")
    if field == "sender_email":
        if not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", value):
            raise InvalidField(field, "that doesn't look like an email address")
    elif field == "sender_phone":
        if not PHONE.fullmatch(value):
            raise InvalidField(field, "that doesn't look like a phone number")
    elif field == "sender_website":
        host = _host(value) or _host(f"https://{value}")
        if not host or " " in host or "." not in host:
            raise InvalidField(field, "that doesn't look like a website")
        value = value if value.startswith(("http://", "https://")) else f"https://{value}"
    elif field == "postal_address":
        if len(value) < 10:
            raise InvalidField(field, "that postal address looks too short")
    elif field == "daily_cap":
        try:
            n = int(value)
        except ValueError:
            raise InvalidField(field, "that needs to be a whole number") from None
        if not 1 <= n <= 30:
            raise InvalidField(field, "the daily cap must be between 1 and 30")
        value = str(n)
    elif field in OPTIONAL_LINKS:
        if not re.match(r"^https?://", value, re.I) or _LINK_PLACEHOLDER.search(value):
            raise InvalidField(field, "that doesn't look like a real link yet")
    elif field not in LABELS:
        raise InvalidField(field, "that isn't a company field I know")
    return value


def _rows(api):
    try:
        return (api.values().get(spreadsheetId=SHEET_ID, range=f"'{TAB}'")
                .execute().get("values", []))
    except Exception:
        return []


def overrides(*, api=None):
    """The latest stored value for each field that has one, as a plain ``{key: value}`` dict.

    Empty (not None) when the tab is absent, empty, or its header does not match - callers merge
    this OVER the base settings, so an absent/empty result changes nothing."""
    values = _rows(api or _api())
    if len(values) < 2 or values[0] != HEADER:
        return {}
    latest = {}
    for row in values[1:]:
        cells = dict(zip(HEADER, row))
        field = (cells.get("Field") or "").strip()
        if field in LABELS:
            latest[field] = (cells.get("Value") or "").strip()  # append order: last write wins
    return latest


def set_field(field, value, *, set_by, api=None, now=None):
    """Append one field's new value, after validation. Returns the cleaned value actually stored."""
    if field not in LABELS:
        raise InvalidField(field, "that isn't a company field I know")
    clean = validate(field, value)
    if not (set_by or "").strip():
        raise ValueError("a company-field change must name who set it")
    api = api or _api()
    ensure_tab(api, TAB, HEADER)
    stamp = (now or datetime.now(timezone.utc)).isoformat()
    api.values().append(
        spreadsheetId=SHEET_ID, range=f"'{TAB}'!A1", valueInputOption="RAW",
        body={"values": [[stamp, set_by, field, clean]]}).execute()
    return clean
