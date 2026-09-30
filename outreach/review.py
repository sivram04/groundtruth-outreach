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

import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path

from outreach import console_auth, drafting

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
    header, or an I/O error), so review and approval are blocked. `enforce` turns this into
    UNREADABLE and `is_reviewed` into False - fail-closed."""


# The append-only Reviews tab schema. The key column holds the review id (the lead id for an initial
# email, `followup:<lead>:<step>` for a follow-up), NOT only a lead id, so an initial's review and a
# follow-up's are separate rows.
REVIEWS_TAB = "Reviews"
REVIEWS_HEADER = ["Review ID", "Fingerprint", "Reviewer", "Decision", "Reviewed at (UTC)"]
_RECORD_FIELDS = ("lead_id", "fingerprint", "reviewer", "decision", "reviewed_at")


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


def enforce(preview, book, settings, *, store, reviewers=None, review_id=None):
    """Raise `ReviewInvalid` unless a valid, current, confirmed human review of THIS candidate
    exists. Returns the candidate fingerprint on success.

    Called at the action boundary, after the candidate has been rebuilt and every existing gate
    has passed, immediately before any Gmail write. Because the fingerprint is recomputed here,
    an edit to the recipient, wording, cited evidence, handbook or offer between review and action
    makes the stored review stale and blocks the draft. `review_id` defaults to the lead id; a
    follow-up passes its own id so its review is separate from the initial email's.
    """
    reviewers = _reviewers(settings, reviewers)
    fingerprint = candidate_fingerprint(preview, book, settings)
    key = review_id or preview.get("lead_id", "")
    try:
        record = store.get(key)
    except Exception as exc:  # a store that cannot be read never permits approval
        raise ReviewInvalid(UNREADABLE, f"the review record could not be read: {exc}") from None
    _evaluate(record, fingerprint, reviewers)
    return fingerprint


def is_reviewed(store, review_id, fingerprint, *, reviewers):
    """True iff a valid, current, confirmed human review with this fingerprint exists for
    `review_id`. Used to gate approval-hash issuance; an unreadable store returns False."""
    reviewers = frozenset(r.strip().lower() for r in reviewers if r and r.strip())
    try:
        record = store.get(review_id)
    except Exception:
        return False
    try:
        _evaluate(record, fingerprint, reviewers)
        return True
    except ReviewInvalid:
        return False


def _record(store, lead_id, reviewer, decision, fingerprint, now=None):
    """Write one review. The reviewer identity must be supplied by an authenticated caller: this
    function never infers or invents it, so the model/worker cannot mint a review of its own work.
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
    record = {"lead_id": lead_id, "fingerprint": fingerprint, "reviewer": reviewer,
              "decision": decision,
              "reviewed_at": (now or datetime.now(timezone.utc)).isoformat()}
    store.put(record)
    return record


def record_confirmation(store, lead_id, reviewer, fingerprint, *, now=None):
    return _record(store, lead_id, reviewer, CONFIRMED, fingerprint, now)


def record_rejection(store, lead_id, reviewer, fingerprint, *, now=None):
    return _record(store, lead_id, reviewer, REJECTED, fingerprint, now)


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


def review_view(preview, book=None, settings=None, *, existing=None):
    """The candidate and its cited evidence, side by side, for a person to confirm or reject.

    Shows the words and the sources; states plainly that confirming is a human judgment, not
    proof. Carries the candidate fingerprint the confirm/reject action must echo back, and the
    status of any existing review for this candidate.
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
        "review": _status(existing, fingerprint),
        "note": HUMAN_JUDGMENT_NOTE,
    }


# --- stores ---------------------------------------------------------------------------------
# One review per lead: the latest confirm or reject for that lead's current candidate. A store
# `get(lead_id)` returns the record or None; `put(record)` replaces it.


class MemoryReviewStore:
    """In memory, for tests and short-lived local use."""

    def __init__(self, records=None):
        self._by_lead = dict(records or {})

    def get(self, lead_id):
        return self._by_lead.get(lead_id)

    def put(self, record):
        self._by_lead[record["lead_id"]] = dict(record)


class JsonFileReviewStore:
    """A local JSON file, for the local console review flow. Never the live Sheet."""

    def __init__(self, path):
        self.path = Path(path)

    def _load(self):
        if not self.path.exists():
            return {}
        return json.loads(self.path.read_text(encoding="utf-8"))

    def get(self, lead_id):
        return self._load().get(lead_id)

    def put(self, record):
        data = self._load()
        data[record["lead_id"]] = dict(record)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")


class UnmigratedReviewStore:
    """The fail-closed default when no review store is configured (no migration applied).

    Reading finds no review, so approval stays blocked (MISSING); writing is refused. This is what
    `default_store()` returns unless `REVIEW_STORE` selects a real one. It touches nothing (no
    Google, no file), so it is safe wherever the review flow is simply not configured."""

    def get(self, review_id):
        return None

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
        confirmation of the same fingerprint because it is the later row.
      - `put(record)` appends one row, then re-reads and confirms the exact row is present; it never
        assumes the append succeeded and never auto-retries (a blind retry could double-write). An
        unconfirmed or ambiguous append raises, so the caller treats it as a failure and approval
        stays blocked.
      - A missing tab, a header that is not exactly `REVIEWS_HEADER`, or any read/write error blocks
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
        if not values or values[0][:len(self.HEADER)] != self.HEADER:
            raise ReviewsUnavailable(f"the {self.TAB} tab's header is missing or changed")
        return values

    @staticmethod
    def _record(row):
        cell = lambda i: row[i] if i < len(row) else ""  # noqa: E731
        return dict(zip(_RECORD_FIELDS, (cell(0), cell(1), cell(2), cell(3), cell(4))))

    def get(self, review_id):
        matches = [row for row in self._values()[1:] if (row[0] if row else "") == review_id]
        if not matches:
            return None
        return self._record(matches[-1])  # append order is the authority

    def put(self, record):
        self._values()  # a missing tab / changed header blocks the write; never create the tab
        api, sid = self._service(), self._sid()
        row = [record.get(field, "") for field in _RECORD_FIELDS]
        try:
            api.values().append(
                spreadsheetId=sid, range=f"'{self.TAB}'!A1", valueInputOption="RAW",
                insertDataOption="INSERT_ROWS", body={"values": [row]}).execute()
        except Exception as exc:
            raise ReviewsUnavailable(
                f"the review could not be appended ({type(exc).__name__})") from exc
        # Do not assume the append landed: re-read and confirm this exact row is present. A
        # concurrent later row may supersede it on read (correct); an absent row means the append
        # did not take, so raise rather than report success or silently retry.
        if not any(list(r) == row for r in self._values()[1:]):
            raise ReviewsUnavailable("the review append could not be confirmed; nothing was recorded")
        return record


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
