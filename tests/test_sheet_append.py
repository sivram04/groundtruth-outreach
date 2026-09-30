"""The real Store.append_leads adapter, against a simulated Sheets API.

This does what a MemoryStore test cannot: it drives the production code path in `outreach/sheet.py`
through a stand-in for Google's Sheets client, so column ordering, a missing destination column and a
failing append are all exercised on the code that actually talks to the Sheet.
"""

import pytest

from outreach.sheet import Store

# The A tab has a Phone column; the B tab does not, so a phone has nowhere to go there.
A_HEADER = ["Company", "Decision maker", "BEST EMAIL", "Website", "Phone", "Lead ID"]
B_HEADER = ["Company", "Decision maker", "BEST EMAIL", "Website", "Lead ID"]


class _Exec:
    def __init__(self, value):
        self.value = value

    def execute(self):
        return self.value


class FakeValues:
    def __init__(self, parent):
        self.parent = parent

    def get(self, spreadsheetId, range):
        name = range.split("!")[0].strip().strip("'")
        return _Exec({"values": self.parent.tabs[name]})

    def append(self, spreadsheetId, range, valueInputOption, insertDataOption, body):
        if self.parent.fail_append:
            raise RuntimeError("the append call failed")
        name = range.split("!")[0].strip().strip("'")
        self.parent.appended.append((name, valueInputOption, insertDataOption,
                                     [list(r) for r in body["values"]]))
        for row in body["values"]:
            self.parent.tabs[name].append(list(row))
        return _Exec({"updates": {"updatedRows": len(body["values"])}})


class FakeSheets:
    """Just enough of spreadsheets(): .get for the titles, .values().get / .append per tab."""

    def __init__(self):
        self.tabs = {
            "A_Contact_Now": [["A tab"], list(A_HEADER),
                              ["Example Electric", "Sam", "sam@example-electric.test", "", "", "A-0001"]],
            "B_Contact_Now": [["B tab"], list(B_HEADER)],
        }
        self.appended = []
        self.fail_append = False

    def get(self, spreadsheetId):
        return _Exec({"sheets": [{"properties": {"title": t}} for t in self.tabs]})

    def values(self):
        return FakeValues(self)


def test_lead_columns_returns_the_tabs_own_header():
    store = Store(api=FakeSheets())
    assert store.lead_columns("A") == A_HEADER
    assert store.lead_columns("B") == B_HEADER
    with pytest.raises(RuntimeError):
        store.lead_columns("Z")


def test_append_leads_writes_in_the_tabs_column_order():
    api = FakeSheets()
    store = Store(api=api)
    store.append_leads("A", [{"Lead ID": "A-0002", "Company": "Acme", "BEST EMAIL": "pat@acme.test",
                              "Phone": "614-555-0100"}])
    name, value_input, insert, values = api.appended[0]
    assert name == "A_Contact_Now" and value_input == "RAW" and insert == "INSERT_ROWS"
    # values are in the tab's header order, blanks where the row said nothing - never the dict's order
    assert values == [["Acme", "", "pat@acme.test", "", "614-555-0100", "A-0002"]]


def test_append_leads_drops_a_field_the_destination_cannot_store():
    api = FakeSheets()
    store = Store(api=api)
    # The B tab has no Phone column: the phone is not written (the preview is what warns the user).
    store.append_leads("B", [{"Lead ID": "B-0004", "Company": "Redwood", "Phone": "614-555-0142"}])
    _, _, _, values = api.appended[0]
    assert values == [["Redwood", "", "", "", "B-0004"]]  # header order, no Phone column at all


def test_append_leads_appends_only_and_leaves_existing_rows_untouched():
    api = FakeSheets()
    store = Store(api=api)
    before = [list(r) for r in api.tabs["A_Contact_Now"]]
    store.append_leads("A", [{"Lead ID": "A-0002", "Company": "Acme"}])
    # the description, header and the existing A-0001 row are unchanged; the new row is appended after
    assert api.tabs["A_Contact_Now"][: len(before)] == before
    assert api.tabs["A_Contact_Now"][-1][-1] == "A-0002"


def test_append_leads_surfaces_a_failed_append():
    api = FakeSheets()
    api.fail_append = True
    store = Store(api=api)
    with pytest.raises(RuntimeError):
        store.append_leads("A", [{"Lead ID": "A-0002", "Company": "Acme"}])


def test_append_leads_refuses_an_unknown_prefix():
    store = Store(api=FakeSheets())
    with pytest.raises(RuntimeError):
        store.append_leads("Z", [{"Lead ID": "Z-0001", "Company": "Acme"}])


def test_append_leads_writes_nothing_for_an_empty_list():
    api = FakeSheets()
    Store(api=api).append_leads("A", [])
    assert api.appended == []
