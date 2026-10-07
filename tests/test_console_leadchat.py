"""The lead-management chat routes through the real Flask app with a synthetic Store. Interpret reads
only; apply writes only on confirm, re-validates server-side, and protects founder columns. Flag-gated."""

import pytest

import console_fixture as fx  # noqa: F401
from outreach import console, console_auth
from stage4_fakes import MemoryStore
from test_console_auth import ALLOWED, AUDIENCE, Keys, token

HEADER = console_auth.HEADER
COLUMNS = ["Company", "Decision maker", "BEST EMAIL", "Website", "Phone", "Lead ID",
           "Email check", "Fit", "Profile status", "Profiled at", "Offerings evidence"]


@pytest.fixture
def built(tmp_path):
    (tmp_path / "assets").mkdir()
    (tmp_path / "index.html").write_text("<!doctype html><div id=root></div>", encoding="utf-8")
    return tmp_path


def signed():
    return {HEADER: token()}


def a_store():
    return MemoryStore([{"Lead ID": "A-0001", "Company": "Existing Electric",
                         "BEST EMAIL": "old@existing.test"}], lead_columns=COLUMNS)


def make(built, store, *, enable=True):
    return console.create_app(
        verifier=console_auth.Verifier(AUDIENCE, ALLOWED, fetch=Keys()), store=lambda: store,
        settings=lambda: {}, static_dir=built, enable_lead_chat=enable).test_client()


def test_routes_absent_when_the_flag_is_off(built):
    client = make(built, a_store(), enable=False)
    assert client.post("/api/leads/interpret", json={"note": "add | Company: X | email: a@b.test"},
                       headers=signed()).status_code in (404, 405)


def test_interpret_proposes_an_add_without_writing(built):
    s = a_store()
    client = make(built, s)
    r = client.post("/api/leads/interpret",
                    json={"note": "add | Company: Acme Electric | email: sam@acme.test | website: https://acme.test"},
                    headers=signed())
    assert r.status_code == 200 and r.get_json()["status"] == "ready" and r.get_json()["op"] == "add"
    assert "A-0001" in s.leads() and len(s.leads()) == 1  # nothing written by interpret


def test_apply_adds_a_new_lead_on_confirm(built):
    s = a_store()
    client = make(built, s)
    r = client.post("/api/leads/apply",
                    json={"op": "add", "fields": {"Company": "Acme Electric", "BEST EMAIL": "sam@acme.test",
                                                  "Website": "https://acme.test"}},
                    headers=signed())
    assert r.status_code == 200 and r.get_json()["ok"] is True
    added = [lid for lid in s.leads() if lid != "A-0001"]
    assert len(added) == 1 and s.leads()[added[0]]["Company"] == "Acme Electric"


def test_apply_updates_a_system_column_on_an_existing_lead(built):
    s = a_store()
    client = make(built, s)
    r = client.post("/api/leads/apply",
                    json={"op": "update", "lead_id": "A-0001", "fields": {"Fit": "QUALIFIED"}},
                    headers=signed())
    assert r.status_code == 200 and r.get_json()["ok"] is True
    assert s.leads()["A-0001"]["Fit"] == "QUALIFIED"


def test_apply_refuses_to_change_a_founder_column(built):
    s = a_store()
    client = make(built, s)
    r = client.post("/api/leads/apply",
                    json={"op": "update", "lead_id": "A-0001", "fields": {"BEST EMAIL": "new@x.test"}},
                    headers=signed())
    assert r.status_code == 409
    assert s.leads()["A-0001"]["BEST EMAIL"] == "old@existing.test"  # unchanged


def test_apply_refuses_a_bad_email(built):
    s = a_store()
    client = make(built, s)
    r = client.post("/api/leads/apply",
                    json={"op": "add", "fields": {"Company": "Acme", "BEST EMAIL": "not-an-email"}},
                    headers=signed())
    assert r.status_code == 409 and len(s.leads()) == 1


def test_apply_needs_a_signed_in_caller(built):
    assert make(built, a_store()).post("/api/leads/apply", json={"op": "add", "fields": {}}).status_code in (401, 403, 503)
