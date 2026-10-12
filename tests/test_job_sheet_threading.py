"""job_check/job_research/job_profile/job_auto accept an explicit (api, sheet_id) pair instead
of always grabbing the single founder singleton - the piece that lets a job run against one
connected account's own Sheet and credential rather than the hardcoded one."""

from outreach import job_auto, job_check, job_profile, job_research


class FakeTab:
    def __init__(self, api, name, system, sheet_id=None):
        self.api, self.name, self.system, self.sheet_id = api, name, system, sheet_id
        self.rows = []

    def ensure_columns(self, names):
        pass

    def write(self, updates):
        return {"written": 0, "skipped": []}


def _no_singleton(monkeypatch, module):
    monkeypatch.setattr(module, "_api",
                       lambda: (_ for _ in ()).throw(AssertionError("must not fall back to the founder singleton")))


def test_job_check_uses_the_given_api_and_sheet_id(monkeypatch):
    _no_singleton(monkeypatch, job_check)
    monkeypatch.setattr(job_check, "Tab", FakeTab)
    seen = {}
    monkeypatch.setattr(job_check, "append_run",
                       lambda api, job, where, result, detail, sheet_id=None: seen.setdefault("sheet_id", sheet_id))
    job_check.run("test", api=object(), sheet_id="tenant-sheet-1")
    assert seen["sheet_id"] == "tenant-sheet-1"


def test_job_research_uses_the_given_api_and_sheet_id(monkeypatch):
    _no_singleton(monkeypatch, job_research)
    monkeypatch.setattr(job_research, "Tab", FakeTab)
    seen = {}
    monkeypatch.setattr(job_research, "append_run",
                       lambda api, job, where, result, detail, sheet_id=None: seen.setdefault("sheet_id", sheet_id))
    job_research.run("test", api=object(), sheet_id="tenant-sheet-2")
    assert seen["sheet_id"] == "tenant-sheet-2"


def test_job_profile_uses_the_given_api_and_sheet_id(monkeypatch):
    _no_singleton(monkeypatch, job_profile)
    monkeypatch.setattr(job_profile, "Tab", FakeTab)
    seen = {}
    monkeypatch.setattr(job_profile, "append_run",
                       lambda api, job, where, result, detail, sheet_id=None: seen.setdefault("sheet_id", sheet_id))
    job_profile.run("test", api=object(), sheet_id="tenant-sheet-3")
    assert seen["sheet_id"] == "tenant-sheet-3"


def test_job_auto_threads_the_same_api_and_sheet_id_to_every_stage(monkeypatch):
    seen = []

    def fake(where, *, api=None, sheet_id=None, **kw):
        seen.append((api, sheet_id))
        return {"results": {}, "written": 0, "skipped": [], "failures": []}

    marker = object()
    monkeypatch.setattr(job_check, "run", fake)
    monkeypatch.setattr(job_research, "run", fake)
    monkeypatch.setattr(job_profile, "run", fake)
    job_auto.run("test", api=marker, sheet_id="tenant-sheet-4")
    assert seen == [(marker, "tenant-sheet-4")] * 3
