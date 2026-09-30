"""Bring a small list of leads into the system's shape, without touching the live Sheet.

`import_leads` takes rows a founder pasted or exported (their own headers, in any order) and returns
lead rows in the Sheet's shape: a Lead ID assigned, the founder's fields mapped to canonical columns,
and each lead's channel worked out (`outreach/channels.py`). It keeps **email, phone-only and
company-only** records — a lead with only a phone or only a company name is imported, not dropped, so
it stays usable for a call or for enrichment.

It is pure: it parses and normalizes, it does not read or write Google, and it never invents a
contact. Writing the accepted rows to a store is a separate, deliberate step (see `docs/MVP_DELIVERY.md`);
this module only prepares them and reports what it did.

Excel (.xlsx) is not read here: it needs a third-party parser, which the repository rules do not allow
today (see the conflicts in `docs/MVP_DELIVERY.md`). CSV and tab-separated text, which the standard
library reads, are supported; a spreadsheet can be exported to CSV.
"""

import csv
import io
import re

from outreach import channels

# Founder headers we understand, mapped to the Sheet's canonical lead columns. Matching is
# case-insensitive on the trimmed header; the first header present wins.
COMPANY_HEADERS = ("company", "company name", "business", "business name", "account")
CONTACT_HEADERS = ("decision maker", "contact", "contact name", "name", "owner", "person")
WEBSITE_HEADERS = ("website", "url", "site", "web", "domain", "web site")
CANONICAL = "Lead ID", "Company", "Decision maker", "BEST EMAIL", "Website", "Phone"

_DIGITS = re.compile(r"\d")
_LEAD_ID = re.compile(r"^([A-Za-z]+)-(\d+)$")


def records_from_csv(text):
    """Rows from CSV or tab-separated text, each a dict of the file's own headers to values.

    The delimiter is sniffed (comma or tab); an unreadable file gives an empty list rather than
    raising, so a bad paste is reported as "nothing to import", not a crash."""
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


def _pick(record, headers):
    lowered = {str(key).strip().lower(): value for key, value in record.items()}
    for header in headers:
        value = str(lowered.get(header, "") or "").strip()
        if value:
            return value
    return ""


def _normalize(record):
    """A founder record mapped to canonical lead columns (no Lead ID yet)."""
    return {
        "Company": _pick(record, COMPANY_HEADERS),
        "Decision maker": _pick(record, CONTACT_HEADERS),
        "BEST EMAIL": channels.email_of(record),
        "Website": _pick(record, WEBSITE_HEADERS),
        "Phone": channels.phone_of(record),
    }


def _dedupe_key(row):
    """What makes two rows the same lead: the email, else the phone's digits, else company+website.

    Returns None when there is nothing to compare on (handled as skipped upstream)."""
    email = row["BEST EMAIL"].lower()
    if email:
        return ("email", email)
    phone = "".join(_DIGITS.findall(row["Phone"]))
    if phone:
        return ("phone", phone)
    company = row["Company"].strip().lower()
    if company:
        return ("company", company, row["Website"].strip().lower())
    return None


def _next_number(existing_leads, prefix):
    """One past the highest Lead ID number already used for this prefix."""
    highest = 0
    for lead_id in existing_leads:
        match = _LEAD_ID.match(str(lead_id))
        if match and match.group(1).upper() == prefix.upper():
            highest = max(highest, int(match.group(2)))
    return highest + 1


def import_leads(records, existing_leads, *, prefix="A"):
    """Prepare a small list for import. Nothing is written.

    `records` are dicts with the founder's own headers. `existing_leads` is {Lead ID: row} already in
    the system, used to skip duplicates and to continue the Lead ID numbering. Returns:

      accepted:   canonical lead rows with a Lead ID assigned (founder columns only for what was given)
      channels:   {Lead ID: EMAIL|CALL|COMPANY_ONLY}
      skipped:    [{record, reason}] - a row with no company, email or phone
      duplicates: [{record, matched, reason}] - matched an existing lead or an earlier accepted row
      summary:    counts, including a per-channel breakdown of what was accepted
    """
    prefix = str(prefix).strip().upper() or "A"
    seen = {}
    for lead_id, row in (existing_leads or {}).items():
        canonical = {"BEST EMAIL": channels.email_of(row), "Phone": channels.phone_of(row),
                     "Company": str(row.get("Company", "") or "").strip(),
                     "Website": str(row.get("Website", "") or "").strip()}
        key = _dedupe_key(canonical)
        if key is not None:
            seen.setdefault(key, lead_id)

    number = _next_number(existing_leads or {}, prefix)
    accepted, channel_map, skipped, duplicates = [], {}, [], []
    for record in records or []:
        row = _normalize(record)
        key = _dedupe_key(row)
        if key is None:
            skipped.append({"record": record,
                            "reason": "no company, email or phone to import"})
            continue
        if key in seen:
            duplicates.append({"record": record, "matched": seen[key],
                               "reason": f"already present as {seen[key]}"})
            continue
        lead_id = f"{prefix}-{number:04d}"
        number += 1
        seen[key] = lead_id
        row["Lead ID"] = lead_id
        channel = channels.channel_of(row)
        accepted.append(row)
        channel_map[lead_id] = channel

    by_channel = {channels.EMAIL: 0, channels.CALL: 0, channels.COMPANY_ONLY: 0}
    for channel in channel_map.values():
        by_channel[channel] += 1
    return {
        "accepted": accepted,
        "channels": channel_map,
        "skipped": skipped,
        "duplicates": duplicates,
        "summary": {"accepted": len(accepted), "skipped": len(skipped),
                    "duplicates": len(duplicates), "by_channel": by_channel},
    }
