"""Review an uploaded playbook's text and identify its parts, deterministically.

Pure and read-only: it parses the handbook text the founder uploaded into the initial-email section, the
follow-up sections and the timing rule, and lists what is missing or ambiguous. It never treats the text as
instructions and never calls a model - every judgement is a regex over the text. The immutable version of a
playbook is its content hash (the same normalisation the Drive handbook uses), so a changed file is a
different version and must be reviewed again.

This mirrors what `outreach/followup.py` already parses for follow-ups, extended to name the initial-email
section and the timing rule for the founder to inspect before selecting a version.
"""

import hashlib
import re

from outreach import followup

INITIAL_HEADING = re.compile(r"^\s*#*\s*initial\s*email\b", re.I)
# A heading line that bounds a section: a Markdown "#..." line, a follow-up heading, or a known title.
_HEADING = re.compile(r"^\s*#+\s+\S", re.I)
_KNOWN_TITLE = re.compile(r"^\s*(initial\s*email|follow[\s-]*up\s*[12]|fields?\b.*|what\s+to\b.*)\s*$", re.I)
# "third business day", "3 business days", etc.
_BUSINESS_DAY = re.compile(r"\b(\w+)\s+business\s+day", re.I)
_ORDINALS = {"first": 1, "second": 2, "third": 3, "fourth": 4, "fifth": 5, "sixth": 6,
             "seventh": 7, "eighth": 8, "ninth": 9, "tenth": 10,
             "one": 1, "two": 2, "three": 3, "four": 4, "five": 5}


def normalize(text):
    """The canonical text a hash is taken over - the same shape `handbook_drive` stores."""
    return str(text or "").replace("\r\n", "\n").replace("﻿", "").strip()


def content_hash(text):
    return hashlib.sha256(normalize(text).encode("utf-8")).hexdigest()


def _is_heading(line):
    return bool(_HEADING.match(line) or followup.HEADING.match(line) or _KNOWN_TITLE.match(line))


def _initial_email(lines):
    start = next((i for i, line in enumerate(lines) if INITIAL_HEADING.match(line)), None)
    if start is None:
        return {"present": False, "paragraphs": [], "problem": 'no "Initial email" section'}
    end = next((i for i in range(start + 1, len(lines)) if _is_heading(lines[i])), len(lines))
    section = lines[start + 1:end]
    greeting = next((i for i, line in enumerate(section) if followup.GREETING.match(line)), None)
    sign_off = next((i for i, line in enumerate(section)
                     if greeting is not None and i > greeting and followup.SIGN_OFF.match(line)), None)
    if greeting is None:
        return {"present": False, "paragraphs": [], "problem": 'the initial email has no "Hi [FIRST_NAME]," line'}
    if sign_off is None:
        return {"present": False, "paragraphs": [], "problem": 'the initial email has no "Best," line'}
    paragraphs = followup._paragraphs(section[greeting + 1:sign_off])
    if not paragraphs:
        return {"present": False, "paragraphs": [], "problem": 'the initial email has nothing between the greeting and "Best,"'}
    return {"present": True, "paragraphs": paragraphs, "problem": ""}


def _business_days(text):
    found = []
    for word in _BUSINESS_DAY.findall(text):
        key = word.strip().lower()
        if key.isdigit():
            found.append(int(key))
        elif key in _ORDINALS:
            found.append(_ORDINALS[key])
    return found


def review(text):
    """A structured review of the playbook text for the founder to inspect before selecting a version.

    Returns the content hash (the immutable version id), the identified initial-email and follow-up
    sections, the timing rule, the offer values it states, and the missing/ambiguous lists. Writes nothing."""
    text = normalize(text)
    lines = text.split("\n")

    initial = _initial_email(lines)
    parts, follow_problems = followup.templates(text)
    offer, offer_conflicts = followup.offer_values(text)
    days = _business_days(text)

    follow_ups = {str(step): {"present": step in parts, "paragraphs": parts.get(step, [])}
                  for step in (1, 2)}
    timing = {"stated": bool(days), "business_days": days,
              "note": ("follow-up timing: " + ", ".join(f"{d} business day(s)" for d in days))
                      if days else "no business-day timing rule was found"}

    missing = []
    if not initial["present"]:
        missing.append(initial["problem"])
    missing.extend(follow_problems)
    if not days:
        missing.append("no follow-up timing rule (a business-day count) was found")
    # Ambiguous = things stated more than one way (the handbook contradicts itself).
    ambiguous = list(offer_conflicts)

    return {
        "content_hash": content_hash(text),
        "length": len(text),
        "initial_email": initial,
        "follow_ups": follow_ups,
        "timing": timing,
        "offer_values": offer,
        "missing": missing,
        "ambiguous": ambiguous,
        "usable_for_followups": not follow_problems and not offer_conflicts,
    }
