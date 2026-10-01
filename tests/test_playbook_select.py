"""The local, time-bounded playbook selection token: it validates only for the exact reviewed hash and
founder it was minted for, and only until it expires; a forged, changed, cross-founder or stale token fails."""

from outreach import playbook_select as ps

SECRET = b"\x01" * 32
HASH = "a" * 64
EMAIL = "admin@lakshyaa.ai"


def test_a_fresh_token_verifies_for_its_hash_and_founder():
    token = ps.mint(SECRET, HASH, EMAIL, now=1000)
    assert ps.verify(SECRET, token, HASH, EMAIL, now=1000) is True
    assert ps.verify(SECRET, token, HASH, EMAIL, now=1000 + ps.TTL_SECONDS - 1) is True


def test_a_changed_hash_fails():
    token = ps.mint(SECRET, HASH, EMAIL, now=1000)
    assert ps.verify(SECRET, token, "b" * 64, EMAIL, now=1000) is False


def test_another_founder_fails():
    token = ps.mint(SECRET, HASH, EMAIL, now=1000)
    assert ps.verify(SECRET, token, HASH, "someone@else.test", now=1000) is False


def test_an_expired_token_fails():
    token = ps.mint(SECRET, HASH, EMAIL, now=1000, ttl=60)
    assert ps.verify(SECRET, token, HASH, EMAIL, now=1000 + 61) is False


def test_a_forged_or_other_secret_token_fails():
    token = ps.mint(SECRET, HASH, EMAIL, now=1000)
    assert ps.verify(b"\x02" * 32, token, HASH, EMAIL, now=1000) is False
    assert ps.verify(SECRET, "garbage", HASH, EMAIL, now=1000) is False
    assert ps.verify(SECRET, "9999999999.deadbeef", HASH, EMAIL, now=1000) is False
