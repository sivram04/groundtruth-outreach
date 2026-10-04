"""The reply-draft candidate route through the real Flask app with a synthetic Store (#6). Reply drafting
is OFF unless switched on; the route only reads, and fails closed when a safety source is unreadable."""

import pytest

import console_fixture as fx  # noqa: F401  (ensures the app's static/build fixture path is importable)
from outreach import calls, console, console_auth, job_draft, sequence
from stage4_fakes import MemoryStore, at
from test_console_auth import ALLOWED, AUDIENCE, Keys, token

HEADER = console_auth.HEADER
COLUMNS = ["Lead ID", "Company", "Decision maker", "BEST EMAIL", "Website", "Phone", "Offerings evidence"]
MON = at("2026-09-28 09:00")
HANDBOOK = {"content_hash": "h1", "name": "Handbook"}
OFFER = {"product_name": "Lakshyaa", "sender_name": "A Founder", "founder_title": "Founder",
         "sender_website": "https://example.test", "postal_address": "1 Example St, Columbus OH",
         "sender_phone": "614-555-0100", "cta_question": "Would next week work?", "offer_approved": True}
QUOTE = "We install electrical distribution systems for commercial buildings."


@pytest.fixture
def built(tmp_path):
    (tmp_path / "assets").mkdir()
    (tmp_path / "index.html").write_text("<!doctype html><div id=root></div>", encoding="utf-8")
    return tmp_path


def signed():
    return {HEADER: token()}


def an_event(kind, at_iso, lead="A-0002", thread="T1", mid="m1"):
    return {"Lead ID": lead, "Event": kind, "Step": "", sequence.OCCURRED: at_iso,
            "Address": "dana@bluebird.test", "Match": "THREAD", "Detail": "", "Thread ID": thread,
            "Gmail message ID": mid, "Event key": f"msg:{mid}:{lead}:{kind}"}


def a_store(events=(), suppression=()):
    return MemoryStore([
        {"Lead ID": "A-0001", "Company": "Redwood Plumbing", "BEST EMAIL": "", "Phone": "614-555-0142"},
        {"Lead ID": "A-0002", "Company": "Bluebird Electric", "BEST EMAIL": "dana@bluebird.test",
         "Phone": "614-555-0100", "Offerings evidence": f'"{QUOTE}" (https://bluebird.test/services)'},
    ], events=list(events), suppression=list(suppression), lead_columns=COLUMNS)


def make(built, store, monkeypatch, *, settings=OFFER, handbook=HANDBOOK, enable=True):
    monkeypatch.setattr(job_draft, "_handbook",
                        lambda s, handbook_arg=None, drive=None: (handbook, None if handbook else "no handbook"))
    return console.create_app(
        verifier=console_auth.Verifier(AUDIENCE, ALLOWED, fetch=Keys()), store=lambda: store,
        settings=lambda: settings, clock=lambda: MON, static_dir=built,
        enable_reply=enable).test_client()


def cand(client, lead="A-0002"):
    return client.get(f"/api/reply/{lead}/candidate", headers=signed())


REPLIED = [lambda: an_event(sequence.REPLIED, "2026-09-27T10:00:00Z", mid="r1")]


def test_the_route_is_absent_until_enabled(built, monkeypatch):
    store = a_store(events=[an_event(sequence.REPLIED, "2026-09-27T10:00:00Z")])
    client = make(built, store, monkeypatch, enable=False)
    assert cand(client).status_code == 404  # no such route when the flag is off


def test_a_reply_candidate_is_offered_after_a_reply(built, monkeypatch):
    store = a_store(events=[an_event(sequence.REPLIED, "2026-09-27T10:00:00Z", mid="r1")])
    client = make(built, store, monkeypatch)
    data = cand(client).get_json()
    c = data["candidate"]
    assert c["to"] == "dana@bluebird.test" and c["thread_id"] == "T1" and c["in_reply_to"] == "r1"
    assert "thank you for getting back to me" in c["body"].lower()
    assert "you said" not in c["body"].lower() and "you asked" not in c["body"].lower()
    assert c["handbook_hash"] == "h1"


def test_a_booking_link_setting_is_used(built, monkeypatch):
    store = a_store(events=[an_event(sequence.REPLIED, "2026-09-27T10:00:00Z")])
    url = "https://cal.example/founder/intro"
    client = make(built, store, monkeypatch, settings={**OFFER, "booking_link": url})
    assert url in cand(client).get_json()["candidate"]["body"]


def test_no_reply_means_no_candidate(built, monkeypatch):
    store = a_store(events=[an_event(sequence.SENT, "2026-09-26T10:00:00Z")])
    client = make(built, store, monkeypatch)
    data = cand(client).get_json()
    assert data["candidate"] is None and data["reason"] == "no_reply"


def test_an_opt_out_after_the_reply_blocks_it(built, monkeypatch):
    store = a_store(events=[an_event(sequence.REPLIED, "2026-09-27T10:00:00Z"),
                            an_event(sequence.OPT_OUT, "2026-09-28T08:00:00Z")])
    client = make(built, store, monkeypatch)
    assert cand(client).get_json()["reason"] == "no_reply"


def test_a_recorded_stop_blocks_the_candidate(built, monkeypatch):
    store = a_store(events=[an_event(sequence.REPLIED, "2026-09-27T10:00:00Z")])
    client = make(built, store, monkeypatch)
    # record a do-not-contact call outcome (a STOP) through the pure module
    store.append_call_events([calls.outcome_event("A-0002", calls.DO_NOT_CONTACT, "", MON.isoformat(),
                                                  no_answer_business_days=3, now=MON)])
    assert cand(client).get_json()["reason"] == "call_stop"


def test_a_suppressed_lead_gets_no_candidate(built, monkeypatch):
    store = a_store(events=[an_event(sequence.REPLIED, "2026-09-27T10:00:00Z")],
                    suppression=[{"Address or domain": "dana@bluebird.test", "Reason": "opted out"}])
    client = make(built, store, monkeypatch)
    assert cand(client).get_json()["reason"] == "suppressed"


def test_handbook_unavailable_is_reported(built, monkeypatch):
    store = a_store(events=[an_event(sequence.REPLIED, "2026-09-27T10:00:00Z")])
    client = make(built, store, monkeypatch, handbook=None)
    data = cand(client).get_json()
    assert data["candidate"] is None and data["unavailable"] and data["reason"] == "handbook_unavailable"


def test_unknown_lead_is_404(built, monkeypatch):
    store = a_store(events=[an_event(sequence.REPLIED, "2026-09-27T10:00:00Z")])
    client = make(built, store, monkeypatch)
    assert cand(client, "Z-9999").status_code == 404
