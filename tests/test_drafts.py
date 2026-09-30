"""The Drafts tab, offline: which leads get a first email written, what each row says, and that a
row can never carry more than the checks allow. Nothing here touches Google."""

import json
from datetime import datetime, timezone

import pytest

from outreach import drafting, drafts, job_draft, review, sequence, sheet
from outreach.sync import _event
from stage4_fakes import MemoryStore, at
from test_draft_pipeline import BOOK, QUOTE, SITE, URL, facts, lead, model_for, settings

NOW = datetime(2026, 9, 29, 14, 0, tzinfo=timezone.utc)


def ready_lead(lead_id="A-0001", **changes):
    return lead(**{"Lead ID": lead_id, **changes})


def store(*rows, events=(), suppression=(), existing=()):
    research = facts() + [dict(fact, **{"Lead ID": "A-0002"}) for fact in facts()]
    return MemoryStore(list(rows), events=list(events), suppression=suppression,
                       drafts=list(existing), research=research)


def test_a_lead_with_no_quote_is_held_without_asking_the_model():
    model = Counting(model_for())
    memory = MemoryStore([ready_lead()], research=[])
    run(memory, model=model)
    assert row_of(memory)["Status"] == drafts.HELD and model.calls == 0
    assert "quote" in row_of(memory)["Why"]


class Counting:
    def __init__(self, model):
        self.model, self.calls = model, 0

    def __call__(self, prompt, schema):
        self.calls += 1
        return self.model(prompt, schema)


def run(memory, *, config=None, model=None, pages=None, review_store=None, **options):
    return drafts.prepare(memory, settings=config or settings(offer_approved=False), handbook=BOOK,
                          model=model or model_for(), now=NOW,
                          pages=pages if pages is not None else {"A-0001": SITE, "A-0002": SITE},
                          review_store=review_store, **options)


def reviewed_store(memory, *, config=None):
    """A store confirming every currently-ready lead's candidate, so `run` can produce READY rows.
    Composes each candidate the same way `prepare` does, then records a human confirmation."""
    cfg = config or settings(offer_approved=True)
    research = (memory.table("Research") or ([], []))[1]
    ready, _existing, _entries = drafts.plan(memory)
    store = review.MemoryReviewStore()
    for row in ready:
        bare = job_draft.written_preview(row, research, cfg, BOOK, suppressed=False,
                                         model=model_for(), pages=SITE,
                                         review_store=review.MemoryReviewStore())
        if bare.get("written"):
            review.record_confirmation(store, bare["lead_id"], "admin@lakshyaa.ai",
                                       review.candidate_fingerprint(bare, BOOK, cfg))
    return store


def row_of(memory, lead_id="A-0001"):
    return next(row for row in memory.draft_rows if row["Lead ID"] == lead_id)


# --- what a row says -------------------------------------------------------------------------

def test_while_the_offer_is_unapproved_the_words_are_kept_to_read_and_nothing_can_send_them():
    memory = store(ready_lead())
    report = run(memory)
    row = row_of(memory)
    assert report["written"] == {"A-0001": {"status": drafts.WAITING, "why": drafts.OFFER_NOT_APPROVED}}
    assert row["Status"] == drafts.WAITING and row["Approval hash"] == ""
    assert row["Body"].startswith("Hi Sam,") and row["Body"].endswith(drafting.OPT_OUT)
    assert row["Subject"] == "A conversation about Example Product next week"
    assert row["Opening quote"] == QUOTE and row["Quote page"] == URL
    assert row["To"] == "sam@example.test" and row["Email"] == drafts.FIRST_EMAIL
    assert json.loads(row["Written"])["sentences"]  # what approving will be checked against
    assert row["Handbook hash"] == BOOK["content_hash"]
    assert row["Prepared at (UTC)"] == "2026-09-29 14:00:00"
    assert set(row) == set(sheet.DRAFTS_HEADER)


def test_the_words_shown_while_waiting_are_the_words_an_approval_would_send():
    waiting = store(ready_lead())
    run(waiting)
    approved = store(ready_lead())
    run(approved, config=settings(offer_approved=True))
    assert row_of(waiting)["Body"] == row_of(approved)["Body"]
    assert row_of(waiting)["Subject"] == row_of(approved)["Subject"]


def test_with_the_offer_approved_a_row_is_ready_and_carries_its_approval_hash():
    memory = store(ready_lead())
    cfg = settings(offer_approved=True)
    run(memory, config=cfg, review_store=reviewed_store(memory, config=cfg))
    row = row_of(memory)
    assert row["Status"] == drafts.READY and row["Why"] == ""
    assert len(row["Approval hash"]) == 64


def test_an_approved_offer_without_a_review_waits_with_no_hash():
    """Even with the offer approved and every check passing, no approval hash is issued until a
    human evidence review exists; the words are kept and the row waits."""
    memory = store(ready_lead())
    run(memory, config=settings(offer_approved=True))  # no review store -> fail-closed
    row = row_of(memory)
    assert row["Status"] == drafts.WAITING and row["Approval hash"] == ""
    assert review.AWAITING_BLOCKER in row["Why"] and row["Body"].startswith("Hi Sam,")


@pytest.mark.parametrize("sentence", [
    "I noticed Example Electric installs solar arrays for regional hospitals.",
    "I noticed Example Electric asks customers to email billing@attacker.test.",
])
def test_a_sentence_the_company_never_said_holds_the_draft_with_no_words(sentence):
    memory = store(ready_lead())
    run(memory, model=model_for(company_text=sentence))
    row = row_of(memory)
    assert row["Status"] == drafts.HELD and row["Body"] == "" and row["Approval hash"] == ""
    assert row["Why"]


def test_a_writer_that_fails_holds_the_draft_and_says_so():
    def broken(prompt, schema):
        raise RuntimeError("Gemini failed")

    memory = store(ready_lead())
    run(memory, model=broken)
    row = row_of(memory)
    assert row["Status"] == drafts.HELD and "writer failed" in row["Why"] and row["Body"] == ""


def test_a_company_name_not_on_its_own_site_is_shown_with_the_name_to_check():
    memory = store(ready_lead())
    run(memory, config=settings(offer_approved=True), pages={"A-0001": "An unrelated page. " + QUOTE})
    row = row_of(memory)
    assert row["Status"] == drafts.WAITING and row["Approval hash"] == ""
    assert drafts.NAME_NOT_ON_SITE in row["Why"] and row["Body"].startswith("Hi Sam,")


def test_the_model_is_asked_once_per_lead_and_never_to_show_the_words():
    model = Counting(model_for())
    run(store(ready_lead(), ready_lead("A-0002")), model=model)
    assert model.calls == 2


# --- who gets a row --------------------------------------------------------------------------

@pytest.mark.parametrize("change", [{"Email check": "RISKY"}, {"Fit": "REVIEW_NEEDED"},
                                    {"Profile status": ""}, {"HOLD": "yes"},
                                    {"Sent by hand": "2026-09-22"}, {"Draft status": "CREATED"}])
def test_a_lead_that_is_not_ready_gets_no_row(change):
    memory = store(ready_lead(**change))
    report = run(memory)
    assert report["to_write"] == [] and memory.draft_rows == []


def test_a_lead_already_emailed_or_suppressed_gets_no_row():
    emailed = _event("A-0001", sequence.SENT, "INITIAL", at("2026-09-22 13:00"), "sam@example.test",
                     "ADDRESS", "t1", "m1", "")
    assert run(store(ready_lead(), events=[emailed]))["to_write"] == []
    stopped = [{"Address or domain": "sam@example.test", "Reason": "opted out"}]
    assert run(store(ready_lead(), suppression=stopped))["to_write"] == []


def test_an_unreadable_suppression_tab_stops_the_run_before_anything_is_written():
    memory = store(ready_lead(), suppression=None)
    with pytest.raises(drafts.DraftsBlocked):
        run(memory)
    assert memory.draft_rows == [] and memory.runs == []


def test_a_lead_with_a_row_is_left_alone_unless_asked_to_write_it_again():
    memory = store(ready_lead(), ready_lead("A-0002"))
    run(memory, limit=1)
    assert [r["Lead ID"] for r in memory.draft_rows] == ["A-0001"]
    second = run(memory)
    assert second["to_write"] == ["A-0002"] and second["already_drafted"] == 1
    assert [r["Lead ID"] for r in memory.draft_rows] == ["A-0001", "A-0002"]
    cfg = settings(offer_approved=True)
    again = run(memory, config=cfg, refresh=True, review_store=reviewed_store(memory, config=cfg))
    assert again["to_write"] == ["A-0001", "A-0002"]
    assert [r["Lead ID"] for r in memory.draft_rows] == ["A-0001", "A-0002"]  # rewritten in place
    assert {r["Status"] for r in memory.draft_rows} == {drafts.READY}


def test_a_dry_run_names_who_would_be_written_and_writes_nothing():
    model = Counting(model_for())
    memory = store(ready_lead(), ready_lead("A-0002"))
    report = run(memory, model=model, dry_run=True)
    assert report["to_write"] == ["A-0001", "A-0002"] and report["written"] == {}
    assert memory.draft_rows == [] and model.calls == 0 and memory.runs == []


@pytest.mark.parametrize("limit", [0, drafts.MAX_LIMIT + 1])
def test_a_run_writes_a_bounded_number_of_drafts(limit):
    with pytest.raises(drafts.DraftsBlocked):
        run(store(ready_lead()), limit=limit)


def test_no_settings_or_no_handbook_stops_the_run(monkeypatch):
    with pytest.raises(drafts.DraftsBlocked):
        drafts.prepare(store(ready_lead()), settings={}, handbook=BOOK, model=model_for(), now=NOW)
    monkeypatch.delenv("HANDBOOK_DOC_ID", raising=False)
    with pytest.raises(drafts.DraftsBlocked):
        drafts.prepare(store(ready_lead()), settings=settings(handbook_doc_id=""), model=model_for(),
                       now=NOW, pages={"A-0001": SITE})


def test_the_run_is_recorded():
    memory = store(ready_lead())
    run(memory)
    assert memory.runs[-1]["Job"] == "drafts" and "WAITING 1" in memory.runs[-1]["Detail"]


# --- the Sheet itself --------------------------------------------------------------------------

class _Exec:
    def __init__(self, value):
        self.value = value

    def execute(self):
        return self.value


class FakeSheets:
    """The parts of the Sheets API the Store's Drafts methods use, over a few tabs."""

    def __init__(self, tabs):
        self.tabs = {name: [list(r) for r in rows] for name, rows in tabs.items()}
        self.calls = []

    def get(self, spreadsheetId):
        return _Exec({"sheets": [{"properties": {"title": name, "sheetId": i}}
                                 for i, name in enumerate(self.tabs)]})

    def batchUpdate(self, spreadsheetId, body):
        for request in body["requests"]:
            self.tabs[request["addSheet"]["properties"]["title"]] = []
        return _Exec({})

    def values(self):
        return _Values(self)


class _Values:
    def __init__(self, api):
        self.api = api

    def get(self, spreadsheetId, range):
        return _Exec({"values": [list(r) for r in self.api.tabs[range.strip("'")]]})

    def update(self, spreadsheetId, range, valueInputOption, body):
        self.api.calls.append(("update", valueInputOption))
        name = range.split("!")[0].strip("'")
        self.api.tabs[name][:1] = body["values"]
        return _Exec({})

    def append(self, spreadsheetId, range, valueInputOption, insertDataOption, body):
        self.api.calls.append(("append", valueInputOption))
        self.api.tabs[range.split("!")[0].strip("'")] += [list(r) for r in body["values"]]
        return _Exec({})

    def batchUpdate(self, spreadsheetId, body):
        self.api.calls.append(("rewrite", body["valueInputOption"]))
        for item in body["data"]:
            name, cell = item["range"].split("!")
            self.api.tabs[name.strip("'")][int(cell[1:]) - 1] = list(item["values"][0])
        return _Exec({})


def sheet_store(drafts_rows=None):
    tabs = {"A_Contact_Now": [["description"], ["Company", "Lead ID"]],
            "B_Contact_Now": [["description"], ["Company", "Lead ID"]]}
    if drafts_rows is not None:
        tabs[sheet.DRAFTS_TAB] = drafts_rows
    api = FakeSheets(tabs)
    return sheet.Store(api), api


def a_row(lead_id, body="Hi there"):
    return {**{h: "" for h in sheet.DRAFTS_HEADER}, "Lead ID": lead_id, "Body": body}


def test_the_drafts_tab_is_made_on_first_write_and_every_cell_is_plain_text():
    memory, api = sheet_store()
    assert memory.drafts() == []
    memory.write_drafts([a_row("A-0001", body="=HYPERLINK(\"https://attacker.test\")")])
    assert api.tabs[sheet.DRAFTS_TAB][0] == sheet.DRAFTS_HEADER
    assert memory.drafts()[0][1]["Body"].startswith("=HYPERLINK")
    assert all(option == "RAW" for _, option in api.calls)


def test_a_row_is_rewritten_in_place_only_while_it_still_holds_the_same_lead():
    header = sheet.DRAFTS_HEADER
    memory, api = sheet_store([header, [a_row("A-0001")[h] for h in header],
                               [a_row("A-0002")[h] for h in header]])
    memory.write_drafts([], {3: a_row("A-0002", body="new words")})
    assert dict(memory.drafts())[3]["Body"] == "new words"
    with pytest.raises(RuntimeError):
        memory.write_drafts([], {2: a_row("A-0002", body="wrong row")})
    assert dict(memory.drafts())[2]["Lead ID"] == "A-0001"
    assert ("rewrite", "RAW") in api.calls


def test_a_drafts_tab_whose_columns_were_changed_is_neither_read_nor_written():
    changed = ["Lead ID", "To", "Email"] + sheet.DRAFTS_HEADER[3:]
    memory, _ = sheet_store([changed, ["A-0001"]])
    with pytest.raises(RuntimeError):
        memory.drafts()


def test_each_reason_a_draft_waits_is_on_its_own_line():
    memory = store(ready_lead())
    run(memory, pages={"A-0001": "An unrelated page. " + QUOTE})
    reasons = row_of(memory)["Why"].splitlines()
    assert reasons[0] == drafts.OFFER_NOT_APPROVED
    assert drafts.NAME_NOT_ON_SITE in reasons[1] and reasons[1].endswith("check it")
