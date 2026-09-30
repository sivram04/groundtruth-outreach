"""Content-bound human evidence review: the gate between a candidate draft and final approval.

Three things are kept separate (founder, 2026-09-29, acceptance-contract option B):

  1. draft identity / candidate — the composed preview, fingerprinted before any review by
     `candidate_fingerprint`. Computing the fingerprint needs no approval hash.
  2. evidence review            — a human confirms or rejects the candidate against its cited
     evidence. The record binds to the candidate fingerprint (`record_confirmation` /
     `record_rejection`), not to the approval hash.
  3. final approval            — the existing approval hash and all existing gates, AND a valid,
     current, confirmed human review of THIS candidate. Enforced at the action boundary
     (`enforce`, called inside `outreach/job_draft.create`), never only in the UI.

What this does and does not do. It gates approval on a person's judgment bound to the exact
candidate and its cited evidence. It does NOT fix entailment, does NOT make the word-overlap
validator in `outreach/writer.py` semantically correct, and does NOT touch quote freshness. It
is a control on approval, not an improvement in the validator's accuracy. It requires a human
evidence review for EVERY draft before it can become approval-ready — the review burden is
accepted for this single-founder pilot.

Storage. The live Google Sheet is not touched by this change. The default is `UnmigratedReviewStore`
(fail-closed: reading finds no review, writing is refused), so where nothing is configured, approval
stays blocked. `store_from_env` selects a store from configuration: `REVIEW_STORE=sheet` chooses the
production `SheetReviewStore` (an append-only `Reviews` tab, implemented and tested against a fake
Sheets API, never run against the live Sheet here), a `REVIEW_STORE_PATH` chooses a local JSON file,
and otherwise the fail-closed default. The local console review flow and the tests use
`MemoryReviewStore` / `JsonFileReviewStore`.

Trust boundary (stated honestly, not overclaimed). The one write path that carries an authenticated
identity is the console `POST /api/review/<lead>`: it derives the reviewer from the IAP-verified
session (`g.email`) and ignores any reviewer field in the request body, and the gate additionally
rejects any reviewer not on the human allow-list. None of the stores here is tamper-resistant: a
party with direct write access to the JSON file, or to the Sheet once migrated, could insert a
record naming an allow-listed reviewer with the correct fingerprint and so forge an approval. The
protection is who can write the store (file permissions; the Sheet's own ACLs and the service
account) plus the authenticated console path - not cryptography. No signing or attestation is
claimed. Revocation works by supersession: a store keeps one effective record per key (the file
store replaces it; the proposed Sheet store appends and `get` returns the latest row), so a later
rejection supersedes an earlier confirmation of the same candidate only if it is the later write.
The file store is last-writer-wins with no locking, so concurrent writes can lose one. The
action-boundary recheck (`enforce`) is the last gate before any write and re-derives the
fingerprint from the exact candidate the action then uses, which NARROWS but does not close the
window: a rejection or edit landing after the recheck and before the Gmail write is not caught. The
recheck is not atomic with the external action; nothing here claims it is. In practice the window is
the reservation write plus the create call, and drafting is disabled anyway.
"""

import base64
import json
import os
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path

from outreach import console_auth, drafting, review_identity

CONFIRMED = "confirmed"
REJECTED = "rejected"
DECISIONS = frozenset({CONFIRMED, REJECTED})

# The record's own fields. Every one must be present and well-formed, or the review is malformed.
REQUIRED_FIELDS = ("lead_id", "fingerprint", "reviewer", "decision", "reviewed_at")

# The offer settings bound into the candidate fingerprint. The body already renders these, but
# binding them explicitly means any change to the offer invalidates a review even in the unlikely
# case it left the rendered body untouched.
OFFER_FIELDS = drafting.FIELDS

_HEX64 = re.compile(r"\A[0-9a-f]{64}\Z")

# Why a review does not permit approval. Every one of these BLOCKS.
MISSING = "REVIEW_MISSING"        # no record for this lead
UNREADABLE = "REVIEW_UNREADABLE"  # the store could not be read at all
MALFORMED = "REVIEW_MALFORMED"    # a record exists but is not a well-formed review
NOT_HUMAN = "REVIEW_NOT_HUMAN"    # the reviewer is not an authorized human (e.g. a forged record)
STALE = "REVIEW_STALE"            # the candidate changed since it was reviewed
REJECTED_REASON = "REVIEW_REJECTED"  # a human reviewed THIS candidate and rejected it

# A blocker added to a preview when a would-be-approvable candidate has no valid review yet, so no
# approval hash is issued. Distinct from writer.REVIEW_PREFIX (a claim the validator held): this one
# still lets the words be read so a person can review them.
AWAITING_BLOCKER = "awaiting a human evidence review of this candidate"
# A blocker when review verification is not configured (no trusted public key): no approval hash is
# issued - a deployable path never falls back to unsigned/unverified review.
UNVERIFIABLE_BLOCKER = "review verification is not configured (no trusted key); cannot approve"


class ReviewInvalid(ValueError):
    """No valid, current, confirmed human review permits approval of this candidate.

    `reason` is one of the machine constants above; the message is for a person."""

    def __init__(self, reason, message):
        self.reason = reason
        super().__init__(message)


class NotMigrated(RuntimeError):
    """A store cannot persist a review yet because its backing storage is not migrated."""


class ReviewsUnavailable(RuntimeError):
    """A review store's backing storage cannot be read or written safely (a missing tab, a changed
    header, or an I/O error), or a write is known to have failed, so review and approval are
    blocked. `enforce` turns this into UNREADABLE and `is_reviewed` into False - fail-closed."""


class ReviewsUncertain(ReviewsUnavailable):
    """A write MAY have landed but could not be confirmed (the append response failed and the
    reconciliation read failed, or the response reported success but the row is not visible). The
    outcome is unknown: do not assume it was or was not recorded, and never auto-retry. Still blocks
    approval (it is a ReviewsUnavailable), but a caller must not say 'nothing was changed'."""


# The append-only Reviews tab schema (EXACT: the header must equal this, no extra columns). The key
# column holds the review id (the lead id for an initial email, `followup:<lead>:<step>` for a
# follow-up), so an initial's review and a follow-up's are separate rows. "Attempt ID" is a unique
# id per append, so a specific write can be reconciled without an older identical row masking it.
# "Prev" and "Signature" carry the signed hash chain (see outreach/review_identity.py): each decision
# names the signature of the one it supersedes, and the worker verifies with the trusted public key.
REVIEWS_TAB = "Reviews"
REVIEWS_HEADER = ["Review ID", "Attempt ID", "Prev", "Fingerprint", "Reviewer", "Decision",
                  "Reviewed at (UTC)", "Signature"]
# Row column index -> review-record field (the Attempt ID column is storage-internal, not a record
# field).
_ROW_TO_RECORD = {0: "lead_id", 2: "prev", 3: "fingerprint", 4: "reviewer", 5: "decision",
                  6: "reviewed_at", 7: "signature"}
_ATTEMPT_COL = 1


def _canonical(material):
    return json.dumps(material, sort_keys=True, ensure_ascii=False).encode("utf-8")


def candidate_fingerprint(preview, book=None, settings=None):
    """A stable fingerprint of everything a review is a judgment about.

    Deliberately separate from the approval hash: it carries no send-day and no sender, so a
    review does not go stale merely because a day passed — the approval hash still binds those
    for send-readiness. It binds recipient, the complete subject and body, the cited quote (text,
    id and source URL), the handbook identity (content hash) and version, and the offer settings.
    Any change to any of these produces a different fingerprint, so a stored review no longer
    matches and approval is blocked until the candidate is reviewed again.

    Computable from a composed preview alone (before any review) and reproducible at the action
    boundary from the rebuilt candidate — both compute over the same fields.
    """
    import hashlib

    settings = settings or {}
    written = preview.get("written") or {}
    evidence = written.get("evidence") or preview.get("evidence")
    handbook_hash = (book or {}).get("content_hash") or preview.get("handbook_hash", "")
    material = {
        "v": 1,
        "lead_id": preview.get("lead_id", ""),
        "to": (preview.get("to") or "").strip().lower(),
        "subject": preview.get("subject", ""),
        "body": preview.get("body", ""),
        "evidence": ({"quote_id": evidence.get("quote_id", ""),
                      "category": evidence.get("category", ""),
                      "quote": evidence.get("quote", ""),
                      "url": evidence.get("url", "")} if evidence else None),
        "handbook_hash": handbook_hash,
        "handbook_version": str(settings.get("version", "")),
        "offer": {key: str(settings.get(key.lower(), "")).strip() for key in OFFER_FIELDS},
    }
    return hashlib.sha256(_canonical(material)).hexdigest()


def allowed_reviewers(settings=None, environ=None):
    """The authorized human reviewers, lower case: the drafting settings' `review_reviewers`
    plus the console's own allow-list (`CONSOLE_ALLOWED_EMAILS`). Empty when none is configured,
    which makes `enforce` fail closed."""
    settings = settings or {}
    environ = os.environ if environ is None else environ
    people = set()
    listed = settings.get("review_reviewers")
    if isinstance(listed, str):
        listed = listed.split(",")
    for person in (listed or []):
        person = str(person).strip().lower()
        if person:
            people.add(person)
    people |= set(console_auth.allowed_emails(environ.get("CONSOLE_ALLOWED_EMAILS", "")))
    return frozenset(people)


def _well_formed(record):
    if not isinstance(record, dict):
        return False
    for field in REQUIRED_FIELDS:
        value = record.get(field)
        if not isinstance(value, str) or not value.strip():
            return False
    if record["decision"] not in DECISIONS:
        return False
    if not _HEX64.match(record["fingerprint"]):
        return False
    try:
        datetime.fromisoformat(record["reviewed_at"].replace("Z", "+00:00"))
    except ValueError:
        return False
    return True


def _reviewers(settings, reviewers):
    return (allowed_reviewers(settings) if reviewers is None
            else frozenset(r.strip().lower() for r in reviewers if r.strip()))


def _evaluate(record, fingerprint, reviewers):
    """Raise `ReviewInvalid` unless `record` is a valid, current, confirmed human review of the
    candidate with this fingerprint. `record` is None when the store held nothing."""
    if record is None:
        raise ReviewInvalid(MISSING, "no human evidence review exists for this candidate")
    if not _well_formed(record):
        raise ReviewInvalid(MALFORMED, "the review record is not a well-formed review")
    reviewer = record["reviewer"].strip().lower()
    if not reviewers or reviewer not in reviewers:
        raise ReviewInvalid(NOT_HUMAN, "the review was not made by an authorized human reviewer")
    if record["fingerprint"] != fingerprint:
        raise ReviewInvalid(STALE, "the candidate changed since it was reviewed; review it again")
    if record["decision"] != CONFIRMED:
        raise ReviewInvalid(REJECTED_REASON, "this candidate was rejected in review")


def enforce(preview, book, settings, *, store, reviewers=None, review_id=None, verifier=None):
    """Raise `ReviewInvalid` unless a valid, current, confirmed human review of THIS candidate
    exists. Returns the candidate fingerprint on success. With a `verifier`, the current decision is
    resolved from the signed hash chain (forged records and concurrent conflicts block).

    Called at the action boundary, after the candidate has been rebuilt and every existing gate
    has passed, immediately before any Gmail write. Because the fingerprint is recomputed here,
    an edit to the recipient, wording, cited evidence, handbook or offer between review and action
    makes the stored review stale and blocks the draft. `review_id` defaults to the lead id; a
    follow-up passes its own id so its review is separate from the initial email's.
    """
    reviewers = _reviewers(settings, reviewers)
    fingerprint = candidate_fingerprint(preview, book, settings)
    key = review_id or preview.get("lead_id", "")
    record = _current_record(store, key, verifier)  # raises ReviewInvalid on read/chain problems
    _evaluate(record, fingerprint, reviewers)
    return fingerprint


def _current_record(store, review_id, verifier):
    """The single current decision record for a review id, or raise ReviewInvalid.

    Without a `verifier` (the default), reads the store's latest record. With one, resolves the
    signed hash chain over the full history, so an unverifiable/forged record or a concurrent
    conflict blocks (TAMPERED / CONFLICT) instead of an arbitrary decision being chosen."""
    if verifier is None:
        try:
            return store.get(review_id)
        except Exception as exc:
            raise ReviewInvalid(UNREADABLE, f"the review record could not be read: {exc}") from None
    try:
        records = store.history(review_id)
    except Exception as exc:
        raise ReviewInvalid(UNREADABLE, f"the review history could not be read: {exc}") from None
    record, code = review_identity.resolve_current(records, verifier)
    if record is None:
        raise ReviewInvalid(code, {
            review_identity.NO_REVIEW: "no human evidence review exists for this candidate",
            review_identity.TAMPERED: "a review record could not be verified",
            review_identity.CONFLICT: "the review decisions conflict; approval is blocked",
        }.get(code, "the review could not be resolved"))
    return record


def is_reviewed(store, review_id, fingerprint, *, reviewers, verifier=None):
    """True iff a valid, current, confirmed human review with this fingerprint exists for
    `review_id`. Used to gate approval-hash issuance; anything unresolved returns False."""
    reviewers = frozenset(r.strip().lower() for r in reviewers if r and r.strip())
    try:
        record = _current_record(store, review_id, verifier)
        _evaluate(record, fingerprint, reviewers)
        return True
    except ReviewInvalid:
        return False


def _record(store, lead_id, reviewer, decision, fingerprint, now=None, signer=None):
    """Write one review. The reviewer identity must be supplied by an authenticated caller: this
    function never infers or invents it, so the model/worker cannot mint a review of its own work.

    With a `signer` (the console's signing authority), the decision is chained onto the current tip
    (`prev`) and signed, so the worker can later verify it and detect conflicts. Without a signer
    (the current default), the record is unsigned and the legacy latest-wins path applies.
    """
    lead_id = str(lead_id).strip()
    reviewer = str(reviewer or "").strip()
    if not lead_id:
        raise ValueError("a review needs a lead id")
    if not reviewer:
        raise ValueError("a review needs the authenticated reviewer's identity")
    if decision not in DECISIONS:
        raise ValueError(f"unknown review decision {decision!r}")
    if not isinstance(fingerprint, str) or not _HEX64.match(fingerprint):
        raise ValueError("a review needs the candidate fingerprint it reviewed")
    reviewed_at = (now or datetime.now(timezone.utc)).isoformat()
    prev, signature = review_identity.FIRST, ""
    if signer is not None:
        history = store.history(lead_id) if hasattr(store, "history") else []
        prev = review_identity.tip_signature(history, review_identity.Verifier(signer.public_key_bytes()))
        signature = signer.sign(review_id=lead_id, prev=prev, fingerprint=fingerprint,
                                reviewer=reviewer, decision=decision, reviewed_at=reviewed_at)
    record = {"lead_id": lead_id, "prev": prev, "fingerprint": fingerprint, "reviewer": reviewer,
              "decision": decision, "reviewed_at": reviewed_at, "signature": signature}
    store.put(record)
    return record


def record_confirmation(store, lead_id, reviewer, fingerprint, *, now=None, signer=None):
    return _record(store, lead_id, reviewer, CONFIRMED, fingerprint, now, signer)


def record_rejection(store, lead_id, reviewer, fingerprint, *, now=None, signer=None):
    return _record(store, lead_id, reviewer, REJECTED, fingerprint, now, signer)


HUMAN_JUDGMENT_NOTE = (
    "Confirming records your judgment that these claims are supported by the cited evidence. "
    "It is not automated proof that they are true. Nothing is sent or drafted by confirming; "
    "sending and drafting stay disabled."
)


def _status(existing, fingerprint):
    if not isinstance(existing, dict):
        return {"decision": None, "current": False}
    return {"decision": existing.get("decision"), "reviewer": existing.get("reviewer", ""),
            "reviewed_at": existing.get("reviewed_at", ""),
            "current": existing.get("fingerprint") == fingerprint}


def review_view(preview, book=None, settings=None, *, existing=None, status=None):
    """The candidate and its cited evidence, side by side, for a person to confirm or reject.

    Shows the words and the sources; states plainly that confirming is a human judgment, not
    proof. Carries the candidate fingerprint the confirm/reject action must echo back. The `review`
    field is the resolved current status (`status`, from `resolved_status` over the signed chain)
    when given - so a conflicted, tampered or unverifiable chain never shows as approval - falling
    back to the legacy latest-record status only for explicitly-unsigned callers.
    """
    settings = settings or {}
    written = preview.get("written") or {}
    evidence = written.get("evidence") or preview.get("evidence")
    fingerprint = candidate_fingerprint(preview, book, settings)
    return {
        "lead_id": preview.get("lead_id", ""),
        "to": preview.get("to", ""),
        "subject": preview.get("subject", ""),
        "body": preview.get("body", ""),
        "claims": [{"kind": s.get("kind", ""), "text": s.get("text", ""),
                    "quote_id": s.get("quote_id", "")} for s in written.get("sentences", [])],
        "evidence": ({"category": evidence.get("category", ""), "quote": evidence.get("quote", ""),
                      "url": evidence.get("url", ""), "quote_id": evidence.get("quote_id", "")}
                     if evidence else None),
        "handbook_hash": (book or {}).get("content_hash") or preview.get("handbook_hash", ""),
        "handbook_version": str(settings.get("version", "")),
        "fingerprint": fingerprint,
        "review": status if status is not None else _status(existing, fingerprint),
        "note": HUMAN_JUDGMENT_NOTE,
    }


# --- stores ---------------------------------------------------------------------------------
# One review per lead: the latest confirm or reject for that lead's current candidate. A store
# `get(lead_id)` returns the record or None; `put(record)` replaces it.


class MemoryReviewStore:
    """In memory, for tests and short-lived local use. Append-only per review id: `get` returns the
    latest recorded decision, `history` returns them all (for chain resolution)."""

    def __init__(self, records=None):
        self._by_lead = {k: [dict(v)] for k, v in (records or {}).items()}

    def get(self, lead_id):
        rows = self._by_lead.get(lead_id)
        return dict(rows[-1]) if rows else None

    def put(self, record):
        self._by_lead.setdefault(record["lead_id"], []).append(dict(record))

    def history(self, lead_id):
        return [dict(r) for r in self._by_lead.get(lead_id, [])]


class JsonFileReviewStore:
    """A local JSON file, for the local console review flow. Never the live Sheet. Append-only per
    review id ({review_id: [records]}); `get` returns the latest, `history` returns them all."""

    def __init__(self, path):
        self.path = Path(path)

    def _load(self):
        if not self.path.exists():
            return {}
        return json.loads(self.path.read_text(encoding="utf-8"))

    def get(self, lead_id):
        rows = self._load().get(lead_id) or []
        return rows[-1] if rows else None

    def put(self, record):
        data = self._load()
        data.setdefault(record["lead_id"], []).append(dict(record))
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")

    def history(self, lead_id):
        return list(self._load().get(lead_id) or [])


class UnmigratedReviewStore:
    """The fail-closed default when no review store is configured (no migration applied).

    Reading finds no review, so approval stays blocked (MISSING); writing is refused. This is what
    `default_store()` returns unless `REVIEW_STORE` selects a real one. It touches nothing (no
    Google, no file), so it is safe wherever the review flow is simply not configured."""

    def get(self, review_id):
        return None

    def history(self, review_id):
        return []

    def put(self, record):
        raise NotMigrated(
            "no review store is configured (set REVIEW_STORE), so a review cannot be persisted; "
            "see docs/AS_BUILT.md")


class SheetReviewStore:
    """The production store: an append-only `Reviews` tab on the leads Google Sheet.

    Contract (append-only, latest-row-wins):
      - `get(review_id)` returns the LATEST row for that id as a record, or None when there is none.
        "Latest" is by row position (append order) - never a client timestamp, which is stored for
        the audit but never trusted for ordering. A later rejection therefore supersedes an earlier
        confirmation of the same fingerprint because it is the later row, so a superseded
        confirmation is never returned as the current decision.
      - `put(record)` writes each attempt with a unique Attempt ID, appends one row, then reconciles
        THAT specific append by its id (an older identical row cannot mask a dropped write). It never
        assumes the append succeeded and never auto-retries (a blind retry could double-write):
          * the attempt id is found  -> recorded (even if the append response failed but the write
            landed);
          * the attempt id is absent and the append response reported success, or the reconciliation
            read failed -> `ReviewsUncertain` (the write may or may not be there; do not assume);
          * the attempt id is absent and the append response failed -> `ReviewsUnavailable` (nothing
            was recorded).
      - A missing tab, a header that is not EXACTLY `REVIEWS_HEADER`, or any read error blocks
        (raises `ReviewsUnavailable`). A malformed latest row is returned as-is and the gate rejects
        it (MALFORMED). This store never creates the tab.

    The `api` is a Sheets service (injected in tests as a fake); in production it is built lazily.
    Reused across worker and console through the one review contract.
    """

    TAB = REVIEWS_TAB
    HEADER = REVIEWS_HEADER

    def __init__(self, api=None, spreadsheet_id=None):
        self._api = api
        self._sheet_id = spreadsheet_id

    def _service(self):
        if self._api is None:
            from outreach import sheet
            self._api = sheet._api()
        return self._api

    def _sid(self):
        if self._sheet_id is None:
            from outreach import sheet
            self._sheet_id = sheet.SHEET_ID
        return self._sheet_id

    def _values(self):
        """Every row of the tab (header first), or ReviewsUnavailable if it cannot be read safely."""
        api, sid = self._service(), self._sid()
        try:
            titles = {s["properties"]["title"]
                      for s in api.get(spreadsheetId=sid).execute()["sheets"]}
            if self.TAB not in titles:
                raise ReviewsUnavailable(f"there is no {self.TAB} tab")
            values = api.values().get(spreadsheetId=sid,
                                      range=f"'{self.TAB}'").execute().get("values", [])
        except ReviewsUnavailable:
            raise
        except Exception as exc:
            raise ReviewsUnavailable(
                f"the {self.TAB} tab could not be read ({type(exc).__name__})") from exc
        # Exact header: the Reviews tab is system-owned; an extra or changed column is drift, and it
        # blocks (fail-closed) rather than being read past.
        if not values or list(values[0]) != self.HEADER:
            raise ReviewsUnavailable(f"the {self.TAB} tab's header is missing or not exactly the schema")
        return values

    @staticmethod
    def _record(row):
        cell = lambda i: row[i] if i < len(row) else ""  # noqa: E731
        return {field: cell(i) for i, field in _ROW_TO_RECORD.items()}

    def _attempt_present(self, attempt_id):
        return any((row[_ATTEMPT_COL] if len(row) > _ATTEMPT_COL else "") == attempt_id
                   for row in self._values()[1:])

    def get(self, review_id):
        matches = [row for row in self._values()[1:] if (row[0] if row else "") == review_id]
        if not matches:
            return None
        return self._record(matches[-1])  # append order is the authority

    def history(self, review_id):
        """Every recorded decision for a review id, in append order, for chain resolution."""
        return [self._record(row) for row in self._values()[1:] if (row[0] if row else "") == review_id]

    def put(self, record):
        self._values()  # a missing tab / changed header blocks the write; never create the tab
        api, sid = self._service(), self._sid()
        attempt_id = uuid.uuid4().hex
        row = [record.get("lead_id", ""), attempt_id, record.get("prev", ""),
               record.get("fingerprint", ""), record.get("reviewer", ""), record.get("decision", ""),
               record.get("reviewed_at", ""), record.get("signature", "")]
        response_ok = True
        try:
            api.values().append(
                spreadsheetId=sid, range=f"'{self.TAB}'!A1", valueInputOption="RAW",
                insertDataOption="INSERT_ROWS", body={"values": [row]}).execute()
        except Exception:
            response_ok = False  # the response failed; the write may or may not have landed
        # Reconcile THIS attempt by its unique id (never a mere identical row). Never retry.
        try:
            landed = self._attempt_present(attempt_id)
        except ReviewsUnavailable as exc:
            raise ReviewsUncertain(
                "the review was sent but the reconciliation read failed, so whether it was recorded "
                "is unknown; do not assume either way and do not retry") from exc
        if landed:
            return record  # recorded, even if the append response itself errored
        if response_ok:
            raise ReviewsUncertain(
                "the append reported success but the row is not present, so the outcome is uncertain; "
                "do not retry")
        raise ReviewsUnavailable("the append failed and no row was recorded; nothing was written")


def store_from_env(environ=None):
    """The review store selected by configuration. `REVIEW_STORE=sheet` -> the Sheet adapter; a
    `REVIEW_STORE_PATH` -> a local JSON file (for the local flow); otherwise the fail-closed default.
    Review being *configured* is separate from being *enabled*: the console's routes stay off unless
    `ENABLE_REVIEW=true`, and drafting/sending stay off regardless."""
    import os
    environ = os.environ if environ is None else environ
    if environ.get("REVIEW_STORE", "").strip().lower() == "sheet":
        return SheetReviewStore()
    path = environ.get("REVIEW_STORE_PATH", "").strip()
    if path:
        return JsonFileReviewStore(path)
    return UnmigratedReviewStore()


def default_store():
    """The store used when a caller injects none: whatever configuration selects, fail-closed by
    default (nothing configured -> `UnmigratedReviewStore`)."""
    return store_from_env()


# --- the one trusted identity configuration -------------------------------------------------
# The worker and console read the PUBLIC verification key from the drafting settings (it is not
# secret). The console reads the PRIVATE signing key from its own environment only (never the
# worker's settings). Where either is absent or invalid, callers BLOCK - deployable paths must not
# fall back to unsigned mode.

def configured_verifier(settings):
    """The trusted `Verifier` from `settings['review_public_key']` (base64 Ed25519 public key), or
    None when unconfigured or the material is invalid. None must BLOCK in deployable paths."""
    key = (settings or {}).get("review_public_key")
    if not key:
        return None
    try:
        return review_identity.Verifier(base64.b64decode(key))
    except Exception:
        return None


def configured_signer_from_env(environ=None):
    """The console's `Signer` from the `REVIEW_PRIVATE_KEY` environment variable (base64 Ed25519
    private key), or None when unconfigured or invalid. Kept out of the worker's settings so the
    worker can verify but never sign. None must BLOCK an authenticated review write."""
    environ = os.environ if environ is None else environ
    key = environ.get("REVIEW_PRIVATE_KEY", "").strip()
    if not key:
        return None
    try:
        return review_identity.Signer(base64.b64decode(key))
    except Exception:
        return None


def resolved_status(store, review_id, fingerprint, verifier):
    """The current review status for display/read-back, resolved from the signed chain. Never
    reports a conflicted, tampered or unverifiable chain as current approval. Returns the dict
    `review_view` uses for its `review` field.

      state: "resolved" (a verified tip; `decision`/`current` are meaningful),
             "unverifiable" (no verifier configured), "unreadable" (history could not be read),
             or a resolve code (REVIEW_MISSING / REVIEW_CONFLICT / REVIEW_TAMPERED)."""
    if verifier is None:
        return {"decision": None, "current": False, "state": "unverifiable"}
    try:
        records = store.history(review_id) if hasattr(store, "history") else []
    except Exception:
        return {"decision": None, "current": False, "state": "unreadable"}
    record, code = review_identity.resolve_current(records, verifier)
    if record is None:
        return {"decision": None, "current": False, "state": code}
    return {"decision": record.get("decision"), "reviewer": record.get("reviewer", ""),
            "reviewed_at": record.get("reviewed_at", ""),
            "current": record.get("fingerprint") == fingerprint, "state": "resolved"}
