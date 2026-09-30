"""The call-task routes through the real Flask app with a synthetic Store: record an outcome, schedule
the next call, act on the task, and see it on reload. Calls are OFF unless switched on."""

import pytest

import console_fixture as fx
from outreach import calls, console, console_auth
from stage4_fakes import MemoryStore, at
from test_console_auth import ALLOWED, AUDIENCE, Keys, token

HEADER = console_auth.HEADER
COLUMNS = ["Lead ID", "Company", "Decision maker", "BEST EMAIL", "Website", "Phone"]
MON = at("2026-09-28 09:00")  # a Monday, 09:00 ET


@pytest.fixture
def built(tmp_path):
    (tmp_path / "assets").mkdir()
    (tmp_path / "index.html").write_text("<!doctype html><div id=root></div>", encoding="utf-8")
    return tmp_path


def signed(**claims):
    return {HEADER: token(**claims)}


def a_store():
    return MemoryStore([
        {"Lead ID": "A-0001", "Company": "Redwood Plumbing", "BEST EMAIL": "", "Phone": "614-555-0142"},
        {"Lead ID": "A-0002", "Company": "Bluebird Electric", "BEST EMAIL": "dana@bluebird.test",
         "Phone": "614-555-0100"},
    ], lead_columns=COLUMNS)


def make(built, store, now=MON):
    clock = now if callable(now) else (lambda: now)
    return console.create_app(
        verifier=console_auth.Verifier(AUDIENCE, ALLOWED, fetch=Keys()), store=lambda: store,
        settings=lambda: {"call_no_answer_business_days": 3}, clock=clock, static_dir=built,
        enable_calls=True).test_client()


def outcome(client, lead, **body):
    return client.post(f"/api/calls/{lead}/outcome", json=body, headers=signed())


def act(client, lead, **body):
    return client.post(f"/api/calls/{lead}/task", json=body, headers=signed())


def snapshot(client):
    return client.get("/api/snapshot", headers=signed()).get_json()


def test_calls_are_off_unless_switched_on(built):
    client = console.create_app(
        verifier=console_auth.Verifier(AUDIENCE, ALLOWED, fetch=Keys()), store=a_store,
        settings=lambda: {}, clock=lambda: MON, static_dir=built).test_client()
    assert client.post("/api/calls/A-0001/outcome", json={"outcome": "NO_ANSWER"},
                       headers=signed()).status_code == 404


def test_calls_need_a_signed_in_session(built):
    assert make(built, a_store()).post("/api/calls/A-0001/outcome",
                                       json={"outcome": "NO_ANSWER"}).status_code == 401


def test_no_answer_schedules_a_dated_task_that_survives_reload(built):
    store = a_store()
    client = make(built, store)
    done = outcome(client, "A-0001", outcome="NO_ANSWER", note="rang out",
                   called_at="2026-09-28T13:00:00+00:00")
    assert done.status_code == 200
    task = done.get_json()["task"]
    assert task["status"] == "scheduled" and task["due"] == "2026-10-01" and task["overdue"] is False
    assert task["why"] == "No answer"
    # a reload shows the same task on the lead and in the call-tasks list
    data = snapshot(client)
    lead = next(v for v in data["leads"] if v["id"] == "A-0001")
    assert lead["call_task"]["due"] == "2026-10-01" and lead["call_task"]["due_text"].endswith("2026-10-01")
    assert [t["lead_id"] for t in data["call_tasks"]] == ["A-0001"]


def test_a_callback_uses_the_explicit_time(built):
    store = a_store()
    client = make(built, store)
    task = outcome(client, "A-0001", outcome="CALLBACK", note="call me thursday",
                   callback_at="2026-10-01T18:00:00+00:00").get_json()["task"]
    assert task["due"] == "2026-10-01T18:00:00+00:00" and task["due_kind"] == "TIME"


def test_a_callback_without_a_time_is_refused(built):
    store = a_store()
    response = outcome(make(built, store), "A-0001", outcome="CALLBACK", note="call me sometime")
    assert response.status_code == 400 and not store.call_events()  # nothing recorded


def test_complete_snooze_and_cancel(built):
    store = a_store()
    client = make(built, store)
    outcome(client, "A-0001", outcome="NO_ANSWER", called_at="2026-09-28T13:00:00+00:00")
    snoozed = act(client, "A-0001", action="SNOOZE", snooze_to="2026-10-09T14:00:00+00:00").get_json()
    assert snoozed["task"]["snoozed"] is True and snoozed["task"]["due"] == "2026-10-09T14:00:00+00:00"
    done = act(client, "A-0001", action="COMPLETE").get_json()
    assert done["task"]["status"] == "done"
    # once done, there is no open task, and acting again is refused
    assert act(client, "A-0001", action="CANCEL").status_code == 409
    assert snapshot(client)["call_tasks"] == []


def test_recording_the_same_outcome_twice_makes_one_task(built):
    store = a_store()
    client = make(built, store)
    body = {"outcome": "NO_ANSWER", "note": "rang out", "called_at": "2026-09-28T13:00:00+00:00"}
    first = outcome(client, "A-0001", **body).get_json()
    second = outcome(client, "A-0001", **body).get_json()
    assert first["task"]["due"] == second["task"]["due"]  # same task
    assert len(store.call_events()) == 1  # only one physical event
    assert len(snapshot(client)["call_tasks"]) == 1


def test_do_not_contact_stops_email_and_leaves_no_task(built):
    store = a_store()
    client = make(built, store)
    result = outcome(client, "A-0002", outcome="DO_NOT_CONTACT", note="asked to be removed").get_json()
    assert result["task"] is None and result["effect"] == calls.STOP
    # the email is suppressed (the scheduler already honours Suppression), distinct from "not interested"
    assert calls.email_effect("DO_NOT_CONTACT") == calls.STOP
    entries = store.suppression()
    assert any(e.get("Address or domain") == "dana@bluebird.test" and "do not contact" in e.get("Reason", "")
               for e in entries)
    assert snapshot(client)["call_tasks"] == []


def test_not_interested_also_stops_but_is_a_distinct_outcome(built):
    store = a_store()
    client = make(built, store)
    result = outcome(client, "A-0002", outcome="NOT_INTERESTED").get_json()
    assert result["effect"] == calls.STOP and result["task"] is None
    entries = store.suppression()
    assert any("not interested" in e.get("Reason", "") for e in entries)  # its own reason, not DNC


def test_a_phone_only_lead_can_be_called_and_an_email_lead_stays_callable(built):
    store = a_store()
    client = make(built, store)
    # phone-only lead: a call is recorded and scheduled
    assert outcome(client, "A-0001", outcome="NO_ANSWER",
                   called_at="2026-09-28T13:00:00+00:00").get_json()["task"]["status"] == "scheduled"
    # email+phone lead: having an email does not prevent calling
    assert outcome(client, "A-0002", outcome="NO_ANSWER",
                   called_at="2026-09-28T13:00:00+00:00").get_json()["task"]["status"] == "scheduled"


def test_a_task_becomes_overdue_on_a_later_clock(built):
    store = a_store()
    now = {"t": MON}
    client = make(built, store, now=lambda: now["t"])
    outcome(client, "A-0001", outcome="NO_ANSWER", called_at="2026-09-28T13:00:00+00:00")  # due 2026-10-01
    assert snapshot(client)["calls_overdue"] == 0
    now["t"] = at("2026-10-02 09:00")  # the New York day after the due date
    data = snapshot(client)
    assert data["calls_overdue"] == 1
    assert next(v for v in data["leads"] if v["id"] == "A-0001")["call_task"]["overdue"] is True


def test_an_unknown_lead_or_outcome_is_refused(built):
    store = a_store()
    client = make(built, store)
    assert outcome(client, "Z-9999", outcome="NO_ANSWER").status_code == 404
    assert outcome(client, "A-0001", outcome="MAYBE").status_code == 400
