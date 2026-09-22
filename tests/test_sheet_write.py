"""The write safeguard: results must land on the lead they were computed for, even if the
founder sorts, inserts or edits rows while a job runs — including rows sharing an email."""

import copy

from outreach.sheet import Tab

SYSTEM = ["Lead ID", "Email check", "Reason", "Checked at"]
HEADER = ["Company", "City", "BEST EMAIL", "Lead ID", "Email check", "Reason", "Checked at"]


class FakeSheets:
    """Just enough of the Sheets API: values().get / batchUpdate on one tab."""

    def __init__(self, rows):
        self.grid = [["description"], HEADER] + [list(r) for r in rows]
        self.after_first_read = None  # callable run once, after the job's first read

    # api.values()
    def values(self):
        return self

    def get(self, spreadsheetId, range):
        grid = copy.deepcopy(self.grid)
        if self.after_first_read:
            hook, self.after_first_read = self.after_first_read, None
            hook(self)
        return _Exec({"values": grid})

    def batchUpdate(self, spreadsheetId, body):
        for item in body["data"]:
            cell = item["range"].split("!")[1]
            col = ord(cell[0]) - ord("A")
            row = int(cell[1:]) - 1
            while len(self.grid[row]) <= col:
                self.grid[row].append("")
            self.grid[row][col] = item["values"][0][0]
        return _Exec({})

    def lead(self, company, city):
        r = next(r for r in self.grid[2:] if r[0] == company and r[1] == city)
        return dict(zip(HEADER, r + [""] * (len(HEADER) - len(r))))


class _Exec:
    def __init__(self, v):
        self.v = v

    def execute(self):
        return self.v


# Two ARCO rows share one address, exactly as in the real Sheet.
ROWS = [
    ["ARCO HOME SERVICES", "BEDFORD HEIGHTS", "brian@goarco.com", "B-0001", "", "", ""],
    ["ARCO HOME SERVICES LLC", "Cleveland", "brian@goarco.com", "B-0002", "", "", ""],
    ["BLUE STAR ELECTRIC", "Lakewood", "hank@bluestar.net", "B-0003", "", "", ""],
]


def job(api, results):
    """Read, compute per Lead ID, write — like the real job."""
    tab = Tab(api, "B", SYSTEM)
    updates = {row: {"Email check": results[v["Lead ID"]]} for row, v in tab.rows}
    return tab.write(updates)


RESULTS = {"B-0001": "OK", "B-0002": "DUPLICATE", "B-0003": "RISKY"}


def test_plain_run_writes_every_row():
    api = FakeSheets(ROWS)
    assert job(api, RESULTS)["written"] == 3
    assert api.lead("ARCO HOME SERVICES LLC", "Cleveland")["Email check"] == "DUPLICATE"


def test_sort_during_run_still_lands_on_the_right_lead():
    api = FakeSheets(ROWS)
    api.after_first_read = lambda s: s.grid.__setitem__(slice(2, None), s.grid[2:][::-1])
    r = job(api, RESULTS)
    assert r["written"] == 3
    assert api.lead("ARCO HOME SERVICES", "BEDFORD HEIGHTS")["Email check"] == "OK"
    assert api.lead("ARCO HOME SERVICES LLC", "Cleveland")["Email check"] == "DUPLICATE"
    assert api.lead("BLUE STAR ELECTRIC", "Lakewood")["Email check"] == "RISKY"


def test_swapping_rows_that_share_an_email_cannot_cross_results():
    # The old guard compared only BEST EMAIL by row number, so this swap went undetected.
    api = FakeSheets(ROWS)

    def swap(s):
        s.grid[2], s.grid[3] = s.grid[3], s.grid[2]
    api.after_first_read = swap
    job(api, RESULTS)
    assert api.lead("ARCO HOME SERVICES", "BEDFORD HEIGHTS")["Email check"] == "OK"
    assert api.lead("ARCO HOME SERVICES LLC", "Cleveland")["Email check"] == "DUPLICATE"


def test_founder_edit_during_run_skips_that_row_only():
    api = FakeSheets(ROWS)
    api.after_first_read = lambda s: s.grid[4].__setitem__(2, "hank@newdomain.com")
    r = job(api, RESULTS)
    assert r["written"] == 2 and "founder columns changed" in r["skipped"][0][1]
    assert api.lead("BLUE STAR ELECTRIC", "Lakewood")["Email check"] == ""


def test_row_inserted_above_during_run():
    api = FakeSheets(ROWS)
    api.after_first_read = lambda s: s.grid.insert(2, ["NEW CO", "Columbus", "a@new.com", "", "", "", ""])
    r = job(api, RESULTS)
    assert r["written"] == 3
    assert api.lead("NEW CO", "Columbus")["Email check"] == ""
    assert api.lead("BLUE STAR ELECTRIC", "Lakewood")["Email check"] == "RISKY"


def test_deleted_row_is_skipped():
    api = FakeSheets(ROWS)
    api.after_first_read = lambda s: s.grid.pop(3)
    r = job(api, RESULTS)
    assert r["written"] == 2 and "not found" in r["skipped"][0][1]


def test_copied_lead_id_is_ambiguous_and_skipped():
    api = FakeSheets(ROWS)
    api.after_first_read = lambda s: s.grid.append(list(s.grid[4]))
    r = job(api, RESULTS)
    assert any("2 rows match" in why for _, why in r["skipped"])


def test_new_leads_matched_by_full_fingerprint_not_email():
    rows = [[*r[:3], "", "", "", ""] for r in ROWS]  # no Lead IDs yet
    api = FakeSheets(rows)

    def swap(s):
        s.grid[2], s.grid[3] = s.grid[3], s.grid[2]
    api.after_first_read = swap
    tab = Tab(api, "B", SYSTEM)
    ids = {"BEDFORD HEIGHTS": "B-0001", "Cleveland": "B-0002", "Lakewood": "B-0003"}
    r = tab.write({row: {"Lead ID": ids[v["City"]]} for row, v in tab.rows})
    assert r["written"] == 3
    assert api.lead("ARCO HOME SERVICES", "BEDFORD HEIGHTS")["Lead ID"] == "B-0001"
    assert api.lead("ARCO HOME SERVICES LLC", "Cleveland")["Lead ID"] == "B-0002"


def test_identical_new_rows_are_ambiguous_and_skipped():
    rows = [["DUP CO", "X", "a@dup.com", "", "", "", ""], ["DUP CO", "X", "a@dup.com", "", "", "", ""]]
    api = FakeSheets(rows)
    tab = Tab(api, "B", SYSTEM)
    r = tab.write({row: {"Lead ID": f"B-{i}"} for i, (row, _) in enumerate(tab.rows)})
    assert r["written"] == 0 and len(r["skipped"]) == 2


def test_system_cell_filled_by_someone_else_is_not_overwritten():
    api = FakeSheets(ROWS)
    api.after_first_read = lambda s: s.grid[2].__setitem__(4, "RISKY")  # founder typed a result
    r = job(api, RESULTS)
    assert "system columns changed" in r["skipped"][0][1]
    assert api.lead("ARCO HOME SERVICES", "BEDFORD HEIGHTS")["Email check"] == "RISKY"
