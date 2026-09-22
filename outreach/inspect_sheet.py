"""Read-only look at the leads Sheet: tabs, headers, row counts, a few sample values.

    python -m outreach.inspect_sheet
"""

from googleapiclient.discovery import build

from outreach.google_auth import founder_credentials
from outreach.sheet import SHEET_ID


def main():
    sheets = build("sheets", "v4", credentials=founder_credentials()).spreadsheets()
    meta = sheets.get(spreadsheetId=SHEET_ID).execute()
    print("Title:", meta["properties"]["title"])
    for tab in meta["sheets"]:
        p = tab["properties"]
        name = p["title"]
        values = sheets.values().get(spreadsheetId=SHEET_ID, range=f"'{name}'").execute().get("values", [])
        print(f"\n== {name}  ({len(values)} rows incl. header, grid {p['gridProperties']['rowCount']}x{p['gridProperties']['columnCount']})")
        if not values:
            continue
        header = values[0]
        filled = [sum(1 for r in values[1:] if i < len(r) and r[i].strip()) for i in range(len(header))]
        for i, h in enumerate(header):
            print(f"  {i+1:>2}. {h!r}  filled {filled[i]}/{len(values)-1}")


if __name__ == "__main__":
    main()
