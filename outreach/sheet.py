"""The only code that reads or writes the leads Sheet.

The founder's tabs keep a description in row 1 and column headers in row 2. Columns are
found by header name, never by position: tabs A and B have different layouts. Rows are
identified by Lead ID once assigned; sheet row numbers are only used within one job run,
and are re-verified immediately before writing.
"""

import re
from datetime import datetime, timezone

from googleapiclient.discovery import build

from outreach import suppression
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
# The console's drafts (outreach/drafts.py): one row per lead's first email, written and checked.
DRAFTS_TAB = "Drafts"
DRAFTS_HEADER = ["Lead ID", "Email", "To", "Company", "Subject", "Body", "Opening quote",
                 "Quote page", "Status", "Why", "Approval hash", "Handbook hash", "Written",
                 "Prepared at (UTC)"]
# Lead import's claim ledger: one append per lead a commit attempt intends to write, so concurrent
# writers are resolved to one (the earliest claim ATTEMPT wins). "Op key" is the durable idempotency
# key of the logical import; "Attempt" is unique per execution, so two attempts of the SAME operation
# (a shared key submitted twice at once) still resolve to a single writer.
CLAIMS_TAB = "Import claims"
CLAIMS_HEADER = ["Lead ID", "Op key", "Attempt", "Claimed at (UTC)"]
# Call outcomes and the tasks they schedule, as an append-only event log (outreach/calls.py). Each
# row is an OUTCOME or an ACTION; the Event ID makes a repeated submission a no-op.
CALLS_TAB = "Call log"
CALLS_HEADER = ["Event ID", "Lead ID", "Recorded at (UTC)", "Kind", "Outcome", "Note",
                "Called at (UTC)", "Due", "Due kind", "Email effect", "Detail"]


_SHEETS = None


def _api():
    """The Sheets client, built once per process and reused, with its connection.

    Building a fresh client (and so a fresh encrypted connection) for every scheduled run grew the
    deployed worker by about 55 MB a sync run until Cloud Run killed it (measured 2026-09-28).
    The credentials refresh themselves; the worker handles one request at a time."""
    global _SHEETS
    if _SHEETS is None:
        _SHEETS = build("sheets", "v4", credentials=founder_credentials(),
                        cache_discovery=False).spreadsheets()
    return _SHEETS


def now_utc():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def col_letter(index):
    """0-based column index -> A1 letters."""
    s, n = "", index + 1
    while n:
        n, r = divmod(n - 1, 26)
        s = chr(65 + r) + s
    return s


class DestinationMismatch(RuntimeError):
    """A write cannot go ahead because the tab's columns are not what the caller expected (a field
    would be lost). Nothing was written; the caller should re-read the columns and try again."""


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
        """The Suppression entries, through the one contract in `outreach/suppression.py`.

        Raises `suppression.Unreadable` when the list cannot be read: a missing tab, a header with
        no address column or with two of them, a row with no address in it, or a read that failed.
        An empty list is valid and means nobody is suppressed. The tab's own rows are read here
        rather than through `table`, which drops blank lines, so a refusal can name its row."""
        if SUPPRESSION_TAB not in self.titles:
            raise suppression.Unreadable(f"there is no {SUPPRESSION_TAB} tab in the Sheet")
        try:
            values = self.api.values().get(
                spreadsheetId=SHEET_ID, range=f"'{SUPPRESSION_TAB}'").execute().get("values", [])
        except suppression.Unreadable:
            raise
        except Exception as exc:
            raise suppression.Unreadable(
                f"the {SUPPRESSION_TAB} tab could not be read ({type(exc).__name__})") from exc
        return suppression.of_values(values)

    def run_rows(self):
        """The Runs tab's rows, oldest first; none when there is no Runs tab."""
        table = self.table(RUNS_TAB)
        return table[1] if table else []

    def drafts(self):
        """The Drafts tab as [(sheet row, {column: value})]; none when there is no Drafts tab.

        Refuses a tab whose columns were changed: a draft read from the wrong column could be
        shown, or later sent, with the wrong words."""
        if DRAFTS_TAB not in self.titles:
            return []
        values = self.api.values().get(spreadsheetId=SHEET_ID,
                                       range=f"'{DRAFTS_TAB}'").execute().get("values", [])
        if not values:
            return []
        header = values[0]
        if header[:len(DRAFTS_HEADER)] != DRAFTS_HEADER:
            raise RuntimeError("the Drafts tab's columns were changed; it is neither read nor written")
        return [(number, {h: (raw[i] if i < len(raw) else "") for i, h in enumerate(header) if h})
                for number, raw in enumerate(values[1:], start=2)
                if any(str(cell).strip() for cell in raw)]

    def write_drafts(self, new, replace=None):
        """Append `new` rows, and rewrite each of `replace` ({sheet row: row}) in place, as plain
        text (a body starting with "=" never becomes a formula). A row is rewritten only if it
        still holds the same lead; if any has moved, nothing is rewritten."""
        replace = replace or {}
        if replace:
            current = dict(self.drafts())
            moved = [n for n, row in replace.items()
                     if current.get(n, {}).get("Lead ID") != row["Lead ID"]]
            if moved:
                raise RuntimeError(f"Drafts rows {moved} changed while drafts were being written; "
                                   f"nothing was rewritten")
            self.api.values().batchUpdate(spreadsheetId=SHEET_ID, body={
                "valueInputOption": "RAW",
                "data": [{"range": f"'{DRAFTS_TAB}'!A{n}", "values": [[row.get(h, "") for h in DRAFTS_HEADER]]}
                         for n, row in sorted(replace.items())]}).execute()
        self._append(DRAFTS_TAB, DRAFTS_HEADER, [[row.get(h, "") for h in DRAFTS_HEADER] for row in new])

    def last_cursor(self):
        """Where the last completed sync stopped reading, from its Runs row."""
        for row in reversed(self.run_rows()):
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
        """New entries, written under the tab's own header.

        `suppression.cell` puts the address in whichever column the header uses for it, so a tab
        headed with an alias is not given a row with a blank address; a header with no address
        column at all is refused rather than written to."""
        if not entries:
            return
        table = self.table(SUPPRESSION_TAB)
        header = table[0] if table and table[0] else SUPPRESSION_HEADER
        suppression.address_column(header)
        self._append(SUPPRESSION_TAB, SUPPRESSION_HEADER,
                     [[suppression.cell(e, h) for h in header] for e in entries])

    def lead_columns(self, prefix):
        """The header of the lead tab for `prefix` (e.g. "A"), so an import can show which fields the
        destination can store before anything is written."""
        name = next((tab for tab, pref in LEAD_TABS.items() if pref == str(prefix).strip().upper()),
                    None)
        if name is None:
            raise RuntimeError(f"{prefix} is not a lead tab prefix")
        return list(next(tab.header for tab in self.tabs if tab.name == name))

    def append_leads(self, prefix, rows):
        """Append new lead rows to the tab for `prefix` (e.g. "A") and return their Lead IDs.

        Each row must already carry an immutable **Lead ID** (assigned before the write, by the import
        preview). The row - Lead ID and all - is written in a **single append**, so there is no
        half-written row and no second, position-based write that a sort could send to the wrong lead.
        New rows only: existing rows are never rewritten or reordered. It refuses (`DestinationMismatch`)
        rather than silently drop a field the tab has no column for. Returns the Lead IDs, in row order."""
        if not rows:
            return []
        name = next((tab for tab, pref in LEAD_TABS.items() if pref == str(prefix).strip().upper()),
                    None)
        if name is None:
            raise RuntimeError(f"{prefix} is not a lead tab prefix")
        header = next(tab.header for tab in self.tabs if tab.name == name)
        if "Lead ID" not in header:
            raise RuntimeError(f"{name} has no Lead ID column; leads cannot be written")
        for row in rows:
            if not str(row.get("Lead ID", "")).strip():
                raise RuntimeError("a lead row has no Lead ID; import must assign one before writing")
            lost = sorted(k for k, v in row.items() if str(v).strip() and k not in header)
            if lost:
                raise DestinationMismatch(
                    f"{name} has no column for {', '.join(lost)}; nothing was written. "
                    f"Preview the list again against the current columns.")
        # Recheck presence immediately before writing, from a FRESH read, and skip any Lead ID that is
        # already there. This bounds a late-completing earlier attempt: whichever append runs second
        # sees the row and does not add a second copy. Returns only the ids actually written now.
        present = {row.get("Lead ID", "") for _, row in Tab(self.api, name, SYSTEM_COLUMNS).rows}
        fresh = [row for row in rows if row["Lead ID"] not in present]
        if not fresh:
            return []
        self.api.values().append(
            spreadsheetId=SHEET_ID, range=f"'{name}'!A{HEADER_ROW}", valueInputOption="RAW",
            insertDataOption="INSERT_ROWS",
            body={"values": [[row.get(h, "") for h in header] for row in fresh]}).execute()
        return [row["Lead ID"] for row in fresh]

    def call_events(self):
        """Every Call log row, oldest first; [] when there is no Call log tab. Refuses a tab whose
        columns were changed, so an event is never read from the wrong column."""
        table = self.table(CALLS_TAB)
        if table is None:
            return []
        header, rows = table
        if header[:len(CALLS_HEADER)] != CALLS_HEADER:
            raise RuntimeError("the Call log tab's columns were changed; it is neither read nor written")
        return rows

    def append_call_events(self, events):
        """Append call events, skipping any whose Event ID is already present (so a repeated submission
        adds nothing). Returns the Event IDs actually written."""
        events = [dict(e) for e in events]
        if not events:
            return []
        present = {row.get("Event ID", "") for row in self.call_events()}
        fresh, seen = [], set(present)
        for event in events:
            eid = event.get("Event ID", "")
            if eid and eid not in seen:
                fresh.append(event)
                seen.add(eid)
        if not fresh:
            return []
        self._append(CALLS_TAB, CALLS_HEADER, [[e.get(h, "") for h in CALLS_HEADER] for e in fresh])
        return [e["Event ID"] for e in fresh]

    def claim_leads(self, lead_ids, op_key, attempt):
        """Resolve who may write each of `lead_ids`, and return a per-lead classification.

        Duplicate prevention without a database. Each intended Lead ID is appended to the append-only
        claims ledger with this commit's `op_key` (the durable identity of the logical import) and
        `attempt` (unique to THIS execution). The ledger is read back and, for each lead, the EARLIEST
        claim (lowest row) is the owner:
          - "won": the earliest claim is this very attempt -> this commit writes the lead;
          - "mine_prior": the earliest claim is an EARLIER attempt of the SAME operation (a retry or a
            resume of my own import) -> I do not write it now; a resume may take it over deliberately;
          - "other": the earliest claim belongs to a DIFFERENT operation -> another submission owns it.
        Two attempts of the same operation submitted at once get different `attempt`s, so exactly one is
        earliest and writes; the other is "mine_prior" and does not (this is what a shared key alone
        could not do). Raises if the ledger cannot be read (fail-closed)."""
        wanted = [lid for lid in dict.fromkeys(lead_ids) if lid]
        if not wanted:
            return {}
        now = now_utc()
        self._append(CLAIMS_TAB, CLAIMS_HEADER, [[lid, op_key, attempt, now] for lid in wanted])
        table = self.table(CLAIMS_TAB)
        if table is None:
            raise RuntimeError("the import claims ledger could not be read; nothing was written")
        _, rows = table
        earliest = {}
        for row in rows:
            lid = row.get("Lead ID", "")
            if lid and lid not in earliest:
                earliest[lid] = (row.get("Op key", ""), row.get("Attempt", ""))
        result = {}
        for lid in wanted:
            owner_op, owner_attempt = earliest.get(lid, ("", ""))
            if owner_attempt == attempt:
                result[lid] = "won"
            elif owner_op == op_key:
                result[lid] = "mine_prior"
            else:
                result[lid] = "other"
        return result

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
