"""Call outcomes and the tasks they schedule: timing by rule or explicit callback, the task lifecycle,
overdue on a controlled clock, timezone handling, idempotent event ids, and the email effect."""

from datetime import datetime, timezone

from outreach import calls

UTC = timezone.utc
MON_9ET = datetime(2026, 9, 28, 13, 0, tzinfo=UTC)  # Monday 09:00 America/New_York


def test_no_answer_schedules_by_the_business_day_rule_on_the_new_york_date():
    due, kind = calls.next_due(calls.NO_ANSWER, MON_9ET.isoformat(), no_answer_business_days=3)
    assert kind == "DATE" and due == "2026-10-01"  # Mon + 3 business days = Thu
    # a call late in the New York evening keeps that New York date, not the next UTC day
    late = datetime(2026, 9, 29, 1, 0, tzinfo=UTC).isoformat()  # 2026-09-28 21:00 ET
    due2, _ = calls.next_due(calls.NO_ANSWER, late, no_answer_business_days=3)
    assert due2 == "2026-10-01"


def test_a_callback_uses_the_explicit_time_and_never_the_note():
    due, kind = calls.next_due(calls.CALLBACK, MON_9ET.isoformat(), no_answer_business_days=3,
                               callback_at="2026-10-05T15:30:00-04:00")
    assert kind == "TIME" and due == "2026-10-05T19:30:00+00:00"  # normalised to UTC


def test_a_callback_without_a_time_is_refused():
    try:
        calls.next_due(calls.CALLBACK, MON_9ET.isoformat(), no_answer_business_days=3)
        assert False, "a callback with no time should raise"
    except ValueError:
        pass


def test_non_scheduling_outcomes_schedule_nothing():
    for outcome in (calls.INTERESTED, calls.NOT_INTERESTED, calls.WRONG_NUMBER, calls.DO_NOT_CONTACT):
        assert calls.next_due(outcome, MON_9ET.isoformat(), no_answer_business_days=3) == (None, None)


def test_email_effect_maps_outcomes():
    assert calls.email_effect(calls.DO_NOT_CONTACT) == calls.STOP
    assert calls.email_effect(calls.NOT_INTERESTED) == calls.STOP
    assert calls.email_effect(calls.INTERESTED) == calls.HOLD
    assert calls.email_effect(calls.CALLBACK) == calls.HOLD
    assert calls.email_effect(calls.NO_ANSWER) == calls.CONTINUE
    assert calls.email_effect(calls.WRONG_NUMBER) == calls.CONTINUE


def test_the_same_outcome_twice_has_the_same_event_id():
    a = calls.outcome_event("A-1", calls.NO_ANSWER, "no answer", MON_9ET.isoformat(),
                            no_answer_business_days=3, now=MON_9ET)
    b = calls.outcome_event("A-1", calls.NO_ANSWER, "no answer", MON_9ET.isoformat(),
                            no_answer_business_days=3, now=datetime(2026, 9, 28, 14, 0, tzinfo=UTC))
    assert a["Event ID"] == b["Event ID"]  # a repeated submission is the same event
    c = calls.outcome_event("A-1", calls.NO_ANSWER, "different note", MON_9ET.isoformat(),
                            no_answer_business_days=3, now=MON_9ET)
    assert c["Event ID"] != a["Event ID"]


def test_call_state_opens_a_task_for_no_answer():
    event = calls.outcome_event("A-1", calls.NO_ANSWER, "rang out", MON_9ET.isoformat(),
                                no_answer_business_days=3, now=MON_9ET)
    state = calls.call_state([event], now=MON_9ET)
    task = state["task"]
    assert task["status"] == "scheduled" and task["due"] == "2026-10-01" and task["due_kind"] == "DATE"
    assert task["outcome"] == calls.NO_ANSWER and task["note"] == "rang out"
    assert state["email_effect"] == calls.CONTINUE


def test_overdue_is_from_the_controlled_clock_and_new_york_date():
    event = calls.outcome_event("A-1", calls.NO_ANSWER, "", MON_9ET.isoformat(),
                                no_answer_business_days=3, now=MON_9ET)  # due 2026-10-01
    assert calls.call_state([event], now=datetime(2026, 9, 30, 13, 0, tzinfo=UTC))["task"]["overdue"] is False
    assert calls.call_state([event], now=datetime(2026, 10, 1, 20, 0, tzinfo=UTC))["task"]["overdue"] is False  # due today
    assert calls.call_state([event], now=datetime(2026, 10, 2, 13, 0, tzinfo=UTC))["task"]["overdue"] is True


def test_complete_snooze_and_cancel_change_the_task():
    outcome = calls.outcome_event("A-1", calls.NO_ANSWER, "", MON_9ET.isoformat(),
                                  no_answer_business_days=3, now=MON_9ET)
    task_id = calls.call_state([outcome], now=MON_9ET)["task"]["id"]
    done = calls.action_event("A-1", calls.COMPLETE, task_id, now=MON_9ET)
    assert calls.call_state([outcome, done], now=MON_9ET)["task"]["status"] == "done"
    cancelled = calls.action_event("A-1", calls.CANCEL, task_id, now=MON_9ET)
    assert calls.call_state([outcome, cancelled], now=MON_9ET)["task"]["status"] == "cancelled"
    snoozed = calls.action_event("A-1", calls.SNOOZE, task_id, snooze_to="2026-10-09T14:00:00+00:00",
                                 now=MON_9ET)
    after = calls.call_state([outcome, snoozed], now=MON_9ET)["task"]
    assert after["snoozed"] is True and after["due"] == "2026-10-09T14:00:00+00:00" and after["status"] == "scheduled"


def test_repeating_an_action_on_the_same_task_is_the_same_event():
    a = calls.action_event("A-1", calls.COMPLETE, "task-x", now=MON_9ET)
    b = calls.action_event("A-1", calls.COMPLETE, "task-x", now=datetime(2026, 9, 28, 15, 0, tzinfo=UTC))
    assert a["Event ID"] == b["Event ID"]
    other = calls.action_event("A-1", calls.COMPLETE, "task-y", now=MON_9ET)  # a different task
    assert other["Event ID"] != a["Event ID"]


def test_a_later_scheduling_outcome_replaces_the_task_and_do_not_contact_closes_it():
    first = calls.outcome_event("A-1", calls.NO_ANSWER, "", MON_9ET.isoformat(),
                                no_answer_business_days=3, now=MON_9ET)
    later = calls.outcome_event("A-1", calls.CALLBACK, "call me", MON_9ET.isoformat(),
                                no_answer_business_days=3, callback_at="2026-10-03T18:00:00+00:00",
                                now=datetime(2026, 9, 28, 14, 0, tzinfo=UTC))
    state = calls.call_state([first, later], now=MON_9ET)
    assert state["task"]["outcome"] == calls.CALLBACK and state["email_effect"] == calls.HOLD
    dnc = calls.outcome_event("A-1", calls.DO_NOT_CONTACT, "", MON_9ET.isoformat(),
                              no_answer_business_days=3, now=datetime(2026, 9, 28, 15, 0, tzinfo=UTC))
    closed = calls.call_state([first, later, dnc], now=MON_9ET)
    assert closed["task"] is None and closed["email_effect"] == calls.STOP  # no task; email stopped


def test_do_not_contact_is_sticky_and_a_later_no_answer_neither_reopens_nor_lifts_it():
    # Finding 2: an explicit do-not-contact is a per-lead block. A routine later outcome logs history but
    # never reschedules a call or lifts the stop.
    dnc = calls.outcome_event("A-1", calls.DO_NOT_CONTACT, "asked to be removed", MON_9ET.isoformat(),
                              no_answer_business_days=3, now=MON_9ET)
    later = calls.outcome_event("A-1", calls.NO_ANSWER, "rang out again", MON_9ET.isoformat(),
                                no_answer_business_days=3, now=datetime(2026, 9, 29, 13, 0, tzinfo=UTC))
    state = calls.call_state([dnc, later], now=datetime(2026, 9, 29, 13, 0, tzinfo=UTC))
    assert state["task"] is None  # no call is scheduled over a do-not-contact
    assert state["email_effect"] == calls.STOP and state["do_not_contact"] is True
    assert len(state["history"]) == 2  # both are recorded - history is separate from permission
    assert calls.outreach_effect([dnc, later]) == calls.STOP


def test_a_stale_action_cannot_close_a_newer_task():
    # Finding 3: a COMPLETE aimed at an old task, recorded after a newer task opened, must not close the
    # newer one - the action names its target and replay honours it.
    first = calls.outcome_event("A-1", calls.NO_ANSWER, "", MON_9ET.isoformat(),
                                no_answer_business_days=3, now=MON_9ET)
    t1 = calls.call_state([first], now=MON_9ET)["task"]["id"]
    later = calls.outcome_event("A-1", calls.CALLBACK, "call me", MON_9ET.isoformat(),
                                no_answer_business_days=3, callback_at="2026-10-03T18:00:00+00:00",
                                now=datetime(2026, 9, 28, 13, 30, tzinfo=UTC))
    t2 = calls.call_state([first, later], now=MON_9ET)["task"]["id"]
    assert t1 != t2
    stale = calls.action_event("A-1", calls.COMPLETE, t1,  # aimed at the superseded task
                               now=datetime(2026, 9, 28, 14, 0, tzinfo=UTC))
    still_open = calls.call_state([first, later, stale], now=MON_9ET)["task"]
    assert still_open["id"] == t2 and still_open["status"] == "scheduled"  # newer task untouched
    aimed = calls.action_event("A-1", calls.COMPLETE, t2,  # aimed at the current task
                               now=datetime(2026, 9, 28, 14, 0, tzinfo=UTC))
    assert calls.call_state([first, later, aimed], now=MON_9ET)["task"]["status"] == "done"


def test_action_event_persists_its_target_task():
    event = calls.action_event("A-1", calls.COMPLETE, "task-x", now=MON_9ET)
    assert event["Task ID"] == "task-x"  # the target is stored, not only folded into the Event ID


def test_a_ui_shaped_retry_is_one_event_though_the_clock_advanced():
    # Finding 4: the UI omits the call time, so each retry gets a fresh server timestamp. A stable
    # submission id makes the retry one logical event; a genuinely new call carries a new id.
    first = calls.outcome_event("A-1", calls.NO_ANSWER, "rang out", "2026-09-28T13:00:05+00:00",
                                no_answer_business_days=3, now=MON_9ET, submission_id="sub-1")
    retry = calls.outcome_event("A-1", calls.NO_ANSWER, "rang out", "2026-09-28T13:00:12+00:00",
                                no_answer_business_days=3,
                                now=datetime(2026, 9, 28, 13, 0, 12, tzinfo=UTC), submission_id="sub-1")
    assert first["Event ID"] == retry["Event ID"]  # retry-stable despite an advancing clock/call time
    fresh = calls.outcome_event("A-1", calls.NO_ANSWER, "rang out", "2026-09-28T13:00:20+00:00",
                                no_answer_business_days=3, now=MON_9ET, submission_id="sub-2")
    assert fresh["Event ID"] != first["Event ID"]  # a genuinely new call is recordable
    # without a submission id the content hash still includes the call time (a programmatic caller)
    a = calls.outcome_event("A-1", calls.NO_ANSWER, "rang out", MON_9ET.isoformat(),
                            no_answer_business_days=3, now=MON_9ET)
    b = calls.outcome_event("A-1", calls.NO_ANSWER, "rang out", "2026-09-28T13:00:30+00:00",
                            no_answer_business_days=3, now=MON_9ET)
    assert a["Event ID"] != b["Event ID"]


def test_outreach_effect_and_blocks_outreach():
    # Finding 1 helper: the effect the eligibility paths read, without a clock.
    def ev(outcome, when, callback=None):
        return calls.outcome_event("A-1", outcome, "", MON_9ET.isoformat(), no_answer_business_days=3,
                                   callback_at=callback, now=when)
    assert calls.outreach_effect([ev(calls.NO_ANSWER, MON_9ET)]) == calls.CONTINUE
    assert calls.outreach_effect([ev(calls.INTERESTED, MON_9ET)]) == calls.HOLD
    assert calls.outreach_effect([ev(calls.NOT_INTERESTED, MON_9ET)]) == calls.STOP
    assert calls.outreach_effect([]) == calls.CONTINUE
    assert calls.blocks_outreach(calls.STOP) and calls.blocks_outreach(calls.HOLD)
    assert not calls.blocks_outreach(calls.CONTINUE)
