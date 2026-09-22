"""The only code that reads or writes the leads Sheet.

The founder's tabs keep a description in row 1 and column headers in row 2. Columns are
found by header name, never by position: tabs A and B have different layouts. Rows are
identified by Lead ID once assigned; sheet row numbers are only used within one job run,
and are re-verified immediately before writing.
"""

from datetime import datetime, timezone

from googleapiclient.discovery import build

from outreach.google_auth import founder_credentials

SHEET_ID = "1eEVkxc0gJMFptYSr_u9prQ5O850TOX28AEq17CKaFiA"
LEAD_TABS = {"A_Contact_Now": "A", "B_Contact_Now": "B"}  # tab -> Lead ID prefix
HEADER_ROW = 2
RUNS_TAB = "Runs"
RUNS_HEADER = ["Run at (UTC)", "Job", "Where", "Result", "Detail"]


def _api():
    return build("sheets", "v4", credentials=founder_credentials(), cache_discovery=False).spreadsheets()


def now_utc():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def col_letter(index):
    """0-based column index -> A1 letters."""
    s, n = "", index + 1
    while n:
        n, r = divmod(n - 1, 26)
        s = chr(65 + r) + s
    return s


class Tab:
    """One lead tab, read once. `rows` holds (sheet_row_number, {header: value})."""

    def __init__(self, api, name):
        self.api, self.name = api, name
        values = api.values().get(spreadsheetId=SHEET_ID, range=f"'{name}'").execute().get("values", [])
        self.header = values[HEADER_ROW - 1] if len(values) >= HEADER_ROW else []
        self.rows = []
        for offset, raw in enumerate(values[HEADER_ROW:]):
            if any(c.strip() for c in raw):
                self.rows.append((HEADER_ROW + 1 + offset, {h: (raw[i].strip() if i < len(raw) else "")
                                                            for i, h in enumerate(self.header) if h}))

    def ensure_columns(self, names):
        """Add any missing system headers to the right of the last header. Never moves existing ones."""
        missing = [n for n in names if n not in self.header]
        if not missing:
            return
        start = len(self.header)
        grid = next(s for s in self.api.get(spreadsheetId=SHEET_ID).execute()["sheets"]
                    if s["properties"]["title"] == self.name)["properties"]
        need = start + len(missing) - grid["gridProperties"]["columnCount"]
        if need > 0:
            self.api.batchUpdate(spreadsheetId=SHEET_ID, body={"requests": [{"appendDimension": {
                "sheetId": grid["sheetId"], "dimension": "COLUMNS", "length": need}}]}).execute()
        self.api.values().update(
            spreadsheetId=SHEET_ID, range=f"'{self.name}'!{col_letter(start)}{HEADER_ROW}",
            valueInputOption="RAW", body={"values": [missing]},
        ).execute()
        self.header = self.header + missing

    def write(self, updates, guard_column):
        """updates: {sheet_row: {header: value}}. Aborts if any row's guard value changed since reading."""
        if not updates:
            return
        now = Tab(self.api, self.name)
        before = {r: v.get(guard_column, "") for r, v in self.rows}
        after = {r: v.get(guard_column, "") for r, v in now.rows}
        moved = [r for r in updates if before.get(r) != after.get(r)]
        if moved:
            raise RuntimeError(f"{self.name}: rows {moved[:5]} changed while the job ran; nothing written")
        data = [
            {"range": f"'{self.name}'!{col_letter(self.header.index(h))}{row}", "values": [[v]]}
            for row, cells in updates.items() for h, v in cells.items()
        ]
        self.api.values().batchUpdate(
            spreadsheetId=SHEET_ID, body={"valueInputOption": "RAW", "data": data}
        ).execute()


def ensure_tab(api, name, header):
    tabs = {t["properties"]["title"] for t in api.get(spreadsheetId=SHEET_ID).execute()["sheets"]}
    if name in tabs:
        return
    api.batchUpdate(spreadsheetId=SHEET_ID, body={"requests": [{"addSheet": {"properties": {"title": name}}}]}).execute()
    api.values().update(
        spreadsheetId=SHEET_ID, range=f"'{name}'!A1", valueInputOption="RAW", body={"values": [header]}
    ).execute()


def append_run(api, job, where, result, detail):
    ensure_tab(api, RUNS_TAB, RUNS_HEADER)
    api.values().append(
        spreadsheetId=SHEET_ID, range=f"'{RUNS_TAB}'!A1", valueInputOption="RAW",
        insertDataOption="INSERT_ROWS", body={"values": [[now_utc(), job, where, result, detail]]},
    ).execute()


def ping(where):
    """Stage 0: prove the worker can read the leads and write to the Sheet."""
    api = _api()
    counts = {tab: len(Tab(api, tab).rows) for tab in LEAD_TABS}
    detail = ", ".join(f"{t}: {n} leads" for t, n in counts.items())
    append_run(api, "ping", where, "OK", detail)
    return counts
