"""Verified company offerings become draft inputs without changing company fit."""

from outreach import company_profile, job_profile, research


PAGES = [
    ("https://example.test/", "We install electrical distribution systems for commercial buildings. "
     "Our customers include schools and manufacturing plants."),
    ("https://example.test/services", "We supply switchgear, lighting controls and industrial panels."),
]


def model_with(*facts):
    def model(prompt, schema):
        assert "Do not write email copy" in prompt
        return {"evidence": [{"page": page, "quote": quote, "category": category}
                             for page, quote, category in facts]}, {"promptTokenCount": 12}
    return model


def test_offerings_and_markets_are_verified_for_later_drafting(monkeypatch):
    monkeypatch.setattr(research, "read_site", lambda website: (PAGES, ""))
    result = company_profile.profile("https://example.test/", model_with(
        (1, "We install electrical distribution systems for commercial buildings.", "OFFERING"),
        (2, "We supply switchgear, lighting controls and industrial panels.", "OFFERING"),
        (1, "Our customers include schools and manufacturing plants.", "MARKET")))
    assert result["status"] == "READY"
    assert len(result["evidence"]) == 3
    assert "switchgear" in company_profile.evidence_cell(result["evidence"], "OFFERING")
    assert "schools" in company_profile.evidence_cell(result["evidence"], "MARKET")
    assert all(fact["url"].startswith("https://example.test/") for fact in result["evidence"])
    assert "fit" not in result  # the existing fit verdict remains a separate decision


def test_invented_or_misattributed_company_claims_cannot_become_draft_inputs(monkeypatch):
    monkeypatch.setattr(research, "read_site", lambda website: (PAGES, ""))
    result = company_profile.profile("https://example.test/", model_with(
        (1, "We reduced our customers' cash gaps by 30 percent.", "OFFERING"),
        (2, "We install electrical distribution systems for commercial buildings.", "OFFERING"),
        (1, "Our customers include schools and manufacturing plants.", "MARKET")))
    assert result["status"] == "REVIEW_NEEDED"
    assert result["rejected"] == 2
    assert not company_profile.evidence_cell(result["evidence"], "OFFERING")


def test_navigation_dump_is_not_used_as_a_personalization_fact(monkeypatch):
    long_list = "We provide " + "plumbing repair replacement installation service " * 13
    pages = [("https://example.test/", long_list)]
    monkeypatch.setattr(research, "read_site", lambda website: (pages, ""))
    result = company_profile.profile("https://example.test/", model_with((1, long_list, "OFFERING")))
    assert result["status"] == "REVIEW_NEEDED"
    assert result["evidence"] == [] and result["rejected"] == 1
    assert "too short or long" in result["reason"]


def test_unreadable_company_has_no_fabricated_profile(monkeypatch):
    monkeypatch.setattr(research, "read_site", lambda website: ([], "blocked by robots.txt"))
    result = company_profile.profile("https://example.test/", model_with())
    assert result["status"] == "REVIEW_NEEDED"
    assert result["evidence"] == []
    assert "blocked" in result["reason"]


def test_off_domain_redirect_is_not_used_as_company_evidence(monkeypatch):
    class Response:
        status_code = 200
        url = "https://unrelated.test/"
        text = "We install electrical distribution systems for commercial buildings. " * 4

    monkeypatch.setattr(research.checks, "_robots", lambda root: type("Rules", (), {"can_fetch": lambda *args: True})())
    monkeypatch.setattr(research.checks, "_get", lambda url: Response())
    called = []

    def model(*args):
        called.append(True)
        return {}, {}

    result = company_profile.profile("https://example.test/", model)
    assert result["status"] == "REVIEW_NEEDED" and result["evidence"] == []
    assert "outside" in result["reason"] and not called


class FakeTab:
    def __init__(self, name, rows):
        self.name, self.rows = name, rows
        self.writes = []

    def ensure_columns(self, names):
        raise AssertionError("dry run must not add Sheet columns")

    def write(self, updates):
        raise AssertionError("dry run must not write to the Sheet")


def test_profile_pilot_selects_only_ok_qualified_unsent_leads():
    rows = [
        (3, {"Lead ID": "A-0001", "Website": "https://example.test/", "Email check": "OK", "Fit": "QUALIFIED"}),
        (4, {"Lead ID": "A-0002", "Email check": "RISKY", "Fit": "QUALIFIED"}),
        (5, {"Lead ID": "A-0003", "Email check": "OK", "Fit": "REVIEW_NEEDED"}),
        (6, {"Lead ID": "A-0004", "Email check": "OK", "Fit": "QUALIFIED", "Profile status": "READY"}),
        (7, {"Lead ID": "A-0005", "Email check": "OK", "Fit": "QUALIFIED", "Sent by hand": "yes"}),
    ]
    tab = FakeTab("A_Contact_Now", rows)
    assert [v["Lead ID"] for _, _, v in job_profile.select([tab])] == ["A-0001"]


def test_dry_run_reads_and_models_without_writing(monkeypatch):
    monkeypatch.setattr(research, "read_site", lambda website: (PAGES, ""))
    monkeypatch.setattr(job_profile, "_api", lambda: object())
    tab = FakeTab("A_Contact_Now", [(3, {"Lead ID": "A-0001", "Company": "Example",
                                            "Website": "https://example.test/", "Email check": "OK",
                                            "Fit": "QUALIFIED"})])
    monkeypatch.setattr(job_profile, "Tab",
                       lambda api, name, system, sheet_id=None: tab if name == tab.name else FakeTab(name, []))
    monkeypatch.setattr(job_profile, "append_run", lambda *a: (_ for _ in ()).throw(AssertionError("no run row")))
    result = job_profile.run("test", limit=1, ids={"A-0001"}, dry_run=True, model=model_with(
        (1, "We install electrical distribution systems for commercial buildings.", "OFFERING")))
    assert result["dry_run"] and result["results"] == {"READY": 1}
    assert result["preview"] == [{"lead_id": "A-0001", "status": "READY",
                                  "offerings": [{"quote": "We install electrical distribution systems for commercial buildings.",
                                                 "url": "https://example.test/"}], "markets": []}]
