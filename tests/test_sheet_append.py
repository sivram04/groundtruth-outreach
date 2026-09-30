"""The real Store.append_leads adapter, against a simulated Sheets API.

This drives the production code path in `outreach/sheet.py` through a stand-in for Google's Sheets
client, so column ordering, **row-based Lead ID allocation from the atomic append**, a refused field
loss and a failing append are all exercised on the code that actually talks to the Sheet. The fake is
thread-safe and serializes appends, the way Google's `values().append` does, so the concurrency
regression in `test_console_import.py` can rely on it.
"""

import re
import threading

import pytest

from outreach.sheet import DestinationMismatch, Store, col_letter

# The A tab has a Phone column; the B tab does not, so a phone has nowhere to go there.
A_HEADER = ["Company", "Decision maker", "BEST EMAIL", "Website", "Phone", "Lead ID"]
B_HEADER = ["Company", "Decision maker", "BEST EMAIL", "Website", "Lead ID"]
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
            return _Exec({"values": [list(r) for r in self.parent.tabs[name]]})

    def append(self, spreadsheetId, range, valueInputOption, insertDataOption, body):
        with self.parent.lock:
            if self.parent.fail_append:
                raise RuntimeError("the append call failed")
            name = range.split("!")[0].strip().strip("'")
            grid = self.parent.tabs[name]
            start = len(grid) + 1  # 1-based row the first appended row lands on
            for row in body["values"]:
                grid.append(list(row))
            width = max((len(r) for r in grid), default=1)
            updated = f"'{name}'!A{start}:{col_letter(width - 1)}{len(grid)}"
            self.parent.appended.append((name, valueInputOption, insertDataOption,
                                         [list(r) for r in body["values"]]))
            return _Exec({"updates": {"updatedRange": updated, "updatedRows": len(body["values"])}})

    def batchUpdate(self, spreadsheetId, body):
        with self.parent.lock:
            for item in body["data"]:
                name, cell = item["range"].split("!")
                name = name.strip().strip("'")
                match = _CELL.match(cell)
                col, row = _col_index(match.group(1)), int(match.group(2))
                grid = self.parent.tabs[name]
                while len(grid) < row:
                    grid.append([])
                while len(grid[row - 1]) <= col:
                    grid[row - 1].append("")
                grid[row - 1][col] = item["values"][0][0]
            return _Exec({})


class FakeSheets:
    """Just enough of spreadsheets(): .get for the titles, .values().get / .append / .batchUpdate.

    Thread-safe, and appends are serialized and report a distinct `updatedRange` each time, as the real
    Sheets API does."""

    def __init__(self):
        self.lock = threading.RLock()
        self.tabs = {
            "A_Contact_Now": [["A tab"], list(A_HEADER),
                              ["Example Electric", "Sam", "sam@example-electric.test", "", "", "A-0001"]],
            "B_Contact_Now": [["B tab"], list(B_HEADER)],
        }
        self.appended = []
        self.fail_append = False

    def get(self, spreadsheetId):
        with self.lock:
            return _Exec({"sheets": [{"properties": {"title": t}} for t in self.tabs]})

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


def test_lead_columns_returns_the_tabs_own_header():
    store = Store(api=FakeSheets())
    assert store.lead_columns("A") == A_HEADER
    assert store.lead_columns("B") == B_HEADER
    with pytest.raises(RuntimeError):
        store.lead_columns("Z")


def test_append_leads_assigns_a_row_based_id_and_writes_in_column_order():
    api = FakeSheets()
    ids = Store(api=api).append_leads("A", [{"Company": "Acme", "BEST EMAIL": "pat@acme.test",
                                             "Phone": "614-555-0100"}])
    # Existing A-0001 sits at row 3, so the new row lands at row 4 -> A-0002 (row 4 minus the 2 header
    # rows). The id comes from the row, not from a pre-read maximum.
    assert ids == ["A-0002"]
    assert api.row_for("A_Contact_Now", "A-0002") == {
        "Company": "Acme", "Decision maker": "", "BEST EMAIL": "pat@acme.test", "Website": "",
        "Phone": "614-555-0100", "Lead ID": "A-0002"}


def test_the_id_is_the_row_not_the_existing_maximum():
    api = FakeSheets()
    api.tabs["A_Contact_Now"][2] = ["Big Co", "", "big@co.test", "", "", "A-0009"]  # a sparse high id
    ids = Store(api=api).append_leads("A", [{"Company": "Acme", "BEST EMAIL": "pat@acme.test"}])
    assert ids == ["A-0002"]  # row 4, not max(9)+1


def test_append_leads_refuses_field_loss_rather_than_dropping():
    api = FakeSheets()
    # The B tab has no Phone column: rather than silently drop the phone, the append is refused.
    with pytest.raises(DestinationMismatch):
        Store(api=api).append_leads("B", [{"Company": "Redwood", "Phone": "614-555-0142"}])
    assert api.appended == []  # nothing was written


def test_append_leads_appends_only_and_leaves_existing_rows_untouched():
    api = FakeSheets()
    before = [list(r) for r in api.tabs["A_Contact_Now"]]
    Store(api=api).append_leads("A", [{"Company": "Acme", "BEST EMAIL": "a@acme.test"}])
    assert api.tabs["A_Contact_Now"][: len(before)] == before  # description, header, A-0001 unchanged
    assert api.row_for("A_Contact_Now", "A-0002")["Company"] == "Acme"


def test_append_leads_surfaces_a_failed_append():
    api = FakeSheets()
    api.fail_append = True
    with pytest.raises(RuntimeError):
        Store(api=api).append_leads("A", [{"Company": "Acme"}])


def test_append_leads_refuses_an_unknown_prefix():
    with pytest.raises(RuntimeError):
        Store(api=FakeSheets()).append_leads("Z", [{"Company": "Acme"}])


def test_append_leads_writes_nothing_for_an_empty_list():
    api = FakeSheets()
    assert Store(api=api).append_leads("A", []) == []
    assert api.appended == []
