"""Local, time-bounded, unforgeable tokens for the two steps of choosing a playbook: REVIEW and SELECT.

A token binds a `purpose` ("review" or "select"), the content hash, the signed-in founder's email, and an
expiry, signed with a per-process secret. Reviewing a file yields a REVIEW token (proof the server read and
parsed this founder's exact text). The founder's explicit Select action exchanges a valid review token for a
SELECT token at an authenticated server boundary. The preview requires a SELECT token, so a reviewed-but-
never-selected version is refused, and a caller cannot forge selection, reuse it for changed text, use
another founder's token, or use an expired one. The hash and email are recomputed at verify time from the
posted text and the session, never carried in the token.

The secret is generated per process at startup, so no token outlives a restart. This is a deliberately
non-durable, in-session choice, not a stored approval, and it grants nothing beyond a local, flag-gated
preview.
"""

import hashlib
import hmac
import time

TTL_SECONDS = 1800  # 30 minutes: the choice is time-bounded, not durable
REVIEW = "review"
SELECT = "select"


def _signature(secret, purpose, content_hash, email, exp):
    payload = f"{purpose}|{content_hash}|{email}|{exp}".encode("utf-8")
    return hmac.new(secret, payload, hashlib.sha256).hexdigest()


def mint(secret, purpose, content_hash, email, *, now=None, ttl=TTL_SECONDS):
    """A token binding the purpose, the hash, the founder and an expiry."""
    exp = int(now if now is not None else time.time()) + int(ttl)
    return f"{exp}.{_signature(secret, purpose, content_hash, email, exp)}"


def verify(secret, token, purpose, content_hash, email, *, now=None):
    """True only when `token` was minted by this process's secret for this exact purpose, content hash and
    founder, and has not expired. A different purpose (e.g. a review token where a select token is required),
    a forged token, changed text, another founder, or an expired token all fail."""
    try:
        exp_text, sig = str(token).split(".", 1)
        exp = int(exp_text)
    except (ValueError, AttributeError):
        return False
    if exp < int(now if now is not None else time.time()):
        return False
    return hmac.compare_digest(sig, _signature(secret, purpose, content_hash, email, exp))
