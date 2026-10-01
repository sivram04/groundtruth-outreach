"""Interpreting a typed call note into a proposal: outcome detection, lead matching, ambiguity, the
callback-time rule (never inferred from prose), and the ready proposal. Read-only; writes nothing."""

from datetime import datetime, timezone

import pytest

from outreach import call_log_chat, calls

UTC = timezone.utc
MON = datetime(2026, 9, 28, 13, 0, tzinfo=UTC)  # Monday 09:00 ET

LEADS = {
    "A-0001": {"Lead ID": "A-0001", "Company": "Bluebird Electric", "Decision maker": "Dana Ray",
               "BEST EMAIL": "dana@bluebird.test", "Phone": "614-555-0100"},
    "A-0002": {"Lead ID": "A-0002", "Company": "Redwood Plumbing", "Decision maker": "Sam Ford",
               "BEST EMAIL": "", "Phone": "614-555-0142"},
    "A-0003": {"Lead ID": "A-0003", "Company": "Summit Mechanical", "Decision maker": "Alex Poe",
               "BEST EMAIL": "alex@summit.test", "Phone": ""},
}

# Two leads that share a distinctive token, to exercise the "choose" prompt.
AMBIG = {
    "A-0010": {"Lead ID": "A-0010", "Company": "Bluebird Electric", "Decision maker": "Dana Ray"},
    "A-0011": {"Lead ID": "A-0011", "Company": "Bluebird Plumbing", "Decision maker": "Alex Poe"},
}


@pytest.mark.parametrize("note,outcome", [
    ("Called Dana, no answer", calls.NO_ANSWER),
    ("left a voicemail for Dana", calls.NO_ANSWER),
    ("Dana is interested, wants a demo", calls.INTERESTED),
    ("wants a call back", calls.CALLBACK),
    ("not interested, said no", calls.NOT_INTERESTED),
    ("wrong number", calls.WRONG_NUMBER),
    ("asked to opt out, do not contact", calls.DO_NOT_CONTACT),
])
def test_detect_outcome(note, outcome):
    assert call_log_chat.detect_outcome(note) == outcome


def test_a_stop_wins_over_a_softer_reading():
    # "do not contact" must win even if "call back" appears too.
    assert call_log_chat.detect_outcome("do not contact, don't call back") == calls.DO_NOT_CONTACT


def test_an_unrecognised_note_has_no_outcome():
    assert call_log_chat.detect_outcome("spoke about the weather") is None
    assert call_log_chat.interpret("spoke about the weather", LEADS, now=MON)["status"] == "unclear_outcome"


def test_a_note_matching_one_lead_is_ready():
    p = call_log_chat.interpret("Called Dana at Bluebird Electric today, no answer", LEADS, now=MON)
    assert p["status"] == "ready" and p["lead"]["lead_id"] == "A-0001"
    assert p["outcome"] == calls.NO_ANSWER and p["effect"] == calls.CONTINUE
    assert p["due_text"] and p["note"].startswith("Called Dana")
    assert p["submission_id"].startswith("chat-")


def test_a_note_matching_several_leads_asks_to_choose():
    p = call_log_chat.interpret("called Bluebird, no answer", AMBIG, now=MON)
    assert p["status"] == "choose_lead"
    assert {l["lead_id"] for l in p["leads"]} == {"A-0010", "A-0011"}  # both Bluebird companies
    # choosing one resolves it
    chosen = call_log_chat.interpret("called Bluebird, no answer", AMBIG, now=MON, chosen_lead_id="A-0011")
    assert chosen["status"] == "ready" and chosen["lead"]["lead_id"] == "A-0011"


def test_no_matching_lead():
    assert call_log_chat.interpret("called Nobody Co, no answer", LEADS, now=MON)["status"] == "no_lead"


def test_a_callback_requires_an_explicit_time_never_inferred_from_prose():
    p = call_log_chat.interpret("Dana wants a call back next Tuesday afternoon", LEADS, now=MON)
    assert p["status"] == "need_time" and p["lead"]["lead_id"] == "A-0001"
    # with an explicit time supplied, it is ready and uses exactly that time
    ready = call_log_chat.interpret("Dana wants a call back", LEADS, now=MON,
                                    callback_at="2026-10-02T18:00:00+00:00")
    assert ready["status"] == "ready" and ready["outcome"] == calls.CALLBACK
    assert ready["callback_at"] == "2026-10-02T18:00:00+00:00" and ready["effect"] == calls.HOLD
    assert "2026-10-02" in ready["due_text"]


def test_a_phone_only_lead_can_be_logged():
    p = call_log_chat.interpret("called Redwood Plumbing, no answer", LEADS, now=MON)
    assert p["status"] == "ready" and p["lead"]["lead_id"] == "A-0002" and p["lead"]["email"] == ""


def test_do_not_contact_is_flagged_as_a_stop():
    p = call_log_chat.interpret("Dana at Bluebird Electric asked to opt out, do not contact", LEADS, now=MON)
    assert p["status"] == "ready" and p["outcome"] == calls.DO_NOT_CONTACT
    assert p["effect"] == calls.STOP and p["do_not_contact"] is True
