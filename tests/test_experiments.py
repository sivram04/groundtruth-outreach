"""The pure A/B module: a deterministic, immutable assignment and an honest variant-level report."""

import pytest

from outreach import experiments, sequence
from stage4_fakes import lead


def ev(lead_id, event, step="", match="ADDRESS", detail=""):
    return {"Lead ID": lead_id, "Event": event, "Step": step, "Match": match, "Detail": detail}


def call(lead_id, kind="OUTCOME"):
    return {"Lead ID": lead_id, "Kind": kind}


# -- the assignment is deterministic and immutable -----------------------------------------------

def test_the_variant_is_deterministic_and_stable():
    first = experiments.variant_index("Subject test", "A-0001")
    assert first == experiments.variant_index("Subject test", "A-0001")  # recomputed, identical
    assert first in (0, 1)
    # Different experiments can place the same lead differently, but each is stable in itself.
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
    # Defining the same experiment again yields the same Record IDs (idempotent on append).
    again = experiments.define_rows("E", "Short", "Long", "later")
    assert [r["Record ID"] for r in again] == [r["Record ID"] for r in rows]


def test_an_assign_record_id_is_the_same_for_a_lead_however_often_assigned():
    a = experiments.assign_rows("E", ["Short", "Long"], ["A-0001"], "now")[0]
    b = experiments.assign_rows("E", ["Short", "Long"], ["A-0001"], "later")[0]
    assert a["Record ID"] == b["Record ID"]  # a re-assignment is the same row -> skipped on append


def test_read_takes_the_earliest_assignment_so_a_lead_never_moves():
    define = experiments.define_rows("E", "Short", "Long", "t0")
    first = {"Record ID": "r1", "Experiment": "E", "Kind": "ASSIGN", "Variant": "Short",
             "Variant index": "0", "Lead ID": "A-0001", "Recorded at (UTC)": "t1"}
    # A later, contradictory row (different index/name) for the same lead must be ignored.
    later = {"Record ID": "r2", "Experiment": "E", "Kind": "ASSIGN", "Variant": "Long",
             "Variant index": "1", "Lead ID": "A-0001", "Recorded at (UTC)": "t2"}
    state = experiments.read([*define, first, later])["E"]
    assert state["assignments"] == {"A-0001": 0}
    assert experiments.variant_name(state, "A-0001") == "Short"


def test_a_rename_changes_the_label_not_the_lead():
    define = experiments.define_rows("E", "Short", "Long", "t0")
    assign = experiments.assign_rows("E", ["Short", "Long"], ["A-0001", "A-0002"], "t1")
    rename = experiments.define_rows("E", "Concise", "Detailed", "t2")  # later DEFINE wins the label
    state = experiments.read([*define, *assign, *rename])["E"]
    assert state["variants"] == ["Concise", "Detailed"]
    # The lead keeps its index; only the shown name changes.
    for lead_id, index in state["assignments"].items():
        assert experiments.variant_name(state, lead_id) == ["Concise", "Detailed"][index]


def test_current_is_the_most_recently_defined_experiment():
    rows = [*experiments.define_rows("Old", "A", "B", "t0"),
            *experiments.define_rows("New", "C", "D", "t1")]
    assert experiments.current(experiments.read(rows)) == "New"
    assert experiments.current({}) is None


def test_eligibility_needs_an_emailable_qualified_lead():
    assert experiments.eligible(lead("A-0001"))  # OK + QUALIFIED + has email
    assert not experiments.eligible(lead("A-0002", **{"BEST EMAIL": "", "Their email": ""}))
    assert not experiments.eligible(lead("A-0003", **{"Email check": "RISKY"}))
    assert not experiments.eligible(lead("A-0004", **{"Fit": "DISQUALIFIED"}))
    assert not experiments.eligible(lead("A-0005", HOLD="later"))


# -- the report -----------------------------------------------------------------------------------

def _two_variant_state():
    # Force two known leads into the two variants regardless of the hash, by reading rows directly.
    define = experiments.define_rows("E", "Short", "Long", "t0")
    rows = [*define,
            {"Record ID": "a", "Experiment": "E", "Kind": "ASSIGN", "Variant": "Short",
             "Variant index": "0", "Lead ID": "A-0001", "Recorded at (UTC)": "t1"},
            {"Record ID": "b", "Experiment": "E", "Kind": "ASSIGN", "Variant": "Long",
             "Variant index": "1", "Lead ID": "A-0002", "Recorded at (UTC)": "t1"}]
    return experiments.read(rows)["E"]


def _metric(variant, key):
    return next(m for m in variant["metrics"] if m["key"] == key)


def test_report_counts_with_explicit_denominators():
    state = _two_variant_state()
    leads = {"A-0001": lead("A-0001"), "A-0002": lead("A-0002")}
    events = [
        ev("A-0001", sequence.DRAFTED, "INITIAL", "DRAFT", "draft x, tracked"),
        ev("A-0001", sequence.SENT, "INITIAL", "DRAFT"),
        ev("A-0001", sequence.REPLIED),
        ev("A-0001", sequence.OPEN, "INITIAL"),
        ev("A-0001", sequence.SENT, "FOLLOWUP_1", "DRAFT"),
        ev("A-0002", sequence.SENT, "INITIAL", "ADDRESS"),
        ev("A-0002", sequence.OPT_OUT),
    ]
    report = experiments.report(state, leads, events, [call("A-0001")], [])
    short, long = report["variants"]
    assert short["name"] == "Short" and long["name"] == "Long"
    assert _metric(short, "assigned")["count"] == 1
    assert _metric(short, "sent")["count"] == 1 and _metric(short, "sent")["denominator_label"] == "assigned"
    replies = _metric(short, "replies")
    assert replies["count"] == 1 and replies["denominator"] == 1 and replies["denominator_label"] == "confirmed sent"
    assert _metric(short, "followups")["count"] == 1 and _metric(short, "followups")["label"] == "Follow-up emails sent"
    assert _metric(short, "calls")["count"] == 1
    assert _metric(long, "opt_outs")["count"] == 1
    # Opens are an estimate over tracked sends.
    assert _metric(short, "opens")["estimate"] is True
    assert _metric(short, "opens")["denominator_label"] == "tracked sends"
    assert _metric(long, "opens")["denominator"] == 0 and _metric(long, "opens")["rate"] == "-"


def test_positive_replies_and_meetings_are_not_available_without_a_real_signal():
    state = _two_variant_state()
    leads = {"A-0001": lead("A-0001"), "A-0002": lead("A-0002")}
    events = [ev("A-0001", sequence.SENT, "INITIAL", "DRAFT")]
    report = experiments.report(state, leads, events, [], [])
    for variant in report["variants"]:
        assert _metric(variant, "positive_replies")["available"] is False
        assert _metric(variant, "meetings")["available"] is False


def test_a_recorded_meeting_event_makes_meetings_available():
    state = _two_variant_state()
    leads = {"A-0001": lead("A-0001"), "A-0002": lead("A-0002")}
    events = [ev("A-0001", sequence.SENT, "INITIAL", "DRAFT"),
              ev("A-0001", experiments.MEETING, "INITIAL")]
    report = experiments.report(state, leads, events, [], [])
    short = report["variants"][0]
    meetings = _metric(short, "meetings")
    assert meetings["available"] is True and meetings["count"] == 1


def test_no_winner_is_declared_and_small_samples_are_flagged():
    state = _two_variant_state()
    leads = {"A-0001": lead("A-0001"), "A-0002": lead("A-0002")}
    report = experiments.report(state, leads, [], [], [])
    assert report["comparison"]["winner"] is None
    assert report["comparison"]["can_compare"] is False
    assert "Too few" in report["comparison"]["note"]


def test_unreadable_calls_and_suppression_are_flagged_not_guessed():
    state = _two_variant_state()
    leads = {"A-0001": lead("A-0001"), "A-0002": lead("A-0002")}
    report = experiments.report(state, leads, [ev("A-0001", sequence.SENT, "INITIAL", "DRAFT")],
                                None, None)
    assert report["calls_unreadable"] is True and report["suppression_unreadable"] is True
    assert report["variants"][0]["suppressed"] is None  # not guessed when the list is unreadable
    assert _metric(report["variants"][0], "calls")["count"] == 0


def test_suppressed_but_assigned_is_counted_as_context():
    state = _two_variant_state()
    leads = {"A-0001": lead("A-0001"), "A-0002": lead("A-0002")}
    entries = [{"Address or domain": "sam@example-electric.test", "Reason": "opted out"}]
    report = experiments.report(state, leads, [], [], entries)
    # A-0001's address is suppressed; it is still assigned, and the suppressed count says so.
    assert report["variants"][0]["suppressed"] == 1
