"""The pure A/B module: a deterministic, immutable assignment; safe-to-assign gating; and a report
that counts only outcomes recorded at or after a lead was assigned."""

import pytest

from outreach import calls, experiments, sequence
from stage4_fakes import lead

ASSIGNED_AT = "2026-09-28 09:00:00"  # when the demo leads were assigned
AFTER = "2026-09-28 10:00:00"        # an hour later — attributable to the experiment
BEFORE = "2026-09-27 17:00:00"       # the evening before — not a result of the experiment


def ev(lead_id, event, step="", match="ADDRESS", detail="", when=AFTER):
    return {"Lead ID": lead_id, "Event": event, "Step": step, "Match": match, "Detail": detail,
            sequence.OCCURRED: when}


def call(lead_id, kind="OUTCOME", when=AFTER):
    return {"Lead ID": lead_id, "Kind": kind, "Called at (UTC)": when}


# -- the assignment is deterministic and immutable -----------------------------------------------

def test_the_variant_is_deterministic_and_stable():
    first = experiments.variant_index("Subject test", "A-0001")
    assert first == experiments.variant_index("Subject test", "A-0001")  # recomputed, identical
    assert first in (0, 1)
    assert all(experiments.variant_index("Other", "A-0001") in (0, 1) for _ in range(3))


def test_define_rows_need_two_distinct_names():
    with pytest.raises(ValueError):
        experiments.define_rows("", "A", "B", "now")
    with pytest.raises(ValueError):
        experiments.define_rows("E", "A", "", "now")
    with pytest.raises(ValueError):
        experiments.define_rows("E", "Same", "Same", "now")
    rows = experiments.define_rows("E", "Short", "Long", "now")
    assert [r["Variant"] for r in rows] == ["Short", "Long"]
    assert [r["Variant index"] for r in rows] == ["0", "1"]
    again = experiments.define_rows("E", "Short", "Long", "later")
    assert [r["Record ID"] for r in again] == [r["Record ID"] for r in rows]


def test_an_assign_record_id_is_the_same_for_a_lead_however_often_assigned():
    a = experiments.assign_rows("E", ["Short", "Long"], ["A-0001"], "now")[0]
    b = experiments.assign_rows("E", ["Short", "Long"], ["A-0001"], "later")[0]
    assert a["Record ID"] == b["Record ID"]  # a re-assignment is the same row -> skipped on append


def test_read_takes_the_earliest_assignment_so_a_lead_never_moves():
    define = experiments.define_rows("E", "Short", "Long", "t0")
    first = {"Record ID": "r1", "Experiment": "E", "Kind": "ASSIGN", "Variant": "Short",
             "Variant index": "0", "Lead ID": "A-0001", "Recorded at (UTC)": ASSIGNED_AT}
    later = {"Record ID": "r2", "Experiment": "E", "Kind": "ASSIGN", "Variant": "Long",
             "Variant index": "1", "Lead ID": "A-0001", "Recorded at (UTC)": AFTER}
    state = experiments.read([*define, first, later])["E"]
    assert state["assignments"] == {"A-0001": 0}
    assert state["assigned_at"]["A-0001"] == ASSIGNED_AT  # the earliest row's time is kept
    assert experiments.variant_name(state, "A-0001") == "Short"


def test_a_rename_changes_the_label_not_the_lead():
    define = experiments.define_rows("E", "Short", "Long", "t0")
    assign = experiments.assign_rows("E", ["Short", "Long"], ["A-0001", "A-0002"], "t1")
    rename = experiments.define_rows("E", "Concise", "Detailed", "t2")
    state = experiments.read([*define, *assign, *rename])["E"]
    assert state["variants"] == ["Concise", "Detailed"]
    for lead_id, index in state["assignments"].items():
        assert experiments.variant_name(state, lead_id) == ["Concise", "Detailed"][index]


def test_current_is_the_most_recently_defined_experiment():
    rows = [*experiments.define_rows("Old", "A", "B", "t0"),
            *experiments.define_rows("New", "C", "D", "t1")]
    assert experiments.current(experiments.read(rows)) == "New"
    assert experiments.current({}) is None


def test_eligibility_needs_an_emailable_qualified_lead():
    assert experiments.eligible(lead("A-0001"))
    assert not experiments.eligible(lead("A-0002", **{"BEST EMAIL": "", "Their email": ""}))
    assert not experiments.eligible(lead("A-0003", **{"Email check": "RISKY"}))
    assert not experiments.eligible(lead("A-0004", **{"Fit": "DISQUALIFIED"}))
    assert not experiments.eligible(lead("A-0005", HOLD="later"))


def test_safe_to_assign_blocks_suppression_and_a_call_stop_or_hold():
    row = lead("A-0001")
    assert experiments.safe_to_assign(row, suppressed=False, call_effect=calls.CONTINUE)
    assert not experiments.safe_to_assign(row, suppressed=True, call_effect=calls.CONTINUE)
    assert not experiments.safe_to_assign(row, suppressed=False, call_effect=calls.STOP)
    assert not experiments.safe_to_assign(row, suppressed=False, call_effect=calls.HOLD)
    # An ineligible lead is unsafe whatever the safety state.
    assert not experiments.safe_to_assign(lead("A-0002", **{"BEST EMAIL": "", "Their email": ""}),
                                          suppressed=False, call_effect=calls.CONTINUE)


# -- the report -----------------------------------------------------------------------------------

def _two_variant_state(assigned_at=ASSIGNED_AT):
    define = experiments.define_rows("E", "Short", "Long", "t0")
    rows = [*define,
            {"Record ID": "a", "Experiment": "E", "Kind": "ASSIGN", "Variant": "Short",
             "Variant index": "0", "Lead ID": "A-0001", "Recorded at (UTC)": assigned_at},
            {"Record ID": "b", "Experiment": "E", "Kind": "ASSIGN", "Variant": "Long",
             "Variant index": "1", "Lead ID": "A-0002", "Recorded at (UTC)": assigned_at}]
    return experiments.read(rows)["E"]


def _metric(variant, key):
    return next(m for m in variant["metrics"] if m["key"] == key)


def _leads():
    return {"A-0001": lead("A-0001"), "A-0002": lead("A-0002")}


def test_report_counts_outcomes_after_assignment_with_explicit_denominators():
    state = _two_variant_state()
    events = [
        ev("A-0001", sequence.DRAFTED, "INITIAL", "DRAFT", "draft x, tracked"),
        ev("A-0001", sequence.SENT, "INITIAL", "DRAFT"),
        ev("A-0001", sequence.REPLIED),
        ev("A-0001", sequence.OPEN, "INITIAL"),
        ev("A-0001", sequence.SENT, "FOLLOWUP_1", "DRAFT"),
        ev("A-0002", sequence.SENT, "INITIAL", "ADDRESS"),
        ev("A-0002", sequence.OPT_OUT),
    ]
    report = experiments.report(state, _leads(), events, [call("A-0001")], [])
    short, long = report["variants"]
    assert short["name"] == "Short" and long["name"] == "Long"
    assert _metric(short, "assigned")["count"] == 1
    assert _metric(short, "sent")["count"] == 1 and _metric(short, "sent")["denominator_label"] == "assigned"
    replies = _metric(short, "replies")
    assert replies["count"] == 1 and replies["denominator"] == 1 and replies["denominator_label"] == "confirmed sent"
    assert _metric(short, "followups")["count"] == 1 and _metric(short, "followups")["label"] == "Follow-up emails sent"
    assert _metric(short, "calls")["count"] == 1
    assert _metric(long, "opt_outs")["count"] == 1
    assert _metric(short, "opens")["estimate"] is True
    assert _metric(short, "opens")["denominator_label"] == "tracked sends"
    assert report["excluded"] == {"before_assignment": 0, "undated": 0}


def test_an_outcome_recorded_before_assignment_is_not_counted():
    # The reviewer's case: a lead assigned Oct 1 with a Sep 30 send + reply. Neither is a result of
    # the test, so neither is counted; both are tallied as excluded.
    state = _two_variant_state(assigned_at="2026-10-01 09:00:00")
    events = [ev("A-0001", sequence.SENT, "INITIAL", "DRAFT", when="2026-09-30 10:00:00"),
              ev("A-0001", sequence.REPLIED, when="2026-09-30 11:00:00")]
    report = experiments.report(state, _leads(), events, [], [])
    short = report["variants"][0]
    assert _metric(short, "sent")["count"] == 0
    assert _metric(short, "replies")["count"] == 0
    assert short["excluded"]["before_assignment"] == 2
    assert report["excluded"]["before_assignment"] == 2


def test_a_call_before_assignment_is_not_counted():
    state = _two_variant_state(assigned_at="2026-10-01 09:00:00")
    report = experiments.report(state, _leads(), [], [call("A-0001", when="2026-09-30 10:00:00")], [])
    assert _metric(report["variants"][0], "calls")["count"] == 0
    assert report["excluded"]["before_assignment"] == 1


def test_an_event_that_cannot_be_dated_is_excluded_not_counted():
    state = _two_variant_state()
    report = experiments.report(state, _leads(), [ev("A-0001", sequence.SENT, "INITIAL", "DRAFT", when="")],
                                [], [])
    assert _metric(report["variants"][0], "sent")["count"] == 0
    assert report["excluded"]["undated"] == 1


def test_everything_is_excluded_when_the_assignment_has_no_time():
    state = _two_variant_state(assigned_at="")  # an assignment row with no readable time
    report = experiments.report(state, _leads(), [ev("A-0001", sequence.SENT, "INITIAL", "DRAFT")], [], [])
    assert _metric(report["variants"][0], "sent")["count"] == 0
    assert report["excluded"]["undated"] == 1


def test_positive_replies_and_meetings_are_not_available_without_a_real_signal():
    state = _two_variant_state()
    report = experiments.report(state, _leads(), [ev("A-0001", sequence.SENT, "INITIAL", "DRAFT")], [], [])
    for variant in report["variants"]:
        assert _metric(variant, "positive_replies")["available"] is False
        assert _metric(variant, "meetings")["available"] is False


def test_a_recorded_meeting_event_after_assignment_makes_meetings_available():
    state = _two_variant_state()
    events = [ev("A-0001", sequence.SENT, "INITIAL", "DRAFT"),
              ev("A-0001", experiments.MEETING, "INITIAL")]
    report = experiments.report(state, _leads(), events, [], [])
    meetings = _metric(report["variants"][0], "meetings")
    assert meetings["available"] is True and meetings["count"] == 1


def test_no_winner_is_declared_and_small_samples_are_flagged():
    report = experiments.report(_two_variant_state(), _leads(), [], [], [])
    assert report["comparison"]["winner"] is None
    assert report["comparison"]["can_compare"] is False
    assert "Too few" in report["comparison"]["note"]


def test_calls_are_unavailable_not_zero_when_the_call_log_is_unreadable():
    state = _two_variant_state()
    report = experiments.report(state, _leads(), [ev("A-0001", sequence.SENT, "INITIAL", "DRAFT")],
                                None, None)
    assert report["calls_unreadable"] is True and report["suppression_unreadable"] is True
    calls_metric = _metric(report["variants"][0], "calls")
    assert calls_metric["available"] is False and "count" not in calls_metric
    assert report["variants"][0]["suppressed"] is None  # not guessed when the list is unreadable


def test_suppressed_but_assigned_is_counted_as_context():
    state = _two_variant_state()
    entries = [{"Address or domain": "sam@example-electric.test", "Reason": "opted out"}]
    report = experiments.report(state, _leads(), [], [], entries)
    assert report["variants"][0]["suppressed"] == 1
