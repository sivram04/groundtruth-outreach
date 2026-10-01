"""The post-call email candidate: wording per outcome, grounded only in saved facts, never inventing a
conversation or the recipient's words, and never offered for a stop or a wrong number."""

from datetime import datetime, timezone

import pytest

from outreach import calls, drafting, post_call

UTC = timezone.utc
MON = datetime(2026, 9, 28, 13, 0, tzinfo=UTC)
HANDBOOK = {"content_hash": "hash-one", "name": "Handbook"}
QUOTE = "We install electrical distribution systems for commercial buildings."


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


def _call(outcome, note="", callback_at=None):
    event = calls.outcome_event("A-0001", outcome, note, MON.isoformat(),
                                no_answer_business_days=3, callback_at=callback_at, now=MON)
    return post_call.latest_call([event])


def test_no_answer_never_claims_a_conversation():
    cand = post_call.candidate(lead(), _call(calls.NO_ANSWER, note="rang out"), settings(), handbook=HANDBOOK, now=MON)
    body = cand["body"].lower()
    assert "tried to reach you" in body
    for claim in ("we spoke", "it was good to talk", "thanks for speaking", "as we discussed", "you said"):
        assert claim not in body
    assert cand["body"].endswith(drafting.OPT_OUT)  # the opt-out footer is always present
    assert cand["subject"] == "Tried to reach you — Lakshyaa"
    assert "rang out" not in cand["body"]  # the internal note is context, not pasted into the email


def test_interested_thanks_for_the_call_without_inventing_words():
    cand = post_call.candidate(lead(), _call(calls.INTERESTED), settings(), handbook=HANDBOOK, now=MON)
    assert "interest in Lakshyaa" in cand["body"]
    assert "you said" not in cand["body"].lower() and "you told me" not in cand["body"].lower()
    assert cand["body"].endswith(drafting.OPT_OUT)


def test_callback_uses_only_the_recorded_time():
    cand = post_call.candidate(lead(), _call(calls.CALLBACK, callback_at="2026-10-02T18:00:00+00:00"),
                               settings(), handbook=HANDBOOK, now=MON)
    assert cand["callback_text"]  # a formatted time from the recorded callback
    assert "2026-10-02" in cand["body"]  # the recorded day appears
    assert cand["body"].endswith(drafting.OPT_OUT)


def test_the_company_evidence_is_the_companys_own_verbatim_words():
    cand = post_call.candidate(lead(), _call(calls.NO_ANSWER), settings(), handbook=HANDBOOK, now=MON)
    assert cand["evidence"] == {"quote": QUOTE, "url": "https://example.test/services"}
    assert QUOTE in cand["body"]  # quoted verbatim, nothing invented
    # with no evidence on the lead, no company line is forced and the candidate is still built
    bare = post_call.candidate(lead(**{"Offerings evidence": ""}), _call(calls.NO_ANSWER), settings(),
                               handbook=HANDBOOK, now=MON)
    assert bare["evidence"] is None and QUOTE not in bare["body"]


@pytest.mark.parametrize("outcome", [calls.DO_NOT_CONTACT, calls.NOT_INTERESTED, calls.WRONG_NUMBER])
def test_a_stop_or_wrong_number_gets_no_candidate(outcome):
    assert not post_call.eligible_outcome(outcome)
    with pytest.raises(post_call.NotEligible):
        post_call.candidate(lead(), _call(outcome), settings(), handbook=HANDBOOK, now=MON)


def test_a_lead_with_no_email_gets_no_candidate():
    with pytest.raises(post_call.NotEligible) as exc:
        post_call.candidate(lead(**{"BEST EMAIL": ""}), _call(calls.NO_ANSWER), settings(), handbook=HANDBOOK, now=MON)
    assert exc.value.reason == "no_email"


def test_no_candidate_without_a_handbook():
    with pytest.raises(post_call.NotEligible) as exc:
        post_call.candidate(lead(), _call(calls.NO_ANSWER), settings(), handbook=None, now=MON)
    assert exc.value.reason == "handbook_unavailable"


def test_no_candidate_when_the_offer_is_not_configured():
    with pytest.raises(post_call.NotEligible) as exc:
        post_call.candidate(lead(), _call(calls.NO_ANSWER), settings(product_name=""), handbook=HANDBOOK, now=MON)
    assert exc.value.reason == "offer_not_configured"


def test_a_sticky_do_not_contact_blocks_a_candidate_even_after_a_later_no_answer():
    # The EFFECTIVE decision is STOP (sticky do-not-contact), so even a later eligible NO_ANSWER gets none.
    dnc = calls.outcome_event("A-0001", calls.DO_NOT_CONTACT, "", MON.isoformat(),
                              no_answer_business_days=3, now=MON)
    later = calls.outcome_event("A-0001", calls.NO_ANSWER, "", MON.isoformat(),
                                no_answer_business_days=3, now=datetime(2026, 9, 29, 13, 0, tzinfo=UTC))
    effect = calls.outreach_effect([dnc, later])
    assert effect == calls.STOP
    latest = post_call.latest_call([dnc, later])
    with pytest.raises(post_call.NotEligible) as exc:
        post_call.candidate(lead(), latest, settings(), handbook=HANDBOOK, now=MON, effect=effect)
    assert exc.value.reason == "call_stop"


def test_no_candidate_until_the_offer_is_approved():
    with pytest.raises(post_call.NotEligible) as exc:
        post_call.candidate(lead(), _call(calls.INTERESTED), settings(offer_approved=False),
                            handbook=HANDBOOK, now=MON)
    assert exc.value.reason == "offer_not_approved"


def _older_now():
    return datetime(2026, 10, 6, 13, 0, tzinfo=UTC)  # well after the MON (2026-09-28) call


def test_today_is_claimed_only_when_the_call_is_today():
    # Same New York day as the call -> "today"; a later day -> no timing claim, for every outcome.
    na_today = post_call.candidate(lead(), _call(calls.NO_ANSWER), settings(), handbook=HANDBOOK, now=MON)
    assert "today" in na_today["body"].lower()
    na_old = post_call.candidate(lead(), _call(calls.NO_ANSWER), settings(), handbook=HANDBOOK, now=_older_now())
    assert "today" not in na_old["body"].lower() and "tried to reach you by phone but" in na_old["body"].lower()

    int_old = post_call.candidate(lead(), _call(calls.INTERESTED), settings(), handbook=HANDBOOK, now=_older_now())
    assert "today" not in int_old["body"].lower() and "interest in Lakshyaa" in int_old["body"]

    cb_old = post_call.candidate(lead(), _call(calls.CALLBACK, callback_at="2026-10-09T18:00:00+00:00"),
                                 settings(), handbook=HANDBOOK, now=_older_now())
    assert "today" not in cb_old["body"].lower() and "Thanks for the call." in cb_old["body"]


def test_latest_call_takes_the_most_recent_outcome():
    first = calls.outcome_event("A-0001", calls.NO_ANSWER, "", MON.isoformat(),
                                no_answer_business_days=3, now=MON)
    later = calls.outcome_event("A-0001", calls.INTERESTED, "keen", MON.isoformat(),
                                no_answer_business_days=3,
                                now=datetime(2026, 9, 28, 14, 0, tzinfo=UTC))
    latest = post_call.latest_call([first, later])
    assert latest["outcome"] == calls.INTERESTED and latest["note"] == "keen"
    assert latest["callback_at"] == ""  # a callback time is recorded only for a CALLBACK
    assert post_call.latest_call([]) is None
