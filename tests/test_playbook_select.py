"""The local, time-bounded playbook tokens for the two steps REVIEW and SELECT: a token validates only for
the exact purpose, reviewed hash and founder it was minted for, and only until it expires; a forged, changed,
cross-purpose, cross-founder or stale token fails."""

from outreach import playbook_select as ps

SECRET = b"\x01" * 32
HASH = "a" * 64
EMAIL = "admin@lakshyaa.ai"


def test_a_fresh_token_verifies_for_its_purpose_hash_and_founder():
    token = ps.mint(SECRET, ps.SELECT, HASH, EMAIL, now=1000)
    assert ps.verify(SECRET, token, ps.SELECT, HASH, EMAIL, now=1000) is True
    assert ps.verify(SECRET, token, ps.SELECT, HASH, EMAIL, now=1000 + ps.TTL_SECONDS - 1) is True


def test_a_review_token_is_not_a_select_token():
    # A review token proves review; it must not verify where a selection is required, and vice versa.
    review = ps.mint(SECRET, ps.REVIEW, HASH, EMAIL, now=1000)
    assert ps.verify(SECRET, review, ps.REVIEW, HASH, EMAIL, now=1000) is True
    assert ps.verify(SECRET, review, ps.SELECT, HASH, EMAIL, now=1000) is False
    select = ps.mint(SECRET, ps.SELECT, HASH, EMAIL, now=1000)
    assert ps.verify(SECRET, select, ps.REVIEW, HASH, EMAIL, now=1000) is False


def test_a_changed_hash_fails():
    token = ps.mint(SECRET, ps.SELECT, HASH, EMAIL, now=1000)
    assert ps.verify(SECRET, token, ps.SELECT, "b" * 64, EMAIL, now=1000) is False


def test_another_founder_fails():
    token = ps.mint(SECRET, ps.SELECT, HASH, EMAIL, now=1000)
    assert ps.verify(SECRET, token, ps.SELECT, HASH, "someone@else.test", now=1000) is False


def test_an_expired_token_fails():
    token = ps.mint(SECRET, ps.SELECT, HASH, EMAIL, now=1000, ttl=60)
    assert ps.verify(SECRET, token, ps.SELECT, HASH, EMAIL, now=1000 + 61) is False


def test_a_forged_or_other_secret_token_fails():
    token = ps.mint(SECRET, ps.SELECT, HASH, EMAIL, now=1000)
    assert ps.verify(b"\x02" * 32, token, ps.SELECT, HASH, EMAIL, now=1000) is False
    assert ps.verify(SECRET, "garbage", ps.SELECT, HASH, EMAIL, now=1000) is False
    assert ps.verify(SECRET, "9999999999.deadbeef", ps.SELECT, HASH, EMAIL, now=1000) is False
