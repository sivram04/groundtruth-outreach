"""The only code that reads or writes the leads Sheet.

The founder's tabs keep a description in row 1 and column headers in row 2. Columns are
found by header name, never by position: tabs A and B have different layouts.
"""

from datetime import datetime, timezone

from googleapiclient.discovery import build

from outreach.google_auth import founder_credentials

SHEET_ID = "1eEVkxc0gJMFptYSr_u9prQ5O850TOX28AEq17CKaFiA"
LEAD_TABS = ["A_Contact_Now", "B_Contact_Now"]
HEADER_ROW = 2
RUNS_TAB = "Runs"
RUNS_HEADER = ["Run at (UTC)", "Job", "Where", "Result", "Detail"]


def _api():
    return build("sheets", "v4", credentials=founder_credentials(), cache_discovery=False).spreadsheets()


def lead_rows(api, tab):
    values = api.values().get(spreadsheetId=SHEET_ID, range=f"'{tab}'").execute().get("values", [])
    header = values[HEADER_ROW - 1] if len(values) >= HEADER_ROW else []
    rows = [r for r in values[HEADER_ROW:] if any(c.strip() for c in r)]
    return header, rows


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
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    api.values().append(
        spreadsheetId=SHEET_ID, range=f"'{RUNS_TAB}'!A1", valueInputOption="RAW",
        insertDataOption="INSERT_ROWS", body={"values": [[now, job, where, result, detail]]},
    ).execute()


def ping(where):
    """Stage 0: prove the worker can read the leads and write to the Sheet."""
    api = _api()
    counts = {tab: len(lead_rows(api, tab)[1]) for tab in LEAD_TABS}
    detail = ", ".join(f"{t}: {n} leads" for t, n in counts.items())
    append_run(api, "ping", where, "OK", detail)
    return counts
