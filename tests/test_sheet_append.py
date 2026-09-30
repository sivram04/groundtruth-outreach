"""The real Store.append_leads / claim_leads adapters, against a simulated Sheets API.

The fake supports the calls these methods make - titles, values().get / .append / .update, and
addSheet via batchUpdate - and is thread-safe with serialized appends, like Google's. So the single
append of a pre-assigned Lead ID, the refusal of field loss, and the claim ledger (earliest claim wins)
are all exercised on the code that actually talks to the Sheet.
"""

import re
import threading

import pytest

from outreach.sheet import CLAIMS_TAB, DestinationMismatch, Store

A_HEADER = ["Company", "Decision maker", "BEST EMAIL", "Website", "Phone", "Lead ID"]
B_HEADER = ["Company", "Decision maker", "BEST EMAIL", "Website", "Lead ID"]
LEAD_TAB_NAMES = {"A_Contact_Now", "B_Contact_Now"}
_CELL = re.compile(r"^([A-Za-z]+)(\d+)$")


def _col_index(letters):
    index = 0
    for ch in letters.upper():
        index = index * 26 + (ord(ch) - ord("A") + 1)
    return index - 1


class _Exec:
    def __init__(self, value):
        self.value = value

    def execute(self):
        return self.value


class FakeValues:
    def __init__(self, parent):
        self.parent = parent

    def get(self, spreadsheetId, range):
        with self.parent.lock:
            name = range.split("!")[0].strip().strip("'")
            return _Exec({"values": [list(r) for r in self.parent.tabs.get(name, [])]})

    def append(self, spreadsheetId, range, valueInputOption, insertDataOption, body):
        name = range.split("!")[0].strip().strip("'")
        # Pause the FIRST lead-tab append (a writer that is past its presence recheck but has not yet
        # committed), OUTSIDE the lock so other requests can proceed. Used to reproduce an overlap.
        if name in LEAD_TAB_NAMES and self.parent.pause_leads and not self.parent._paused_once:
            self.parent._paused_once = True
            self.parent.reached.set()
            self.parent.release.wait(timeout=10)
        with self.parent.lock:
            if self.parent.fail_append:
                raise RuntimeError("the append call failed")
            grid = self.parent.tabs.setdefault(name, [])
            for row in body["values"]:
                grid.append(list(row))
            self.parent.appends.append((name, [list(r) for r in body["values"]]))
            return _Exec({"updates": {"updatedRows": len(body["values"])}})

    def update(self, spreadsheetId, range, valueInputOption, body):
        with self.parent.lock:
            name, cell = range.split("!")
            name = name.strip().strip("'")
            match = _CELL.match(cell)
            col, row = _col_index(match.group(1)), int(match.group(2))
            grid = self.parent.tabs.setdefault(name, [])
            for offset, values in enumerate(body["values"]):
                while len(grid) < row + offset:
                    grid.append([])
                line = grid[row - 1 + offset]
                for i, value in enumerate(values):
                    while len(line) <= col + i:
                        line.append("")
                    line[col + i] = value
            return _Exec({})


class FakeSheets:
    """Titles via .get; values().get / .append / .update; addSheet via .batchUpdate. Thread-safe."""

    def __init__(self):
        self.lock = threading.RLock()
        self.tabs = {
            "A_Contact_Now": [["A tab"], list(A_HEADER),
                              ["Example Electric", "Sam", "sam@example-electric.test", "", "", "A-0001"]],
            "B_Contact_Now": [["B tab"], list(B_HEADER)],
        }
        self.appends = []
        self.fail_append = False
        # An optional one-shot pause of the first lead append, to reproduce an overlapping write.
        self.pause_leads = False
        self._paused_once = False
        self.reached = threading.Event()
        self.release = threading.Event()

    def get(self, spreadsheetId):
        with self.lock:
            return _Exec({"sheets": [{"properties": {"title": t}} for t in self.tabs]})

    def batchUpdate(self, spreadsheetId, body):
        with self.lock:
            for request in body.get("requests", []):
                if "addSheet" in request:
                    title = request["addSheet"]["properties"]["title"]
                    self.tabs.setdefault(title, [])
            return _Exec({})

    def values(self):
        return FakeValues(self)

    def row_for(self, name, lead_id):
        with self.lock:
            header = self.tabs[name][1]
            idx = header.index("Lead ID")
            for row in self.tabs[name][2:]:
                if len(row) > idx and row[idx] == lead_id:
                    return dict(zip(header, row + [""] * (len(header) - len(row))))
        return None

    def count(self, name, lead_id):
        with self.lock:
            header = self.tabs[name][1]
            idx = header.index("Lead ID")
            return sum(1 for row in self.tabs[name][2:] if len(row) > idx and row[idx] == lead_id)


def test_lead_columns_returns_the_tabs_own_header():
    store = Store(api=FakeSheets())
    assert store.lead_columns("A") == A_HEADER
    assert store.lead_columns("B") == B_HEADER
    with pytest.raises(RuntimeError):
        store.lead_columns("Z")


def test_append_leads_writes_the_row_with_its_own_id_in_one_operation():
    api = FakeSheets()
    ids = Store(api=api).append_leads("A", [{"Lead ID": "A-abc123", "Company": "Acme",
                                             "BEST EMAIL": "pat@acme.test", "Phone": "614-555-0100"}])
    assert ids == ["A-abc123"]  # the id the caller assigned, unchanged
    assert len(api.appends) == 1  # a single append; no second, position-based write
    assert api.row_for("A_Contact_Now", "A-abc123") == {
        "Company": "Acme", "Decision maker": "", "BEST EMAIL": "pat@acme.test", "Website": "",
        "Phone": "614-555-0100", "Lead ID": "A-abc123"}


def test_append_leads_refuses_a_row_with_no_id():
    with pytest.raises(RuntimeError):
        Store(api=FakeSheets()).append_leads("A", [{"Company": "Acme"}])  # id must be pre-assigned


def test_append_leads_refuses_field_loss_rather_than_dropping():
    api = FakeSheets()
    with pytest.raises(DestinationMismatch):  # B has no Phone column
        Store(api=api).append_leads("B", [{"Lead ID": "B-abc", "Company": "Redwood",
                                           "Phone": "614-555-0142"}])
    assert api.appends == []


def test_append_leads_leaves_existing_rows_and_ids_untouched():
    api = FakeSheets()
    before = [list(r) for r in api.tabs["A_Contact_Now"]]
    Store(api=api).append_leads("A", [{"Lead ID": "A-new1", "Company": "Acme"}])
    assert api.tabs["A_Contact_Now"][: len(before)] == before  # A-0001 and the header unchanged
    assert api.row_for("A_Contact_Now", "A-new1")["Company"] == "Acme"


def test_a_sort_cannot_move_an_id_because_there_is_no_second_write():
    # The old failure needed a second, position-based write. There is none now: one append, no
    # batchUpdate, so a concurrent sort cannot land an id on the wrong lead.
    api = FakeSheets()
    Store(api=api).append_leads("A", [{"Lead ID": "A-new1", "Company": "Acme"}])
    assert len(api.appends) == 1
    # even if rows are reordered afterwards, every row keeps the id it was written with
    grid = api.tabs["A_Contact_Now"]
    grid[2], grid[3] = grid[3], grid[2]
    assert api.row_for("A_Contact_Now", "A-0001")["Company"] == "Example Electric"
    assert api.row_for("A_Contact_Now", "A-new1")["Company"] == "Acme"


def test_append_leads_surfaces_a_failed_append():
    api = FakeSheets()
    api.fail_append = True
    with pytest.raises(RuntimeError):
        Store(api=api).append_leads("A", [{"Lead ID": "A-x", "Company": "Acme"}])


def test_append_leads_refuses_an_unknown_prefix():
    with pytest.raises(RuntimeError):
        Store(api=FakeSheets()).append_leads("Z", [{"Lead ID": "Z-x", "Company": "Acme"}])


def test_append_leads_writes_nothing_for_an_empty_list():
    api = FakeSheets()
    assert Store(api=api).append_leads("A", []) == []
    assert api.appends == []


def test_append_leads_skips_an_id_already_present():
    api = FakeSheets()
    store = Store(api=api)
    assert store.append_leads("A", [{"Lead ID": "A-abc", "Company": "Acme"}]) == ["A-abc"]
    # a late second writer of the same id writes nothing (the pre-append recheck skips it)
    assert store.append_leads("A", [{"Lead ID": "A-abc", "Company": "Acme"}]) == []
    assert api.count("A_Contact_Now", "A-abc") == 1


def test_claim_leads_classifies_won_mine_prior_and_other():
    api = FakeSheets()
    first = Store(api=api).claim_leads(["A-1", "A-2"], op_key="op-1", attempt="att-1")
    assert first == {"A-1": "won", "A-2": "won"}
    # a DIFFERENT operation: A-2 is owned by op-1 -> other; A-3 is new -> won
    second = Store(api=api).claim_leads(["A-2", "A-3"], op_key="op-2", attempt="att-2")
    assert second == {"A-2": "other", "A-3": "won"}
    # a LATER attempt of op-1 (a resume): its own earlier attempt owns A-1 -> mine_prior
    resume = Store(api=api).claim_leads(["A-1"], op_key="op-1", attempt="att-3")
    assert resume == {"A-1": "mine_prior"}
    assert CLAIMS_TAB in api.tabs


def test_two_attempts_of_the_same_operation_resolve_to_a_single_writer():
    api = FakeSheets()
    a = Store(api=api).claim_leads(["A-9"], op_key="op", attempt="att-a")  # first -> won
    b = Store(api=api).claim_leads(["A-9"], op_key="op", attempt="att-b")  # same op, later -> mine_prior
    assert a == {"A-9": "won"} and b == {"A-9": "mine_prior"}  # a shared key does not authorize both
