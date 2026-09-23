"""Pure rendering and eligibility gates for founder-reviewed initial-email previews.

Written previews use a verified Research quote and a Drive handbook. Word screening does
not prove semantic support; the founder reviews the exact copy and cited source.
"""

import hashlib
import json
import re
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

from outreach import checks, eligibility

HANDBOOK = Path(__file__).resolve().parent / "handbook" / "prelaunch_initial.txt"
FIELDS = ("PRODUCT_NAME", "INTENDED_USE", "NEXT_WEEK_ACTION", "CTA_QUESTION",
          "SENDER_NAME", "FOUNDER_TITLE", "SENDER_WEBSITE", "POSTAL_ADDRESS")
# The Drive handbook supplies the offer wording, so a written draft needs only the identity
# fields that must never come from a model.
SIGNATURE_FIELDS = ("PRODUCT_NAME", "SENDER_NAME", "FOUNDER_TITLE", "SENDER_WEBSITE",
                    "POSTAL_ADDRESS")
OPT_OUT = 'If you don\'t want further outreach from me, reply "no thanks" and I\'ll stop.'
WITHHELD = "[draft withheld]"
TOKEN = re.compile(r"\[[^\]\n]+\]")


def assemble(written, values):
    """Build the body around the model's sentences. Greeting, signature, postal address and
    opt-out line are written here, never by the model."""
    signature = [f'{values["SENDER_NAME"]}', f'{values["FOUNDER_TITLE"]}, {values["PRODUCT_NAME"]}',
                 values["SENDER_WEBSITE"]]
    if values.get("SENDER_PHONE"):
        signature.append(values["SENDER_PHONE"])
    signature.append(values["POSTAL_ADDRESS"])
    return "\n\n".join([f'Hi {values["FIRST_NAME"]},', written["company"], written["product"],
                        written["ask"], "Best,\n" + "\n".join(signature) + "\n" + OPT_OUT])


def initial_template(path=HANDBOOK):
    """Read the versioned runtime template included in the Cloud Run image."""
    text = Path(path).read_text(encoding="utf-8")
    subject, body = text.strip().split("\n\n", 1)
    if not subject.startswith("Subject: "):
        raise ValueError("initial email subject is missing")
    return subject.removeprefix("Subject: ").strip(), "\n".join(
        line.rstrip() for line in body.strip().splitlines())


# A Sheet name is often shouted ("APPLIED MECHANICAL SYSTEMS INC"). The company's own site
# shows how it writes its name; we take that, never an abbreviation we made up.
LEGAL_SUFFIX = re.compile(r"[\s,]+(?:inc|llc|l\.l\.c|corp|corporation|co|company|ltd|"
                          r"limited|plc|lp|llp)\.?\s*$", re.I)


def verified_company_name(sheet_name, site_text):
    """Return (name, verified). The site's own capitalisation wins; otherwise title case."""
    sheet_name = " ".join(sheet_name.split())
    candidates = [sheet_name]
    stripped = LEGAL_SUFFIX.sub("", sheet_name).strip(" ,.&-")
    if stripped and stripped != sheet_name:
        candidates.append(stripped)
    for candidate in candidates:
        if not candidate:
            continue
        pattern = r"\s+".join(re.escape(word) for word in candidate.split())
        found = re.search(pattern, site_text or "", re.I)
        if found:
            return " ".join(found.group(0).split()), True
    return (stripped or sheet_name).title(), False


def _host(url):
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        return ""
    return (parsed.hostname or "").removeprefix("www.").lower()


def supported_quotes(lead, research_rows):
    """Match the current profile's Research rows to the evidence on the lead row."""
    site = _host(lead.get("Website", ""))
    stamp = lead.get("Profiled at", "")
    if not site or not stamp:
        return []
    result = []
    for fact in research_rows:
        if fact.get("Lead ID") != lead.get("Lead ID") or fact.get("Researched at") != stamp:
            continue
        category, quote, url = (fact.get("Category", ""), fact.get("Quote", ""),
                                fact.get("Page URL", ""))
        if category not in {"OFFERING", "MARKET"} or not (5 <= len(quote.split()) <= 50):
            continue
        host = _host(url)
        if not host or not (host == site or host.endswith("." + site)):
            continue
        if any(c in quote for c in "\r\n"):
            continue
        evidence_col = "Offerings evidence" if category == "OFFERING" else "Markets evidence"
        if f'"{quote}" ({url})' not in lead.get(evidence_col, ""):
            continue
        result.append({"category": category, "quote": quote, "url": url})
    return result


def opening_options(facts, company=""):
    """Show every current verified fact, but avoid weak copy as an automatic default."""
    options = []
    for fact in facts:
        quote, url = fact["quote"], fact["url"]
        path = urlparse(url).path.lower()
        residential = bool(re.search(r"(?:^|[/_-])residential(?:$|[/_-])", path))
        long_quote = len(quote.split()) > 35
        company_words = re.findall(r"[a-z0-9]+", company.casefold().removeprefix("the "))
        quote_words = re.findall(r"[a-z0-9]+", quote.casefold().removeprefix("the "))
        starts_with_company = len(company_words) >= 2 and quote_words[:2] == company_words[:2]
        run_in_heading = (not starts_with_company and bool(re.match(
            r"^(?:[A-Z][A-Za-z'’-]*\s+){2,4}[a-z]", quote)))
        cut_off = not quote.rstrip().endswith((".", "!", "?", "”"))
        fragment = not quote[:1].isupper()
        residential_words = bool(re.search(r"\b(residential|homeowners|homes)\b", quote, re.I))
        sentence_verb = bool(re.search(
            r"\b(is|are|was|were|has|have|include|includes|install|installs|modifies|"
            r"serve|serves|provide|provides|offer|offers|work|works|specialize|specializes|"
            r"build|builds|construct|constructs|deliver|delivers|perform|performs)\b", quote, re.I))
        generic_boast = bool(re.search(r"\b(proud of its reputation|first-class)\b", quote, re.I))
        reasons = []
        if residential:
            reasons.append("residential page")
        if long_quote:
            reasons.append("too long for an opening")
        if run_in_heading:
            reasons.append("heading runs into sentence")
        if cut_off:
            reasons.append("appears cut off")
        if fragment:
            reasons.append("starts mid-sentence")
        if residential_words:
            reasons.append("mentions residential work")
        if not sentence_verb:
            reasons.append("not a complete sentence")
        if generic_boast:
            reasons.append("generic self-description")
        score = (2 * (fact["category"] == "OFFERING")
                 + 2 * bool(re.search(r"\b(commercial|industrial|office|school|hospital|"
                                      r"facility|warehouse|tenant|project)\w*\b", quote, re.I))
                 + 2 * bool(re.search(r"\b(install|modif|renovat|construct|build)\w*\b", quote, re.I)))
        quote_id = hashlib.sha256(
            f'{fact["category"]}\0{quote}\0{url}'.encode()).hexdigest()[:16]
        options.append({**fact, "quote_id": quote_id,
                        "usable": not (residential or residential_words or long_quote),
                        "default_eligible": not reasons, "warnings": reasons,
                        "score": score})
    return options


# Automatic opening selection (founder, 2026-09-23): prefer specific work or projects over
# generic services, market lists and self-praise; never force an opener when none is good.
DOING = re.compile(r"\b(install\w*|modif\w*|fabricat\w*|construct\w*|build\w*|renovat\w*|"
                   r"retrofit\w*|upgrad\w*|replac\w*|repip\w*|wir\w*|pip\w*|weld\w*|"
                   r"maintain\w*|servic\w+|design\w*|engineer\w*|complet\w+|deliver\w+)\b", re.I)
PROJECT_WORDS = re.compile(r"\b(construction|build-?out\w*|fit-?out\w*|tenant|design[-/ ]build|"
                           r"new construction|renovation\w*|retrofit\w*|project\w*|portfolio|"
                           r"installation\w*)\b", re.I)
PLACES = re.compile(r"\b(school\w*|hospital\w*|clinic\w*|universit\w*|college\w*|campus\w*|"
                    r"office\w*|retail|restaurant\w*|warehouse\w*|plant\w*|facilit\w*|"
                    r"church\w*|mall\w*|bank\w*|hotel\w*|arena\w*|venue\w*|treatment|"
                    r"data cent\w*|manufactur\w*|distribution|municipal\w*|"
                    r"commercial|industrial|institutional)\b", re.I)
# An opener must stand on its own. "In all three markets ..." refers to something the reader
# has not been told.
BACK_REFERENCE = re.compile(r"^(?:in (?:all|both|these|those|that|this)\b|for (?:these|those|it)\b|"
                            r"also\b|additionally\b|they\b|these\b|those\b|it\b|we also\b)", re.I)
# A quote that only says it provides services, with nothing specific attached.
GENERIC_ONLY = re.compile(r"^(?:the\s+)?[\w.,'&\- ]{0,60}?\b(?:specializes? in|provides?|offers?|"
                          r"is a|are a)\b[^.]{0,80}\b(?:services?|solutions?|needs?)\b[^.]{0,20}\.?$",
                          re.I)
# A source quote is refused only when nothing in it may be used: residential work, or no
# work at all. A heading, a boast or a clipped edge is a reason to prefer another quote, not
# to throw the source away — the model may still take a factual span from it, and the email
# checks (unsupported words, self-praise) decide what actually reaches the recipient.
DISQUALIFYING = {"mentions residential work", "residential page"}
PENALTIES = {"heading runs into sentence": 1, "appears cut off": 1, "starts mid-sentence": 2,
             "not a complete sentence": 1, "generic self-description": 3,
             "too long for an opening": 2}


def rank_opening(option):
    """Score one verified quote as a source for the opening, with what marked it down.

    Returns (score, reasons). A score of None means the source itself must not be used.
    """
    quote = option["quote"]
    warnings = set(option.get("warnings", []))
    reasons = sorted(warnings & DISQUALIFYING)
    if not option.get("usable"):
        reasons.append("not usable for a commercial pilot")
    if reasons:
        return None, reasons

    from outreach.writer import SELF_PRAISE  # local import keeps this module import-light
    penalty = sum(weight for warning, weight in PENALTIES.items() if warning in warnings)
    notes = sorted(warnings & set(PENALTIES))
    if SELF_PRAISE.search(quote):
        # Usable as a source; the email may not repeat the boast, and that is checked there.
        penalty += 1
        notes.append("contains the company's own praise, which the email may not repeat")

    doing = bool(DOING.search(quote))
    project = bool(PROJECT_WORDS.search(quote))
    places = len(set(m.group(0).lower() for m in PLACES.finditer(quote)))
    if not (doing or project):
        return None, ["names no work the company does"]
    if GENERIC_ONLY.match(quote.strip()) and not (project or places):
        return None, ["only a generic description of services"]
    commas = quote.count(",")
    listy = commas >= 3 and not doing
    back_reference = bool(BACK_REFERENCE.match(quote.strip()))
    score = (3 * project + 2 * doing + min(places, 3)
             + (option["category"] == "OFFERING") - (2 if listy else 0)
             - (2 if back_reference else 0) - penalty)
    if listy:
        notes.append("reads as a list of markets")
    if back_reference:
        notes.append("opens by referring to something unsaid")
    return score, sorted(set(notes))


def choose_opening(options):
    """Pick the opening automatically, or return None when nothing is good enough.

    Returns (chosen, report): report lists every candidate with its score or its reasons, so a
    lead held for review says why.
    """
    report = []
    for option in options:
        score, reasons = rank_opening(option)
        report.append({"quote_id": option["quote_id"], "quote": option["quote"],
                       "url": option["url"], "category": option["category"],
                       "score": score, "reasons": reasons})
    ranked = [(r["score"], r["quote_id"], r) for r in report if r["score"] is not None]
    if not ranked:
        return None, report
    # Deterministic: best score, then the quote id, so the same evidence always wins.
    ranked.sort(key=lambda item: (-item[0], item[1]))
    best = ranked[0][2]
    chosen = next(o for o in options if o["quote_id"] == best["quote_id"])
    return chosen, report


def _fill(template, values):
    for key, value in values.items():
        template = template.replace(f"[{key}]", value)
    return template


def verified_first_name(lead):
    """Use the named decision maker only when their recorded address is the recipient."""
    recipient = lead.get("BEST EMAIL", "").strip().casefold()
    contact_email = lead.get("Their email", "").strip().casefold()
    if not recipient or recipient != contact_email:
        return "there"
    local_part = recipient.partition("@")[0]
    if local_part in checks.GENERIC_INBOXES | {"owner", "owners", "president", "ceo", "founder"}:
        return "there"
    name = lead.get("Decision maker", "").split(",", 1)[0].strip()
    parts = name.split()
    if not 2 <= len(parts) <= 4 or any(p.casefold() in {"and", "or"} for p in parts):
        return "there"
    if not all(p.replace("-", "").replace("'", "").isalpha() for p in parts):
        return "there"
    if parts[0].casefold() in {"owner", "president", "ceo", "founder", "office", "team"}:
        return "there"
    return parts[0]


def _finish(lead, settings, sender_email, subject, body, evidence, chosen, options, blockers,
            *, handbook=None, written=None):
    """Last checks shared by both paths, then the approval hash over everything that matters."""
    # A body already withheld for other reasons must not invent extra blockers about itself.
    if body != WITHHELD:
        if TOKEN.search(subject + "\n" + body):
            blockers.append("unresolved template placeholder")
        if not body.endswith(OPT_OUT):
            blockers.append("opt-out footer is missing")
        if len(body) > 2500:
            blockers.append("body exceeds the pilot length limit")
    if "\n" in subject or "\r" in subject or len(subject) > 100:
        blockers.append("subject is invalid")

    recipient = lead.get("BEST EMAIL", "").strip().lower()
    if not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", recipient):
        blockers.append("recipient email is invalid")
    if not lead.get("Company", "").strip():
        blockers.append("company name is missing")
    if not settings.get("version"):
        blockers.append("handbook version is missing")

    preview_date = datetime.now(ZoneInfo("America/New_York")).date().isoformat()
    digest = None
    if not blockers:
        material = {"lead_id": lead["Lead ID"], "to": recipient, "subject": subject,
                    "from": sender_email.lower(), "body": body, "evidence": evidence,
                    "quote_id": chosen["quote_id"], "version": settings["version"],
                    "preview_date": preview_date,
                    "handbook": (handbook or {}).get("content_hash", ""),
                    "handbook_doc": (handbook or {}).get("document_id", "")}
        digest = hashlib.sha256(json.dumps(material, sort_keys=True).encode()).hexdigest()
    return {"lead_id": lead.get("Lead ID", ""), "company": lead.get("Company", ""),
            "to": recipient, "subject": subject, "body": body, "evidence": evidence,
            "evidence_options": options, "selected_quote_id": chosen["quote_id"] if chosen else None,
            "handbook_hash": (handbook or {}).get("content_hash", ""),
            "written": {k: v for k, v in (written or {}).items() if k != "usage"} or None,
            "preview_date": preview_date, "blockers": blockers, "preview_hash": digest}


def preview(lead, research_rows, settings, *, suppressed=None, subject_template=None,
            selected_quote_id=None, handbook=None, written=None, company=None):
    """Return reviewable copy and blockers. A hash exists only for send-ready copy.

    `suppressed=None` means the suppression list was unavailable; this blocks a write.
    Approval of the exact hash is still required before Gmail draft creation.

    With `handbook` and `written` (from `writer.compose`), the copy is the model's grounded
    sentences inside a signature this code controls, and the handbook's content hash is bound
    into the approval hash: edit the Drive document and the approval dies with it.
    """
    blockers = []
    if written is not None and not handbook:
        blockers.append("a written draft needs its handbook identity")
    ok, why = eligibility.draft_eligible(lead)
    if not ok:
        blockers.append(why)
    if lead.get("Profile status") != "READY":
        blockers.append("company profile is not READY")
    if any(lead.get(k) for k in ("Draft action", "Draft status", "Draft ID", "Draft link")):
        blockers.append("a draft action or draft already exists")
    if suppressed is None:
        blockers.append("suppression has not been checked")
    elif suppressed:
        blockers.append("address or domain is suppressed")

    options = opening_options(supported_quotes(lead, research_rows),
                              company or lead.get("Company", ""))
    if written is not None:
        # The writer must have cited a quote that is still verified for this lead right now.
        cited = (written.get("evidence") or {}).get("quote_id", "")
        selected_quote_id = cited if cited else "missing"
    if selected_quote_id:
        selected = [f for f in options if f["quote_id"] == selected_quote_id]
        chosen = selected[0] if len(selected) == 1 else None
        if not chosen:
            blockers.append("selected opening quote is not among current verified quotes")
        elif not chosen["usable"]:
            blockers.append("selected opening quote is not usable for this commercial pilot")
    else:
        chosen = max((f for f in options if f["default_eligible"]),
                     key=lambda f: f["score"], default=None)
    if not chosen:
        blockers.append("no current, verified company quote" if not options
                        else "no strong default opening quote; select a verified option")
    evidence = ({key: chosen[key] for key in ("category", "quote", "url")} if chosen else None)

    required = SIGNATURE_FIELDS if written is not None else FIELDS
    values = {key: str(settings.get(key.lower(), "")).strip() or f"[{key}]" for key in FIELDS}
    for key in required:
        if not values[key] or TOKEN.search(values[key]):
            blockers.append(f"handbook field {key} is missing")
    if settings.get("offer_approved") is not True:
        blockers.append("founder has not approved the offer wording")
    sender_email = str(settings.get("sender_email", "")).strip()
    if not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", sender_email):
        blockers.append("sender email is missing or invalid")
    try:
        daily_cap = int(settings.get("daily_cap", 0))
    except (TypeError, ValueError):
        daily_cap = 0
    if not 1 <= daily_cap <= 30:
        blockers.append("daily cap must be between 1 and 30")
    if not _host(values["SENDER_WEBSITE"]):
        blockers.append("sender website is invalid")
    if written is None and values["CTA_QUESTION"] and not values["CTA_QUESTION"].endswith("?"):
        blockers.append("CTA must be a question")
    if values["POSTAL_ADDRESS"] and len(values["POSTAL_ADDRESS"]) < 10:
        blockers.append("postal address is too short")
    if any("\n" in v or "\r" in v for v in values.values()):
        blockers.append("handbook fields must be one line each")

    values["FIRST_NAME"] = verified_first_name(lead)
    if any(c in values["FIRST_NAME"] for c in "\r\n"):
        blockers.append("first name is invalid")
    values["VERIFIED_COMPANY_OBSERVATION"] = (
        f'Your site says, “{evidence["quote"]}”' if evidence else "[VERIFIED_COMPANY_OBSERVATION]")
    subject_source, body_source = initial_template()
    subject_source = subject_template or subject_source
    # Optional signature phone (founder, 2026-09-22). Absent: the line is dropped entirely.
    phone = str(settings.get("sender_phone", "")).strip()
    if phone:
        if not re.fullmatch(r"\+?1?[\s.-]?\(?\d{3}\)?[\s.-]?\d{3}[\s.-]?\d{4}", phone):
            blockers.append("sender phone is invalid")
        values["SENDER_PHONE"] = phone
    else:
        body_source = body_source.replace("[SENDER_PHONE]\n", "")
    values["COMPANY"] = (company or lead.get("Company", "")).strip()
    if written is not None:
        subject = written["subject"]
        body = assemble(written, values) if not blockers else WITHHELD
        return _finish(lead, settings, sender_email, subject, body, evidence, chosen, options,
                       blockers, handbook=handbook, written=written)
    subject = _fill(subject_source, values)
    body = _fill(body_source, values)
    return _finish(lead, settings, sender_email, subject, body, evidence, chosen, options,
                   blockers, handbook=handbook)
