"""Interpret a typed message about the founder's own sender/company identity into a proposal to
confirm - the "information about my company" channel, parallel to ``lead_chat.py`` for leads and
the paperclip for the playbook.

Deterministic and read-only: no model, nothing invented. Two ways to answer:
  * Name the field explicitly: ``email: admin@lakshyaa.ai``, ``phone: 614-555-0100``.
  * Or, when a required field is still unset, just type the bare value - it is read as the
    answer to whichever field ``company_settings.next_missing`` says is still needed, so the
    assistant can guide one field at a time without the server having to remember the
    conversation: the current settings alone determine what is being asked.

Returns ``{"status": "ready", "field": ..., "label": ..., "value": ...}`` to confirm, or
``{"status": "invalid", "field": ..., "label": ..., "reason": ...}`` to report back without
writing, or ``{"status": "unclear"}`` when the message names no known field and nothing is
currently being asked - the caller then treats it as an ordinary question, not a company edit.
"""

import re

from outreach.company_settings import ALIASES, InvalidField, LABELS, next_missing, validate

_KEY_VALUE = re.compile(r"^\s*([a-zA-Z][a-zA-Z_ ]{1,30}?)\s*[:=]\s*(.+?)\s*$")


def _named_field(note):
    """The field an explicit ``key: value`` message names, and the raw value - or (None, None)."""
    m = _KEY_VALUE.match(note)
    if not m:
        return None, None
    key = m.group(1).strip().lower()
    canonical = key.replace(" ", "_")
    field = ALIASES.get(key) or (canonical if canonical in LABELS else None)
    return field, m.group(2)


def interpret(note, settings):
    """``settings`` is the live, currently-stored settings dict (so the guided order is read from
    the actual state, never a cached one)."""
    note = (note or "").strip()
    if not note:
        return {"status": "unclear"}
    field, raw = _named_field(note)
    if field is None:
        asking = next_missing(settings)
        if asking is None:
            return {"status": "unclear"}  # nothing pending, and no field named: not a company edit
        field, raw = asking[0], note
    label = LABELS.get(field, field)
    try:
        value = validate(field, raw)
    except InvalidField as exc:
        return {"status": "invalid", "field": field, "label": label, "reason": str(exc)}
    return {"status": "ready", "field": field, "label": label, "value": value}
