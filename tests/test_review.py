"""The content-bound human evidence-review contract (outreach/review.py).

The fingerprint binds exactly what a review is a judgment about; enforce() blocks every way a
review can fail to permit approval; the stores never touch the live Sheet in these tests.
"""

import pytest

from outreach import review


def preview(**changes):
    base = {
        "lead_id": "A-0001",
        "to": "Sam@Example.Test",
        "subject": "A conversation about Example Product next week",
        "body": "Hi Sam,\n\nExample Electric installs distribution systems.\n\nBest,\nA Founder",
        "handbook_hash": "hash-one",
        "written": {
            "subject": "A conversation about Example Product next week",
            "sentences": [{"text": "Example Electric installs distribution systems.",
                           "kind": "COMPANY", "quote_id": "q1"}],
            "evidence": {"quote_id": "q1", "category": "OFFERING",
                         "quote": "We install distribution systems.", "url": "https://example.test/s"},
        },
    }
    base.update(changes)
    return base


def settings(**changes):
    base = {"version": "prelaunch-v1", "product_name": "Example Product",
            "intended_use": "an early preview", "next_week_action": "a short call",
            "cta_question": "Would next week work?", "sender_name": "A Founder",
            "founder_title": "Founder", "sender_website": "https://example.test",
            "postal_address": "1 Example St, Columbus, OH 43215",
            "review_reviewers": ["founder@lakshyaa.ai"]}
    base.update(changes)
    return base


def fingerprint(pv=None, st=None):
    return review.candidate_fingerprint(pv or preview(), None, st or settings())


# --- the fingerprint ------------------------------------------------------------------------

def test_the_fingerprint_ignores_the_send_day_the_sender_and_the_approval_hash():
    """A review is about the content and its evidence, not the calendar day or the send-readiness
    hash: those stay bound by the approval hash, separately."""
    noisy = preview(preview_date="2026-09-29", preview_hash="0" * 64, blockers=[],
                    handbook_hash="hash-one")
    assert fingerprint(noisy) == fingerprint(preview())


def test_the_fingerprint_lowercases_the_recipient():
    assert fingerprint(preview(to="sam@example.test")) == fingerprint(preview(to="SAM@EXAMPLE.TEST"))


@pytest.mark.parametrize("pv,st", [
    (preview(to="other@example.test"), settings()),
    (preview(subject="A different subject entirely"), settings()),
    (preview(body="Hi Sam,\n\nsomething else\n\nBest,"), settings()),
    (preview(handbook_hash="hash-two"), settings()),
    (preview(), settings(version="prelaunch-v2")),
    (preview(), settings(intended_use="a much longer paid pilot")),
    (preview(written={"sentences": [], "evidence": {"quote_id": "q1", "category": "OFFERING",
                                                    "quote": "A different quote.",
                                                    "url": "https://example.test/s"}}), settings()),
    (preview(written={"sentences": [], "evidence": {"quote_id": "q1", "category": "OFFERING",
                                                    "quote": "We install distribution systems.",
                                                    "url": "https://example.test/other"}}), settings()),
])
def test_changing_any_bound_input_changes_the_fingerprint(pv, st):
    assert fingerprint(pv, st) != fingerprint()


# --- enforce: every way a review fails to permit approval blocks -----------------------------

def confirmed_store(pv=None, reviewer="founder@lakshyaa.ai", fp=None):
    store = review.MemoryReviewStore()
    review.record_confirmation(store, (pv or preview())["lead_id"], reviewer,
                               fp or fingerprint(pv))
    return store


def test_a_valid_current_confirmed_human_review_permits_approval():
    store = confirmed_store()
    assert review.enforce(preview(), None, settings(), store=store) == fingerprint()


def test_no_review_blocks():
    with pytest.raises(review.ReviewInvalid) as exc:
        review.enforce(preview(), None, settings(), store=review.MemoryReviewStore())
    assert exc.value.reason == review.MISSING


def test_an_unreadable_store_blocks():
    class Broken:
        def get(self, lead_id):
            raise RuntimeError("down")
    with pytest.raises(review.ReviewInvalid) as exc:
        review.enforce(preview(), None, settings(), store=Broken())
    assert exc.value.reason == review.UNREADABLE


@pytest.mark.parametrize("record", [
    {"lead_id": "A-0001", "reviewer": "founder@lakshyaa.ai", "decision": "confirmed",
     "reviewed_at": "2026-09-29T00:00:00+00:00"},  # no fingerprint
    {"lead_id": "A-0001", "fingerprint": "x" * 64, "reviewer": "", "decision": "confirmed",
     "reviewed_at": "2026-09-29T00:00:00+00:00"},  # blank reviewer
    {"lead_id": "A-0001", "fingerprint": "x" * 64, "reviewer": "founder@lakshyaa.ai",
     "decision": "unsure", "reviewed_at": "2026-09-29T00:00:00+00:00"},  # bad decision
    {"lead_id": "A-0001", "fingerprint": "nothex", "reviewer": "founder@lakshyaa.ai",
     "decision": "confirmed", "reviewed_at": "2026-09-29T00:00:00+00:00"},  # bad fingerprint
    {"lead_id": "A-0001", "fingerprint": "x" * 64, "reviewer": "founder@lakshyaa.ai",
     "decision": "confirmed", "reviewed_at": "not-a-time"},  # bad timestamp
    "not even a dict",
])
def test_a_malformed_review_blocks(record):
    class Fixed:
        def get(self, lead_id):
            return record
    with pytest.raises(review.ReviewInvalid) as exc:
        review.enforce(preview(), None, settings(), store=Fixed())
    assert exc.value.reason == review.MALFORMED


def test_a_review_by_a_non_human_is_rejected_even_if_it_matches():
    store = confirmed_store(reviewer="model@service.internal")
    with pytest.raises(review.ReviewInvalid) as exc:
        review.enforce(preview(), None, settings(), store=store)
    assert exc.value.reason == review.NOT_HUMAN


def test_no_configured_reviewers_fails_closed():
    store = confirmed_store()
    with pytest.raises(review.ReviewInvalid) as exc:
        review.enforce(preview(), None, settings(review_reviewers=[]), store=store,
                       reviewers=frozenset())
    assert exc.value.reason == review.NOT_HUMAN


def test_a_stale_review_blocks():
    store = confirmed_store(fp="a" * 64)
    with pytest.raises(review.ReviewInvalid) as exc:
        review.enforce(preview(), None, settings(), store=store)
    assert exc.value.reason == review.STALE


def test_a_rejection_blocks():
    store = review.MemoryReviewStore()
    review.record_rejection(store, "A-0001", "founder@lakshyaa.ai", fingerprint())
    with pytest.raises(review.ReviewInvalid) as exc:
        review.enforce(preview(), None, settings(), store=store)
    assert exc.value.reason == review.REJECTED_REASON


# --- allowed_reviewers ----------------------------------------------------------------------

def test_allowed_reviewers_comes_from_settings_and_the_console_allow_list(monkeypatch):
    monkeypatch.setenv("CONSOLE_ALLOWED_EMAILS", "boss@lakshyaa.ai, Extra@Lakshyaa.AI")
    people = review.allowed_reviewers(settings(review_reviewers=["founder@lakshyaa.ai"]))
    assert people == frozenset({"founder@lakshyaa.ai", "boss@lakshyaa.ai", "extra@lakshyaa.ai"})


def test_allowed_reviewers_is_empty_when_nothing_is_configured(monkeypatch):
    monkeypatch.delenv("CONSOLE_ALLOWED_EMAILS", raising=False)
    assert review.allowed_reviewers({}) == frozenset()


# --- recording a review ---------------------------------------------------------------------

def test_a_review_needs_the_reviewer_identity_the_model_cannot_invent_one():
    store = review.MemoryReviewStore()
    with pytest.raises(ValueError):
        review.record_confirmation(store, "A-0001", "", fingerprint())


def test_a_review_needs_the_candidate_fingerprint():
    store = review.MemoryReviewStore()
    with pytest.raises(ValueError):
        review.record_confirmation(store, "A-0001", "founder@lakshyaa.ai", "not-a-fingerprint")


def test_a_recorded_review_carries_who_when_what_and_the_fingerprint():
    store = review.MemoryReviewStore()
    record = review.record_confirmation(store, "A-0001", "founder@lakshyaa.ai", fingerprint())
    assert record["reviewer"] == "founder@lakshyaa.ai" and record["decision"] == review.CONFIRMED
    assert record["fingerprint"] == fingerprint() and record["reviewed_at"]
    assert store.get("A-0001") == record


# --- stores ---------------------------------------------------------------------------------

def test_the_json_file_store_round_trips(tmp_path):
    store = review.JsonFileReviewStore(tmp_path / "reviews" / "reviews.json")
    assert store.get("A-0001") is None
    record = review.record_confirmation(store, "A-0001", "founder@lakshyaa.ai", fingerprint())
    assert review.JsonFileReviewStore(tmp_path / "reviews" / "reviews.json").get("A-0001") == record


def test_the_sheet_store_is_fail_closed_and_never_writes():
    store = review.SheetReviewStore()
    assert store.get("A-0001") is None
    with pytest.raises(review.NotMigrated):
        store.put({"lead_id": "A-0001", "fingerprint": "a" * 64, "reviewer": "x",
                   "decision": "confirmed", "reviewed_at": "2026-09-29T00:00:00+00:00"})


def test_the_default_store_is_the_fail_closed_sheet_store():
    assert isinstance(review.default_store(), review.SheetReviewStore)


# --- the review view ------------------------------------------------------------------------

def test_the_review_view_shows_the_candidate_its_evidence_and_a_human_judgment_note():
    view = review.review_view(preview(), None, settings())
    assert view["subject"] and view["body"] and view["to"] == "Sam@Example.Test"
    assert view["claims"][0]["kind"] == "COMPANY"
    assert view["evidence"]["quote"] == "We install distribution systems."
    assert view["fingerprint"] == fingerprint()
    assert "not automated proof" in view["note"]
    assert view["review"]["decision"] is None and view["review"]["current"] is False


def test_the_review_view_marks_a_matching_review_current():
    existing = {"fingerprint": fingerprint(), "decision": "confirmed",
                "reviewer": "founder@lakshyaa.ai", "reviewed_at": "2026-09-29T00:00:00+00:00"}
    view = review.review_view(preview(), None, settings(), existing=existing)
    assert view["review"]["current"] is True and view["review"]["decision"] == "confirmed"
    stale = review.review_view(preview(subject="changed"), None, settings(), existing=existing)
    assert stale["review"]["current"] is False
