"""Stage 2: is this company a commercial trade subcontractor? Read from its own website.

The model only proposes quotes. The code keeps a quote only if it appears word for word in
the page it names, and the verdict is computed here from the kept quotes, never taken from
the model. Company fit is separate from email risk: this module never looks at the address.
"""

import re
import unicodedata
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from outreach import checks

QUALIFIED, REVIEW_NEEDED, DISQUALIFIED = "QUALIFIED", "REVIEW_NEEDED", "DISQUALIFIED"
COMMERCIAL_PROJECT, COMMERCIAL_SERVICE, RESIDENTIAL = "COMMERCIAL_PROJECT", "COMMERCIAL_SERVICE", "RESIDENTIAL"
GENERAL_CONTRACTOR = "GENERAL_CONTRACTOR"
CATEGORIES = [COMMERCIAL_PROJECT, COMMERCIAL_SERVICE, RESIDENTIAL, GENERAL_CONTRACTOR]
# Never offered to the model: set by the code when a project quote only speaks in general
# terms ("residential and commercial projects"). Counts like service; cannot qualify.
COMMERCIAL_GENERIC = "COMMERCIAL_GENERIC"
ALL_CATEGORIES = CATEGORIES + [COMMERCIAL_GENERIC]

# A quote only counts as project work if it says so in words, not because the model labelled
# it. Found necessary on the 2026-09-22 sample: fixture lists ("Toilet Installation and Repair"),
# product lines ("Cat 5 & Cat 6 Internet Cabling"), dealer statements and testimonials were
# labelled project work. Without one of these signals a project quote counts as service.
PROJECT_SIGNAL = re.compile(
    r"construct|build-?out|fit-?out|tenant|design[- /]?build|new build|\bbid|general contractor|"
    r"\bgcs?\b|builders?\b|prevailing wage|union|plan[- ]and[- ]spec|project|renovat|"
    r"hospital|school|universit|college|campus|industrial|institutional|manufactur|plant\b|"
    r"warehouse|distribution cent|office building|municipal|government|public work|church|"
    r"healthcare|data cent|facilit", re.I)
MIXED_MIN_PROJECT_QUOTES = 2

# Specific project evidence (founder review of the sample, 2026-09-22): a repeated generic phrase
# such as "residential and commercial projects" must not by itself establish commercial trade
# project work. A project quote is specific only if it names construction activity, or names a
# commercial sector together with project or installation work. A quote that also mentions
# homes or residential work must name construction activity.
CONSTRUCTION_ACTIVITY = re.compile(
    r"construct|build-?outs?\b|fit-?outs?\b|tenant|design[- /]?build|new build|\bbid|"
    r"general contractor|\bgcs?\b|\bbuilders?\b|prevailing wage|\bunion\b|plan[- ]?(and|&)[- ]?spec|"
    r"portfolio|turn-?key", re.I)
COMMERCIAL_SECTOR = re.compile(
    r"hospital|school|universit|college|campus|industrial|institutional|manufactur|\bplants?\b|"
    r"warehouse|distribution cent|office building|municipal|government|public work|church|"
    r"healthcare|data cent|facilit", re.I)
PROJECT_WORK = re.compile(r"project|renovat|install", re.I)
MENTIONS_RESIDENTIAL = re.compile(r"residential|\bhomes?\b|homeowner", re.I)


# A single quote can qualify a commercial-only firm only if it explicitly establishes commercial
# trade construction or installation work (founder, 2026-09-22): it names a commercial setting
# AND construction or installation work. "bid on your project" and "School District Projects
# Completed" name neither the work nor, respectively, the setting.
COMMERCIAL_SETTING = re.compile(
    r"commercial|industrial|institutional|tenant|office|retail|business|hospital|school|universit|"
    r"college|campus|warehouse|\bplants?\b|facilit|municipal|government|healthcare|manufactur|"
    r"data cent|church", re.I)
CONSTRUCTION_OR_INSTALLATION = re.compile(
    r"construct|install|build-?outs?\b|fit-?outs?\b|design[- /]?build|new build|wiring|renovat", re.I)


def is_explicit(quote):
    return bool(COMMERCIAL_SETTING.search(quote) and CONSTRUCTION_OR_INSTALLATION.search(quote)
                and not MENTIONS_RESIDENTIAL.search(quote))


# Terms that only exist in commercial construction count on their own. Other construction words
# ("construction", "design-build", "new build", "bid", "portfolio", "turn-key") need a commercial
# setting in the same quote (founder, 2026-09-22, after batch 1: A-0040, a landscape design firm,
# qualified on "from design and permits to construction" and "The Design/Build Approach").
COMMERCIAL_CONSTRUCTION_ONLY = re.compile(
    r"tenant|build-?outs?\b|fit-?outs?\b|general contractor|\bgcs?\b|plan[- ]?(and|&)[- ]?spec|"
    r"prevailing wage|\bunion\b", re.I)

# Narrow subcontracting evidence (founder, 2026-09-22, A-0059 Cinfab): the company says it works
# as a subcontractor, or as a subcontractor or partner to a general contractor or construction
# manager. Counts as the commercial setting only alongside verified construction or installation
# work; never on its own.
SUBCONTRACTING = re.compile(
    r"\bsub-?contractor\b|(?:partner|subcontract\w*)[^.]{0,60}?"
    r"(?:general contractor|construction manager|\bgcs?\b)", re.I)


def is_specific(quote):
    if COMMERCIAL_CONSTRUCTION_ONLY.search(quote):
        return True
    if MENTIONS_RESIDENTIAL.search(quote):
        # Residential in the same breath: only a named commercial sector with construction counts.
        return bool(COMMERCIAL_SECTOR.search(quote) and CONSTRUCTION_ACTIVITY.search(quote))
    if COMMERCIAL_SETTING.search(quote) and CONSTRUCTION_ACTIVITY.search(quote):
        return True
    # Bare "commercial projects" is not enough: a named sector is needed with project work.
    return bool(COMMERCIAL_SECTOR.search(quote) and PROJECT_WORK.search(quote))


def subcontracting_support(kept):
    """A-0059 rule: one verified quote establishes commercial subcontracting and one (the same or
    another) names construction or installation work. Residential and GC quotes do not count."""
    usable = [k for k in kept if k["category"] in (COMMERCIAL_PROJECT, COMMERCIAL_GENERIC, COMMERCIAL_SERVICE)
              and not MENTIONS_RESIDENTIAL.search(k["quote"])]
    subs = [k for k in usable if SUBCONTRACTING.search(k["quote"])]
    work = [k for k in usable if CONSTRUCTION_OR_INSTALLATION.search(k["quote"])]
    return subs, work


# A general-contractor quote must say so. On the sample the model called "design-build HVAC
# contractor" and "electrical contracting ... project management" general contractors.
GC_SIGNAL = re.compile(r"general contract|construction manag|\bdeveloper|real estate develop|"
                       r"\bgc\b|owner'?s rep", re.I)

MAX_PAGES = 8
PAGE_CHARS = 8000
# Pages most likely to say who the company works for.
USEFUL_LINK = re.compile(
    r"about|service|commercial|industrial|institutional|project|portfolio|market|industr|"
    r"residential|who-we-are|company|client|experience|capabilit|construction|what-we-do|work", re.I)

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

PROMPT = """You are reading a construction trade company's own website to find out who it works for.

Return up to 8 pieces of evidence. Each is an exact quote copied character for character from
ONE page below (5 to 40 words; do not join text from different places, do not fix spelling,
do not paraphrase), the number of the page it came from, and one category:

- COMMERCIAL_PROJECT: construction project work on commercial, industrial, institutional or
  public buildings - new construction, build-outs, tenant improvements, design-build, bid or
  plan-and-spec work, named projects, work for general contractors, prevailing wage or union work.
- COMMERCIAL_SERVICE: service, repair or maintenance for businesses or commercial buildings,
  with no construction project work.
- RESIDENTIAL: work for homes or homeowners.
- GENERAL_CONTRACTOR: the company presents itself as a general contractor, construction
  manager, design-build firm managing whole buildings, or developer - not a trade that works
  under one.

Never use customer testimonials or reviews, product or brand names, dealer or certification
statements, or bare lists of fixtures and services as evidence of project work.

Only quote text that states what the company itself does. Ignore job ads, blog posts about
other companies, and generic marketing that names no kind of customer. If the pages say
nothing about who the company works for, return an empty list.

{pages}"""


def _norm(s):
    s = unicodedata.normalize("NFKC", s)
    s = s.replace("’", "'").replace("‘", "'").replace("“", '"').replace("”", '"')
    s = s.replace("–", "-").replace("—", "-").replace("\xa0", " ")
    return re.sub(r"\s+", " ", s).strip()


def page_text(html):
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "noscript", "svg", "template", "iframe"]):
        tag.decompose()
    return _norm(soup.get_text(" "))


def read_site(website):
    """Returns (pages, why_unreadable). pages: [(url, text)]. Honours robots.txt."""
    if not website:
        return [], "no website"
    start = checks._url(website)
    root = checks._root(start)
    host = checks.base_domain(checks.site_domain(start))
    robots = checks._robots(root)
    queue, seen, pages, blocked, errors = [start, root], set(), [], 0, []
    while queue and len(seen) < MAX_PAGES * 2 and len(pages) < MAX_PAGES:
        url = queue.pop(0)
        if url.rstrip("/") in seen:
            continue
        seen.add(url.rstrip("/"))
        if not robots.can_fetch(checks.USER_AGENT, url):
            blocked += 1
            continue
        try:
            r = checks._get(url)
        except Exception as e:
            errors.append(type(e).__name__)
            continue
        if r.status_code >= 400:
            errors.append(f"HTTP {r.status_code}")
            continue
        text = page_text(r.text)[:PAGE_CHARS]
        if len(text) >= 80:
            pages.append((url, text))
        links = []
        for href in re.findall(r'href=["\']([^"\'#]+)', r.text):
            link = urljoin(url, href)
            if (checks.base_domain(checks.site_domain(link)) == host and USEFUL_LINK.search(link)
                    and not re.search(r"\.(pdf|jpe?g|png|gif|webp|zip|docx?)$", link, re.I)):
                links.append(link)
        queue += links
    if pages:
        return pages, ""
    if blocked:
        return [], "the site asks robots not to read it"
    return [], f"could not read the website ({', '.join(sorted(set(errors))) or 'no readable text'})"


def verify(evidence, pages):
    """Keep only quotes found word for word (ignoring case, spacing and curly quotes) in the page
    they name. The stored quote is the page's own text, not the model's copy."""
    kept, rejected, seen = [], 0, set()
    for item in evidence:
        n, quote, cat = item.get("page"), _norm(item.get("quote", "")), item.get("category")
        if cat not in CATEGORIES or not isinstance(n, int) or not (1 <= n <= len(pages)) or len(quote) < 12:
            rejected += 1
            continue
        url, text = pages[n - 1]
        at = text.lower().find(quote.lower())
        if at < 0:
            rejected += 1
            continue
        exact = text[at:at + len(quote)]
        if (exact.lower(), cat) in seen:
            continue
        seen.add((exact.lower(), cat))
        kept.append({"category": cat, "quote": exact, "url": url})
    return kept, rejected


def downgrade_unsupported(kept):
    """Categories must be supported by the quote's own words. A GENERAL_CONTRACTOR quote with no
    general-contracting signal is project work; a COMMERCIAL_PROJECT quote with no project signal
    at all is COMMERCIAL_SERVICE, and one that is not specific is COMMERCIAL_GENERIC.
    Idempotent, so it can re-evaluate stored quotes."""
    out = []
    for k in kept:
        cat = k["category"]
        if cat == GENERAL_CONTRACTOR and not GC_SIGNAL.search(k["quote"]):
            cat = COMMERCIAL_PROJECT
        if cat == COMMERCIAL_PROJECT and not PROJECT_SIGNAL.search(k["quote"]):
            cat = COMMERCIAL_SERVICE
        elif cat == COMMERCIAL_PROJECT and not is_specific(k["quote"]):
            cat = COMMERCIAL_GENERIC
        out.append({**k, "category": cat})
    return out


def verdict(kept, pages_read, why_unreadable=""):
    """Fit from verified quotes only. Returns (fit, work_mix, reason)."""
    if not pages_read:
        return REVIEW_NEEDED, "UNREADABLE", why_unreadable or "could not read the website"
    n = {c: sum(1 for k in kept if k["category"] == c) for c in ALL_CATEGORIES}
    cp, cs, res, gc = n[COMMERCIAL_PROJECT], n[COMMERCIAL_SERVICE], n[RESIDENTIAL], n[GENERAL_CONTRACTOR]
    gen = n[COMMERCIAL_GENERIC]
    generic_note = f"; {gen} mention commercial work only in general terms" if gen else ""
    if gc:
        return REVIEW_NEEDED, "GENERAL_CONTRACTOR", (f"{gc} quote(s) suggest a general contractor or "
                                                     f"construction manager, not a trade subcontractor")
    if cp >= 2 and not res:
        return QUALIFIED, "COMMERCIAL", (f"{cp} quote(s) show specific commercial project work; "
                                         f"none show residential")
    if cp == 1 and not res:
        # One project quote is enough only with explicit commercial construction or installation
        # work - in that quote or in another verified, non-residential quote.
        support = [k for k in kept if k["category"] in (COMMERCIAL_PROJECT, COMMERCIAL_GENERIC, COMMERCIAL_SERVICE)
                   and is_explicit(k["quote"])]
        if support:
            return QUALIFIED, "COMMERCIAL", ("1 quote shows specific commercial project work and "
                                             f"{len(support)} explicitly show commercial construction or "
                                             "installation work; none show residential")
        subs, work = subcontracting_support(kept)
        if subs and work:
            return QUALIFIED, "COMMERCIAL", ("1 quote shows specific commercial project work; the company states "
                                             "it works as a subcontractor or partner to general contractors or "
                                             "construction managers, and a verified quote names construction or "
                                             "installation work; none show residential")
        return REVIEW_NEEDED, "COMMERCIAL", ("only 1 quote shows commercial project work and no verified quote "
                                             "explicitly shows commercial construction or installation work"
                                             f"{generic_note}; needs a person to judge")
    if cp >= MIXED_MIN_PROJECT_QUOTES and res:
        return QUALIFIED, "MIXED", (f"{cp} quote(s) show specific commercial project work; "
                                    f"{res} show residential work too")
    if cp and res:
        return REVIEW_NEEDED, "MIXED", (f"only {cp} quote shows specific commercial project work against {res} "
                                        f"residential{generic_note}; needs a person to judge")
    if cs or gen:
        mix = "MIXED" if res else "COMMERCIAL_SERVICE"
        parts = []
        if gen:
            parts.append(f"{gen} mention commercial work only in general terms")
        if cs:
            parts.append(f"{cs} show commercial service or repair")
        return REVIEW_NEEDED, mix, ("no specific commercial project work: " + ", ".join(parts)
                                    + (f"; {res} show residential" if res else ""))
    if res:
        return DISQUALIFIED, "RESIDENTIAL", f"{res} quote(s) show residential work; none show commercial work"
    return REVIEW_NEEDED, "UNCLEAR", f"read {pages_read} page(s); none says clearly who the company works for"


def build_prompt(pages):
    blocks = "\n\n".join(f"=== PAGE {i} ({url}) ===\n{text}" for i, (url, text) in enumerate(pages, 1))
    return PROMPT.replace("{pages}", blocks)


def research(website, model):
    """model(prompt, schema) -> (json, usage). Returns a dict with fit, work_mix, reason,
    evidence (verified), pages, rejected, usage."""
    pages, why = read_site(website)
    if not pages:
        fit, mix, reason = verdict([], 0, why)
        return {"fit": fit, "work_mix": mix, "reason": reason, "evidence": [], "pages": [], "rejected": 0, "usage": {}}
    out, usage = model(build_prompt(pages), SCHEMA)
    kept, rejected = verify(out.get("evidence", []), pages)
    kept = downgrade_unsupported(kept)
    fit, mix, reason = verdict(kept, len(pages))
    if rejected:
        reason += f"; {rejected} proposed quote(s) discarded as not found word for word"
    return {"fit": fit, "work_mix": mix, "reason": reason, "evidence": kept,
            "pages": [u for u, _ in pages], "rejected": rejected, "usage": usage}


def evidence_cell(kept, limit=3):
    order = {GENERAL_CONTRACTOR: 0, COMMERCIAL_PROJECT: 1, RESIDENTIAL: 2, COMMERCIAL_GENERIC: 3,
             COMMERCIAL_SERVICE: 4}
    top = sorted(kept, key=lambda k: order[k["category"]])[:limit]
    return "\n".join(f'[{k["category"]}] "{k["quote"]}" ({k["url"]})' for k in top)
