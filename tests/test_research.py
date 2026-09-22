"""Stage 2 research against fake websites and a fake model. No network, no Gemini."""

import pytest
import requests

from outreach import checks, eligibility, research
from outreach.research import (COMMERCIAL_PROJECT as CP, COMMERCIAL_SERVICE as CS, RESIDENTIAL as RES,
                               DISQUALIFIED, QUALIFIED, REVIEW_NEEDED)


class Resp:
    def __init__(self, status, text=""):
        self.status_code, self.text = status, text


@pytest.fixture
def web(monkeypatch):
    pages = {}

    def fake_get(url, **kw):
        if url not in pages:
            raise requests.ConnectionError("no route")
        return pages[url]
    monkeypatch.setattr(checks.requests, "get", fake_get)
    monkeypatch.setattr(checks.time, "sleep", lambda s: None)
    return pages


def site(web, home, **more):
    web["https://co.com/robots.txt"] = Resp(404)
    web["https://co.com/"] = Resp(200, home)
    for path, html in more.items():
        web[f"https://co.com/{path}"] = Resp(200, html)


def model_returning(*items):
    """Fake model: returns the given (page, quote, category) evidence and records the prompt."""
    calls = []

    def model(prompt, schema):
        calls.append(prompt)
        return {"evidence": [{"page": p, "quote": q, "category": c} for p, q, c in items]}, {"promptTokenCount": 10}
    model.calls = calls
    return model


COMMERCIAL_HOME = """<html><body><nav><a href="/about-us">About</a> <a href="/careers">Jobs</a></nav>
<h1>Acme Mechanical</h1><p>We install HVAC and plumbing systems for new commercial construction,
including hospitals, schools and office buildings, working with general contractors across Ohio.</p>
<script>var x = "residential homes";</script></body></html>"""
ABOUT = "<p>Founded in 1978, Acme is a union signatory contractor serving industrial plants.</p>" * 2
RESIDENTIAL_HOME = ("<p>Family owned since 1990, we fix furnaces and water heaters for homeowners "
                    "across Columbus. Call today for fast residential service.</p>")
MIXED_HOME = ("<p>We provide residential service and repair for homeowners. Our commercial division "
              "handles tenant build-outs and new construction for general contractors. Recent projects "
              "include two elementary schools and a hospital wing.</p>")
PLUMBER_LIST = ("<p>Toilets Toilet Installation and Repair Urinal Installation and Repair. Bathroom Remodeling "
                "Basement Bathroom Installation Tub and Shower Installation for your home.</p>")
GC_HOME = ("<p>Pleasant Co provides integrated real estate, construction and facility management services "
           "as general contractor and construction manager for retail chains.</p>")
SERVICE_HOME = ("<p>We keep restaurants and retail stores running with commercial refrigeration repair "
                "and preventive maintenance contracts, 24 hours a day.</p>")


# --- verdicts from real page text --------------------------------------------------------

def test_commercial_site_is_qualified(web):
    site(web, COMMERCIAL_HOME, **{"about-us": ABOUT})
    model = model_returning(
        (1, "new commercial construction, including hospitals, schools and office buildings", CP),
        (2, "a union signatory contractor serving industrial plants", CP))
    r = research.research("https://co.com/", model)
    assert (r["fit"], r["work_mix"]) == (QUALIFIED, "COMMERCIAL")
    assert all(k["url"].startswith("https://co.com/") for k in r["evidence"]) and len(r["evidence"]) == 2
    assert "https://co.com/about-us" in r["pages"] and "https://co.com/careers" not in r["pages"]


def test_residential_site_is_disqualified(web):
    site(web, RESIDENTIAL_HOME)
    r = research.research("https://co.com/", model_returning(
        (1, "we fix furnaces and water heaters for homeowners across Columbus", RES)))
    assert (r["fit"], r["work_mix"]) == (DISQUALIFIED, "RESIDENTIAL")


def test_mixed_site_with_two_project_quotes_is_qualified_and_labelled_mixed(web):
    site(web, MIXED_HOME)
    r = research.research("https://co.com/", model_returning(
        (1, "residential service and repair for homeowners", RES),
        (1, "handles tenant build-outs and new construction for general contractors", CP),
        (1, "Recent projects include two elementary schools and a hospital wing", CP)))
    assert (r["fit"], r["work_mix"]) == (QUALIFIED, "MIXED")
    assert "residential" in r["reason"]


def test_mixed_site_with_one_project_quote_needs_review(web):
    site(web, MIXED_HOME)
    r = research.research("https://co.com/", model_returning(
        (1, "residential service and repair for homeowners", RES),
        (1, "handles tenant build-outs and new construction for general contractors", CP)))
    assert (r["fit"], r["work_mix"]) == (REVIEW_NEEDED, "MIXED")


def test_fixture_list_labelled_project_work_is_downgraded(web):
    # A-0295 in the 2026-09-22 sample: a service list was labelled project work.
    site(web, PLUMBER_LIST)
    r = research.research("https://co.com/", model_returning(
        (1, "Toilets Toilet Installation and Repair Urinal Installation and Repair", CP),
        (1, "Bathroom Remodeling Basement Bathroom Installation Tub and Shower Installation", RES)))
    assert r["fit"] != QUALIFIED
    assert r["evidence"][0]["category"] == CS


def test_trade_firm_labelled_general_contractor_is_treated_as_project_work(web):
    # A-0112 and B-0115 in the sample: trades the model called general contractors.
    site(web, "<p>Cincinnati's original design-build HVAC contractor, delivering complete mechanical "
              "solutions for hospitals and schools from planning through installation.</p>")
    r = research.research("https://co.com/", model_returning(
        (1, "Cincinnati's original design-build HVAC contractor", research.GENERAL_CONTRACTOR),
        (1, "complete mechanical solutions for hospitals and schools from planning through installation", CP)))
    assert (r["fit"], r["work_mix"]) == (QUALIFIED, "COMMERCIAL")


def test_general_contractor_needs_review_even_with_project_work(web):
    site(web, GC_HOME)
    r = research.research("https://co.com/", model_returning(
        (1, "integrated real estate, construction and facility management services", CP),
        (1, "as general contractor and construction manager for retail chains", research.GENERAL_CONTRACTOR)))
    assert (r["fit"], r["work_mix"]) == (REVIEW_NEEDED, "GENERAL_CONTRACTOR")


def test_commercial_service_without_projects_needs_review(web):
    site(web, SERVICE_HOME)
    r = research.research("https://co.com/", model_returning(
        (1, "commercial refrigeration repair and preventive maintenance contracts", CS)))
    assert (r["fit"], r["work_mix"]) == (REVIEW_NEEDED, "COMMERCIAL_SERVICE")


def test_site_that_says_nothing_clear_needs_review(web):
    site(web, "<p>Quality you can trust. Excellence in every job we do, every single day of the year.</p>")
    r = research.research("https://co.com/", model_returning())
    assert (r["fit"], r["work_mix"]) == (REVIEW_NEEDED, "UNCLEAR")


@pytest.mark.parametrize("setup,why", [
    (lambda w: None, "could not read"),                                                     # no answer
    (lambda w: w.update({"https://co.com/robots.txt": Resp(404), "https://co.com/": Resp(500)}), "HTTP 500"),
    (lambda w: w.update({"https://co.com/robots.txt": Resp(200, "User-agent: *\nDisallow: /"),
                         "https://co.com/": Resp(200, COMMERCIAL_HOME)}), "robots"),
    (lambda w: w.update({"https://co.com/robots.txt": Resp(404),
                         "https://co.com/": Resp(200, "<script>app()</script>")}), "no readable text"),
])
def test_unreadable_site_needs_review_and_never_calls_the_model(web, setup, why):
    setup(web)
    model = model_returning((1, "anything at all here", CP))
    r = research.research("https://co.com/", model)
    assert (r["fit"], r["work_mix"]) == (REVIEW_NEEDED, "UNREADABLE") and why in r["reason"]
    assert model.calls == []


def test_no_website_needs_review():
    r = research.research("", model_returning())
    assert (r["fit"], r["work_mix"]) == (REVIEW_NEEDED, "UNREADABLE")


# --- quotes must be verbatim ------------------------------------------------------------

def test_paraphrased_quote_is_discarded_and_cannot_qualify(web):
    site(web, RESIDENTIAL_HOME)
    r = research.research("https://co.com/", model_returning(
        (1, "we build commercial office buildings for general contractors", CP)))  # not on the page
    assert r["fit"] == REVIEW_NEEDED and r["evidence"] == [] and r["rejected"] == 1
    assert "discarded" in r["reason"]


def test_quote_attributed_to_the_wrong_page_is_discarded(web):
    site(web, COMMERCIAL_HOME, **{"about-us": ABOUT})
    r = research.research("https://co.com/", model_returning(
        (2, "new commercial construction, including hospitals", CP)))  # it is on page 1
    assert r["evidence"] == [] and r["rejected"] == 1


def test_quote_from_a_script_is_not_page_text(web):
    site(web, COMMERCIAL_HOME)
    r = research.research("https://co.com/", model_returning((1, 'var x = "residential homes"', RES)))
    assert r["evidence"] == []


def test_stored_quote_is_the_pages_own_text(web):
    site(web, COMMERCIAL_HOME)
    r = research.research("https://co.com/", model_returning(
        (1, "NEW   COMMERCIAL construction,  including hospitals", CP)))  # case/spacing differ
    assert r["evidence"][0]["quote"] == "new commercial construction, including hospitals"


def test_unknown_category_and_bad_page_numbers_are_discarded(web):
    site(web, COMMERCIAL_HOME)
    r = research.research("https://co.com/", model_returning(
        (1, "new commercial construction, including hospitals", "GOVERNMENT"),
        (9, "new commercial construction, including hospitals", CP)))
    assert r["evidence"] == [] and r["rejected"] == 2


def test_evidence_cell_puts_project_quotes_first():
    kept = [{"category": RES, "quote": "homes", "url": "u1"}, {"category": CP, "quote": "schools", "url": "u2"}]
    assert research.evidence_cell(kept).startswith('[COMMERCIAL_PROJECT] "schools" (u2)')


# --- email risk and fit stay separate ----------------------------------------------------

def row(**kw):
    base = {"Email check": "OK", "Fit": QUALIFIED, "Sent by hand": ""}
    return {**base, **kw}


def test_draft_needs_ok_email_and_qualified_fit():
    assert eligibility.draft_eligible(row()) == (True, "")


@pytest.mark.parametrize("change", [{"Email check": "RISKY"}, {"Email check": "DUPLICATE"},
                                    {"Email check": "INVALID"}, {"Email check": ""}])
def test_risky_or_bad_address_never_gets_a_draft_even_if_qualified(change):
    assert eligibility.draft_eligible(row(**change))[0] is False


@pytest.mark.parametrize("fit", [REVIEW_NEEDED, DISQUALIFIED, ""])
def test_ok_address_at_unqualified_company_gets_no_draft(fit):
    assert eligibility.draft_eligible(row(Fit=fit))[0] is False


def test_sent_by_hand_gets_no_draft():
    assert eligibility.draft_eligible(row(**{"Sent by hand": "Sent email on 9/22/2026"}))[0] is False
