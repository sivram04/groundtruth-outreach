"""Bring a small list of leads into the system's shape, without touching the live Sheet.

The flow has two steps so a person can see exactly what will be stored before anything is written:

- `import_leads(records, existing_leads, prefix=, destination_columns=)` builds a **preview**: each
  record mapped to the destination tab's own columns, its channel, the fields that have **no column to
  go in** (shown, never silently dropped), the duplicates, the skipped rows, and a `fingerprint` that
  binds the accepted set.
- `prepare_commit(rows, existing_leads, prefix=)` takes the accepted rows back at commit time,
  re-checks them against the leads that exist **now** (so a row added in between is not added twice),
  assigns Lead IDs from the current numbering (so two commits cannot collide), and returns the rows to
  append. `store.append_leads` does the write.

It is pure: it parses and normalizes, it does not read or write Google, and it never invents a
contact. Email, phone-only, company-only and email+phone records are all kept, and every contact field
the user supplied is preserved where the destination can store it.

CSV, tab-separated text and **.xlsx** are read (all with libraries that run locally and send nothing to
any service). A spreadsheet in another format can be exported to one of these.
"""

import csv
import hashlib
import io
import json
import re

from outreach import channels

# Founder headers we understand, mapped to the Sheet's canonical lead columns. Matching is
# case-insensitive on the trimmed header; the first header present wins.
COMPANY_HEADERS = ("company", "company name", "business", "business name", "account")
CONTACT_HEADERS = ("decision maker", "contact", "contact name", "name", "owner", "person")
WEBSITE_HEADERS = ("website", "url", "site", "web", "domain", "web site")
# The canonical destination columns a lead tab is expected to have; a real tab's header overrides this.
CANONICAL = ["Lead ID", "Company", "Decision maker", "BEST EMAIL", "Website", "Phone"]
# A small list, imported at once. A larger file is refused rather than silently truncated.
MAX_ROWS = 1000

# Each contact role: (canonical destination column, the headers that mean it, a plain label).
_ROLES = (
    ("BEST EMAIL", channels.EMAIL_HEADERS, "email"),
    ("Phone", channels.PHONE_HEADERS, "phone"),
    ("Company", COMPANY_HEADERS, "company"),
    ("Decision maker", CONTACT_HEADERS, "contact"),
    ("Website", WEBSITE_HEADERS, "website"),
)
_ROLE_HEADERS = {h for _, headers, _ in _ROLES for h in headers}

_DIGITS = re.compile(r"\d")
_LEAD_ID = re.compile(r"^([A-Za-z]+)-(\d+)$")


def records_from_csv(text):
    """Rows from CSV or tab-separated text, each a dict of the file's own headers to values.

    The delimiter is sniffed (comma, tab or semicolon); an unreadable file gives an empty list rather
    than raising, so a bad paste is reported as "nothing to import", not a crash."""
    text = (text or "").lstrip("﻿")
    if not text.strip():
        return []
    try:
        dialect = csv.Sniffer().sniff(text[:2048], delimiters=",\t;")
    except csv.Error:
        dialect = csv.excel
    reader = csv.DictReader(io.StringIO(text), dialect=dialect)
    rows = []
    for raw in reader:
        rows.append({(key or "").strip(): (value or "").strip()
                     for key, value in raw.items() if key is not None})
    return rows


def _records_from_xlsx(data):
    """Rows from the first sheet of an .xlsx workbook, headers from its first row.

    openpyxl runs locally; nothing is sent anywhere. A cell that is a number or a date is read as its
    text, so a phone stored as a number is not lost."""
    import openpyxl  # imported here so the rest of the module needs no spreadsheet library

    workbook = openpyxl.load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    try:
        sheet = workbook.active
        rows = sheet.iter_rows(values_only=True)
        header_row = next(rows, None)
        if not header_row:
            return []
        headers = [("" if cell is None else str(cell).strip()) for cell in header_row]
        records = []
        for raw in rows:
            if raw is None:
                continue
            values = [("" if cell is None else str(cell).strip()) for cell in raw]
            if not any(values):
                continue
            records.append({headers[i]: (values[i] if i < len(values) else "")
                            for i in range(len(headers)) if headers[i]})
        return records
    finally:
        workbook.close()


def records_from_file(filename, data):
    """Rows from an uploaded file, by its extension. Raises ValueError for a type we cannot read."""
    name = str(filename or "").lower()
    if name.endswith(".xlsx"):
        return _records_from_xlsx(data)
    if name.endswith((".csv", ".tsv", ".txt")):
        return records_from_csv(data.decode("utf-8-sig", errors="replace")
                                if isinstance(data, (bytes, bytearray)) else str(data))
    raise ValueError("unsupported file type; upload a .csv, .tsv or .xlsx file")


def _pick(record, headers):
    lowered = {str(key).strip().lower(): value for key, value in record.items()}
    for header in headers:
        value = str(lowered.get(header, "") or "").strip()
        if value:
            return value
    return ""


def _semantic(record):
    """The contact facts a record carries, used for dedupe and channel regardless of the destination."""
    return {
        "email": channels.email_of(record),
        "phone": channels.phone_of(record),
        "company": _pick(record, COMPANY_HEADERS),
        "website": _pick(record, WEBSITE_HEADERS),
    }


def map_record(record, destination_columns):
    """(row keyed by destination column, unstorable). `unstorable` are fields with a value but no
    column in the destination to hold them - shown to the user, never silently dropped."""
    by_lower = {}
    for column in destination_columns:
        by_lower.setdefault(str(column).strip().lower(), column)  # first wins

    def destination_for(canonical, headers):
        if canonical.lower() in by_lower:
            return by_lower[canonical.lower()]
        for header in headers:
            if header in by_lower:
                return by_lower[header]
        return None

    row, unstorable, used = {}, [], set()
    for canonical, headers, label in _ROLES:
        value = (channels.email_of(record) if label == "email"
                 else channels.phone_of(record) if label == "phone"
                 else _pick(record, headers))
        if not value:
            continue
        column = destination_for(canonical, headers)
        if column and column not in used:
            row[column] = value
            used.add(column)
        else:
            unstorable.append({"field": label, "value": value})

    # Any other field the user supplied (a location, a title, ...): store it if the destination has a
    # column of that name, otherwise show it as unstorable rather than dropping it.
    for key, value in record.items():
        header = str(key).strip()
        text = str(value).strip()
        if not text or header.lower() in _ROLE_HEADERS:
            continue
        column = by_lower.get(header.lower())
        if column and column not in used:
            row[column] = text
            used.add(column)
        elif column is None:
            unstorable.append({"field": header, "value": text})
    return row, unstorable


def _dedupe_key(semantic):
    """What makes two rows the same lead: the email, else the phone's digits, else company+website."""
    if semantic["email"]:
        return ("email", semantic["email"].lower())
    if semantic["phone"]:
        digits = "".join(_DIGITS.findall(semantic["phone"]))
        if digits:
            return ("phone", digits)
    if semantic["company"]:
        return ("company", semantic["company"].lower(), semantic["website"].lower())
    return None


def _existing_keys(existing_leads):
    seen = {}
    for lead_id, row in (existing_leads or {}).items():
        key = _dedupe_key(_semantic(row))
        if key is not None:
            seen.setdefault(key, lead_id)
    return seen


def _next_number(existing_leads, prefix):
    highest = 0
    for lead_id in existing_leads or {}:
        match = _LEAD_ID.match(str(lead_id))
        if match and match.group(1).upper() == prefix.upper():
            highest = max(highest, int(match.group(2)))
    return highest + 1


def fingerprint(rows, prefix, columns):
    """A stable hash of the accepted rows, the destination prefix AND the destination's columns, so a
    commit can prove it is writing exactly what the preview showed into the same schema. If the tab's
    columns change between preview and commit (e.g. a Phone column is removed), this changes and the
    commit is refused - a field is never silently dropped."""
    payload = json.dumps({"prefix": str(prefix).upper(), "rows": rows, "columns": list(columns)},
                         sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _invalid_contacts(record):
    """Contact values the user supplied that cannot be used, each with why. Never discarded silently:
    they are shown in the preview so the founder can fix them."""
    invalid = []
    raw_email = _pick(record, channels.EMAIL_HEADERS)
    if raw_email and not channels.email_of(record):
        invalid.append({"field": "email", "value": raw_email, "reason": "not a valid email address"})
    raw_phone = _pick(record, channels.PHONE_HEADERS)
    if raw_phone and not channels.phone_of(record):
        invalid.append({"field": "phone", "value": raw_phone,
                        "reason": "not enough digits for a phone number"})
    return invalid


def import_leads(records, existing_leads, *, prefix="A", destination_columns=None):
    """Build the import preview. Nothing is written.

    Returns accepted rows (each mapped to the destination columns, with a provisional Lead ID, its
    channel and its unstorable fields), the duplicates, the skipped rows, the aggregate unstorable
    field names, a summary, and a `fingerprint` that binds the accepted rows for the commit step.
    """
    prefix = str(prefix).strip().upper() or "A"
    destination_columns = list(destination_columns) if destination_columns else list(CANONICAL)
    seen = _existing_keys(existing_leads)
    number = _next_number(existing_leads, prefix)

    accepted, skipped, duplicates, unstorable_fields = [], [], [], []
    invalid_count = 0
    for record in records or []:
        semantic = _semantic(record)
        invalid = _invalid_contacts(record)
        key = _dedupe_key(semantic)
        if key is None:
            # Nothing to key on, but any supplied-yet-unusable contact values are still reported.
            skipped.append({"record": record, "reason": "no company, email or phone to import",
                            "invalid": invalid})
            invalid_count += len(invalid)
            continue
        if key in seen:
            duplicates.append({"record": record, "matched": seen[key],
                               "reason": f"already present as {seen[key]}"})
            continue
        row, unstorable = map_record(record, destination_columns)
        # A PROVISIONAL Lead ID for display only; the real ID is assigned atomically at append time
        # (Store.append_leads), so two instances importing at once cannot land on the same ID.
        lead_id = f"{prefix}-{number:04d}"
        number += 1
        seen[key] = lead_id
        # The channel is what the lead actually has (from the uploaded record), not what the
        # destination can store: a phone-only lead whose phone has no column is still a CALL lead in
        # the preview, with the phone shown as unstorable.
        accepted.append({"lead_id": lead_id, "channel": channels.channel_of(record), "row": row,
                         "unstorable": unstorable, "invalid": invalid})
        invalid_count += len(invalid)
        for item in unstorable:
            if item["field"] not in unstorable_fields:
                unstorable_fields.append(item["field"])

    by_channel = {channels.EMAIL: 0, channels.CALL: 0, channels.COMPANY_ONLY: 0}
    for item in accepted:
        by_channel[item["channel"]] += 1
    rows_only = [item["row"] for item in accepted]
    return {
        "prefix": prefix,
        "destination_columns": destination_columns,
        "accepted": accepted,
        "duplicates": duplicates,
        "skipped": skipped,
        "unstorable_fields": unstorable_fields,
        "summary": {"accepted": len(accepted), "duplicates": len(duplicates),
                    "skipped": len(skipped), "unstorable": len(unstorable_fields),
                    "invalid": invalid_count, "by_channel": by_channel},
        "fingerprint": fingerprint(rows_only, prefix, destination_columns),
    }


def prepare_commit(rows, existing_leads, *, prefix="A"):
    """(rows to append, rows now already present) from the accepted rows.

    Re-checks against the leads that exist NOW, so a row added since the preview is not added again.
    It does NOT assign Lead IDs: `Store.append_leads` allocates them from the atomic append, so two
    application instances committing at once cannot land on the same ID."""
    seen = _existing_keys(existing_leads)
    to_append, already_present = [], []
    for row in rows or []:
        key = _dedupe_key(_semantic(row))
        if key is not None and key in seen:
            already_present.append({"row": row, "matched": seen[key]})
            continue
        if key is not None:
            seen[key] = "(pending)"  # a second identical row in the same batch is caught too
        to_append.append(dict(row))
    return to_append, already_present
