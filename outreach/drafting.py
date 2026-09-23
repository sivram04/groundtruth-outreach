"""Pure, fail-closed rendering of founder-reviewed initial-email previews.

Company words are copied from a previously verified Research quote. The model does not
paraphrase a company's finances or invent a pain point in this pilot.
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
TOKEN = re.compile(r"\[[^\]\n]+\]")


def initial_template(path=HANDBOOK):
    """Read the versioned runtime template included in the Cloud Run image."""
    text = Path(path).read_text(encoding="utf-8")
    subject, body = text.strip().split("\n\n", 1)
    if not subject.startswith("Subject: "):
        raise ValueError("initial email subject is missing")
    return subject.removeprefix("Subject: ").strip(), "\n".join(
        line.rstrip() for line in body.strip().splitlines())


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


def preview(lead, research_rows, settings, *, suppressed=None, subject_template=None,
            selected_quote_id=None):
    """Return reviewable copy and blockers. A hash exists only for send-ready copy.

    `suppressed=None` means the suppression list was unavailable; this blocks a write.
    Approval of the exact hash is still required before Gmail draft creation.
    """
    blockers = []
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

    options = opening_options(supported_quotes(lead, research_rows), lead.get("Company", ""))
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

    values = {key: str(settings.get(key.lower(), "")).strip() or f"[{key}]" for key in FIELDS}
    for key in FIELDS:
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
    if values["CTA_QUESTION"] and not values["CTA_QUESTION"].endswith("?"):
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
    values["COMPANY"] = lead.get("Company", "").strip()
    subject = _fill(subject_source, values)
    body = _fill(body_source, values)
    if TOKEN.search(subject + "\n" + body):
        blockers.append("unresolved template placeholder")
    if "\n" in subject or "\r" in subject or len(subject) > 100:
        blockers.append("subject is invalid")
    if not body.endswith('reply "no thanks" and I\'ll stop.'):
        blockers.append("opt-out footer is missing")
    if len(body) > 2500:
        blockers.append("body exceeds the pilot length limit")

    recipient = lead.get("BEST EMAIL", "").strip().lower()
    if not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", recipient):
        blockers.append("recipient email is invalid")
    if not values["COMPANY"]:
        blockers.append("company name is missing")
    if not settings.get("version"):
        blockers.append("handbook version is missing")

    preview_date = datetime.now(ZoneInfo("America/New_York")).date().isoformat()
    digest = None
    if not blockers:
        material = {"lead_id": lead["Lead ID"], "to": recipient, "subject": subject,
                    "from": sender_email.lower(), "body": body, "evidence": evidence,
                    "quote_id": chosen["quote_id"], "version": settings["version"],
                    "preview_date": preview_date}
        digest = hashlib.sha256(json.dumps(material, sort_keys=True).encode()).hexdigest()
    return {"lead_id": lead.get("Lead ID", ""), "company": lead.get("Company", ""),
            "to": recipient, "subject": subject, "body": body, "evidence": evidence,
            "evidence_options": options, "selected_quote_id": chosen["quote_id"] if chosen else None,
            "preview_date": preview_date, "blockers": blockers, "preview_hash": digest}
