"""Signed, ordered review decisions the worker can verify but not forge.

Two properties the review store on its own cannot give (see docs/REVIEW_IDENTITY_RECOMMENDATION.md):

  1. **Authenticity the worker can verify but not forge.** The console signs each decision with an
     Ed25519 PRIVATE key only it holds (`Signer`); the worker verifies with the PUBLIC key, supplied
     as trusted configuration (`Verifier`) and never read from the writable store, so a writer cannot
     substitute a key. The signature covers the review id, the predecessor link, the candidate
     fingerprint, the authenticated reviewer and the decision, so altering any of them invalidates it.

  2. **An enforceable order that blocks conflicts instead of guessing.** Each decision names the
     signature of the decision it supersedes (`prev`), forming a per-review hash chain. The current
     decision is the single tip of a single unbroken chain. Two decisions off the same predecessor
     (concurrent writes from any thread, process or instance), a replayed row, a reordering, a cycle
     or a detached branch all make the tip non-unique or the chain ill-formed, and are reported as a
     CONFLICT that BLOCKS approval - never an arbitrary confirmation. No sequence counter is
     allocated (there is no safe allocator on a bare Sheet); ordering is the chain itself.

This is the mechanism. Review activation stays disabled; nothing here provisions or generates a
production key, and the worker gate only uses a `Verifier` when one is explicitly configured.
"""

import base64
import json

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat, PrivateFormat, NoEncryption

# resolve_current outcome codes (map to the gate's block reasons).
OK = ""
NO_REVIEW = "REVIEW_MISSING"
TAMPERED = "REVIEW_TAMPERED"        # an unverifiable, forged, altered or duplicate record
CONFLICT = "REVIEW_CONFLICT"        # concurrent/forked/ambiguous decisions, or an ill-formed chain

FIRST = ""  # the `prev` of the first decision on a review id


def _canonical(review_id, prev, fingerprint, reviewer, decision, reviewed_at):
    return json.dumps(
        {"v": 1, "review_id": review_id, "prev": prev, "fingerprint": fingerprint,
         "reviewer": reviewer, "decision": decision, "reviewed_at": reviewed_at},
        sort_keys=True, ensure_ascii=False).encode("utf-8")


def _payload(record):
    return _canonical(record.get("lead_id", ""), record.get("prev", ""),
                      record.get("fingerprint", ""), record.get("reviewer", ""),
                      record.get("decision", ""), record.get("reviewed_at", ""))


class Signer:
    """The console's signing authority. Holds the Ed25519 private key; nothing without it can produce
    a signature the worker will accept."""

    def __init__(self, private_key):
        if isinstance(private_key, (bytes, bytearray)):
            private_key = Ed25519PrivateKey.from_private_bytes(bytes(private_key))
        self._key = private_key

    def sign(self, *, review_id, prev, fingerprint, reviewer, decision, reviewed_at):
        signature = self._key.sign(
            _canonical(review_id, prev, fingerprint, reviewer, decision, reviewed_at))
        return base64.b64encode(signature).decode("ascii")

    def public_key_bytes(self):
        return self._key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)

    def private_key_bytes(self):
        return self._key.private_bytes(Encoding.Raw, PrivateFormat.Raw, NoEncryption())

    @staticmethod
    def generate():
        """A fresh keypair. FOR TESTS ONLY - not production key generation or provisioning."""
        return Signer(Ed25519PrivateKey.generate())


class Verifier:
    """The worker's verification configuration: the Ed25519 PUBLIC key, supplied as trusted config
    (never read from the writable store). It can verify a decision but cannot produce one."""

    def __init__(self, public_key):
        if isinstance(public_key, (bytes, bytearray)):
            public_key = Ed25519PublicKey.from_public_bytes(bytes(public_key))
        self._key = public_key

    def valid(self, record):
        signature = record.get("signature") or ""
        try:
            self._key.verify(base64.b64decode(signature), _payload(record))
            return True
        except (InvalidSignature, ValueError, TypeError, Exception):
            return False


def resolve_current(records, verifier):
    """The single current decision for one review id, or a block reason.

    Returns (record, code): (tip, OK) when a unique, verified tip of a single unbroken chain exists;
    otherwise (None, code) - NO_REVIEW / TAMPERED / CONFLICT. Fail-closed: any doubt blocks.
    """
    if not records:
        return None, NO_REVIEW
    # Every record must verify against the trusted key. One unverifiable (forged/altered/unsigned)
    # record blocks the whole review - we do not silently drop it and trust the rest.
    for record in records:
        if not verifier.valid(record):
            return None, TAMPERED
    by_sig = {}
    for record in records:
        signature = record.get("signature", "")
        if not signature or signature in by_sig:  # signatures are unique per decision; a repeat is a replay
            return None, TAMPERED
        by_sig[signature] = record
    roots, children = [], {}
    for record in records:
        prev = record.get("prev", "")
        if prev == FIRST:
            roots.append(record)
        elif prev in by_sig:
            children.setdefault(prev, []).append(record)
        else:
            return None, TAMPERED  # references a predecessor that is not present
    if len(roots) != 1:
        return None, CONFLICT  # no root, or several roots (a replay/fork at the start)
    node, seen = roots[0], set()
    while True:
        if node["signature"] in seen:
            return None, CONFLICT  # a cycle
        seen.add(node["signature"])
        kids = children.get(node["signature"], [])
        if len(kids) > 1:
            return None, CONFLICT  # two decisions supersede the same one: concurrent conflict
        if not kids:
            break
        node = kids[0]
    if len(seen) != len(records):
        return None, CONFLICT  # a detached branch that does not hang off the single chain
    return node, OK


def tip_signature(records, verifier):
    """The signature to set as `prev` for the next decision: the current verified tip's signature,
    or FIRST when there is none or the chain is not currently resolvable (a new decision off an
    unresolvable chain still lands, and the worker keeps blocking until the conflict is settled)."""
    record, code = resolve_current(records, verifier)
    if record is not None:
        return record["signature"]
    # No single tip (empty, or already conflicted): chain onto the latest well-formed record we can
    # see, so a genuine new decision is still recorded; resolution stays blocked until it is fixed.
    signed = [r for r in records if verifier.valid(r) and r.get("signature")]
    return signed[-1]["signature"] if signed else FIRST
