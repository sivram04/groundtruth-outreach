"""The only code that reads or writes the leads Sheet.

The founder's tabs keep a description in row 1 and column headers in row 2. Columns are
found by header name, never by position: tabs A and B have different layouts. Rows are
identified by Lead ID once assigned; sheet row numbers are only used within one job run,
and are re-verified immediately before writing.
"""

import re
from datetime import datetime, timezone

from googleapiclient.discovery import build

from outreach.google_auth import founder_credentials

SHEET_ID = "1eEVkxc0gJMFptYSr_u9prQ5O850TOX28AEq17CKaFiA"
LEAD_TABS = {"A_Contact_Now": "A", "B_Contact_Now": "B"}  # tab -> Lead ID prefix
HEADER_ROW = 2
RUNS_TAB = "Runs"
RUNS_HEADER = ["Run at (UTC)", "Job", "Where", "Result", "Detail"]
CURSOR = re.compile(r"\bcursor (\S+)")

# Columns this code owns, added to the right of the founder's columns. Everything else in a
# lead tab is the founder's and is never written.
CHECK_COLUMNS = ["Lead ID", "Email check", "Reason", "Checked at"]
RESEARCH_COLUMNS = ["Fit", "Work mix", "Fit reason", "Fit evidence", "Researched at"]
PROFILE_COLUMNS = ["Profile status", "Offerings evidence", "Markets evidence", "Profile reason", "Profiled at"]
DRAFT_COLUMNS = ["Draft action", "Draft action at", "Draft status", "Draft hash",
                 "Draft quote ID", "Draft ID", "Draft link", "Drafted at", "Draft thread ID",
                 "Draft tracked"]
# Stage 4. "Outreach status", not "Status": a plain "Status" is too likely to be the name of a
# column of the founder's own.
SYNC_COLUMNS = ["Outreach status", "Sent to", "Sent at", "Replied at", "Follow-ups sent",
                "Last event", "Next action"]
FOLLOWUP_COLUMNS = ["Follow-up step", "Follow-up action", "Follow-up action at",
                    "Follow-up status", "Follow-up draft ID"]
# Stage 5. Blank until the lead has had an email this system drafted with tracking on.
TRACKING_COLUMNS = ["Tracked sends", "Opens (est.)", "Clicks"]
SYSTEM_COLUMNS = (CHECK_COLUMNS + RESEARCH_COLUMNS + PROFILE_COLUMNS + DRAFT_COLUMNS
                  + SYNC_COLUMNS + FOLLOWUP_COLUMNS + TRACKING_COLUMNS)
EVENTS_TAB = "Events"
EVENTS_HEADER = ["Recorded at (UTC)", "Lead ID", "Event", "Step", "Occurred at (UTC)", "Address",
                 "Match", "Detail", "Thread ID", "Gmail message ID", "Event key"]
SUPPRESSION_TAB = "Suppression"
SUPPRESSION_HEADER = ["Address or domain", "Reason", "Added at", "Source"]


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


def founder_column_clash(tab, names):
    """System column names that already exist among the founder's columns.

    Every system column is added to the right of `Lead ID`, the first one stage 1 added, so a
    header of the same name to its left is the founder's own. Writing there would overwrite it.
    Without a `Lead ID` column there is no telling, so every name counts as a clash.
    """
    if "Lead ID" not in tab.header:
        return list(names)
    founder = tab.header[:tab.header.index("Lead ID")]
    return [name for name in names if name in founder]


class Store:
    """The Sheet as the stage 4 jobs see it: the lead tabs, Events, Suppression and Runs, read
    once at the start of a run. Tests use an in-memory double with the same methods."""

    def __init__(self, api=None):
        self.api = api or _api()
        self.titles = {s["properties"]["title"]
                       for s in self.api.get(spreadsheetId=SHEET_ID).execute()["sheets"]}
        self.tabs = [Tab(self.api, name, SYSTEM_COLUMNS) for name in LEAD_TABS]

    def leads(self):
        return {row["Lead ID"]: row for tab in self.tabs for _, row in tab.rows if row.get("Lead ID")}

    def table(self, name):
        """(header, rows) of a tab whose header is in row 1, or None when there is no such tab."""
        if name not in self.titles:
            return None
        values = self.api.values().get(spreadsheetId=SHEET_ID, range=f"'{name}'").execute().get("values", [])
        if not values:
            return [], []
        header = values[0]
        rows = [{h: (row[i] if i < len(row) else "") for i, h in enumerate(header) if h}
                for row in values[1:] if any(str(cell).strip() for cell in row)]
        return header, rows

    def events(self):
        table = self.table(EVENTS_TAB)
        if table is None:
            return []
        header, rows = table
        # Columns the founder adds to the right are harmless; any change to ours is not.
        if header and header[:len(EVENTS_HEADER)] != EVENTS_HEADER:
            raise RuntimeError("the Events tab's columns were changed; it is neither read nor written")
        return rows

    def suppression(self):
        """The Suppression entries, or None when the tab is missing: unknown, never empty."""
        table = self.table(SUPPRESSION_TAB)
        if table is None or "Address or domain" not in table[0]:
            return None
        return table[1]

    def last_cursor(self):
        """Where the last completed sync stopped reading, from its Runs row."""
        table = self.table(RUNS_TAB)
        for row in reversed(table[1] if table else []):
            if row.get("Job") == "sync" and row.get("Result") in ("OK", "PARTIAL"):
                found = CURSOR.search(row.get("Detail", ""))
                if found:
                    return datetime.fromisoformat(found.group(1).replace("Z", "+00:00"))
        return None

    def _append(self, name, header, rows):
        if not rows:
            return
        ensure_tab(self.api, name, header)
        self.titles.add(name)
        self.api.values().append(
            spreadsheetId=SHEET_ID, range=f"'{name}'!A1", valueInputOption="RAW",
            insertDataOption="INSERT_ROWS", body={"values": rows}).execute()

    def append_events(self, events):
        self._append(EVENTS_TAB, EVENTS_HEADER, [[e.get(h, "") for h in EVENTS_HEADER] for e in events])

    def append_suppression(self, entries):
        table = self.table(SUPPRESSION_TAB)
        header = table[0] if table and table[0] else SUPPRESSION_HEADER
        self._append(SUPPRESSION_TAB, SUPPRESSION_HEADER, [[e.get(h, "") for h in header] for e in entries])

    def write_leads(self, updates, columns):
        """updates: {Lead ID: {system column: value}}. Returns (written, skipped reasons)."""
        written, skipped = 0, []
        for tab in self.tabs:
            wanted = {number: updates[row["Lead ID"]] for number, row in tab.rows
                      if row.get("Lead ID") in updates}
            if not wanted:
                continue
            clash = founder_column_clash(tab, columns)
            if clash:
                raise RuntimeError(f"{tab.name} already has founder columns named {clash}; "
                                   f"nothing was written")
            tab.ensure_columns(columns)
            result = tab.write(wanted)
            written += result["written"]
            skipped += [f"{tab.name} row {number}: {why}" for number, why in result["skipped"]]
        return written, skipped

    def fresh_lead(self, lead_id):
        """(tab, sheet row, values) for one lead, read again now."""
        name = {prefix: tab for tab, prefix in LEAD_TABS.items()}.get(lead_id.split("-", 1)[0])
        if not name:
            raise RuntimeError(f"{lead_id} is not a lead ID")
        tab = Tab(self.api, name, SYSTEM_COLUMNS)
        found = [(number, row) for number, row in tab.rows if row.get("Lead ID") == lead_id]
        if len(found) != 1:
            raise RuntimeError(f"{lead_id}: {len(found)} rows found")
        return tab, found[0][0], found[0][1]

    def run_row(self, job, where, result, detail):
        append_run(self.api, job, where, result, detail)
