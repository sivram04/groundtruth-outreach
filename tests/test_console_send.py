"""The Approve-and-send route through the real Flask app. Sending is OFF unless switched on; the
route sends only on the signed-in identity's approval, refuses a guard block as 409, and is absent
when the flag is off. The send itself (at-most-once, flag gate, etc.) is covered by test_send.py."""

import pytest

import console_fixture as fx  # noqa: F401  (makes the app's static/build fixture path importable)
from outreach import console, console_auth
from outreach import send as send_mod
from stage4_fakes import MemoryStore
from test_console_auth import ALLOWED, AUDIENCE, Keys, token

HEADER = console_auth.HEADER
COLUMNS = ["Lead ID", "Company", "BEST EMAIL"]


@pytest.fixture
def built(tmp_path):
    (tmp_path / "assets").mkdir()
    (tmp_path / "index.html").write_text("<!doctype html><div id=root></div>", encoding="utf-8")
    return tmp_path


def signed():
    return {HEADER: token()}


def a_store():
    store = MemoryStore([{"Lead ID": "A-0001", "Company": "Example Electric",
                          "BEST EMAIL": "sam@example.test"}], lead_columns=COLUMNS)
    store.api = object()  # the route passes st.api to the send path; the stub ignores it
    return store


def make(built, store, *, enable=True, gmail=None):
    return console.create_app(
        verifier=console_auth.Verifier(AUDIENCE, ALLOWED, fetch=Keys()), store=lambda: store,
        settings=lambda: {}, static_dir=built, enable_send=enable,
        gmail_client=lambda: (gmail or object())).test_client()


def test_the_send_route_is_absent_when_the_flag_is_off(built):
    client = make(built, a_store(), enable=False)
    assert client.post("/api/send/A-0001", headers=signed()).status_code in (404, 405)


def test_it_sends_on_the_signed_in_identitys_approval(built, monkeypatch):
    seen = {}

    def fake_send(lead_id, *, sent_by, api, gmail):
        seen["lead_id"], seen["sent_by"], seen["api"] = lead_id, sent_by, api
        return {"lead_id": lead_id, "sent": True, "message_id": "m-1", "thread_id": "t-1",
                "recorded": True, "sent_by": sent_by}

    monkeypatch.setattr(send_mod, "send_created_draft", fake_send)
    store = a_store()
    client = make(built, store)
    r = client.post("/api/send/A-0001", headers=signed())
    assert r.status_code == 200 and r.get_json()["sent"] is True and r.get_json()["message_id"] == "m-1"
    assert seen["lead_id"] == "A-0001"
    assert seen["sent_by"] and "@" in seen["sent_by"]  # the IAP identity, never a client value
    assert seen["api"] is store.api  # writes through the store's own Sheets client


def test_an_unknown_lead_is_404(built):
    client = make(built, a_store())
    assert client.post("/api/send/Z-9999", headers=signed()).status_code == 404


def test_a_guard_block_is_409_not_500(built, monkeypatch):
    def blocked(lead_id, *, sent_by, api, gmail):
        raise send_mod.SendBlocked("no created draft to send for this lead")

    monkeypatch.setattr(send_mod, "send_created_draft", blocked)
    client = make(built, a_store())
    assert client.post("/api/send/A-0001", headers=signed()).status_code == 409


def test_it_needs_a_signed_in_caller(built):
    client = make(built, a_store())
    assert client.post("/api/send/A-0001").status_code in (401, 403, 503)
