"""One-off, founder-approved 2026-09-22: remove unneeded columns from tabs A and B,
and name tab A's unlabelled "Sent email on ..." column `Sent by hand`.

Every column is re-verified immediately before deletion: an empty column must still be
empty, a constant column must still hold only its one value. Anything unexpected aborts
the whole run with nothing changed.

    python -m tools.tidy_columns_2026_09_22            # dry run
    python -m tools.tidy_columns_2026_09_22 --apply
"""

import sys

from outreach.sheet import HEADER_ROW, SHEET_ID, _api

# (tab, header, 0-based position when approved, expectation)
# expectation: "empty" | ("const", value) | "any"
DELETE = [
    ("A_Contact_Now", "", 22, "empty"),                    # W
    ("A_Contact_Now", "", 25, "empty"),                    # Z
    ("A_Contact_Now", "Sheet", 3, ("const", "A")),
    ("A_Contact_Now", "Commercial confidence", 23, ("const", "HIGH")),
    ("A_Contact_Now", "Apollo lookup", 7, "any"),
    ("B_Contact_Now", "Strong proof", 26, "empty"),
    ("B_Contact_Now", "Sheet", 3, ("const", "B")),
    ("B_Contact_Now", "Commercial confidence", 24, ("const", "MEDIUM")),
    ("B_Contact_Now", "Apollo lookup", 8, "any"),
    ("B_Contact_Now", "Bucket", 7, "any"),
]
RENAME = ("A_Contact_Now", 24, "Sent by hand")  # Y: currently no header, holds "Sent email on ..."


def column(rows, i):
    return [r[i].strip() for r in rows if i < len(r) and r[i].strip()]


def main(apply):
    api = _api()
    meta = api.get(spreadsheetId=SHEET_ID).execute()
    ids = {s["properties"]["title"]: s["properties"]["sheetId"] for s in meta["sheets"]}

    data = {}
    for tab in {d[0] for d in DELETE}:
        values = api.values().get(spreadsheetId=SHEET_ID, range=f"'{tab}'").execute()["values"]
        data[tab] = (values[HEADER_ROW - 1], values[HEADER_ROW:])

    problems = []
    for tab, name, pos, expect in DELETE:
        header, rows = data[tab]
        got = header[pos] if pos < len(header) else ""
        if got != name:
            problems.append(f"{tab} col {pos+1}: header is {got!r}, expected {name!r}")
            continue
        vals = column(rows, pos)
        if expect == "empty" and vals:
            problems.append(f"{tab} col {pos+1}: expected empty, has {len(vals)} values")
        if isinstance(expect, tuple) and set(vals) != {expect[1]}:
            problems.append(f"{tab} {name!r}: expected only {expect[1]!r}, found {sorted(set(vals))[:5]}")
        print(f"delete {tab} col {pos+1} {name!r}: {len(vals)} filled cells")

    tab, pos, new = RENAME
    header, rows = data[tab]
    vals = column(rows, pos)
    if (header[pos] if pos < len(header) else "") != "" or not all(v.startswith("Sent email on") for v in vals):
        problems.append(f"{tab} col {pos+1}: not the unlabelled 'Sent email on' column")
    print(f"rename {tab} col {pos+1} -> {new!r} ({len(vals)} sent marks kept)")

    if problems:
        sys.exit("ABORTED, nothing changed:\n" + "\n".join(problems))
    if not apply:
        print("dry run: nothing changed")
        return

    # Name the column first, while positions are still as verified.
    api.values().update(
        spreadsheetId=SHEET_ID, range=f"'{tab}'!{chr(ord('A') + pos)}{HEADER_ROW}",
        valueInputOption="RAW", body={"values": [[new]]},
    ).execute()

    # Delete right-to-left within each tab so earlier positions do not shift.
    requests = [
        {"deleteDimension": {"range": {"sheetId": ids[t], "dimension": "COLUMNS", "startIndex": p, "endIndex": p + 1}}}
        for t, _, p, _ in sorted(DELETE, key=lambda d: (d[0], -d[2]))
    ]
    api.batchUpdate(spreadsheetId=SHEET_ID, body={"requests": requests}).execute()
    print("applied")


if __name__ == "__main__":
    main("--apply" in sys.argv)
