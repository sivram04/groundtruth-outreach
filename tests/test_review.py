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


def test_the_unmigrated_store_is_fail_closed_and_never_writes():
    store = review.UnmigratedReviewStore()
    assert store.get("A-0001") is None  # -> MISSING, blocks
    with pytest.raises(review.NotMigrated):
        store.put({"lead_id": "A-0001", "fingerprint": "a" * 64, "reviewer": "x",
                   "decision": "confirmed", "reviewed_at": "2026-09-29T00:00:00+00:00"})


def test_the_default_store_is_fail_closed_unless_configured(monkeypatch):
    monkeypatch.delenv("REVIEW_STORE", raising=False)
    monkeypatch.delenv("REVIEW_STORE_PATH", raising=False)
    assert isinstance(review.default_store(), review.UnmigratedReviewStore)
    monkeypatch.setenv("REVIEW_STORE", "sheet")
    assert isinstance(review.default_store(), review.SheetReviewStore)


# --- the Sheet adapter (against a fake Sheets API; never the live Sheet) --------------------

class _Exec:
    def __init__(self, value):
        self.value = value

    def execute(self):
        if isinstance(self.value, Exception):
            raise self.value
        return self.value


class _Values:
    def __init__(self, api):
        self.api = api

    def get(self, spreadsheetId, range):
        name = range.split("!")[0].strip("'")
        if self.api.read_error or (self.api.fail_read_after_write and self.api._wrote):
            return _Exec(RuntimeError("boom"))
        return _Exec({"values": [list(r) for r in (self.api.tabs.get(name) or [])]})

    def append(self, spreadsheetId, range, valueInputOption, insertDataOption, body):
        name = range.split("!")[0].strip("'")
        rows = [list(r) for r in body["values"]]
        if self.api.write_error:  # the request errored and nothing was written
            return _Exec(RuntimeError("boom"))
        if self.api.commit_then_error:  # the row WAS written, but the response errored
            self.api.tabs.setdefault(name, []).extend(rows)
            self.api._wrote = True
            self.api.appends += 1
            return _Exec(RuntimeError("boom"))
        if self.api.drop_write:  # the response says ok, but the row did NOT persist
            self.api.appends += 1
            self.api._wrote = True
            return _Exec({})
        self.api.tabs.setdefault(name, []).extend(rows)
        self.api._wrote = True
        self.api.appends += 1
        return _Exec({})


class Sheets:
    """A fake Sheets service for the review store: get() lists tabs, values() reads/appends.

    Failure modes: read_error (reads fail), write_error (append request fails, nothing written),
    commit_then_error (row written but append response fails), drop_write (append response ok but
    nothing persisted), fail_read_after_write (reads fail once anything has been appended)."""

    def __init__(self, tabs, *, read_error=False, write_error=False, drop_write=False,
                 commit_then_error=False, fail_read_after_write=False):
        self.tabs = {n: (None if rows is None else [list(r) for r in rows]) for n, rows in tabs.items()}
        self.read_error, self.write_error, self.drop_write = read_error, write_error, drop_write
        self.commit_then_error, self.fail_read_after_write = commit_then_error, fail_read_after_write
        self.appends = 0
        self._wrote = False

    def get(self, spreadsheetId):
        return _Exec({"sheets": [{"properties": {"title": n}} for n, r in self.tabs.items() if r is not None]})

    def values(self):
        return _Values(self)


HDR = review.REVIEWS_HEADER


def srow(review_id, fingerprint, decision, at, *, attempt="att", reviewer="founder@lakshyaa.ai",
         prev="", signature="sig"):
    """A Reviews row: Review ID | Attempt ID | Prev | Fingerprint | Reviewer | Decision | at | Sig."""
    return [review_id, attempt, prev, fingerprint, reviewer, decision, at, signature]


def sheet_store(tabs, **kw):
    return review.SheetReviewStore(api=Sheets(tabs, **kw), spreadsheet_id="sid")


def test_the_sheet_store_reads_the_latest_row_for_a_review_id():
    store = sheet_store({"Reviews": [HDR,
                                     srow("A-0001", "b" * 64, "confirmed", "t1", attempt="a1"),
                                     srow("A-0002", "c" * 64, "rejected", "t2", attempt="a2"),
                                     srow("A-0001", "d" * 64, "rejected", "t3", attempt="a3")]})
    got = store.get("A-0001")
    assert got["decision"] == "rejected" and got["fingerprint"] == "d" * 64  # the later row wins
    assert store.get("A-9999") is None  # no row -> MISSING


def test_a_later_rejection_row_supersedes_an_earlier_confirmation_by_position():
    store = sheet_store({"Reviews": [HDR,
                                     srow("A-0001", "b" * 64, "confirmed", "z-later", attempt="a1"),
                                     srow("A-0001", "b" * 64, "rejected", "a-earlier", attempt="a2")]})
    # ordering is by ROW POSITION, not the (here misleading) client timestamps
    assert store.get("A-0001")["decision"] == "rejected"


def test_the_sheet_store_blocks_on_a_missing_tab_a_changed_header_and_read_errors():
    with pytest.raises(review.ReviewsUnavailable):
        sheet_store({"Reviews": None}).get("A-0001")  # missing tab
    with pytest.raises(review.ReviewsUnavailable):
        sheet_store({"Reviews": [["Lead ID", "Wrong"], ["A-0001"]]}).get("A-0001")  # header drift
    with pytest.raises(review.ReviewsUnavailable):
        sheet_store({"Reviews": [HDR]}, read_error=True).get("A-0001")  # read error


def test_an_extra_header_column_is_rejected_by_the_exact_schema():
    with pytest.raises(review.ReviewsUnavailable):
        sheet_store({"Reviews": [HDR + ["Extra"], srow("A-0001", "b" * 64, "confirmed", "t") + ["x"]]}).get("A-0001")
    # an older 5-column header (before Attempt ID) is also rejected
    with pytest.raises(review.ReviewsUnavailable):
        sheet_store({"Reviews": [["Review ID", "Fingerprint", "Reviewer", "Decision",
                                  "Reviewed at (UTC)"]]}).get("A-0001")


def test_a_malformed_latest_row_is_rejected_by_the_gate():
    store = sheet_store({"Reviews": [HDR, srow("A-0001", "not-hex", "confirmed", "t")]})
    record = store.get("A-0001")
    with pytest.raises(review.ReviewInvalid) as exc:
        review._evaluate(record, "a" * 64, frozenset({"founder@lakshyaa.ai"}))
    assert exc.value.reason == review.MALFORMED


def test_the_review_store_fails_closed_without_a_configured_spreadsheet(monkeypatch):
    # No REVIEW_SPREADSHEET_ID and no injected id -> the store refuses rather than touching the
    # leads Sheet (which the worker's founder OAuth could write). The gate therefore blocks.
    monkeypatch.delenv("REVIEW_SPREADSHEET_ID", raising=False)
    store = review.SheetReviewStore(api=Sheets({"Reviews": [HDR]}))  # no spreadsheet_id
    with pytest.raises(review.ReviewsUnavailable):
        store.get("A-0001")


def test_the_review_store_uses_the_configured_separate_spreadsheet(monkeypatch):
    monkeypatch.setenv("REVIEW_SPREADSHEET_ID", "reviews-sheet-123")
    store = review.SheetReviewStore(api=Sheets({"Reviews": [HDR]}))
    assert store._sid() == "reviews-sheet-123"  # the separate review spreadsheet, never the leads Sheet


def test_the_review_store_builds_its_client_as_the_service_account_not_the_founder_oauth(monkeypatch):
    # With no injected api, the store must build through sheet.review_api() (the service-account
    # client), never sheet._api() (the shared founder OAuth), so write-exclusivity holds.
    from outreach import sheet
    monkeypatch.setattr(sheet, "review_api", lambda: "SA-CLIENT")
    monkeypatch.setattr(sheet, "_api", lambda: pytest.fail("the review store used the founder OAuth client"))
    store = review.SheetReviewStore(spreadsheet_id="sid")  # no api injected
    assert store._service() == "SA-CLIENT"


def test_the_sheet_store_appends_a_row_and_confirms_it():
    api = Sheets({"Reviews": [HDR]})
    store = review.SheetReviewStore(api=api, spreadsheet_id="sid")
    record = review.record_confirmation(store, "A-0001", "founder@lakshyaa.ai", "b" * 64)
    assert api.appends == 1
    assert store.get("A-0001")["decision"] == "confirmed" and store.get("A-0001")["fingerprint"] == "b" * 64
    assert record["reviewed_at"]  # stored for the audit, not used for ordering


def test_the_sheet_store_blocks_a_write_when_the_tab_is_missing_and_never_creates_it():
    api = Sheets({"Reviews": None})
    store = review.SheetReviewStore(api=api, spreadsheet_id="sid")
    with pytest.raises(review.ReviewsUnavailable):
        review.record_confirmation(store, "A-0001", "founder@lakshyaa.ai", "b" * 64)
    assert api.tabs["Reviews"] is None and api.appends == 0  # nothing written, tab not created


def test_a_definite_write_failure_reports_nothing_recorded():
    api = Sheets({"Reviews": [HDR]}, write_error=True)  # request errored; the row is absent
    store = review.SheetReviewStore(api=api, spreadsheet_id="sid")
    with pytest.raises(review.ReviewsUnavailable) as exc:
        review.record_confirmation(store, "A-0001", "founder@lakshyaa.ai", "b" * 64)
    assert not isinstance(exc.value, review.ReviewsUncertain)  # definitely failed, not uncertain
    assert store.get("A-0001") is None


# --- the four failure modes the founder called out (each would be mis-handled before this fix) ---

def test_a_pre_existing_identical_row_does_not_mask_a_dropped_append():
    """An older row with EVERY original field identical - including the timestamp - must not confirm
    THIS append when it did not land. Only the unique Attempt ID distinguishes the attempted write,
    so reconciliation cannot lean on any other field."""
    from datetime import datetime, timezone
    when = datetime(2026, 9, 30, 12, 0, tzinfo=timezone.utc)
    # the existing row and the new attempt share review id, fingerprint, reviewer, decision AND
    # reviewed_at; they differ only by Attempt ID.
    existing = srow("A-0001", "b" * 64, "confirmed", when.isoformat(),
                    attempt="the-old-attempt-id", reviewer="founder@lakshyaa.ai")
    api = Sheets({"Reviews": [HDR, existing]}, drop_write=True)  # this append does not persist
    store = review.SheetReviewStore(api=api, spreadsheet_id="sid")
    with pytest.raises(review.ReviewsUncertain):
        review.record_confirmation(store, "A-0001", "founder@lakshyaa.ai", "b" * 64, now=when)
    # only the pre-existing row is there; the dropped append was NOT confirmed by it
    assert [r for r in api.tabs["Reviews"][1:]] == [existing]


def test_a_committed_append_whose_response_failed_is_recorded_not_lost():
    api = Sheets({"Reviews": [HDR]}, commit_then_error=True)  # row written, response errored
    store = review.SheetReviewStore(api=api, spreadsheet_id="sid")
    record = review.record_confirmation(store, "A-0001", "founder@lakshyaa.ai", "b" * 64)
    assert record["decision"] == "confirmed"  # reconciled by attempt id, reported accurately
    assert store.get("A-0001")["fingerprint"] == "b" * 64


def test_an_unreadable_reconciliation_is_reported_as_uncertain():
    api = Sheets({"Reviews": [HDR]}, fail_read_after_write=True)  # append lands, re-read fails
    store = review.SheetReviewStore(api=api, spreadsheet_id="sid")
    with pytest.raises(review.ReviewsUncertain):
        review.record_confirmation(store, "A-0001", "founder@lakshyaa.ai", "b" * 64)


def test_a_concurrent_later_rejection_is_not_reported_as_approval():
    api = Sheets({"Reviews": [HDR]})
    store = review.SheetReviewStore(api=api, spreadsheet_id="sid")
    reviewers = frozenset({"founder@lakshyaa.ai"})
    review.record_confirmation(store, "A-0001", "founder@lakshyaa.ai", fingerprint())  # succeeds
    review.record_rejection(store, "A-0001", "founder@lakshyaa.ai", fingerprint())  # later row wins
    assert store.get("A-0001")["decision"] == "rejected"
    assert review.is_reviewed(store, "A-0001", fingerprint(), reviewers=reviewers) is False


def test_the_sheet_store_enforces_end_to_end_through_the_gate():
    api = Sheets({"Reviews": [HDR]})
    store = review.SheetReviewStore(api=api, spreadsheet_id="sid")
    reviewers = frozenset({"founder@lakshyaa.ai"})
    # no review -> blocks
    assert review.is_reviewed(store, "A-0001", fingerprint(), reviewers=reviewers) is False
    review.record_confirmation(store, "A-0001", "founder@lakshyaa.ai", fingerprint())
    assert review.is_reviewed(store, "A-0001", fingerprint(), reviewers=reviewers) is True
    # a later rejection supersedes it
    review.record_rejection(store, "A-0001", "founder@lakshyaa.ai", fingerprint())
    assert review.is_reviewed(store, "A-0001", fingerprint(), reviewers=reviewers) is False


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


# --- item 5: revocation and concurrency -----------------------------------------------------

def test_a_later_rejection_supersedes_an_earlier_confirmation_of_the_same_candidate():
    store = review.MemoryReviewStore()
    review.record_confirmation(store, "A-0001", "founder@lakshyaa.ai", fingerprint())
    review.record_rejection(store, "A-0001", "founder@lakshyaa.ai", fingerprint())  # same fingerprint
    with pytest.raises(review.ReviewInvalid) as exc:
        review.enforce(preview(), None, settings(), store=store)
    assert exc.value.reason == review.REJECTED_REASON


def test_a_later_confirmation_supersedes_an_earlier_rejection():
    store = review.MemoryReviewStore()
    review.record_rejection(store, "A-0001", "founder@lakshyaa.ai", fingerprint())
    review.record_confirmation(store, "A-0001", "founder@lakshyaa.ai", fingerprint())
    assert review.enforce(preview(), None, settings(), store=store) == fingerprint()


def test_duplicate_confirmations_are_idempotent():
    store = review.MemoryReviewStore()
    review.record_confirmation(store, "A-0001", "founder@lakshyaa.ai", fingerprint())
    review.record_confirmation(store, "A-0001", "founder@lakshyaa.ai", fingerprint())
    assert review.enforce(preview(), None, settings(), store=store) == fingerprint()


def test_a_confirmation_of_an_old_candidate_does_not_admit_a_new_one():
    """An edit between display and action: the confirmation is for the earlier fingerprint, so the
    changed candidate is stale and blocked (the action boundary rechecks)."""
    store = review.MemoryReviewStore()
    review.record_confirmation(store, "A-0001", "founder@lakshyaa.ai", fingerprint())
    changed = preview(subject="An edited subject after the review")
    with pytest.raises(review.ReviewInvalid) as exc:
        review.enforce(changed, None, settings(), store=store)
    assert exc.value.reason == review.STALE
