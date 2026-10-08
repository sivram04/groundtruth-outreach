"""The written pipeline end to end, offline: Drive handbook -> Gemini -> checks -> approval.

Nothing here touches Google. Every path that could put an unapproved or unsupported email in
front of a recipient must fail closed.
"""

from pathlib import Path

import pytest

import review_fixtures as rf
from outreach import calls, drafting, gmail_drafts, handbook_drive, job_draft, review, sheet, worker, writer
from outreach.review_identity import Signer
from outreach.sheet import CALLS_HEADER


def _stub_sheet_projects(monkeypatch):
    """The worker draft routes read projects from the Sheet; in a unit test there is no Sheet, so give
    them a dummy api and an empty projects map (a single-project default is applied downstream)."""
    monkeypatch.setattr(sheet, "_api", lambda: object())
    monkeypatch.setattr(sheet, "Store", lambda api: type("S", (), {"projects": lambda self, s=None: {}})())
from test_sheet_append import FakeSheets

# The genuine call-log reader, captured before `ready` patches it to CONTINUE, so the call-gate tests
# can restore it and read synthetic persisted call events through the real code.
_REAL_CALL_EFFECT = job_draft._call_effect
CALL_NOW = __import__("datetime").datetime(2026, 9, 28, 13, 0, tzinfo=__import__("datetime").timezone.utc)

HANDBOOK_TEXT = (Path(__file__).resolve().parent.parent / "examples" / "synthetic_handbook.txt"
                 ).read_text(encoding="utf-8")
BOOK = {"text": HANDBOOK_TEXT, "content_hash": "hash-one", "document_id": "doc-one",
        "name": "Handbook", "version": "1", "modified": "2026-09-22T10:00:00Z", "source": "drive"}
QUOTE = "We install electrical distribution systems for commercial buildings."
SITE = "Example Electric is an electrical contractor. " + QUOTE
URL = "https://example.test/services"


def lead(**changes):
    row = {"Lead ID": "A-0001", "Company": "Example Electric", "BEST EMAIL": "sam@example.test",
           "Their email": "sam@example.test", "Decision maker": "Sam Rivers",
           "Website": "https://example.test/", "Email check": "OK", "Fit": "QUALIFIED",
           "Profile status": "READY", "Profiled at": "2026-09-22 12:00:00",
           "Offerings evidence": f'"{QUOTE}" ({URL})'}
    row.update(changes)
    return row


def facts():
    return [{"Lead ID": "A-0001", "Researched at": "2026-09-22 12:00:00", "Category": "OFFERING",
             "Quote": QUOTE, "Page URL": URL}]


def settings(**changes):
    config = {"product_name": "Example Product", "sender_name": "A Founder",
              "founder_title": "Founder", "sender_website": "https://example.test",
              "postal_address": "1 Example St, Columbus, OH 43215", "sender_phone": "614-555-0100",
              "sender_email": "admin@lakshyaa.ai", "daily_cap": 4, "offer_approved": True,
              "version": "prelaunch-v1", "handbook_doc_id": "1AbCdEfGhIjKlMnOpQrStUvWxYz01234",
              "intended_use": "an early preview", "next_week_action": "a short call",
              "cta_question": "Would next week work?", "review_reviewers": ["admin@lakshyaa.ai"],
              "review_public_key": rf.PUBLIC_KEY_B64}  # the trusted verifier key for the signed gate
    config.update(changes)
    return config


def quote_id(row=None):
    options = drafting.opening_options(drafting.supported_quotes(row or lead(), facts()),
                                       "Example Electric")
    return options[0]["quote_id"]


def model_for(company_text=None, subject="A conversation about Example Product next week"):
    def model(prompt, schema):
        return {"subject": subject, "sentences": [
            {"text": company_text or ("I noticed Example Electric installs electrical distribution "
                                      "systems for commercial buildings."),
             "kind": "COMPANY", "quote_id": quote_id()},
            {"text": "I'm building Example Product, a cash-flow decision tool for construction "
                     "subcontractors. The MVP is still being finished.",
             "kind": "PRODUCT", "quote_id": ""},
            {"text": "Would you be open to a twenty minute conversation next week about the early "
                     "preview?", "kind": "ASK", "quote_id": ""},
        ]}, {"promptTokenCount": 10}
    return model


def _compose(row=None, *, book=BOOK, model=None, config=None, suppressed=False, review_store):
    row = row or lead()
    return job_draft.previews(["A-0001"], settings=config or settings(), write=True,
                              handbook=book, model=model or model_for(), review_store=review_store,
                              fixture={"leads": [row], "research": facts(), "pages": SITE,
                                       "suppressed": {"A-0001": suppressed}})[0]


def confirmed_store(row=None, *, book=BOOK, model=None, config=None, reviewer="admin@lakshyaa.ai"):
    """A store holding a SIGNED confirmation of the standard candidate for `row` (composed once,
    unreviewed, to get its fingerprint), the way the console would record it."""
    bare = _compose(row, book=book, model=model, config=config, review_store=review.MemoryReviewStore())
    store = review.MemoryReviewStore()
    rf.confirm(store, bare["lead_id"], reviewer,
               review.candidate_fingerprint(bare, book, config or settings()))
    return store


def preview(row=None, *, book=BOOK, model=None, config=None, suppressed=False,
            review_store=None, reviewed=True):
    """A composed preview. Reviewed by default (a confirmed review lets the approval hash mint);
    pass reviewed=False to see an unreviewed candidate (words, but no approval hash)."""
    if review_store is None:
        review_store = (confirmed_store(row, book=book, model=model, config=config)
                        if reviewed else review.MemoryReviewStore())
    return _compose(row, book=book, model=model, config=config, suppressed=suppressed,
                    review_store=review_store)


# --- the good path ------------------------------------------------------------------------

def test_a_review_flagged_claim_yields_no_approval_hash_through_the_whole_pipeline():
    """Enforcement, end to end: a company sentence the validator holds for review (work credited to
    a subcontractor under the company's own name) produces NO preview_hash from the full
    write->verify->assemble path, even with offer_approved=True. Review is a real gate on the
    approval hash, not just a verify() return value."""
    delegation = ("Example Electric's subcontractors install electrical distribution systems for "
                  "commercial buildings.")
    out = preview(model=model_for(company_text=delegation))
    assert out["preview_hash"] is None
    assert any(writer.REVIEW_PREFIX in b for b in out["blockers"])


def test_a_written_preview_is_approvable_and_carries_its_sources():
    out = preview()
    assert out["blockers"] == [] and out["preview_hash"]
    assert out["handbook_hash"] == "hash-one"
    assert out["evidence"]["quote"] == QUOTE and out["evidence"]["url"] == URL
    assert out["body"].startswith("Hi Sam,") and out["body"].endswith(drafting.OPT_OUT)
    assert "1 Example St" in out["body"] and "614-555-0100" in out["body"]
    assert out["written"]["sentences"] and "usage" not in out["written"]


# --- no approval hash before review (the hash-producing path is gated) ----------------------

def test_no_approval_hash_is_issued_before_review_but_the_words_are_kept():
    """An otherwise-approvable candidate with no valid review carries NO approval hash - it is held
    for a person to review, with its words intact so they can be read."""
    out = preview(reviewed=False)
    assert out["preview_hash"] is None
    assert review.AWAITING_BLOCKER in out["blockers"]
    assert out["written"]["sentences"] and out["body"].startswith("Hi Sam,")


def test_a_confirmed_review_lets_the_approval_hash_mint():
    out = preview()  # reviewed=True
    assert out["preview_hash"] and review.AWAITING_BLOCKER not in out["blockers"]


def test_the_default_hash_path_is_fail_closed_without_a_review():
    """With no store injected, written_preview uses the fail-closed production store, so no approval
    hash is issued."""
    out = _compose(review_store=review.default_store())
    assert out["preview_hash"] is None and review.AWAITING_BLOCKER in out["blockers"]


def test_no_verifier_configured_issues_no_hash():
    """Missing verification configuration (no trusted public key) blocks approval-hash issuance; the
    deployable path never falls back to unsigned review."""
    no_key = settings()
    no_key.pop("review_public_key")
    out = _compose(config=no_key, review_store=confirmed_store())
    assert out["preview_hash"] is None and review.UNVERIFIABLE_BLOCKER in out["blockers"]


def test_an_edit_after_review_stops_the_hash_being_reissued():
    """A review confirmed for one candidate does not carry over to an edited one: the approval hash
    is not reissued for the changed candidate (a stale review does not mint a hash)."""
    store = confirmed_store()  # confirms the standard candidate under the default settings
    out = _compose(config=settings(intended_use="a much longer paid pilot than described"),
                   review_store=store)
    assert out["preview_hash"] is None and review.AWAITING_BLOCKER in out["blockers"]


def _template_preview(review_store, row=None):
    """The template (write=False) path a CLI run takes, which does not load the Drive handbook."""
    return job_draft.previews(["A-0001"], settings=settings(), write=False, review_store=review_store,
                              fixture={"leads": [row or lead()], "research": facts(),
                                       "suppressed": {"A-0001": False}})[0]


def test_the_template_cli_path_exposes_no_approval_hash_without_a_review():
    """The lower-level producer's digest must not be exposed as an approval hash on the template
    (write=False) path either - the path the `job_draft` CLI takes by default."""
    out = _template_preview(review.MemoryReviewStore())
    assert out["preview_hash"] is None and review.AWAITING_BLOCKER in out["blockers"]


def test_a_reviewed_template_candidate_can_carry_a_hash_but_create_refuses_to_use_it(monkeypatch):
    """It is the review gate, not a blanket disable: a confirmed review lets the template digest
    become a hash. But that hash is not an actionable approval token - create refuses a template
    (non-written) draft, so no consumer can USE it."""
    monkeypatch.setenv("ENABLE_GMAIL_DRAFTS", "true")
    bare = _template_preview(review.MemoryReviewStore())  # unreviewed: content present, no hash
    store = review.MemoryReviewStore()
    rf.confirm(store, bare["lead_id"], "admin@lakshyaa.ai",
               review.candidate_fingerprint(bare, None, settings()))
    reviewed = _template_preview(store)
    assert reviewed["preview_hash"]  # gated on review, not disabled
    # ...but create will not act on a template hash (it requires a Drive-handbook written draft).
    with pytest.raises(job_draft.DraftBlocked, match="Drive-handbook written draft"):
        job_draft.create("A-0001", reviewed["preview_hash"], written=None, settings=settings(),
                         api=object(), gmail=Mailbox(), handbook=BOOK, pages=SITE,
                         review_store=store)


# --- the handbook is the only source, and it must be readable ------------------------------

def test_a_role_inbox_keeps_a_neutral_greeting():
    out = preview(lead(**{"BEST EMAIL": "office@example.test", "Their email": "office@example.test"}))
    assert out["body"].startswith("Hi there,") and out["preview_hash"]


def test_no_handbook_means_no_preview(monkeypatch):
    monkeypatch.delenv("HANDBOOK_DOC_ID", raising=False)
    out = job_draft.previews(["A-0001"], settings=settings(handbook_doc_id=""), write=True,
                             model=model_for(),
                             fixture={"leads": [lead()], "research": facts(),
                                      "suppressed": {"A-0001": False}})[0]
    assert out["preview_hash"] is None and out["body"] == ""
    assert any("handbook unavailable" in b for b in out["blockers"])


def test_an_unreadable_drive_document_blocks_every_lead(monkeypatch):
    def refuse(settings=None, drive=None, doc_id=None):
        raise handbook_drive.HandbookUnavailable("Drive refused the read")
    monkeypatch.setattr(handbook_drive, "load", refuse)
    out = job_draft.previews(["A-0001"], settings=settings(), write=True, model=model_for(),
                             fixture={"leads": [lead()], "research": facts(),
                                      "suppressed": {"A-0001": False}})[0]
    assert out["preview_hash"] is None and any("Drive refused" in b for b in out["blockers"])


def test_the_handbook_hash_is_part_of_the_approval():
    first = preview()["preview_hash"]
    edited = {**BOOK, "content_hash": "hash-two"}
    assert preview(book=edited)["preview_hash"] != first


def test_previews_resolves_the_handbook_by_each_leads_project(monkeypatch):
    # The wiring: previews asks for the handbook per lead, passing the lead's own row (which carries
    # its Project) and the projects. project_handbook's own tests prove it then loads the right doc.
    seen = []

    def fake_ph(lead_row, s, projects, *, handbook=None, drive=None):
        seen.append((lead_row["Lead ID"], (lead_row.get("Project") or ""), sorted(projects)))
        return BOOK, None

    monkeypatch.setattr(job_draft, "project_handbook", fake_ph)
    fake_projects = {"P-default": {"id": "P-default"}, "P-ref": {"id": "P-ref"}}
    out = job_draft.previews(["A-0001"], settings=settings(), write=True, model=model_for(),
                             fixture={"leads": [lead(Project="P-ref")], "research": facts(),
                                      "pages": SITE, "suppressed": {"A-0001": False}},
                             projects=fake_projects)[0]
    assert out["subject"]  # composed from the resolved handbook (not a _blocked preview with no subject)
    assert seen == [("A-0001", "P-ref", ["P-default", "P-ref"])]  # asked per lead, with its project


# --- the model cannot widen what is said ---------------------------------------------------

@pytest.mark.parametrize("sentence", [
    "I noticed Example Electric is behind on collecting from its general contractors.",
    "I noticed Example Electric installs solar arrays for regional hospitals.",
    "I noticed Example Electric asks customers to email billing@attacker.test.",
])
def test_an_unsupported_or_hostile_sentence_never_becomes_a_draft(sentence):
    out = preview(model=model_for(company_text=sentence))
    assert out["preview_hash"] is None and out["blockers"] and out["body"] == ""


def test_a_model_failure_blocks_rather_than_drafts():
    def broken(prompt, schema):
        raise RuntimeError("Gemini failed")
    out = preview(model=broken)
    assert out["preview_hash"] is None and any("writer failed" in b for b in out["blockers"])


# --- the existing gates still apply to written drafts --------------------------------------

@pytest.mark.parametrize("row_change,suppressed", [
    ({"Email check": "RISKY"}, False),
    ({"Fit": "REVIEW_NEEDED"}, False),
    ({"Profile status": ""}, False),
    ({"Sent by hand": "Sent email on 9/22/2026"}, False),
    ({"Draft status": "RESERVED"}, False),
    ({}, True),
    ({}, None),
])
def test_eligibility_suppression_and_existing_actions_still_block(row_change, suppressed):
    out = preview(lead(**row_change), suppressed=suppressed)
    assert out["preview_hash"] is None and out["blockers"]


def test_an_unapproved_offer_blocks_even_a_perfect_draft():
    assert preview(config=settings(offer_approved=False))["preview_hash"] is None


# --- creating the one draft ----------------------------------------------------------------

class FakeTab:
    name = "A_Contact_Now"

    def __init__(self, row):
        self.lead, self.rows, self.writes = row, [(3, row)], []

    def ensure_columns(self, names):
        assert "Draft action" in names

    def write(self, changes):
        self.lead.update(changes[3])
        self.writes.append(changes[3])
        return {"written": 1, "skipped": []}


class Mailbox:
    def users(self):
        return self

    def getProfile(self, **kwargs):
        return self

    def execute(self):
        return {"emailAddress": "admin@lakshyaa.ai"}


@pytest.fixture
def ready(monkeypatch):
    monkeypatch.setenv("ENABLE_GMAIL_DRAFTS", "true")
    row = lead()
    tab = FakeTab(row)
    monkeypatch.setattr(job_draft, "_read", lambda api, ids: ([tab], [(tab, 3, row)], facts()))
    monkeypatch.setattr(job_draft, "_suppressed", lambda api, email: False)
    # By default no call decision restricts this lead; the call-gate tests restore the real reader.
    monkeypatch.setattr(job_draft, "_call_effect", lambda api, lead_id: calls.CONTINUE)
    monkeypatch.setattr(gmail_drafts, "prior_sends", lambda gmail, recipient: False)
    monkeypatch.setattr(gmail_drafts, "existing_drafts", lambda gmail, recipient: [])
    monkeypatch.setattr(job_draft, "Tab", lambda api, name, cols: tab)
    # The candidate is confirmed by an authorized human, so the happy path clears the review gate.
    # Built once here (the model is available now); the review-gate tests override the store.
    store = confirmed_store(row)
    monkeypatch.setattr(review, "default_store", lambda: store)
    created = []
    monkeypatch.setattr(gmail_drafts, "create",
                        lambda gmail, **kw: created.append(kw) or {"id": "draft-1"})
    return row, tab, created


def approved_written(row=None):
    out = preview(row)
    return out["written"], out["preview_hash"]


def test_one_approved_written_draft_reaches_gmail_once(ready):
    row, tab, created = ready
    written, digest = approved_written(row)
    result = job_draft.create("A-0001", digest, written=written, settings=settings(),
                              api=object(), gmail=Mailbox(), handbook=BOOK, pages=SITE)
    assert result["status"] == "CREATED" and len(created) == 1
    assert created[0]["to"] == "sam@example.test" and created[0]["body"].endswith(drafting.OPT_OUT)
    assert tab.lead["Draft status"] == "CREATED" and tab.lead["Draft hash"] == digest


# --- the editable "approve and send": the founder's OWN words, no grounding/review gate ------------

def test_create_edited_sends_the_founders_own_words(ready):
    row, tab, created = ready
    result = job_draft.create_edited(
        "A-0001", "A quick question", "Hi Sam,\n\nI wrote this myself.\n\nBest,",
        approver="admin@lakshyaa.ai", settings=settings(), api=object(), gmail=Mailbox())
    assert result["status"] == "CREATED" and len(created) == 1
    assert created[0]["to"] == "sam@example.test"
    assert created[0]["subject"] == "A quick question"
    assert "I wrote this myself." in created[0]["body"]
    assert created[0]["body"].endswith(drafting.OPT_OUT)  # opt-out kept on every send
    assert tab.lead["Draft status"] == "CREATED" and tab.lead["Draft ID"]


def test_create_edited_restores_the_opt_out_if_it_was_removed(ready):
    row, tab, created = ready
    job_draft.create_edited("A-0001", "Hello", "Just my words, no opt-out line.",
                            approver="admin@lakshyaa.ai", settings=settings(), api=object(), gmail=Mailbox())
    assert created[0]["body"].endswith(drafting.OPT_OUT)


def test_create_edited_refuses_an_empty_subject_or_body(ready):
    for subject, body in [("", "a body"), ("a subject", "   ")]:
        with pytest.raises(job_draft.DraftBlocked):
            job_draft.create_edited("A-0001", subject, body, approver="admin@lakshyaa.ai",
                                    settings=settings(), api=object(), gmail=Mailbox())


def test_create_edited_needs_an_approver(ready):
    with pytest.raises(job_draft.DraftBlocked):
        job_draft.create_edited("A-0001", "Hi", "words", approver="",
                                settings=settings(), api=object(), gmail=Mailbox())


# --- a recorded call decision blocks initial Gmail draft creation (the real write boundary) --------
# drafts.plan is candidate selection; job_draft.create is the only path that turns an approved candidate
# into a Gmail draft (the worker create route calls it). So the call-decision gate must live here too, or
# a candidate approved BEFORE a later do-not-contact / interested / callback would still be drafted. The
# call log is re-read here through the real reader, from synthetic persisted events.

def _call_log_row(outcome, **kw):
    event = calls.outcome_event("A-0001", outcome, kw.get("note", ""), "2026-09-28T13:00:00+00:00",
                                no_answer_business_days=3, callback_at=kw.get("callback_at"),
                                now=CALL_NOW)
    return [event.get(h, "") for h in CALLS_HEADER]


def _create_with_call_log(monkeypatch, seed):
    """Run job_draft.create with a valid approved candidate and a FakeSheets whose Call log `seed`
    (a list of value rows, or None for no tab) the REAL _call_effect reads. Returns (created, api)."""
    row, _tab, created = ready.__wrapped__(monkeypatch)
    monkeypatch.setattr(job_draft, "_call_effect", _REAL_CALL_EFFECT)  # use the genuine reader
    api = FakeSheets()
    if seed is not None:
        api.tabs["Call log"] = [list(CALLS_HEADER), *seed]
    written, digest = approved_written(row)
    return created, api, written, digest


def test_a_recorded_do_not_contact_blocks_initial_draft_creation(monkeypatch):
    # No suppression entry is seeded (the redundant write may have failed); the call event alone blocks.
    created, api, written, digest = _create_with_call_log(monkeypatch,
                                                          [_call_log_row(calls.DO_NOT_CONTACT, note="stop")])
    with pytest.raises(job_draft.DraftBlocked, match="recorded call outcome"):
        job_draft.create("A-0001", digest, written=written, settings=settings(),
                         api=api, gmail=Mailbox(), handbook=BOOK, pages=SITE)
    assert created == []  # no Gmail draft was created, and no reservation was attempted


def test_a_callback_hold_blocks_initial_draft_creation(monkeypatch):
    created, api, written, digest = _create_with_call_log(
        monkeypatch, [_call_log_row(calls.CALLBACK, callback_at="2026-10-02T14:00:00+00:00")])
    with pytest.raises(job_draft.DraftBlocked, match="recorded call outcome"):
        job_draft.create("A-0001", digest, written=written, settings=settings(),
                         api=api, gmail=Mailbox(), handbook=BOOK, pages=SITE)
    assert created == []


def test_unreadable_call_history_blocks_initial_draft_creation(monkeypatch):
    # A Call log tab whose columns were changed cannot be read: fail closed, never draft.
    created, api, written, digest = _create_with_call_log(monkeypatch, seed=[])
    api.tabs["Call log"] = [["Something", "Else"], ["x", "y"]]  # wrong header
    with pytest.raises(job_draft.DraftBlocked, match="call log"):
        job_draft.create("A-0001", digest, written=written, settings=settings(),
                         api=api, gmail=Mailbox(), handbook=BOOK, pages=SITE)
    assert created == []


def test_a_lead_with_no_call_history_still_drafts(monkeypatch):
    # The gate must not block a lead that simply has no call decisions (no Call log tab): eligible passes.
    created, api, written, digest = _create_with_call_log(monkeypatch, seed=None)
    result = job_draft.create("A-0001", digest, written=written, settings=settings(),
                              api=api, gmail=Mailbox(), handbook=BOOK, pages=SITE)
    assert result["status"] == "CREATED" and len(created) == 1


def test_a_valid_call_log_header_with_no_events_still_drafts(monkeypatch):
    # A present Call log with its header but no event rows is "no call history", not a block.
    created, api, written, digest = _create_with_call_log(monkeypatch, seed=[])  # header only
    result = job_draft.create("A-0001", digest, written=written, settings=settings(),
                              api=api, gmail=Mailbox(), handbook=BOOK, pages=SITE)
    assert result["status"] == "CREATED" and len(created) == 1


def test_a_present_call_log_without_its_header_blocks_drafting(monkeypatch):
    # An existing Call log tab that carries no required header is unreadable: block (align with
    # sheet.Store.call_events, which refuses the same case), never draft.
    created, api, written, digest = _create_with_call_log(monkeypatch, seed=[])
    api.tabs["Call log"] = []  # the tab exists but has no header row at all
    with pytest.raises(job_draft.DraftBlocked, match="call log"):
        job_draft.create("A-0001", digest, written=written, settings=settings(),
                         api=api, gmail=Mailbox(), handbook=BOOK, pages=SITE)
    assert created == []


# --- the human evidence-review gate (acceptance-contract option B) --------------------------
# The word-overlap validator cannot certify that a claim is faithful; the two measured false
# accepts prove it. So no approved draft may become a Gmail draft without a valid, current,
# confirmed human review of THIS exact candidate. The gate lives in job_draft.create (the only
# path to a Gmail draft, and the one the HTTP create route calls), rechecked at the action
# boundary, so a direct API call cannot bypass it.

class HistoryStore:
    """A store exposing a fixed history for the gate's signed-chain resolution."""

    def __init__(self, records):
        self._records = list(records)

    def get(self, lead_id):
        return self._records[-1] if self._records else None

    def history(self, lead_id):
        return list(self._records)

    def put(self, record):
        raise AssertionError("the gate must never write")


class BrokenStore:
    def get(self, lead_id):
        raise RuntimeError("the review store is unreachable")

    def history(self, lead_id):
        raise RuntimeError("the review store is unreachable")

    def put(self, record):
        raise AssertionError("the gate must never write")


def _signed_root(fingerprint, decision, at, *, signer=rf.SIGNER, reviewer="admin@lakshyaa.ai"):
    """A signed decision at the root of a chain (prev="")."""
    sig = signer.sign(review_id="A-0001", prev="", fingerprint=fingerprint, reviewer=reviewer,
                      decision=decision, reviewed_at=at)
    return {"lead_id": "A-0001", "prev": "", "fingerprint": fingerprint, "reviewer": reviewer,
            "decision": decision, "reviewed_at": at, "signature": sig}


def _blocks(row, store, config=None, match="review"):
    written, digest = approved_written(row)
    with pytest.raises(job_draft.DraftBlocked, match=match):
        job_draft.create("A-0001", digest, written=written, settings=config or settings(),
                         api=object(), gmail=Mailbox(), handbook=BOOK, pages=SITE, review_store=store)


def test_no_confirmed_review_blocks_even_a_perfect_approved_draft(ready):
    row, _, created = ready
    _blocks(row, review.MemoryReviewStore(), match="REVIEW_MISSING")
    assert created == []


def test_the_default_review_store_is_fail_closed(monkeypatch):
    """With no store injected, create uses the unmigrated production store, which finds no review
    and blocks. Sending is disabled anyway, but the content gate is real without it."""
    monkeypatch.setenv("ENABLE_GMAIL_DRAFTS", "true")
    row = lead()
    tab = FakeTab(row)
    monkeypatch.setattr(job_draft, "_read", lambda api, ids: ([tab], [(tab, 3, row)], facts()))
    monkeypatch.setattr(job_draft, "_suppressed", lambda api, email: False)
    # By default no call decision restricts this lead; the call-gate tests restore the real reader.
    monkeypatch.setattr(job_draft, "_call_effect", lambda api, lead_id: calls.CONTINUE)
    monkeypatch.setattr(gmail_drafts, "prior_sends", lambda gmail, recipient: False)
    monkeypatch.setattr(gmail_drafts, "existing_drafts", lambda gmail, recipient: [])
    monkeypatch.setattr(job_draft, "Tab", lambda api, name, cols: tab)
    created = []
    monkeypatch.setattr(gmail_drafts, "create",
                        lambda gmail, **kw: created.append(kw) or {"id": "draft-1"})
    written, digest = approved_written(row)
    with pytest.raises(job_draft.DraftBlocked, match="REVIEW_MISSING"):
        job_draft.create("A-0001", digest, written=written, settings=settings(),
                         api=object(), gmail=Mailbox(), handbook=BOOK, pages=SITE)
    assert created == []


def test_no_verifier_configured_blocks_create(ready):
    """Missing verification configuration blocks draft creation; no unsigned fallback."""
    row, _, created = ready
    no_key = settings()
    no_key.pop("review_public_key")
    _blocks(row, confirmed_store(), config=no_key, match="verification is not configured")
    assert created == []


def test_a_signed_rejection_blocks(ready):
    row, _, created = ready
    store = review.MemoryReviewStore()
    rf.reject(store, "A-0001", "admin@lakshyaa.ai",
              review.candidate_fingerprint(preview(row), BOOK, settings()))
    _blocks(row, store, match="REVIEW_REJECTED")
    assert created == []


def test_a_signed_review_of_a_different_candidate_is_stale(ready):
    row, _, created = ready
    store = review.MemoryReviewStore()
    rf.confirm(store, "A-0001", "admin@lakshyaa.ai", "a" * 64)  # a different candidate's fingerprint
    _blocks(row, store, match="REVIEW_STALE")
    assert created == []


def test_an_offer_edit_between_review_and_action_invalidates_the_review(ready):
    """A confirmed review, then an offer setting changes before the action: the candidate no
    longer matches the fingerprint reviewed, so the draft is blocked (rechecked at the boundary)."""
    row, _, created = ready
    written, digest = approved_written(row)  # reviewed under the standard settings (via `ready`)
    with pytest.raises(job_draft.DraftBlocked, match="REVIEW_STALE"):
        job_draft.create("A-0001", digest, written=written,
                         settings=settings(intended_use="a much longer paid pilot than described"),
                         api=object(), gmail=Mailbox(), handbook=BOOK, pages=SITE)
    assert created == []


def test_a_signed_review_by_a_non_human_reviewer_is_rejected(ready):
    row, _, created = ready
    store = review.MemoryReviewStore()
    rf.confirm(store, "A-0001", "model@service.internal",
               review.candidate_fingerprint(preview(row), BOOK, settings()))
    _blocks(row, store, match="REVIEW_NOT_HUMAN")
    assert created == []


def test_an_unsigned_record_blocks(ready):
    row, _, created = ready
    store = review.MemoryReviewStore()
    review.record_confirmation(store, "A-0001", "admin@lakshyaa.ai",  # no signer -> unsigned
                               review.candidate_fingerprint(preview(row), BOOK, settings()))
    _blocks(row, store, match="REVIEW_TAMPERED")
    assert created == []


def test_a_record_signed_by_the_wrong_key_blocks(ready):
    row, _, created = ready
    store = review.MemoryReviewStore()
    other = Signer.generate()  # a key the configured verifier does not trust
    review.record_confirmation(store, "A-0001", "admin@lakshyaa.ai",
                               review.candidate_fingerprint(preview(row), BOOK, settings()),
                               signer=other)
    _blocks(row, store, match="REVIEW_TAMPERED")
    assert created == []


def test_a_conflicting_history_blocks(ready):
    row, _, created = ready
    fingerprint = review.candidate_fingerprint(preview(row), BOOK, settings())
    store = HistoryStore([_signed_root(fingerprint, "confirmed", "t1"),
                          _signed_root(fingerprint, "rejected", "t2")])  # two roots -> conflict
    _blocks(row, store, match="REVIEW_CONFLICT")
    assert created == []


def test_an_unreadable_review_store_blocks(ready):
    row, _, created = ready
    _blocks(row, BrokenStore(), match="REVIEW_UNREADABLE")
    assert created == []


def test_create_consults_the_review_gate_so_removing_it_would_be_caught(ready, monkeypatch):
    """If the enforce call were deleted from create, this and the no-review test would fail."""
    row, _, created = ready
    written, digest = approved_written(row)
    monkeypatch.setattr(review, "enforce",
                        lambda *a, **k: (_ for _ in ()).throw(
                            review.ReviewInvalid(review.MISSING, "gate reached")))
    with pytest.raises(job_draft.DraftBlocked, match="review"):
        job_draft.create("A-0001", digest, written=written, settings=settings(),
                         api=object(), gmail=Mailbox(), handbook=BOOK, pages=SITE)
    assert created == []


def test_the_worker_create_route_goes_through_the_gated_create(monkeypatch):
    """The HTTP create surface funnels through job_draft.create (where the gate lives), so it
    cannot bypass review; here the gated create refuses and the route surfaces the refusal."""
    monkeypatch.setenv("ENABLE_GMAIL_DRAFTS", "true")
    _stub_sheet_projects(monkeypatch)
    seen = {}

    def spy(lead_id, approved_hash, *, written=None, **kwargs):
        seen.update(lead_id=lead_id, approved_hash=approved_hash, written=written)
        raise job_draft.DraftBlocked("human evidence review required (REVIEW_MISSING): none")
    monkeypatch.setattr(job_draft, "create", spy)
    response = worker.app.test_client().post(
        "/jobs/draft/create",
        json={"lead_id": "A-0001", "approved_hash": "h", "written": {"sentences": [{}]}})
    assert seen == {"lead_id": "A-0001", "approved_hash": "h", "written": {"sentences": [{}]}}
    assert response.status_code == 400 and "review" in response.get_json()["error"]


# --- concurrency: the recheck narrows the window; it does not make the action atomic ----------

def test_the_created_draft_is_exactly_the_candidate_that_was_reviewed(ready):
    """The action uses the exact `result` the recheck validated - no re-derivation between the
    review recheck and the Gmail write - so the draft created is the reviewed candidate."""
    row, _, created = ready
    approved = preview(row)
    job_draft.create("A-0001", approved["preview_hash"], written=approved["written"],
                     settings=settings(), api=object(), gmail=Mailbox(), handbook=BOOK, pages=SITE)
    assert created[0]["to"] == approved["to"]
    assert created[0]["subject"] == approved["subject"]
    assert created[0]["body"] == approved["body"]


def test_a_revocation_before_the_recheck_is_caught(ready, monkeypatch):
    """A rejection that lands before the final recheck (here, during the prior-sends check) is
    caught: the recheck is the last gate before any write."""
    row, _, created = ready
    written, digest = approved_written(row)
    store = review.default_store()  # the confirmed store the fixture installed
    fingerprint = review.candidate_fingerprint(preview(row), BOOK, settings())

    def reject_first(gmail, recipient):
        rf.reject(store, "A-0001", "admin@lakshyaa.ai", fingerprint)  # signed, chained rejection
        return False
    monkeypatch.setattr(gmail_drafts, "prior_sends", reject_first)
    with pytest.raises(job_draft.DraftBlocked, match="REVIEW_REJECTED"):
        job_draft.create("A-0001", digest, written=written, settings=settings(),
                         api=object(), gmail=Mailbox(), handbook=BOOK, pages=SITE)
    assert created == []


def test_a_revocation_after_the_recheck_is_not_caught_the_window_is_not_closed(ready, monkeypatch):
    """Honest limitation: the recheck is not atomic with the Gmail write. A rejection landing
    after the recheck (here, at the moment of the write) is not seen. The window is small (the
    reservation write plus the create call) and drafting is disabled, but it is not zero."""
    row, _, created = ready
    written, digest = approved_written(row)
    store = review.default_store()
    fingerprint = review.candidate_fingerprint(preview(row), BOOK, settings())

    def write_then_revoke(gmail, **kwargs):
        rf.reject(store, "A-0001", "admin@lakshyaa.ai", fingerprint)  # signed, chained
        created.append(kwargs)
        return {"id": "draft-1"}
    monkeypatch.setattr(gmail_drafts, "create", write_then_revoke)
    result = job_draft.create("A-0001", digest, written=written, settings=settings(),
                              api=object(), gmail=Mailbox(), handbook=BOOK, pages=SITE)
    assert result["status"] == "CREATED" and len(created) == 1  # not caught: the window is open


def test_create_refuses_the_old_template_even_with_its_approved_hash(ready):
    row, tab, created = ready
    old = drafting.preview(row, facts(), settings(
        intended_use="an early preview", next_week_action="a call",
        cta_question="Would next week work?"), suppressed=False)
    assert old["preview_hash"]
    with pytest.raises(job_draft.DraftBlocked, match="Drive-handbook written draft"):
        job_draft.create("A-0001", old["preview_hash"], settings=settings(),
                         api=object(), gmail=Mailbox())
    assert tab.writes == [] and created == []


def test_worker_preview_always_uses_the_drive_writer(monkeypatch):
    _stub_sheet_projects(monkeypatch)
    called = []
    monkeypatch.setattr(job_draft, "previews", lambda ids, **kwargs:
                        called.append(kwargs) or [{"preview_hash": None}])
    response = worker.app.test_client().post("/jobs/draft/preview",
                                              json={"ids": ["A-0001"], "write": False})
    assert response.status_code == 200
    assert called[0]["write"] is True


def test_a_handbook_edited_after_approval_stops_the_draft(ready):
    row, _, created = ready
    written, digest = approved_written(row)
    edited = {**BOOK, "content_hash": "hash-two"}
    with pytest.raises(job_draft.DraftBlocked, match="approved hash"):
        job_draft.create("A-0001", digest, written=written, settings=settings(),
                         api=object(), gmail=Mailbox(), handbook=edited, pages=SITE)
    assert created == []


def test_a_handbook_whose_offer_was_removed_stops_the_draft(ready):
    row, _, created = ready
    written, digest = approved_written(row)
    thinner = {**BOOK, "text": HANDBOOK_TEXT.replace("preview", "coffee")}
    with pytest.raises(job_draft.DraftBlocked):
        job_draft.create("A-0001", digest, written=written, settings=settings(),
                         api=object(), gmail=Mailbox(), handbook=thinner, pages=SITE)
    assert created == []


def test_a_tampered_body_cannot_be_created(ready):
    row, _, created = ready
    written, digest = approved_written(row)
    written["sentences"][2]["text"] = "Would you send me your bank login this week?"
    with pytest.raises(job_draft.DraftBlocked):
        job_draft.create("A-0001", digest, written=written, settings=settings(),
                         api=object(), gmail=Mailbox(), handbook=BOOK, pages=SITE)
    assert created == []


def test_a_wrong_or_missing_hash_cannot_be_created(ready):
    row, _, created = ready
    written, _ = approved_written(row)
    for bad in ("", "0" * 64):
        with pytest.raises(job_draft.DraftBlocked):
            job_draft.create("A-0001", bad, written=written, settings=settings(),
                             api=object(), gmail=Mailbox(), handbook=BOOK, pages=SITE)
    assert created == []


def test_gmail_writes_stay_disabled_without_authorization(monkeypatch, ready):
    monkeypatch.delenv("ENABLE_GMAIL_DRAFTS", raising=False)
    row, _, created = ready
    written, digest = approved_written(row)
    with pytest.raises(job_draft.DraftBlocked, match="disabled"):
        job_draft.create("A-0001", digest, written=written, settings=settings(),
                         api=object(), gmail=Mailbox(), handbook=BOOK, pages=SITE)
    assert created == []


def test_a_second_draft_for_the_same_lead_is_refused(ready):
    row, tab, created = ready
    written, digest = approved_written(row)
    job_draft.create("A-0001", digest, written=written, settings=settings(),
                     api=object(), gmail=Mailbox(), handbook=BOOK, pages=SITE)
    with pytest.raises(job_draft.DraftBlocked):
        job_draft.create("A-0001", digest, written=written, settings=settings(),
                         api=object(), gmail=Mailbox(), handbook=BOOK, pages=SITE)
    assert len(created) == 1


def test_a_reserved_action_counts_toward_the_daily_cap(ready):
    row, tab, created = ready
    tab.rows.append((4, lead(**{"Lead ID": "A-0002", "Draft status": "RESERVED",
                              "Draft action at": job_draft.datetime.now(
                                  job_draft.timezone.utc).isoformat()})))
    written, digest = approved_written(row)
    with pytest.raises(job_draft.DraftBlocked, match="daily draft cap"):
        job_draft.create("A-0001", digest, written=written,
                         settings=settings(daily_cap=1), api=object(),
                         gmail=Mailbox(), handbook=BOOK, pages=SITE)
    assert tab.writes == [] and created == []


def test_the_draft_s_thread_is_recorded_so_its_send_can_be_recognised(ready, monkeypatch):
    row, tab, created = ready
    monkeypatch.setattr(gmail_drafts, "create", lambda gmail, **kw: created.append(kw) or
                        {"id": "draft-1", "message": {"id": "m-1", "threadId": "thread-1"}})
    written, digest = approved_written(row)
    job_draft.create("A-0001", digest, written=written, settings=settings(),
                     api=object(), gmail=Mailbox(), handbook=BOOK, pages=SITE)
    assert tab.lead["Draft thread ID"] == "thread-1"


def test_with_tracking_on_the_draft_carries_a_tracked_copy_of_the_same_words(ready, monkeypatch):
    from outreach import tracking
    row, tab, created = ready
    monkeypatch.setattr(tracking, "key", lambda: bytes(range(32)))
    written, digest = approved_written(row)
    job_draft.create("A-0001", digest, written=written, settings=settings(tracking_enabled=True),
                     api=object(), gmail=Mailbox(), handbook=BOOK, pages=SITE)
    html = created[0]["html"]
    assert tracking.BASE + "/o/" in html
    # The website in these settings is not the allowed site, so its link stays as it is.
    assert 'href="https://example.test"' in html and tracking.BASE + "/c/" not in html
    assert created[0]["body"].endswith(drafting.OPT_OUT) and "t.lakshyaa.ai" not in created[0]["body"]
    assert tab.lead["Draft tracked"] == "yes" and tab.lead["Draft hash"] == digest


def test_with_tracking_off_the_draft_is_plain_text(ready):
    row, tab, created = ready
    written, digest = approved_written(row)
    job_draft.create("A-0001", digest, written=written, settings=settings(),
                     api=object(), gmail=Mailbox(), handbook=BOOK, pages=SITE)
    assert created[0]["html"] is None and tab.lead["Draft tracked"] == ""


def test_tracking_on_without_its_key_makes_no_draft_at_all(ready, monkeypatch):
    from outreach import tracking
    row, tab, created = ready

    def missing():
        raise tracking.TrackingUnavailable("the tracking signing key is not available")
    monkeypatch.setattr(tracking, "key", missing)
    written, digest = approved_written(row)
    with pytest.raises(job_draft.DraftBlocked, match="tracking is on"):
        job_draft.create("A-0001", digest, written=written, settings=settings(tracking_enabled=True),
                         api=object(), gmail=Mailbox(), handbook=BOOK, pages=SITE)
    assert created == [] and tab.writes == []


def test_a_follow_up_drafted_today_counts_toward_the_same_daily_cap(ready):
    row, tab, created = ready
    tab.rows.append((4, lead(**{"Lead ID": "A-0002", "Follow-up status": "CREATED",
                              "Follow-up action at": job_draft.datetime.now(
                                  job_draft.timezone.utc).isoformat()})))
    written, digest = approved_written(row)
    with pytest.raises(job_draft.DraftBlocked, match="daily draft cap"):
        job_draft.create("A-0001", digest, written=written, settings=settings(daily_cap=1),
                         api=object(), gmail=Mailbox(), handbook=BOOK, pages=SITE)
    assert created == []


def test_an_uncertain_gmail_result_leaves_a_reservation_and_no_retry(ready, monkeypatch):
    row, tab, created = ready
    written, digest = approved_written(row)

    def uncertain(gmail, **kw):
        created.append(kw)
        raise TimeoutError("unknown if Gmail committed")
    monkeypatch.setattr(gmail_drafts, "create", uncertain)
    with pytest.raises(TimeoutError):
        job_draft.create("A-0001", digest, written=written, settings=settings(),
                         api=object(), gmail=Mailbox(), handbook=BOOK, pages=SITE)
    assert tab.lead["Draft status"] == "RESERVED"
    with pytest.raises(job_draft.DraftBlocked):
        job_draft.create("A-0001", digest, written=written, settings=settings(),
                         api=object(), gmail=Mailbox(), handbook=BOOK, pages=SITE)
    assert len(created) == 1


def test_a_mailbox_that_is_not_the_configured_sender_is_refused(ready):
    row, _, created = ready
    written, digest = approved_written(row)

    class Other(Mailbox):
        def execute(self):
            return {"emailAddress": "someone.else@lakshyaa.ai"}
    with pytest.raises(job_draft.DraftBlocked, match="mailbox"):
        job_draft.create("A-0001", digest, written=written, settings=settings(),
                         api=object(), gmail=Other(), handbook=BOOK, pages=SITE)
    assert created == []


def test_create_never_calls_the_model(ready, monkeypatch):
    row, _, created = ready
    written, digest = approved_written(row)

    def forbidden(*args, **kwargs):
        raise AssertionError("create must re-check, never re-write")
    monkeypatch.setattr(writer, "compose", forbidden)
    assert job_draft.create("A-0001", digest, written=written, settings=settings(),
                            api=object(), gmail=Mailbox(), handbook=BOOK, pages=SITE)["status"] == "CREATED"


# --- the company's own name, and the operator's choice of quote ----------------------------

def test_the_shouted_sheet_name_becomes_the_site_s_own_capitalisation():
    row = lead(Company="EXAMPLE ELECTRIC INC")
    out = preview(row)
    assert out["company_name_used"] == "Example Electric" and out["preview_hash"]
    assert "EXAMPLE ELECTRIC INC" not in out["body"]


def test_a_name_absent_from_the_site_blocks_the_preview(monkeypatch):
    out = job_draft.previews(["A-0001"], settings=settings(), write=True, handbook=BOOK,
                             model=model_for(company_text="Installs electrical distribution "
                                             "systems for commercial buildings."),
                             fixture={"leads": [lead(Company="UNSEEN WIDGETS LLC")],
                                      "research": facts(), "pages": SITE,
                                      "suppressed": {"A-0001": False}})[0]
    assert out["preview_hash"] is None
    assert any("not found on its own site" in b for b in out["blockers"])


def test_an_unconfirmed_name_stops_the_draft(ready):
    row, _, created = ready
    written, digest = approved_written(row)
    row["Company"] = "RENAMED HOLDINGS LLC"
    with pytest.raises(job_draft.DraftBlocked, match="no longer confirmed"):
        job_draft.create("A-0001", digest, written=written, settings=settings(),
                         api=object(), gmail=Mailbox(), handbook=BOOK, pages=SITE)
    assert created == []


def test_the_operator_can_choose_which_verified_quote_is_written_from():
    market = "We serve schools and hospitals with switchgear and fire alarm work."
    market_url = "https://example.test/markets"
    row = lead(**{"Markets evidence": f'"{market}" ({market_url})'})
    rows = facts() + [{"Lead ID": "A-0001", "Researched at": "2026-09-22 12:00:00",
                       "Category": "MARKET", "Quote": market, "Page URL": market_url}]
    options = drafting.opening_options(drafting.supported_quotes(row, rows), "Example Electric")
    chosen = [o for o in options if o["quote"] == market][0]["quote_id"]

    def model(prompt, schema):
        assert market in prompt and QUOTE not in prompt  # only the chosen quote is offered
        return {"subject": "A conversation about Example Product next week", "sentences": [
            {"text": "Example Electric serves schools and hospitals with switchgear and fire "
                     "alarm work.", "kind": "COMPANY", "quote_id": chosen},
            {"text": "I'm building Example Product, a cash-flow decision tool for construction "
                     "subcontractors. The MVP is still being finished.", "kind": "PRODUCT"},
            {"text": "Would you be open to a twenty minute conversation next week about the "
                     "early preview?", "kind": "ASK"}]}, {}

    def compose(store):
        return job_draft.previews(["A-0001"], settings=settings(), write=True, handbook=BOOK,
                                  model=model, quote_choices={"A-0001": chosen}, review_store=store,
                                  fixture={"leads": [row], "research": rows, "pages": SITE,
                                           "suppressed": {"A-0001": False}})[0]
    bare = compose(review.MemoryReviewStore())
    store = review.MemoryReviewStore()
    rf.confirm(store, bare["lead_id"], "admin@lakshyaa.ai",
               review.candidate_fingerprint(bare, BOOK, settings()))
    out = compose(store)
    assert out["evidence"]["quote"] == market and out["preview_hash"]


def test_an_unknown_quote_choice_blocks_rather_than_falling_back():
    out = job_draft.previews(["A-0001"], settings=settings(), write=True, handbook=BOOK,
                             model=model_for(), quote_choices={"A-0001": "0" * 16},
                             fixture={"leads": [lead()], "research": facts(), "pages": SITE,
                                      "suppressed": {"A-0001": False}})[0]
    assert out["preview_hash"] is None
    assert "the selected quote is not a current, usable quote" in out["blockers"]


# --- automatic opening selection ------------------------------------------------------------

def options_for(*quotes):
    return drafting.opening_options(
        [{"category": c, "quote": q, "url": "https://example.test/p"} for c, q in quotes], "Acme")


def test_specific_work_beats_a_generic_service_line():
    chosen, _ = choose = drafting.choose_opening(options_for(
        ("OFFERING", "Acme specializes in electrical services for its customers."),
        ("OFFERING", "Acme installs switchgear and distribution systems in hospitals and schools.")))
    assert "switchgear" in chosen["quote"]


def test_a_market_list_is_not_chosen_over_real_work():
    chosen, _ = drafting.choose_opening(options_for(
        ("MARKET", "We work with offices, retail spaces, restaurants, warehouses and clinics."),
        ("OFFERING", "Acme installs and modifies commercial gas lines for equipment upgrades.")))
    assert "gas lines" in chosen["quote"]


def test_a_boastful_quote_loses_to_a_plain_one_but_is_not_thrown_away():
    """A source may contain a boast; the email simply may not repeat it (see test_writer)."""
    chosen, report = drafting.choose_opening(options_for(
        ("OFFERING", "Acme is the region's leading and finest installer of fire alarm systems "
                     "in schools and hospitals."),
        ("OFFERING", "Acme installs fire alarm systems in schools and hospitals.")))
    praised = [r for r in report if "leading" in r["quote"]][0]
    plain = [r for r in report if "leading" not in r["quote"]][0]
    assert praised["score"] is not None  # still usable as a source
    assert any("own praise" in note for note in praised["reasons"])
    assert plain["score"] > praised["score"] and chosen["quote"] == plain["quote"]


def test_a_boastful_quote_is_still_chosen_when_it_is_the_only_real_evidence():
    chosen, _ = drafting.choose_opening(options_for(
        ("MARKET", "Healthcare, workplace, retail, hospitality and industrial."),
        ("OFFERING", "Acme is the leading design/build electrical construction firm for "
                     "shopping malls, banks and hospitals.")))
    assert chosen is not None and "design/build" in chosen["quote"]


def test_a_heading_no_longer_throws_the_source_away():
    chosen, _ = drafting.choose_opening(options_for(
        ("OFFERING", "CONSTRUCTION From shopping malls to hospitals, we install electrical "
                     "systems and build out tenant spaces.")))
    assert chosen is not None


def test_an_opener_that_refers_to_something_unsaid_is_marked_down():
    chosen, _ = drafting.choose_opening(options_for(
        ("OFFERING", "In all three markets Acme performs design/build and plan/spec work."),
        ("OFFERING", "Acme performs design/build and plan/spec work for schools and plants.")))
    assert chosen["quote"].startswith("Acme performs")


def test_nothing_good_enough_holds_the_lead_for_review():
    chosen, report = drafting.choose_opening(options_for(
        ("MARKET", "Healthcare, workplace, retail, hospitality, industrial, and automotive."),
        ("OFFERING", "Acme is proud of its reputation as a first-class contractor.")))
    assert chosen is None and all(r["score"] is None for r in report)


def test_selection_is_deterministic():
    opts = options_for(("OFFERING", "Acme installs switchgear in hospitals."),
                       ("OFFERING", "Acme installs panels in schools."))
    assert (drafting.choose_opening(opts)[0]["quote_id"]
            == drafting.choose_opening(list(reversed(opts)))[0]["quote_id"])


def test_the_preview_chooses_without_a_pin_and_says_so():
    out = preview()
    assert out["chosen_automatically"] and out["preview_hash"]
    assert out["evidence"]["quote"] == QUOTE


def test_a_lead_with_no_good_opening_is_held_not_forced():
    weak = "Healthcare, workplace, retail, hospitality, industrial, and automotive environments."
    row = lead(**{"Offerings evidence": "", "Markets evidence": f'"{weak}" ({URL})'})
    rows = [{"Lead ID": "A-0001", "Researched at": "2026-09-22 12:00:00", "Category": "MARKET",
             "Quote": weak, "Page URL": URL}]
    out = job_draft.previews(["A-0001"], settings=settings(), write=True, handbook=BOOK,
                             model=model_for(),
                             fixture={"leads": [row], "research": rows, "pages": SITE,
                                      "suppressed": {"A-0001": False}})[0]
    assert out["preview_hash"] is None
    assert any("no quote is good enough to open with" in b for b in out["blockers"])


def test_a_site_name_longer_than_the_sheet_name_is_still_verified():
    site = "Muetzel Plumbing, Heating & Air Conditioning has served Columbus since 1908."
    assert drafting.verified_company_name("MUETZEL PLUMBING & HEATING CO", site) == \
        ("Muetzel Plumbing", True)


def test_a_name_that_is_nowhere_on_the_site_is_still_unverified():
    assert drafting.verified_company_name("ZEPHYR WIDGETS LLC", "Acme Electric does wiring.")[1] is False
