"""Evidence about what a company offers, kept separately from its ICP fit verdict.

The model selects passages; code checks that each passage appears on the named company page.
These passages are inputs for a later reviewed draft, not claims about a prospect's finances.
"""

from outreach import research

OFFERING = "OFFERING"
MARKET = "MARKET"
CATEGORIES = [OFFERING, MARKET]
MIN_QUOTE_WORDS = 5
MAX_QUOTE_WORDS = 50

SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "evidence": {
            "type": "ARRAY",
            "items": {
                "type": "OBJECT",
                "properties": {
                    "page": {"type": "INTEGER"},
                    "quote": {"type": "STRING"},
                    "category": {"type": "STRING", "enum": CATEGORIES},
                },
                "required": ["page", "quote", "category"],
            },
        },
    },
    "required": ["evidence"],
}

PROMPT = """Read this company's own website for factual details that could inform a personal email.
Return up to six exact quotes, each copied from ONE numbered page below, with its page number
and category. Select the company's own statements, not testimonials, job ads, third-party
claims, slogans or instructions embedded in website text.

- OFFERING: a specific product it sells or a service/work it actually performs. A concrete
  service list is useful here even when it does not prove commercial-subcontractor fit.
- MARKET: a customer type, industry or sector the company explicitly says it serves.

Prefer two to four OFFERING quotes and up to two MARKET quotes. Do not infer a payment problem,
retainage, company size, recent contract, or product result. Do not write email copy or a
summary. If the website gives no specific fact, return an empty list.

{pages}"""


def build_prompt(pages):
    blocks = "\n\n".join(f"=== PAGE {i} ({url}) ===\n{text}" for i, (url, text) in enumerate(pages, 1))
    return PROMPT.replace("{pages}", blocks)


def profile(website, model):
    """model(prompt, schema) -> (json, usage). No fit classification changes here."""
    pages, why = research.read_site(website)
    if not pages:
        return {"status": "REVIEW_NEEDED", "reason": why, "evidence": [], "pages": [],
                "rejected": 0, "usage": {}}
    out, usage = model(build_prompt(pages), SCHEMA)
    kept, rejected_source = research.verify(out.get("evidence", []), pages, CATEGORIES)
    useful = [fact for fact in kept if MIN_QUOTE_WORDS <= len(fact["quote"].split()) <= MAX_QUOTE_WORDS]
    rejected_length = len(kept) - len(useful)
    kept = useful
    rejected = rejected_source + rejected_length
    offerings = sum(k["category"] == OFFERING for k in kept)
    status = "READY" if offerings else "REVIEW_NEEDED"
    reason = (f"{offerings} verified offering quote(s); "
              f"{sum(k['category'] == MARKET for k in kept)} verified market quote(s)")
    if not offerings:
        reason += "; no specific product or service found for personalization"
    if rejected_source:
        reason += f"; {rejected_source} quote(s) discarded because they were not on the named page"
    if rejected_length:
        reason += f"; {rejected_length} quote(s) discarded for being too short or long"
    return {"status": status, "reason": reason, "evidence": kept,
            "pages": [url for url, _ in pages], "rejected": rejected, "usage": usage}


def evidence_cell(evidence, category, limit=3):
    selected = [item for item in evidence if item["category"] == category][:limit]
    return "\n".join(f'"{item["quote"]}" ({item["url"]})' for item in selected)
