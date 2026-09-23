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

# Columns this code owns, added to the right of the founder's columns. Everything else in a
# lead tab is the founder's and is never written.
CHECK_COLUMNS = ["Lead ID", "Email check", "Reason", "Checked at"]
RESEARCH_COLUMNS = ["Fit", "Work mix", "Fit reason", "Fit evidence", "Researched at"]
PROFILE_COLUMNS = ["Profile status", "Offerings evidence", "Markets evidence", "Profile reason", "Profiled at"]
DRAFT_COLUMNS = ["Draft action", "Draft action at", "Draft status", "Draft hash", "Draft ID",
                 "Draft link", "Drafted at"]
SYSTEM_COLUMNS = CHECK_COLUMNS + RESEARCH_COLUMNS + PROFILE_COLUMNS + DRAFT_COLUMNS


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
    """One lead tab, read once. `rows` holds (sheet_row_number, {header: value}).

    `system_columns` are the columns this code owns. Everything else is the founder's, and a
    row's founder values together are its fingerprint: the evidence that a row found later is
    the same lead that was read."""

    def __init__(self, api, name, system_columns=()):
        self.api, self.name, self.system = api, name, set(system_columns)
        values = api.values().get(spreadsheetId=SHEET_ID, range=f"'{name}'").execute().get("values", [])
        self.header = values[HEADER_ROW - 1] if len(values) >= HEADER_ROW else []
        self.rows = []
        for offset, raw in enumerate(values[HEADER_ROW:]):
            if any(c.strip() for c in raw):
                self.rows.append((HEADER_ROW + 1 + offset, {h: (raw[i].strip() if i < len(raw) else "")
                                                            for i, h in enumerate(self.header) if h}))

    def fingerprint(self, values):
        return tuple((h, values.get(h, "")) for h in self.header if h and h not in self.system)

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

    def write(self, updates):
        """updates: {sheet_row_when_read: {system_header: value}}.

        Re-reads the tab and re-finds each lead before writing, so a sort, insert or edit made
        while the job ran cannot put a result on the wrong lead:
          - a lead that had a Lead ID is found by that ID, and must be the only row with it;
          - a lead without one is found by its full founder fingerprint, among rows still
            without an ID, and must match exactly one row;
          - either way its founder values must be unchanged, and the system cells about to be
            written must still hold what was read.
        Anything else is skipped, left blank, and picked up by the next run.
        Returns {"written": n, "skipped": [(sheet_row_when_read, why)]}."""
        result = {"written": 0, "skipped": []}
        if not updates:
            return result
        read = dict(self.rows)
        fresh = Tab(self.api, self.name, self.system)
        by_id, by_print = {}, {}
        for row, v in fresh.rows:
            if v.get("Lead ID"):
                by_id.setdefault(v["Lead ID"], []).append((row, v))
            else:
                by_print.setdefault(fresh.fingerprint(v), []).append((row, v))

        data = []
        for old_row, cells in updates.items():
            before = read[old_row]
            lead_id = before.get("Lead ID", "")
            matches = by_id.get(lead_id, []) if lead_id else by_print.get(self.fingerprint(before), [])
            if len(matches) != 1:
                why = "not found" if not matches else f"{len(matches)} rows match"
                result["skipped"].append((old_row, f"{lead_id or 'new lead'}: {why}"))
                continue
            row, now = matches[0]
            if fresh.fingerprint(now) != self.fingerprint(before):
                result["skipped"].append((old_row, f"{lead_id or 'new lead'}: founder columns changed"))
                continue
            if any(now.get(h, "") != before.get(h, "") for h in cells):
                result["skipped"].append((old_row, f"{lead_id or 'new lead'}: system columns changed"))
                continue
            data += [{"range": f"'{self.name}'!{col_letter(fresh.header.index(h))}{row}", "values": [[v]]}
                     for h, v in cells.items()]
            result["written"] += 1
        if data:
            self.api.values().batchUpdate(
                spreadsheetId=SHEET_ID, body={"valueInputOption": "RAW", "data": data}
            ).execute()
        return result


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
