"""The reply-draft candidate (#6): offered only after a genuine inbound reply, grounded only in saved
facts, never stating what the lead wrote, blocked by opt-out/bounce/stop/suppression, and carrying a
real booking link only when one is configured."""

import pytest

from outreach import calls, drafting, reply, sequence

HANDBOOK = {"content_hash": "hash-one", "name": "Handbook"}
QUOTE = "We install electrical distribution systems for commercial buildings."
BOOK_URL = "https://cal.example/founder/intro"


def lead(**changes):
    row = {"Lead ID": "A-0001", "Company": "Example Electric", "Decision maker": "Sam Rivers",
           "BEST EMAIL": "sam@example.test", "Their email": "sam@example.test",
           "Offerings evidence": f'"{QUOTE}" (https://example.test/services)'}
    row.update(changes)
    return row


def settings(**changes):
    config = {"product_name": "Lakshyaa", "sender_name": "A Founder", "founder_title": "Founder",
              "sender_website": "https://example.test", "postal_address": "1 Example St, Columbus OH",
              "sender_phone": "614-555-0100", "cta_question": "Would next week work?",
              "offer_approved": True}
    config.update(changes)
    return config


def _event(kind, at, thread="T1", mid="m1"):
    return {"Lead ID": "A-0001", "Event": kind, "Step": "", sequence.OCCURRED: at,
            "Address": "sam@example.test", "Match": "THREAD", "Detail": "", "Thread ID": thread,
            "Gmail message ID": mid, "Event key": f"msg:{mid}"}


def reply_inbound():
    return reply.latest_inbound([_event(sequence.SENT, "2026-09-28T10:00:00Z"),
                                 _event(sequence.REPLIED, "2026-09-29T09:00:00Z", mid="r1")])


# --- latest_inbound ---

def test_a_genuine_reply_is_the_latest_inbound():
    inbound = reply_inbound()
    assert inbound and inbound["message_id"] == "r1" and inbound["thread"] == "T1"


def test_an_opt_out_after_the_reply_cancels_the_candidate():
    assert reply.latest_inbound([_event(sequence.REPLIED, "2026-09-29T09:00:00Z"),
                                 _event(sequence.OPT_OUT, "2026-09-30T09:00:00Z")]) is None


def test_a_bounce_after_the_reply_cancels_the_candidate():
    assert reply.latest_inbound([_event(sequence.REPLIED, "2026-09-29T09:00:00Z"),
                                 _event(sequence.BOUNCED, "2026-09-30T09:00:00Z")]) is None


def test_an_auto_reply_alone_is_not_a_reply():
    assert reply.latest_inbound([_event(sequence.AUTO_REPLY, "2026-09-29T09:00:00Z")]) is None


def test_no_inbound_at_all_is_none():
    assert reply.latest_inbound([_event(sequence.SENT, "2026-09-28T10:00:00Z")]) is None


# --- candidate wording and grounding ---

def test_a_reply_candidate_is_grounded_and_never_states_what_they_said():
    cand = reply.candidate(lead(), reply_inbound(), settings(), handbook=HANDBOOK)
    body = cand["body"].lower()
    assert "thank you for getting back to me" in body
    assert QUOTE.lower() in body  # the company's own words, cited
    for invented in ("you said", "you mentioned", "you asked", "as you noted", "you wrote"):
        assert invented not in body
    assert cand["body"].endswith(drafting.OPT_OUT)
    assert cand["thread_id"] == "T1" and cand["in_reply_to"] == "r1"
    assert cand["handbook_hash"] == "hash-one"


def test_booking_link_is_used_when_configured():
    cand = reply.candidate(lead(), reply_inbound(), settings(booking_link=BOOK_URL), handbook=HANDBOOK)
    assert cand["booking_link"] == BOOK_URL
    assert BOOK_URL in cand["body"]
    assert "book a time" in cand["body"].lower()


def test_without_a_booking_link_the_cta_question_is_used():
    cand = reply.candidate(lead(), reply_inbound(), settings(), handbook=HANDBOOK)
    assert cand["booking_link"] == ""
    assert "Would next week work?" in cand["body"]


@pytest.mark.parametrize("bad", ["[your booking link]", "booking-link", "http://example.com/x",
                                 "cal.example/no-scheme", "", "   "])
def test_a_placeholder_or_schemeless_booking_link_is_refused(bad):
    assert reply.booking_link(settings(booking_link=bad)) == ""


# --- the blockers ---

def test_a_stop_blocks_even_after_a_reply():
    with pytest.raises(reply.NotEligible) as exc:
        reply.candidate(lead(), reply_inbound(), settings(), handbook=HANDBOOK, effect=calls.STOP)
    assert exc.value.reason == "call_stop"


def test_a_hold_does_not_block_a_reply():
    cand = reply.candidate(lead(), reply_inbound(), settings(), handbook=HANDBOOK, effect=calls.HOLD)
    assert cand["to"] == "sam@example.test"


def test_a_suppressed_lead_gets_no_candidate():
    with pytest.raises(reply.NotEligible) as exc:
        reply.candidate(lead(), reply_inbound(), settings(), handbook=HANDBOOK, suppressed=True)
    assert exc.value.reason == "suppressed"


def test_no_email_blocks():
    with pytest.raises(reply.NotEligible) as exc:
        reply.candidate(lead(**{"BEST EMAIL": ""}), reply_inbound(), settings(), handbook=HANDBOOK)
    assert exc.value.reason == "no_email"


def test_no_inbound_blocks():
    with pytest.raises(reply.NotEligible) as exc:
        reply.candidate(lead(), None, settings(), handbook=HANDBOOK)
    assert exc.value.reason == "no_reply"


def test_handbook_required():
    with pytest.raises(reply.NotEligible) as exc:
        reply.candidate(lead(), reply_inbound(), settings(), handbook=None)
    assert exc.value.reason == "handbook_unavailable"


def test_offer_must_be_approved_and_configured():
    with pytest.raises(reply.NotEligible) as exc:
        reply.candidate(lead(), reply_inbound(), settings(offer_approved=False), handbook=HANDBOOK)
    assert exc.value.reason == "offer_not_approved"
    with pytest.raises(reply.NotEligible) as exc:
        reply.candidate(lead(), reply_inbound(), settings(product_name=""), handbook=HANDBOOK)
    assert exc.value.reason == "offer_not_configured"
