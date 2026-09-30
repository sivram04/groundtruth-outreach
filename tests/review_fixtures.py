"""Ephemeral review-identity keys for tests, and helpers to write signed reviews.

One in-memory Ed25519 keypair per test run (never a production key). `PUBLIC_KEY_B64` goes into the
drafting settings so the application paths resolve a verifier; `SIGNER` signs reviews the way the
console would. Unsigned records are only used where a test explicitly wants the legacy path.
"""

import base64

from outreach import review
from outreach.review_identity import Signer, Verifier

SIGNER = Signer.generate()  # ephemeral: FOR TESTS ONLY
PUBLIC_KEY_B64 = base64.b64encode(SIGNER.public_key_bytes()).decode("ascii")
PRIVATE_KEY_B64 = base64.b64encode(SIGNER.private_key_bytes()).decode("ascii")


def verifier():
    return Verifier(SIGNER.public_key_bytes())


def confirm(store, review_id, reviewer, fingerprint, *, now=None):
    return review.record_confirmation(store, review_id, reviewer, fingerprint, now=now, signer=SIGNER)


def reject(store, review_id, reviewer, fingerprint, *, now=None):
    return review.record_rejection(store, review_id, reviewer, fingerprint, now=now, signer=SIGNER)
