"""The company-settings chat routes through the real Flask app. interpret is read-only; apply
writes one field only on confirm, re-validated server-side, under the same flag as the lead chat
(enable_lead_chat) since both are "the assistant may propose a write, you confirm" surfaces."""

import pytest

from outreach import company_settings, console, console_auth
from stage4_fakes import MemoryStore
from test_console_auth import ALLOWED, AUDIENCE, Keys, token
from test_handbook_store import FakeApi

HEADER = console_auth.HEADER


@pytest.fixture
def built(tmp_path):
    (tmp_path / "assets").mkdir()
    (tmp_path / "index.html").write_text("<!doctype html><div id=root></div>", encoding="utf-8")
    return tmp_path


def signed():
    return {HEADER: token()}


def _store(api=None):
    store = MemoryStore([])
    if api is not None:
        store.api = api
    return store


def make(built, *, enable=True, settings=None, api=None):
    return console.create_app(
        verifier=console_auth.Verifier(AUDIENCE, ALLOWED, fetch=Keys()), store=lambda: _store(api),
        settings=lambda: (settings or {}), static_dir=built, enable_lead_chat=enable).test_client()


def test_routes_absent_when_the_flag_is_off(built):
    client = make(built, enable=False)
    assert client.post("/api/company/interpret", json={"note": "name: John Doe"},
                       headers=signed()).status_code in (404, 405)


def test_interpret_proposes_the_next_missing_field_for_a_bare_answer(built):
    client = make(built)
    r = client.post("/api/company/interpret", json={"note": "John Doe"}, headers=signed())
    body = r.get_json()
    assert r.status_code == 200
    assert body == {"status": "ready", "field": "sender_name", "label": body["label"], "value": "John Doe"}


def test_interpret_proposes_an_explicitly_named_field(built):
    client = make(built, settings={"sender_name": "John Doe"})  # not next-missing anymore
    r = client.post("/api/company/interpret", json={"note": "email: admin@lakshyaa.ai"}, headers=signed())
    body = r.get_json()
    assert body["status"] == "ready" and body["field"] == "sender_email" and body["value"] == "admin@lakshyaa.ai"


def test_interpret_reads_what_was_already_saved_through_the_live_sheets_client(built):
    api = FakeApi()
    company_settings.set_field("sender_name", "John Doe", set_by="a@x", api=api)
    client = make(built, api=api)
    r = client.post("/api/company/interpret", json={"note": "Owner"}, headers=signed())
    assert r.get_json()["field"] == "founder_title"  # sender_name is already set; this is next


def test_apply_saves_the_field_and_it_is_readable_back(built):
    api = FakeApi()
    client = make(built, api=api)
    r = client.post("/api/company/apply", json={"field": "sender_name", "value": "  John   Doe  "},
                    headers=signed())
    assert r.status_code == 200 and r.get_json()["ok"] is True
    assert r.get_json()["value"] == "John Doe"  # whitespace collapsed, same as validate()
    assert company_settings.overrides(api=api) == {"sender_name": "John Doe"}


def test_apply_names_the_signed_in_caller_as_who_set_it(built):
    api = FakeApi()
    make(built, api=api).post("/api/company/apply", json={"field": "sender_name", "value": "John Doe"},
                              headers=signed())
    row = api.tabs[company_settings.TAB][-1]
    set_by = dict(zip(company_settings.HEADER, row))["Set by"]
    assert set_by and "@" in set_by  # the IAP identity, never a client-supplied value


def test_apply_reports_the_next_missing_field_after_saving(built):
    api = FakeApi()
    client = make(built, api=api)
    r = client.post("/api/company/apply", json={"field": "sender_name", "value": "John Doe"}, headers=signed())
    assert r.get_json()["next_field"] == "founder_title"


def test_apply_reports_no_next_field_once_everything_required_is_set(built):
    api = FakeApi()
    full = {"sender_name": "John Doe", "founder_title": "Owner", "sender_email": "a@x.test",
            "sender_website": "https://x.test", "product_name": "Lakshyaa", "daily_cap": "4"}
    for field, value in full.items():
        company_settings.set_field(field, value, set_by="a@x", api=api)
    client = make(built, api=api)
    r = client.post("/api/company/apply",
                    json={"field": "postal_address", "value": "123 Main St, Columbus OH"}, headers=signed())
    assert r.get_json()["next_field"] is None


def test_apply_refuses_an_invalid_value_before_touching_the_sheet(built):
    # Real company_settings.set_field validates before any Sheet call, so a store with no .api at
    # all (MemoryStore's default) never needs one here.
    client = make(built)
    r = client.post("/api/company/apply", json={"field": "sender_email", "value": "not an email"},
                    headers=signed())
    assert r.status_code == 422


def test_apply_refuses_an_unknown_field(built):
    client = make(built)
    r = client.post("/api/company/apply", json={"field": "favourite_colour", "value": "blue"},
                    headers=signed())
    assert r.status_code == 422


def test_snapshot_carries_the_next_missing_company_field(built):
    client = make(built)
    r = client.get("/api/snapshot", headers=signed())
    assert r.get_json()["company_next_field"] == "sender_name"


def test_snapshot_has_no_next_field_once_everything_required_is_set(built):
    api = FakeApi()
    full = {"sender_name": "John Doe", "founder_title": "Owner", "sender_email": "a@x.test",
            "sender_website": "https://x.test", "postal_address": "123 Main St, Columbus OH",
            "product_name": "Lakshyaa", "daily_cap": "4"}
    for field, value in full.items():
        company_settings.set_field(field, value, set_by="a@x", api=api)
    r = make(built, api=api).get("/api/snapshot", headers=signed())
    assert r.get_json()["company_next_field"] is None


def test_snapshot_omits_company_next_field_when_the_flag_is_off(built):
    r = make(built, enable=False).get("/api/snapshot", headers=signed())
    assert "company_next_field" not in r.get_json()


def test_apply_needs_a_signed_in_caller(built):
    client = make(built)
    assert client.post("/api/company/apply", json={"field": "sender_name", "value": "John Doe"}).status_code in (401, 403, 503)
