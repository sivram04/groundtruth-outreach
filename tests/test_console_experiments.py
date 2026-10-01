"""The A/B routes through the real Flask app with a synthetic Store: define two variants, assign
eligible leads, and read the per-lead variant and the variant report back from the snapshot. Stable
across reload/retry; idempotent writes; suppression and unreadable data handled honestly. A/B is OFF
unless switched on."""

import pytest

from outreach import calls, console, console_auth, experiments, sequence
from outreach.sync import _event
from stage4_fakes import MemoryStore, at, lead
from test_console_auth import ALLOWED, AUDIENCE, Keys, token

HEADER = console_auth.HEADER
COLUMNS = ["Lead ID", "Company", "Decision maker", "BEST EMAIL", "Their email", "Website", "Phone",
           "Email check", "Fit", "HOLD", "Sent by hand"]
MON = at("2026-09-28 09:00")


@pytest.fixture
def built(tmp_path):
    (tmp_path / "assets").mkdir()
    (tmp_path / "index.html").write_text("<!doctype html><div id=root></div>", encoding="utf-8")
    return tmp_path


def signed(**claims):
    return {HEADER: token(**claims)}


def a_store():
    # Three emailable, qualified leads (eligible) and two that are not (no email; disqualified).
    return MemoryStore([
        lead("A-0001"), lead("A-0002", **{"BEST EMAIL": "pat@acme.test", "Their email": "pat@acme.test"}),
        lead("A-0003", **{"BEST EMAIL": "robin@north.test", "Their email": "robin@north.test"}),
        lead("A-0004", **{"BEST EMAIL": "", "Their email": ""}),           # phone/company only
        lead("A-0005", **{"Fit": "DISQUALIFIED"}),                          # not qualified
    ], lead_columns=COLUMNS)


def make(built, store, *, enable=True, now=MON):
    return console.create_app(
        verifier=console_auth.Verifier(AUDIENCE, ALLOWED, fetch=Keys()), store=lambda: store,
        settings=lambda: {}, clock=lambda: now, static_dir=built,
        enable_experiments=enable).test_client()


def define(client, **body):
    return client.post("/api/experiments/define", json=body, headers=signed())


def assign(client, **body):
    return client.post("/api/experiments/assign", json=body, headers=signed())


def snapshot(client):
    return client.get("/api/snapshot", headers=signed()).get_json()


# -- the write routes are off unless switched on --------------------------------------------------

def test_the_routes_are_absent_unless_experiments_are_enabled(built):
    client = make(built, a_store(), enable=False)
    assert define(client, experiment="E", variant_a="A", variant_b="B").status_code == 404
    assert assign(client, experiment="E").status_code == 404
    assert snapshot(client)["experiments_enabled"] is False


# -- define ---------------------------------------------------------------------------------------

def test_define_saves_two_variants_and_is_idempotent(built):
    store = a_store()
    client = make(built, store)
    r = define(client, experiment="Subject test", variant_a="Short", variant_b="Long")
    assert r.status_code == 200 and r.get_json()["written"] == 2
    assert r.get_json()["variants"] == ["Short", "Long"]
    # The same definition again writes nothing new (idempotent by Record ID).
    assert define(client, experiment="Subject test", variant_a="Short",
                  variant_b="Long").get_json()["written"] == 0
    assert len(store.ab_records()) == 2


def test_define_refuses_two_equal_or_empty_names(built):
    client = make(built, a_store())
    assert define(client, experiment="E", variant_a="Same", variant_b="Same").status_code == 400
    assert define(client, experiment="E", variant_a="A", variant_b="").status_code == 400
    assert define(client, experiment="", variant_a="A", variant_b="B").status_code == 400


# -- assign ---------------------------------------------------------------------------------------

def test_assign_before_define_is_refused(built):
    client = make(built, a_store())
    assert assign(client, experiment="Subject test").status_code == 400


def test_assign_covers_eligible_leads_only_and_is_stable(built):
    store = a_store()
    client = make(built, store)
    define(client, experiment="Subject test", variant_a="Short", variant_b="Long")
    first = assign(client, experiment="Subject test").get_json()
    assert first["assigned"] == 3 and first["eligible"] == 3 and first["ineligible"] == 2

    # Record what each lead was assigned to, then assign again: nothing new, nothing moved.
    before = experiments.read(store.ab_records())["Subject test"]["assignments"]
    again = assign(client, experiment="Subject test").get_json()
    assert again["assigned"] == 0 and again["already_assigned"] == 3
    after = experiments.read(store.ab_records())["Subject test"]["assignments"]
    assert after == before  # a retry cannot move a lead between variants


def test_a_rename_then_reassign_keeps_each_lead_in_place(built):
    store = a_store()
    client = make(built, store)
    define(client, experiment="Subject test", variant_a="Short", variant_b="Long")
    assign(client, experiment="Subject test")
    indices = experiments.read(store.ab_records())["Subject test"]["assignments"]
    # Rename the variants and assign again; indices (the real identity) are unchanged.
    define(client, experiment="Subject test", variant_a="Concise", variant_b="Detailed")
    assign(client, experiment="Subject test")
    renamed = experiments.read(store.ab_records())["Subject test"]
    assert renamed["assignments"] == indices
    assert renamed["variants"] == ["Concise", "Detailed"]


# -- the snapshot shows assignments and the report ------------------------------------------------

def test_snapshot_shows_each_leads_variant_and_the_report(built):
    store = a_store()
    client = make(built, store)
    define(client, experiment="Subject test", variant_a="Short", variant_b="Long")
    assign(client, experiment="Subject test")
    data = snapshot(client)
    assert data["experiments_enabled"] is True
    report = data["experiments"]
    assert report["name"] == "Subject test" and report["defined"] is True
    assert sum(v["assigned"] for v in report["variants"]) == 3
    assert report["comparison"]["winner"] is None  # never a winner from these samples
    # Each assigned lead carries its variant; the two ineligible ones do not.
    by_id = {l["id"]: l for l in data["leads"]}
    assigned = [l for l in data["leads"] if l["variant"]]
    assert len(assigned) == 3 and by_id["A-0004"]["variant"] == "" and by_id["A-0005"]["variant"] == ""
    for item in assigned:
        assert item["variant"] in ("Short", "Long") and item["experiment"] == "Subject test"


def test_an_unreadable_ab_tab_is_flagged_not_guessed(built):
    class Refusing(MemoryStore):
        def ab_records(self):
            raise RuntimeError("the A/B tests tab's columns were changed")

    store = Refusing([lead("A-0001")], lead_columns=COLUMNS)
    data = snapshot(make(built, store))
    assert data["experiments_unreadable"] is True and data["experiments"] is None
    assert any("A/B tests tab cannot be read" in w for w in data["warnings"])


# -- outcomes are attributed only after assignment (through the real snapshot) ---------------------

def _sent_total(report):
    return sum(next(m for m in v["metrics"] if m["key"] == "sent")["count"] for v in report["variants"])


def _replies_total(report):
    return sum(next(m for m in v["metrics"] if m["key"] == "replies")["count"] for v in report["variants"])


def test_a_previously_emailed_leads_old_send_and_reply_are_not_counted(built):
    # The reviewer's case, end to end: a lead with a send + reply on 2026-09-30 is assigned on
    # 2026-10-01; neither old outcome is a result of the test, so the snapshot counts neither.
    store = MemoryStore(
        [lead("A-0001"),
         lead("A-0002", **{"BEST EMAIL": "pat@acme.test", "Their email": "pat@acme.test"}),
         lead("A-0003", **{"BEST EMAIL": "robin@north.test", "Their email": "robin@north.test"})],
        events=[_event("A-0001", sequence.SENT, "INITIAL", at("2026-09-30 10:00"),
                       "sam@example-electric.test", "ADDRESS", "t1", "m1", "hand"),
                _event("A-0001", sequence.REPLIED, "", at("2026-09-30 11:00"),
                       "sam@example-electric.test", "THREAD", "t1", "m1r", "")],
        lead_columns=COLUMNS)
    client = make(built, store, now=at("2026-10-01 09:00"))
    define(client, experiment="Subject test", variant_a="Short", variant_b="Long")
    assign(client, experiment="Subject test")
    data = snapshot(client)
    report = data["experiments"]
    assert _sent_total(report) == 0 and _replies_total(report) == 0
    assert report["excluded"]["before_assignment"] == 2
    # The previously-emailed lead is still assigned; only its old outcomes are excluded.
    by_id = {l["id"]: l for l in data["leads"]}
    assert by_id["A-0001"]["variant"] in ("Short", "Long")


def test_a_reply_to_a_pre_assignment_send_is_excluded_in_the_snapshot(built):
    # Initial email sent 2026-09-30 (before assignment on 2026-10-01), then a reply on the same thread
    # on 2026-10-02 (after assignment). The reply links only to a pre-assignment send, so the snapshot
    # counts neither the send nor the reply, and labels the report observed activity, not A/B results.
    store = MemoryStore(
        [lead("A-0001"),
         lead("A-0002", **{"BEST EMAIL": "pat@acme.test", "Their email": "pat@acme.test"}),
         lead("A-0003", **{"BEST EMAIL": "robin@north.test", "Their email": "robin@north.test"})],
        events=[_event("A-0001", sequence.SENT, "INITIAL", at("2026-09-30 10:00"),
                       "sam@example-electric.test", "ADDRESS", "t1", "m1", "hand"),
                _event("A-0001", sequence.REPLIED, "", at("2026-10-02 10:00"),
                       "sam@example-electric.test", "THREAD", "t1", "m1r", "")],
        lead_columns=COLUMNS)
    client = make(built, store, now=at("2026-10-01 09:00"))
    define(client, experiment="Subject test", variant_a="Short", variant_b="Long")
    assign(client, experiment="Subject test")
    report = snapshot(client)["experiments"]
    assert _sent_total(report) == 0 and _replies_total(report) == 0
    assert report["excluded"]["before_assignment"] == 1   # the pre-assignment send
    assert report["excluded"]["unattributable"] == 1      # the reply, linked only to that send
    assert report["basis"] == "observed_activity"
    assert report["comparison"]["comparable"] is False and report["comparison"]["winner"] is None


def test_a_tracked_open_is_counted_in_the_snapshot(built):
    # A post-assignment tracked draft + sent email, then a tracker open as tracking_job.hit_event writes
    # it (Match TRACKER, blank thread, the draft action in Detail). The open links by its draft action to
    # the qualifying send and is counted — not excluded by the thread rule.
    store = MemoryStore(
        [lead("A-0001"),
         lead("A-0002", **{"BEST EMAIL": "pat@acme.test", "Their email": "pat@acme.test"}),
         lead("A-0003", **{"BEST EMAIL": "robin@north.test", "Their email": "robin@north.test"})],
        events=[_event("A-0001", sequence.DRAFTED, "INITIAL", at("2026-09-28 09:30"),
                       "sam@example-electric.test", "DRAFT", "t1", "", "draft draft-1, tracked",
                       key="draft:act1"),
                _event("A-0001", sequence.SENT, "INITIAL", at("2026-09-28 10:00"),
                       "sam@example-electric.test", "DRAFT", "t1", "m1", ""),
                _event("A-0001", sequence.OPEN, "INITIAL", at("2026-09-28 11:00"),
                       "", "TRACKER", "", "", "draft act1", key="hit:open1")],
        lead_columns=COLUMNS)
    client = make(built, store, now=at("2026-09-28 09:00"))
    define(client, experiment="Subject test", variant_a="Short", variant_b="Long")
    assign(client, experiment="Subject test")
    report = snapshot(client)["experiments"]
    opens = sum(next(m for m in v["metrics"] if m["key"] == "opens")["count"] for v in report["variants"])
    assert _sent_total(report) == 1 and opens == 1
    assert report["excluded"]["unattributable"] == 0


def test_calls_are_unavailable_in_the_snapshot_when_the_call_log_cannot_be_read(built):
    class ToggleCalls(MemoryStore):
        fail_calls = False

        def call_events(self):
            if self.fail_calls:
                raise RuntimeError("the Call log tab's columns were changed")
            return super().call_events()

    store = ToggleCalls([lead("A-0001"), lead("A-0002", **{"BEST EMAIL": "pat@acme.test",
                                                           "Their email": "pat@acme.test"})],
                        lead_columns=COLUMNS)
    client = make(built, store)
    define(client, experiment="Subject test", variant_a="Short", variant_b="Long")
    assign(client, experiment="Subject test")  # needs the call log readable
    store.fail_calls = True                     # now it cannot be read
    report = snapshot(client)["experiments"]
    assert report["calls_unreadable"] is True
    for variant in report["variants"]:
        calls_metric = next(m for m in variant["metrics"] if m["key"] == "calls")
        assert calls_metric["available"] is False and "count" not in calls_metric


# -- assignment safety --------------------------------------------------------------------------

def test_a_suppressed_lead_is_not_assigned(built):
    store = MemoryStore(
        [lead("A-0001"),  # sam@example-electric.test, which is suppressed below
         lead("A-0002", **{"BEST EMAIL": "pat@acme.test", "Their email": "pat@acme.test"})],
        suppression=[{"Address or domain": "sam@example-electric.test", "Reason": "opted out",
                      "Added at": "", "Source": ""}],
        lead_columns=COLUMNS)
    client = make(built, store)
    define(client, experiment="Subject test", variant_a="Short", variant_b="Long")
    result = assign(client, experiment="Subject test").get_json()
    assert result["eligible"] == 1  # only A-0002 is safe to assign
    by_id = {l["id"]: l for l in snapshot(client)["leads"]}
    assert by_id["A-0001"]["variant"] == "" and by_id["A-0002"]["variant"] in ("Short", "Long")


def test_a_lead_in_a_call_stop_or_hold_state_is_not_assigned(built):
    store = MemoryStore(
        [lead("A-0001"),
         lead("A-0002", **{"BEST EMAIL": "pat@acme.test", "Their email": "pat@acme.test"}),
         lead("A-0003", **{"BEST EMAIL": "robin@north.test", "Their email": "robin@north.test"})],
        lead_columns=COLUMNS)
    now = at("2026-09-28 09:00")
    store.append_call_events([
        calls.outcome_event("A-0001", calls.DO_NOT_CONTACT, "", now.isoformat(),
                            no_answer_business_days=3, now=now),   # STOP
        calls.outcome_event("A-0002", calls.INTERESTED, "", now.isoformat(),
                            no_answer_business_days=3, now=now)])   # HOLD
    client = make(built, store, now=now)
    define(client, experiment="Subject test", variant_a="Short", variant_b="Long")
    result = assign(client, experiment="Subject test").get_json()
    assert result["eligible"] == 1  # only A-0003 is neither stopped nor held
    by_id = {l["id"]: l for l in snapshot(client)["leads"]}
    assert by_id["A-0001"]["variant"] == "" and by_id["A-0002"]["variant"] == ""
    assert by_id["A-0003"]["variant"] in ("Short", "Long")


def test_an_unreadable_safety_source_refuses_the_whole_assignment(built):
    # Suppression unreadable -> nobody is assigned (an unreadable safety source is not permission).
    store = MemoryStore([lead("A-0001")], suppression=None, lead_columns=COLUMNS)
    client = make(built, store)
    define(client, experiment="Subject test", variant_a="Short", variant_b="Long")
    assert assign(client, experiment="Subject test").status_code == 502
    assert experiments.read(store.ab_records()).get("Subject test", {}).get("assignments", {}) == {}

    # Call log unreadable -> likewise refused.
    class RefusingCalls(MemoryStore):
        def call_events(self):
            raise RuntimeError("the Call log tab's columns were changed")

    store2 = RefusingCalls([lead("A-0001")], lead_columns=COLUMNS)
    client2 = make(built, store2)
    define(client2, experiment="Subject test", variant_a="Short", variant_b="Long")
    assert assign(client2, experiment="Subject test").status_code == 502
    assert experiments.read(store2.ab_records()).get("Subject test", {}).get("assignments", {}) == {}
