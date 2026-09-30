"""Signed, ordered review decisions: the console signs, the worker verifies, conflicts block.

These tests prove the CRYPTO and chain logic (authenticity, replay, forks, tampering, missing
verification material). They do NOT and cannot prove the deployed Drive permissions (the separate
review spreadsheet with console-exclusive write, worker read-only). That write-exclusivity is a
Google Workspace configuration verified with the admin, not by this suite; the stores here are fakes.
"""

import pytest

from outreach import review
from outreach.review_identity import CONFLICT, NO_REVIEW, OK, TAMPERED, Signer, Verifier, resolve_current
from test_review import HDR, Sheets  # the fake Sheets service

FP = "a" * 64
REVIEWERS = frozenset({"founder@lakshyaa.ai"})
WHO = "founder@lakshyaa.ai"


def signer_and_verifier():
    signer = Signer.generate()
    return signer, Verifier(signer.public_key_bytes())


def signed(signer, review_id, decision, *, prev="", fingerprint=FP, reviewer=WHO,
           at="2026-09-30T00:00:00+00:00"):
    sig = signer.sign(review_id=review_id, prev=prev, fingerprint=fingerprint, reviewer=reviewer,
                      decision=decision, reviewed_at=at)
    return {"lead_id": review_id, "prev": prev, "fingerprint": fingerprint, "reviewer": reviewer,
            "decision": decision, "reviewed_at": at, "signature": sig}


# --- 1. valid decisions ---------------------------------------------------------------------

def test_a_signed_confirmation_verifies_and_gates_approval():
    signer, verifier = signer_and_verifier()
    store = review.MemoryReviewStore()
    review.record_confirmation(store, "A-0001", WHO, FP, signer=signer)
    record, code = resolve_current(store.history("A-0001"), verifier)
    assert code == OK and record["decision"] == "confirmed"
    assert review.is_reviewed(store, "A-0001", FP, reviewers=REVIEWERS, verifier=verifier) is True


def test_a_later_signed_rejection_supersedes_an_earlier_confirmation():
    signer, verifier = signer_and_verifier()
    store = review.MemoryReviewStore()
    review.record_confirmation(store, "A-0001", WHO, FP, signer=signer)
    review.record_rejection(store, "A-0001", WHO, FP, signer=signer)  # chains onto the confirmation
    record, code = resolve_current(store.history("A-0001"), verifier)
    assert code == OK and record["decision"] == "rejected"
    assert review.is_reviewed(store, "A-0001", FP, reviewers=REVIEWERS, verifier=verifier) is False


# --- 2. forged or altered records -----------------------------------------------------------

@pytest.mark.parametrize("field,value", [
    ("decision", "confirmed"),  # a rejection flipped to a confirmation
    ("fingerprint", "b" * 64),  # bound to a different candidate
    ("reviewer", "someone.else@lakshyaa.ai"),
    ("prev", "tampered"),
])
def test_altering_a_signed_field_is_detected(field, value):
    signer, verifier = signer_and_verifier()
    record = signed(signer, "A-0001", "rejected" if field == "decision" else "confirmed")
    record[field] = value  # tamper after signing
    assert verifier.valid(record) is False
    assert resolve_current([record], verifier) == (None, TAMPERED)


def test_a_record_signed_by_another_key_is_rejected():
    signer, verifier = signer_and_verifier()
    other, _ = signer_and_verifier()
    record = signed(other, "A-0001", "confirmed")  # signed by the wrong key
    assert verifier.valid(record) is False
    assert resolve_current([record], verifier)[1] == TAMPERED


# --- 3. replay after rejection --------------------------------------------------------------

def test_replaying_an_old_confirmation_after_a_rejection_blocks():
    signer, verifier = signer_and_verifier()
    confirm = signed(signer, "A-0001", "confirmed", prev="")
    reject = signed(signer, "A-0001", "rejected", prev=confirm["signature"],
                    at="2026-09-30T01:00:00+00:00")
    # an attacker copies the genuinely-signed old confirmation back in
    replay = dict(confirm)
    record, code = resolve_current([confirm, reject, replay], verifier)
    assert record is None and code == TAMPERED  # duplicate signature is a replay


def test_a_reconfirmation_chained_after_a_rejection_is_allowed():
    signer, verifier = signer_and_verifier()
    confirm = signed(signer, "A-0001", "confirmed", prev="")
    reject = signed(signer, "A-0001", "rejected", prev=confirm["signature"],
                    at="2026-09-30T01:00:00+00:00")
    reconfirm = signed(signer, "A-0001", "confirmed", prev=reject["signature"],
                       at="2026-09-30T02:00:00+00:00")  # a genuine new decision, chained on
    record, code = resolve_current([confirm, reject, reconfirm], verifier)
    assert code == OK and record["decision"] == "confirmed"


# --- 4. conflicting concurrent decisions ----------------------------------------------------

def test_two_decisions_off_the_same_predecessor_block_as_a_conflict():
    signer, verifier = signer_and_verifier()
    # concurrent writes both see an empty history and both root at "" -> two roots -> conflict
    a = signed(signer, "A-0001", "confirmed", prev="", at="2026-09-30T00:00:00+00:00")
    b = signed(signer, "A-0001", "rejected", prev="", at="2026-09-30T00:00:01+00:00")
    assert resolve_current([a, b], verifier) == (None, CONFLICT)


def test_two_decisions_superseding_the_same_confirmation_block_as_a_conflict():
    signer, verifier = signer_and_verifier()
    root = signed(signer, "A-0001", "confirmed", prev="")
    x = signed(signer, "A-0001", "rejected", prev=root["signature"], at="2026-09-30T01:00:00+00:00")
    y = signed(signer, "A-0001", "confirmed", prev=root["signature"], at="2026-09-30T01:00:01+00:00")
    assert resolve_current([root, x, y], verifier) == (None, CONFLICT)


# --- 5. missing or invalid verification material --------------------------------------------

def test_no_records_is_missing():
    _, verifier = signer_and_verifier()
    assert resolve_current([], verifier) == (None, NO_REVIEW)


def test_an_unsigned_record_blocks():
    signer, verifier = signer_and_verifier()
    record = signed(signer, "A-0001", "confirmed")
    record["signature"] = ""  # no signature at all
    assert resolve_current([record], verifier)[1] == TAMPERED


def test_the_wrong_public_key_blocks_every_record():
    signer, _ = signer_and_verifier()
    wrong = Verifier(Signer.generate().public_key_bytes())  # a verifier with the wrong key
    record = signed(signer, "A-0001", "confirmed")
    assert wrong.valid(record) is False
    assert resolve_current([record], wrong)[1] == TAMPERED


def test_the_gate_blocks_a_conflict_with_a_clear_reason():
    signer, verifier = signer_and_verifier()
    store = review.MemoryReviewStore()
    store.put(signed(signer, "A-0001", "confirmed", prev="", at="2026-09-30T00:00:00+00:00"))
    store.put(signed(signer, "A-0001", "rejected", prev="", at="2026-09-30T00:00:01+00:00"))
    with pytest.raises(review.ReviewInvalid) as exc:
        review.enforce({"lead_id": "A-0001"}, None, {"review_reviewers": [WHO]},
                       store=store, verifier=verifier)
    assert exc.value.reason == review.review_identity.CONFLICT


# --- the signed write still goes through the store's uncertain-write handling ----------------

def test_a_signed_write_preserves_uncertain_write_handling():
    signer, _ = signer_and_verifier()
    api = Sheets({"Reviews": [HDR]}, drop_write=True)  # append "succeeds" but nothing persists
    store = review.SheetReviewStore(api=api, spreadsheet_id="sid")
    with pytest.raises(review.ReviewsUncertain):
        review.record_confirmation(store, "A-0001", WHO, FP, signer=signer)


def test_a_signed_decision_round_trips_through_the_sheet_store_and_verifies():
    signer, verifier = signer_and_verifier()
    api = Sheets({"Reviews": [HDR]})
    store = review.SheetReviewStore(api=api, spreadsheet_id="sid")
    review.record_confirmation(store, "A-0001", WHO, FP, signer=signer)
    review.record_rejection(store, "A-0001", WHO, FP, signer=signer)
    record, code = resolve_current(store.history("A-0001"), verifier)
    assert code == OK and record["decision"] == "rejected"  # the chain resolves after a round-trip
