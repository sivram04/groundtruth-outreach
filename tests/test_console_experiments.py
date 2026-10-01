"""The A/B routes through the real Flask app with a synthetic Store: define two variants, assign
eligible leads, and read the per-lead variant and the variant report back from the snapshot. Stable
across reload/retry; idempotent writes; suppression and unreadable data handled honestly. A/B is OFF
unless switched on."""

import pytest

from outreach import console, console_auth, experiments
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
