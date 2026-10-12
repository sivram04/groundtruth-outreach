"""One reading of the Suppression tab, and every job that acts on it stopping when it cannot be read.

An empty list is a valid answer: nobody is suppressed. A missing tab, a header with no address
column or two of them, a row with no address, and a read that fails are all unknown - and a job that
would decide from the answer has to stop rather than proceed as though the list were empty.
"""

import pytest

from outreach import drafts as drafts_job
from outreach import followup, job_draft, suppression, sync, tracking_check
from outreach.sheet import SUPPRESSION_HEADER, SUPPRESSION_TAB, Store
from stage4_fakes import MemoryStore
from test_followup import initial_sent, lead
from test_tracking_job import SETTINGS as TRACKING_SETTINGS

FIELD = suppression.FIELD
HEADER = [FIELD, "Reason", "Added at", "Source"]


# --- the contract itself --------------------------------------------------------------------

def test_a_tab_with_only_its_header_is_an_empty_list_not_an_unknown():
    """Nobody is suppressed, which is a real answer and must not block anything."""
    assert suppression.of_values([HEADER]) == []


def test_rows_are_read_and_carry_the_canonical_field():
    entries = suppression.of_values([HEADER, ["bob@acme.test", "asked to stop", "2026-09-01", "hand"]])
    assert entries == [{FIELD: "bob@acme.test", "Reason": "asked to stop",
                        "Added at": "2026-09-01", "Source": "hand"}]


def test_no_values_at_all_is_unknown():
    with pytest.raises(suppression.Unreadable) as raised:
        suppression.of_values([])
    assert "not even a header row" in raised.value.reason


@pytest.mark.parametrize("header", [["Email", "Reason"], ["Lead ID"], [""], ["addresses"]])
def test_a_header_with_no_address_column_is_unknown(header):
    with pytest.raises(suppression.Unreadable) as raised:
        suppression.of_values([header, ["bob@acme.test"]])
    assert f"no {FIELD} column" in raised.value.reason
    assert "its header reads" in raised.value.reason


@pytest.mark.parametrize("header", [[FIELD, "Address"], ["Address", "Domain"], [FIELD, FIELD]])
def test_two_address_columns_are_unknown_because_neither_is_stated(header):
    """Choosing one by position is the silent guess this contract exists to prevent."""
    with pytest.raises(suppression.Unreadable) as raised:
        suppression.of_values([header, ["bob@acme.test", "acme.test"]])
    assert "more than one address column" in raised.value.reason


@pytest.mark.parametrize("alias", ["Address", "Domain"])
def test_an_alias_is_normalised_to_the_canonical_field(alias):
    """The row is not accepted with its address left where no caller would look for it."""
    entries = suppression.of_values([[alias, "Reason"], ["bob@acme.test", "asked to stop"]])
    assert entries[0][FIELD] == "bob@acme.test"
    assert suppression.covers(entries, "bob@acme.test") is True


def test_a_row_with_no_address_is_unknown_and_names_its_row():
    with pytest.raises(suppression.Unreadable) as raised:
        suppression.of_values([HEADER, ["bob@acme.test", "stop"], ["", "bounced"]])
    assert "row 3" in raised.value.reason and FIELD in raised.value.reason


def test_a_row_that_is_blank_all_through_is_skipped_not_refused():
    """The Sheet keeps empty lines; they say nothing, so they are neither read nor a refusal."""
    entries = suppression.of_values([HEADER, ["", "", "", ""], ["bob@acme.test", "stop", "", ""]])
    assert [e[FIELD] for e in entries] == ["bob@acme.test"]


def test_a_short_row_is_read_to_the_end_of_what_it_has():
    assert suppression.of_values([HEADER, ["bob@acme.test"]])[0] == {
        FIELD: "bob@acme.test", "Reason": "", "Added at": "", "Source": ""}


def test_an_address_is_covered_and_its_case_and_spaces_do_not_matter():
    entries = suppression.of_values([HEADER, ["  Bob@Acme.TEST "]])
    assert suppression.covers(entries, "bob@acme.test") is True
    assert suppression.covers(entries, "BOB@ACME.TEST") is True
    assert suppression.covers(entries, "sue@acme.test") is False


@pytest.mark.parametrize("listed", ["acme.test", "@acme.test"])
def test_a_whole_domain_is_covered(listed):
    entries = suppression.of_values([HEADER, [listed]])
    assert suppression.covers(entries, "anyone@acme.test") is True
    assert suppression.covers(entries, "anyone@other.test") is False


def test_an_address_on_the_list_does_not_suppress_its_domain():
    entries = suppression.of_values([HEADER, ["bob@acme.test"]])
    assert suppression.covers(entries, "sue@acme.test") is False


def test_nothing_covers_an_empty_address():
    assert suppression.covers(suppression.of_values([HEADER, ["acme.test"]]), "") is False


def test_the_cell_written_back_lands_in_whichever_column_the_header_uses():
    entry = {FIELD: "bob@acme.test", "Reason": "bounced"}
    assert suppression.cell(entry, FIELD) == "bob@acme.test"
    assert suppression.cell(entry, "Address") == "bob@acme.test"
    assert suppression.cell(entry, "Domain") == "bob@acme.test"
    assert suppression.cell(entry, "Reason") == "bounced"
    assert suppression.cell(entry, "Added at") == ""


# --- the store's reader -------------------------------------------------------------------------

class FakeValues:
    def __init__(self, values, fail=False):
        self.values, self.fail = values, fail

    def get(self, **kwargs):
        return self

    def execute(self):
        if self.fail:
            raise RuntimeError("the Sheets API said no")
        return {"values": self.values}


class FakeApi:
    def __init__(self, values, fail=False):
        self._values = FakeValues(values, fail)

    def values(self):
        return self._values


def store_reading(values, *, fail=False, titles=(SUPPRESSION_TAB,)):
    store = Store.__new__(Store)
    store.api = FakeApi(values, fail)
    store.titles = list(titles)
    store.sheet_id = "fake-sheet-id"
    return store


def test_the_store_reads_the_tab_through_the_contract():
    assert store_reading([HEADER, ["bob@acme.test"]]).suppression()[0][FIELD] == "bob@acme.test"
    assert store_reading([HEADER]).suppression() == []


def test_the_store_says_a_missing_tab_is_unknown():
    with pytest.raises(suppression.Unreadable) as raised:
        store_reading([], titles=["Leads"]).suppression()
    assert "there is no Suppression tab" in raised.value.reason


def test_the_store_says_a_failed_read_is_unknown_without_leaking_the_error():
    with pytest.raises(suppression.Unreadable) as raised:
        store_reading([HEADER], fail=True).suppression()
    assert "could not be read (RuntimeError)" in raised.value.reason
    assert "said no" not in raised.value.reason


def test_the_store_and_job_drafts_own_reader_agree_on_every_case():
    """They read the tab by two different routes; one contract means one answer."""
    cases = [[], [["Email"], ["bob@acme.test"]], [[FIELD, "Address"], ["a", "b"]],
             [HEADER, ["", "bounced"]], [HEADER], [HEADER, ["bob@acme.test"]], [HEADER, ["acme.test"]]]
    for values in cases:
        try:
            through_store = suppression.covers(store_reading(values).suppression(), "bob@acme.test")
        except suppression.Unreadable:
            through_store = None
        assert job_draft._suppressed(FakeApi(values), "bob@acme.test") == through_store, values


def test_job_drafts_reader_is_unknown_when_the_read_fails():
    assert job_draft._suppressed(FakeApi([HEADER], fail=True), "bob@acme.test") is None


# --- what each consumer does when the list cannot be read ---------------------------------------

def unreadable():
    return suppression.Unreadable("the Suppression tab has no Address or domain column: "
                                  "its header reads Email, Reason")


def test_the_sync_records_nothing_and_says_why(monkeypatch):
    """The defect this fixes: it used to treat the unknown list as an empty one and write."""
    from stage4_fakes import FakeGmail
    store = MemoryStore([lead()], events=[initial_sent()], suppression=unreadable())
    with pytest.raises(sync.SyncBlocked) as raised:
        sync.run(store=store, gmail=FakeGmail(), settings={}, where="test")
    assert "the Suppression list cannot be read" in str(raised.value)
    assert "no Address or domain column" in str(raised.value)
    assert store.lead_writes == [] and store.event_rows == [initial_sent()]
    assert [(r["Result"], r["Job"]) for r in store.runs] == [("BLOCKED", "sync")]
    assert "cursor" not in store.runs[0]["Detail"] and store.last_cursor() is None


def test_a_blocked_dry_run_writes_no_runs_row_either():
    from stage4_fakes import FakeGmail
    store = MemoryStore([lead()], suppression=unreadable())
    with pytest.raises(sync.SyncBlocked):
        sync.run(store=store, gmail=FakeGmail(), settings={}, where="test", dry_run=True)
    assert store.runs == []


def test_the_drafts_job_calls_no_lead_ready():
    store = MemoryStore([lead()], suppression=unreadable())
    with pytest.raises(drafts_job.DraftsBlocked) as raised:
        drafts_job.plan(store)
    assert "no lead can be called ready" in str(raised.value)
    assert "no Address or domain column" in str(raised.value)


def test_the_followup_job_gates_the_run_and_drafts_nothing():
    store = MemoryStore([lead()], events=[initial_sent()], suppression=unreadable())
    report = followup.run(store=store, dry_run=True, settings={}, handbook="")
    assert report["gates"] == [unreadable().reason]
    assert report["due"] == [] and report["created"] == []


def test_the_tracking_check_refuses_to_draft_a_test(monkeypatch):
    """Drafting has to be on first, or its own gate speaks and this one is never reached."""
    monkeypatch.setenv("ENABLE_GMAIL_DRAFTS", "true")
    store = MemoryStore([lead()], suppression=unreadable())
    with pytest.raises(tracking_check.CheckBlocked) as raised:
        tracking_check.create("someone@example.test", store=store,
                              settings=TRACKING_SETTINGS)
    assert "no test can be drafted" in str(raised.value)
    assert "no Address or domain column" in str(raised.value)


def test_the_tracking_check_names_the_list_when_the_address_is_on_it(monkeypatch):
    monkeypatch.setenv("ENABLE_GMAIL_DRAFTS", "true")
    store = MemoryStore([lead()], suppression=[{FIELD: "someone@example.test"}])
    with pytest.raises(tracking_check.CheckBlocked) as raised:
        tracking_check.create("someone@example.test", store=store,
                              settings=TRACKING_SETTINGS)
    assert "is on the Suppression list" in str(raised.value)


def test_an_empty_list_lets_every_consumer_go_on():
    """The valid-empty case: none of the four may treat "nobody is suppressed" as a blocker."""
    store = MemoryStore([lead()], events=[initial_sent()], suppression=[])
    gates = followup.run(store=store, dry_run=True, settings={}, handbook="")["gates"]
    assert not [gate for gate in gates if "Suppression" in gate]
    assert drafts_job.plan(MemoryStore([lead()], suppression=[]))[0] == []
    assert suppression.covers(store.suppression(), "bob@acme.test") is False


@pytest.mark.parametrize("listed,address,domain", [
    ("bob@acme.test", True, False), ("acme.test", True, True)])
def test_a_listed_address_or_domain_reaches_the_consumers(listed, address, domain):
    entries = [{FIELD: listed}]
    assert sync.on_list(entries, "bob@acme.test") is address
    assert sync.on_list(entries, "sue@acme.test") is domain
    assert job_draft._suppressed(FakeApi([HEADER, [listed]]), "bob@acme.test") is address


# --- writing new entries back -------------------------------------------------------------------

class RecordingStore(Store):
    def __init__(self, header):
        self.header, self.appended = header, []

    def table(self, name):
        return (self.header, [])

    def _append(self, name, header, rows):
        self.appended = rows


def test_a_new_entry_is_written_under_an_alias_header_with_its_address():
    """It used to be written as a blank address, which `covers` then skipped for ever."""
    store = RecordingStore(["Address", "Reason", "Added at", "Source"])
    store.append_suppression([{FIELD: "bob@acme.test", "Reason": "bounced",
                              "Added at": "2026-09-01", "Source": "sync"}])
    assert store.appended == [["bob@acme.test", "bounced", "2026-09-01", "sync"]]


def test_a_new_entry_is_written_under_the_canonical_header():
    store = RecordingStore(list(SUPPRESSION_HEADER))
    store.append_suppression([{FIELD: "bob@acme.test", "Reason": "bounced",
                              "Added at": "2026-09-01", "Source": "sync"}])
    assert store.appended == [["bob@acme.test", "bounced", "2026-09-01", "sync"]]


def test_a_header_with_no_address_column_is_refused_rather_than_written_to():
    store = RecordingStore(["Email", "Reason"])
    with pytest.raises(suppression.Unreadable):
        store.append_suppression([{FIELD: "bob@acme.test"}])
    assert store.appended == []


# --- the console, the fifth reader: it only shows, but it must not show a guess ------------------

def test_the_console_says_the_list_cannot_be_read_and_counts_nobody():
    """A broken list must not be drawn as "nobody is suppressed" with nothing said."""
    import console_fixture as fx

    from outreach import console_model
    store = MemoryStore(fx.rows(), events=fx.events(), suppression=unreadable(), runs=fx.runs(),
                        drafts=fx.draft_rows())
    data = console_model.snapshot(store, settings=dict(fx.SETTINGS), now=fx.NOW)
    assert data["suppression_count"] is None
    assert [w for w in data["warnings"]
            if "Suppression tab cannot be read" in w and "no Address or domain column" in w]


def test_the_console_counts_an_empty_list_as_nobody_suppressed_without_a_warning():
    import console_fixture as fx

    from outreach import console_model
    store = MemoryStore(fx.rows(), events=fx.events(), suppression=[], runs=fx.runs(),
                        drafts=fx.draft_rows())
    data = console_model.snapshot(store, settings=dict(fx.SETTINGS), now=fx.NOW)
    assert data["suppression_count"] == 0
    assert not [w for w in data["warnings"] if "Suppression" in w]
