"""Interpret a short typed instruction about a lead into a proposed change for the founder to confirm.

Deterministic and read-only: it never writes and never calls a model, so it cannot invent a value - it
only restates, in a structured proposal, what the founder typed. The console writes only when the founder
confirms, through the lead routes (append for a new lead, a system-column update for an existing one).

Two boundaries are built in, matching the rest of the system:
  * A new lead's fields are taken verbatim from the instruction; nothing is guessed.
  * An existing lead's FOUNDER columns (its company, email, website, contact, phone) are protected - the
    system never overwrites them. An instruction to change one is reported as protected, not applied. Only
    the system columns this code owns (fit, profile status, email check, evidence, ...) can be updated.

Format the founder uses (fields separated by a newline or a `|`):
    add | Company: Acme Electric | email: sam@acme.test | website: https://acme.test
    update A-0001 | fit: QUALIFIED | profile: READY | email check: OK
"""

import re
import uuid

from outreach.sheet import SYSTEM_COLUMNS

# Natural words -> the canonical Sheet column. Lowercase keys; longest alias wins on a tie.
FIELD_ALIASES = {
    "company": "Company", "name of company": "Company",
    "contact": "Decision maker", "decision maker": "Decision maker", "contact name": "Decision maker",
    "email": "BEST EMAIL", "best email": "BEST EMAIL", "e-mail": "BEST EMAIL",
    "website": "Website", "site": "Website", "url": "Website", "web": "Website",
    "phone": "Phone", "phone number": "Phone", "number": "Phone",
    "email check": "Email check", "check": "Email check",
    "fit": "Fit",
    "profile": "Profile status", "profile status": "Profile status", "status": "Profile status",
    "profiled at": "Profiled at",
    "offerings evidence": "Offerings evidence", "offering evidence": "Offerings evidence",
    "evidence": "Offerings evidence", "offering": "Offerings evidence",
}
# Columns this code owns and may set on an EXISTING lead; everything else on an existing row is the
# founder's and is protected. A new lead (append) may carry any of the aliased columns.
_SYSTEM = set(SYSTEM_COLUMNS)
# Values uppercased so "qualified"/"ready"/"ok" land as the system's enums.
_UPPERCASE_COLUMNS = {"Email check", "Fit", "Profile status"}
_LEAD_ID = re.compile(r"\b([A-Za-z]-[A-Za-z0-9]{3,})\b")
_EMAIL = re.compile(r"[^\s@]+@[^\s@]+\.[^\s@]+")
_URL = re.compile(r"https?://[^\s|]+", re.I)


_LEADING_OP = re.compile(r"^\s*(add|create|new lead|update|set|change|edit)\b\s*", re.I)


def _parse_fields(note):
    """{canonical column: value} from `field: value` / `field = value` segments, plus a lone email/URL."""
    # Strip a leading operation word and lead ID so the first field's key is not polluted
    # ("add Company: Acme" -> key "Company", not "add Company").
    cleaned = _LEADING_OP.sub("", note)
    cleaned = re.sub(r"^\s*" + _LEAD_ID.pattern + r"\s*", "", cleaned)
    fields = {}
    leftovers = []  # segments that are not a recognised `field: value`; a bare email/URL may live here
    for segment in re.split(r"[\n|]+", cleaned):
        m = re.match(r"\s*([A-Za-z][A-Za-z /-]*?)\s*[:=]\s*(.+?)\s*$", segment)
        col = FIELD_ALIASES.get(m.group(1).strip().lower()) if m else None
        if col:
            value = m.group(2).strip()
            fields[col] = value.upper() if col in _UPPERCASE_COLUMNS else value
        elif segment.strip():
            leftovers.append(segment)
    # Auto-detect a bare email/URL ONLY from the leftover text, never from inside a labelled value.
    # (A URL inside an Offerings-evidence value, for instance, must stay intact for quote matching.)
    leftover_text = " ".join(leftovers)
    if "BEST EMAIL" not in fields:
        found = _EMAIL.search(leftover_text)
        if found:
            fields["BEST EMAIL"] = found.group(0)
    if "Website" not in fields:
        found = _URL.search(leftover_text)
        if found:
            fields["Website"] = found.group(0)
    return fields


def _valid_email(value):
    return bool(_EMAIL.fullmatch(value.strip()))


def interpret(note, leads, *, columns):
    """A proposal for the founder to confirm, as a dict with a `status`:

      unclear       - no field could be read from the instruction
      need_more     - an add is missing a company or any way to reach the lead
      bad_email     - a supplied email is not a valid address
      no_lead       - an update names a lead ID that does not exist
      protected     - an update would change a founder column (company/email/website/contact/phone)
      ready         - everything needed, with `op` ("add"/"update"), the fields, and a Lead ID for update

    Reads only; writes nothing. `columns` is the destination tab header, so an add never proposes a field
    the tab cannot store."""
    note = str(note or "").strip()
    fields = _parse_fields(note)
    if not fields:
        return {"status": "unclear"}

    for col in ("BEST EMAIL",):
        if col in fields and not _valid_email(fields[col]):
            return {"status": "bad_email", "value": fields[col]}

    target = next((lid for lid in _LEAD_ID.findall(note) if lid in leads), None)
    wants_add = bool(re.search(r"\badd\b|\bnew lead\b|\bcreate\b", note, re.I))

    if target and not wants_add:
        changing = [c for c in fields if c not in _SYSTEM]
        if changing:
            return {"status": "protected", "lead_id": target, "columns": sorted(changing)}
        if not fields:
            return {"status": "unclear"}
        return {"status": "ready", "op": "update", "lead_id": target, "fields": fields,
                "company": leads[target].get("Company", ""), "submission_id": _sid()}

    # An add. A lead ID in the text that is NOT an existing lead is ignored (we never reuse it).
    if _LEAD_ID.search(note) and not target and not wants_add:
        return {"status": "no_lead", "lead_id": _LEAD_ID.search(note).group(1)}
    missing_dest = [c for c in fields if c not in set(columns)]
    if missing_dest:
        return {"status": "need_more", "reason": "unstorable", "columns": sorted(missing_dest)}
    if not fields.get("Company") or not (fields.get("BEST EMAIL") or fields.get("Phone")
                                         or fields.get("Website")):
        return {"status": "need_more", "reason": "add_needs_company_and_contact"}
    return {"status": "ready", "op": "add", "fields": fields, "submission_id": _sid()}


def _sid():
    return f"leadchat-{uuid.uuid4().hex[:16]}"


def validate(op, *, lead_id, fields, leads, columns):
    """Re-check a confirmed proposal at the write boundary, so the server never trusts the client.
    Returns None when it may proceed, or a refusal reason string matching interpret's statuses."""
    fields = fields or {}
    if not fields:
        return "unclear"
    if "BEST EMAIL" in fields and not _valid_email(str(fields["BEST EMAIL"])):
        return "bad_email"
    if op == "update":
        if lead_id not in leads:
            return "no_lead"
        if any(c not in _SYSTEM for c in fields):
            return "protected"
        return None
    if op == "add":
        if any(c not in set(columns) for c in fields):
            return "unstorable"
        if not fields.get("Company") or not (fields.get("BEST EMAIL") or fields.get("Phone")
                                             or fields.get("Website")):
            return "need_more"
        return None
    return "unclear"


def build_add_row(fields):
    """A new lead row with a stable Lead ID assigned from its contact details (never reused)."""
    from outreach import importer
    key = (fields.get("BEST EMAIL") or fields.get("Phone")
           or (fields.get("Company", "") + "|" + fields.get("Website", ""))).strip().lower()
    return dict(fields, **{"Lead ID": importer.stable_lead_id("A", key)})
