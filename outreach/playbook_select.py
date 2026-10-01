"""A local, time-bounded, unforgeable selection token for a reviewed playbook.

When a playbook is reviewed, the server mints a token bound to the reviewed content hash, the signed-in
founder's email, and an expiry. The preview route requires that token, so a caller cannot obtain a
"selected playbook" preview by posting arbitrary text and its own matching hash: only a version this founder
actually reviewed - and whose text still hashes to the same value - can be previewed, and only until the
token expires.

The signing secret is generated per process at startup, so a token never outlives a restart. This is a
deliberately non-durable, in-session selection, not a stored approval, and it grants nothing beyond a local,
flag-gated preview.
"""

import hashlib
import hmac
import time

TTL_SECONDS = 1800  # 30 minutes: the selection is time-bounded, not durable


def _signature(secret, content_hash, email, exp):
    payload = f"{content_hash}|{email}|{exp}".encode("utf-8")
    return hmac.new(secret, payload, hashlib.sha256).hexdigest()


def mint(secret, content_hash, email, *, now=None, ttl=TTL_SECONDS):
    """A token binding the reviewed hash, the founder and an expiry. The hash and email are not carried in
    the token - they are recomputed at verify time from the posted text and the session - so the token can
    only validate the exact version it was minted for, for the founder it was minted for."""
    exp = int(now if now is not None else time.time()) + int(ttl)
    return f"{exp}.{_signature(secret, content_hash, email, exp)}"


def verify(secret, token, content_hash, email, *, now=None):
    """True only when `token` was minted by this process's secret for this content hash and founder, and has
    not expired. A forged token, a changed text (different hash), another founder, or an expired token all
    fail."""
    try:
        exp_text, sig = str(token).split(".", 1)
        exp = int(exp_text)
    except (ValueError, AttributeError):
        return False
    if exp < int(now if now is not None else time.time()):
        return False
    return hmac.compare_digest(sig, _signature(secret, content_hash, email, exp))
