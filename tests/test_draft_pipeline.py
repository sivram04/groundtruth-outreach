"""The written pipeline end to end, offline: Drive handbook -> Gemini -> checks -> approval.

Nothing here touches Google. Every path that could put an unapproved or unsupported email in
front of a recipient must fail closed.
"""

from pathlib import Path

import pytest

from outreach import drafting, gmail_drafts, handbook_drive, job_draft, worker, writer

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
              "version": "prelaunch-v1", "handbook_doc_id": "1AbCdEfGhIjKlMnOpQrStUvWxYz01234"}
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


def preview(row=None, *, book=BOOK, model=None, config=None, suppressed=False):
    row = row or lead()
    return job_draft.previews(["A-0001"], settings=config or settings(), write=True,
                              handbook=book, model=model or model_for(),
                              fixture={"leads": [row], "research": facts(), "pages": SITE,
                                       "suppressed": {"A-0001": suppressed}})[0]


# --- the good path ------------------------------------------------------------------------

def test_a_written_preview_is_approvable_and_carries_its_sources():
    out = preview()
    assert out["blockers"] == [] and out["preview_hash"]
    assert out["handbook_hash"] == "hash-one"
    assert out["evidence"]["quote"] == QUOTE and out["evidence"]["url"] == URL
    assert out["body"].startswith("Hi Sam,") and out["body"].endswith(drafting.OPT_OUT)
    assert "1 Example St" in out["body"] and "614-555-0100" in out["body"]
    assert out["written"]["sentences"] and "usage" not in out["written"]


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
    def refuse(settings=None, drive=None):
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
    monkeypatch.setattr(gmail_drafts, "prior_sends", lambda gmail, recipient: False)
    monkeypatch.setattr(gmail_drafts, "existing_drafts", lambda gmail, recipient: [])
    monkeypatch.setattr(job_draft, "Tab", lambda api, name, cols: tab)
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
    market = "We serve commercial and institutional clients across the region."
    market_url = "https://example.test/markets"
    row = lead(**{"Markets evidence": f'"{market}" ({market_url})'})
    rows = facts() + [{"Lead ID": "A-0001", "Researched at": "2026-09-22 12:00:00",
                       "Category": "MARKET", "Quote": market, "Page URL": market_url}]
    options = drafting.opening_options(drafting.supported_quotes(row, rows), "Example Electric")
    chosen = [o for o in options if o["quote"] == market][0]["quote_id"]

    def model(prompt, schema):
        assert market in prompt and QUOTE not in prompt  # only the chosen quote is offered
        return {"subject": "A conversation about Example Product next week", "sentences": [
            {"text": "Example Electric serves commercial and institutional clients across the "
                     "region.", "kind": "COMPANY", "quote_id": chosen},
            {"text": "I'm building Example Product, a cash-flow decision tool for construction "
                     "subcontractors. The MVP is still being finished.", "kind": "PRODUCT"},
            {"text": "Would you be open to a twenty minute conversation next week about the "
                     "early preview?", "kind": "ASK"}]}, {}

    out = job_draft.previews(["A-0001"], settings=settings(), write=True, handbook=BOOK,
                             model=model, quote_choices={"A-0001": chosen},
                             fixture={"leads": [row], "research": rows, "pages": SITE,
                                      "suppressed": {"A-0001": False}})[0]
    assert out["evidence"]["quote"] == market and out["preview_hash"]


def test_an_unknown_quote_choice_blocks_rather_than_falling_back():
    out = job_draft.previews(["A-0001"], settings=settings(), write=True, handbook=BOOK,
                             model=model_for(), quote_choices={"A-0001": "0" * 16},
                             fixture={"leads": [lead()], "research": facts(), "pages": SITE,
                                      "suppressed": {"A-0001": False}})[0]
    assert out["preview_hash"] is None
    assert "the selected quote is not a current, usable quote" in out["blockers"]
