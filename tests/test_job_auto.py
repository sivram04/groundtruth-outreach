"""job_auto.run is pure orchestration: check, then research, then profile, in that order (each
stage's pending set depends on the previous stage's write already landing). Each sub-job keeps
its own tests and its own Runs row; this only proves the chaining and the limits passed through.
"""

from outreach import job_auto, job_check, job_profile, job_research


def test_runs_check_research_then_profile_in_order(monkeypatch):
    order = []

    def fake_check(where, **kwargs):
        order.append("check")
        return {"results": {}, "written": 0, "skipped": []}

    def fake_research(where, limit=job_research.DEFAULT_LIMIT, ids=None, **kwargs):
        order.append("research")
        return {"results": {}, "written": 0, "skipped": [], "failures": []}

    def fake_profile(where, limit=job_profile.MAX_LIMIT, ids=None, dry_run=False, **kwargs):
        order.append("profile")
        return {"results": {}, "written": 0, "skipped": [], "failures": []}

    monkeypatch.setattr(job_check, "run", fake_check)
    monkeypatch.setattr(job_research, "run", fake_research)
    monkeypatch.setattr(job_profile, "run", fake_profile)

    result = job_auto.run("cloud-run")
    assert order == ["check", "research", "profile"]
    assert set(result) == {"checked", "researched", "profiled"}


def test_passes_through_where_and_limits(monkeypatch):
    seen = {}

    monkeypatch.setattr(job_check, "run", lambda where, **kw: seen.setdefault("check", where) and {})
    monkeypatch.setattr(job_research, "run",
                       lambda where, limit=None, ids=None, **kw: seen.update(research_where=where, research_limit=limit) or {})
    monkeypatch.setattr(job_profile, "run",
                       lambda where, limit=None, ids=None, dry_run=False, **kw: seen.update(profile_where=where, profile_limit=limit) or {})

    job_auto.run("cloud-run", research_limit=10, profile_limit=3)
    assert seen["check"] == "cloud-run"
    assert seen["research_where"] == "cloud-run" and seen["research_limit"] == 10
    assert seen["profile_where"] == "cloud-run" and seen["profile_limit"] == 3


def test_defaults_match_each_jobs_own_default_limit():
    assert job_auto.RESEARCH_LIMIT == job_research.DEFAULT_LIMIT
    assert job_auto.PROFILE_LIMIT == job_profile.MAX_LIMIT
