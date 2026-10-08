"""outreach/auto_send.py: the scheduled, cap-limited drip of already-created, already-approved
drafts. Offline, against the simulated Sheets API and a fake Gmail (test_send.py's fakes).
"""

import pytest

from outreach import auto_send, job_draft
from test_send import FakeGmail, _Sheets

HEADER = ["Company", "Decision maker", "BEST EMAIL", "Website", "Lead ID",
          "Draft status", "Draft ID", "Draft action at", "Sent at"]


def sheets(rows=None, b_rows=None):
    fake = _Sheets()
    fake.tabs = {
        "A_Contact_Now": [["A tab"], list(HEADER), *(rows or [])],
        "B_Contact_Now": [["B tab"], list(HEADER), *(b_rows or [])],
        "Suppression": [["Address or domain", "Reason", "Added at", "Source"]],
    }
    return fake


def row(lead_id, *, draft_status="CREATED", draft_id="draft-1", action_at="2026-10-01T10:00:00+00:00",
        sent_at="", email="sam@example.test", company="Example Electric"):
    return [company, "Sam", email, "https://example.test/", lead_id, draft_status, draft_id,
            action_at, sent_at]


@pytest.fixture(autouse=True)
def _settings(monkeypatch):
    monkeypatch.setattr(job_draft, "load_settings", lambda: {"daily_cap": 2})


def test_auto_send_is_disabled_without_the_flag(monkeypatch):
    monkeypatch.delenv("ENABLE_AUTO_SEND", raising=False)
    with pytest.raises(auto_send.AutoSendBlocked):
        auto_send.run(api=sheets([row("A-0001")]), gmail=FakeGmail())


def test_it_sends_a_created_draft_up_to_the_cap(monkeypatch):
    monkeypatch.setenv("ENABLE_AUTO_SEND", "true")
    monkeypatch.setenv("ENABLE_SEND", "true")
    api, gmail = sheets([row("A-0001")]), FakeGmail()
    result = auto_send.run(api=api, gmail=gmail)
    assert [s["lead_id"] for s in result["sent"]] == ["A-0001"]
    assert result["skipped"] == []
    assert result["remaining_cap"] == 1  # cap 2, one sent


def test_it_stops_at_the_daily_cap_and_reports_the_rest_skipped(monkeypatch):
    monkeypatch.setenv("ENABLE_AUTO_SEND", "true")
    monkeypatch.setenv("ENABLE_SEND", "true")
    api = sheets([row("A-0001", action_at="2026-10-01T09:00:00+00:00"),
                  row("A-0002", action_at="2026-10-01T10:00:00+00:00"),
                  row("A-0003", action_at="2026-10-01T11:00:00+00:00")])
    result = auto_send.run(api=api, gmail=FakeGmail())
    assert [s["lead_id"] for s in result["sent"]] == ["A-0001", "A-0002"]
    assert result["skipped"] == [{"lead_id": "A-0003", "reason": "the daily send cap is reached"}]
    assert result["remaining_cap"] == 0


def test_todays_sends_count_against_the_cap(monkeypatch):
    monkeypatch.setenv("ENABLE_AUTO_SEND", "true")
    monkeypatch.setenv("ENABLE_SEND", "true")
    import datetime as _dt
    import zoneinfo as _zi
    today = _dt.datetime.now(_zi.ZoneInfo("America/New_York")).date().isoformat()
    api = sheets([row("A-0001", draft_status="SENT", sent_at=f"{today}T09:00:00+00:00"),
                  row("A-0002", draft_status="SENT", sent_at=f"{today}T10:00:00+00:00"),
                  row("A-0003")])
    result = auto_send.run(api=api, gmail=FakeGmail())
    assert result["sent"] == []
    assert result["skipped"] == [{"lead_id": "A-0003", "reason": "the daily send cap is reached"}]


def test_a_recorded_stop_call_blocks_the_send(monkeypatch):
    monkeypatch.setenv("ENABLE_AUTO_SEND", "true")
    monkeypatch.setenv("ENABLE_SEND", "true")
    from outreach.sheet import CALLS_HEADER, CALLS_TAB
    api = sheets([row("A-0001")])
    api.tabs[CALLS_TAB] = [list(CALLS_HEADER),
                           ["evt-1", "A-0001", "2026-10-01T08:00:00Z", "OUTCOME", "DO_NOT_CONTACT",
                            "", "2026-10-01T08:00:00Z", "", "", "", "", ""]]
    result = auto_send.run(api=api, gmail=FakeGmail())
    assert result["sent"] == []
    assert len(result["skipped"]) == 1
    assert "stop" in result["skipped"][0]["reason"].lower()


def test_a_suppressed_recipient_is_skipped(monkeypatch):
    monkeypatch.setenv("ENABLE_AUTO_SEND", "true")
    monkeypatch.setenv("ENABLE_SEND", "true")
    api = sheets([row("A-0001", email="sam@example.test")])
    api.tabs["Suppression"] = [["Address or domain", "Reason", "Added at", "Source"],
                                ["sam@example.test", "opted out", "2026-09-01T00:00:00+00:00", "sync"]]
    result = auto_send.run(api=api, gmail=FakeGmail())
    assert result["sent"] == []
    assert result["skipped"] == [{"lead_id": "A-0001", "reason": "this recipient is on the suppression list"}]


def test_leads_with_no_created_draft_are_never_candidates(monkeypatch):
    monkeypatch.setenv("ENABLE_AUTO_SEND", "true")
    monkeypatch.setenv("ENABLE_SEND", "true")
    api = sheets([row("A-0001", draft_status="RESERVED"), row("A-0002", draft_status="WAITING", draft_id="")])
    result = auto_send.run(api=api, gmail=FakeGmail())
    assert result["sent"] == []
    assert result["skipped"] == []


def test_missing_daily_cap_blocks_the_whole_run(monkeypatch):
    monkeypatch.setenv("ENABLE_AUTO_SEND", "true")
    monkeypatch.setattr(job_draft, "load_settings", lambda: {})
    with pytest.raises(auto_send.AutoSendBlocked):
        auto_send.run(api=sheets([row("A-0001")]), gmail=FakeGmail())
