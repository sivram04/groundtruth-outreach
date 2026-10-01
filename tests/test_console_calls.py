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
    tid = outcome(client, "A-0001", outcome="NO_ANSWER",
                  called_at="2026-09-28T13:00:00+00:00").get_json()["task"]["id"]
    snoozed = act(client, "A-0001", action="SNOOZE", task_id=tid,
                  snooze_to="2026-10-09T14:00:00+00:00").get_json()
    assert snoozed["task"]["snoozed"] is True and snoozed["task"]["due"] == "2026-10-09T14:00:00+00:00"
    done = act(client, "A-0001", action="COMPLETE", task_id=tid).get_json()
    assert done["task"]["status"] == "done"
    # once done, there is no open task, and acting again is refused
    assert act(client, "A-0001", action="CANCEL", task_id=tid).status_code == 409


def test_a_task_action_without_a_task_id_is_refused(built):
    # The previous UI omitted task_id and the route fell back to the current task; that fallback is gone.
    store = a_store()
    client = make(built, store)
    a = outcome(client, "A-0001", outcome="NO_ANSWER",
                called_at="2026-09-28T13:00:00+00:00").get_json()["task"]["id"]
    b = outcome(client, "A-0001", outcome="CALLBACK", note="call me",
                callback_at="2026-10-02T14:00:00+00:00").get_json()["task"]["id"]
    assert a != b
    assert act(client, "A-0001", action="COMPLETE").status_code == 400  # missing
    assert act(client, "A-0001", action="COMPLETE", task_id="").status_code == 400  # blank
    assert act(client, "A-0001", action="COMPLETE", task_id=a).status_code == 409  # stale
    # none of those touched the newer task B
    lead = next(v for v in snapshot(client)["leads"] if v["id"] == "A-0001")
    assert lead["call_task"]["id"] == b and lead["call_task"]["status"] == "scheduled"
    assert act(client, "A-0001", action="COMPLETE", task_id=b).get_json()["task"]["status"] == "done"
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


def _when(data, lead_id):
    return next(t for t in data["call_tasks"] if t["lead_id"] == lead_id)["when"]


def test_the_queue_buckets_overdue_today_and_upcoming(built):
    store = a_store()
    now = {"t": at("2026-10-01 09:00")}  # Thursday
    client = make(built, store, now=lambda: now["t"])
    # A-0001 no-answer called Monday -> due Thursday 2026-10-01 (a DATE): due today, not overdue.
    outcome(client, "A-0001", outcome="NO_ANSWER", called_at="2026-09-28T13:00:00+00:00")
    # A-0002 callback for Tuesday (a TIME already past by Thursday): overdue.
    outcome(client, "A-0002", outcome="CALLBACK", callback_at="2026-09-30T14:00:00+00:00")
    data = snapshot(client)
    assert _when(data, "A-0001") == "TODAY" and _when(data, "A-0002") == "OVERDUE"
    assert data["calls_overdue"] == 1 and data["calls_due_today"] == 1
    # overdue sorts before due-today
    assert [t["lead_id"] for t in data["call_tasks"]] == ["A-0002", "A-0001"]
    assert data["calls_unreadable"] is False


def test_an_upcoming_call_is_bucketed_separately(built):
    store = a_store()
    client = make(built, store, now=lambda: MON)  # Monday
    outcome(client, "A-0001", outcome="NO_ANSWER", called_at="2026-09-28T13:00:00+00:00")  # due Thu
    data = snapshot(client)
    assert _when(data, "A-0001") == "UPCOMING"
    assert data["calls_overdue"] == 0 and data["calls_due_today"] == 0


def test_an_unreadable_call_log_is_an_unavailable_queue_not_no_calls(built):
    store = a_store()
    client = make(built, store)
    outcome(client, "A-0001", outcome="NO_ANSWER", called_at="2026-09-28T13:00:00+00:00")

    def boom():
        raise RuntimeError("the Call log tab's columns were changed")

    store.call_events = boom
    data = snapshot(client)
    assert data["calls_unreadable"] is True and data["call_tasks"] == []  # unavailable, not "no calls due"


def test_an_unknown_lead_or_outcome_is_refused(built):
    store = a_store()
    client = make(built, store)
    assert outcome(client, "Z-9999", outcome="NO_ANSWER").status_code == 404
    assert outcome(client, "A-0001", outcome="MAYBE").status_code == 400


def test_do_not_contact_stays_effective_through_a_later_no_answer(built):
    # Finding 2: a phone-only lead marked do-not-contact must not be rescheduled by a routine no-answer.
    store = a_store()
    client = make(built, store)
    first = outcome(client, "A-0001", outcome="DO_NOT_CONTACT", note="asked to be removed").get_json()
    assert first["task"] is None and first["effect"] == calls.STOP
    second = outcome(client, "A-0001", outcome="NO_ANSWER",
                     called_at="2026-09-29T13:00:00+00:00").get_json()
    assert second["task"] is None and second["effect"] == calls.STOP  # not reopened, not lifted
    data = snapshot(client)
    assert data["call_tasks"] == [] and data["calls_overdue"] == 0
    lead = next(v for v in data["leads"] if v["id"] == "A-0001")
    assert lead["call_effect"] == calls.STOP and lead["call_task"] is None


def test_a_stale_task_action_is_refused_and_the_newer_task_is_untouched(built):
    # Finding 3: an action carrying the old task's id must be refused, not applied to the newer task.
    store = a_store()
    client = make(built, store)
    old = outcome(client, "A-0001", outcome="NO_ANSWER",
                  called_at="2026-09-28T13:00:00+00:00").get_json()["task"]
    new = outcome(client, "A-0001", outcome="CALLBACK", note="call me",
                  callback_at="2026-10-02T14:00:00+00:00").get_json()["task"]
    assert old["id"] != new["id"]
    stale = act(client, "A-0001", action="COMPLETE", task_id=old["id"])
    assert stale.status_code == 409  # refused: the task changed since it was shown
    lead = next(v for v in snapshot(client)["leads"] if v["id"] == "A-0001")
    assert lead["call_task"]["id"] == new["id"] and lead["call_task"]["status"] == "scheduled"
    # naming the current task still works
    assert act(client, "A-0001", action="COMPLETE",
               task_id=new["id"]).get_json()["task"]["status"] == "done"


def test_a_ui_shaped_retry_with_an_advancing_clock_makes_one_event(built):
    # Finding 4: the UI omits called_at, so each retry gets a fresh server time. A submission id keeps it
    # one logical call even as the clock advances (a lost response after a successful write, retried).
    store = a_store()
    now = {"t": MON}
    client = make(built, store, now=lambda: now["t"])
    body = {"outcome": "NO_ANSWER", "note": "rang out", "submission_id": "sub-42"}  # no called_at, as the UI sends
    first = outcome(client, "A-0001", **body).get_json()
    now["t"] = at("2026-09-28 09:05")  # the clock has advanced between the retry, as in the review's probe
    second = outcome(client, "A-0001", **body).get_json()
    assert first["task"]["due"] == second["task"]["due"]
    assert len(store.call_events()) == 1  # one event, one history row - not two
    assert len(snapshot(client)["call_tasks"]) == 1


def test_a_suppression_write_failure_still_enforces_the_stop_and_reports_it(built):
    # Finding 1: if the redundant Suppression entry cannot be written, the stop is still recorded (the
    # Call log is what the eligibility paths read) and the response says so rather than claiming success.
    store = a_store()

    def boom(_entries):
        raise RuntimeError("the Suppression tab could not be written")

    store.append_suppression = boom
    client = make(built, store)
    result = outcome(client, "A-0002", outcome="DO_NOT_CONTACT", note="remove me")
    assert result.status_code == 200
    body = result.get_json()
    assert body["recorded"] is True and body["effect"] == calls.STOP
    assert body["suppression_written"] is False and "Suppression" in body.get("warning", "")
    # the stop is enforced by the recorded call event, independent of the Suppression tab
    assert calls.outreach_effect([e for e in store.call_events() if e["Lead ID"] == "A-0002"]) == calls.STOP
