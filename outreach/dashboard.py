"""The Dashboard tab: formulas only, worked out by Sheets from the lead tabs and Events.

Every figure is the Sheet's own arithmetic on columns this system writes; nothing here is a
stored number. A lead column is found by its header, so a column the founder moves is still
found, and one that does not exist yet (the B tab before its first email) counts as nothing.

    python -m outreach.dashboard       # create the tab, or refresh the formulas in it
"""

import json

from outreach.sheet import EVENTS_TAB, SHEET_ID, _api

TAB = "Dashboard"
TITLE = ("Outreach dashboard. Formulas only, worked out from the lead tabs and Events; "
         "do not type here.")
TIERS = [("A_Contact_Now", "A-", "A: proven commercial"),
         ("B_Contact_Now", "B-", "B: likely commercial")]
NOTES = [
    "Sync fills the lead tabs and Events every 10 minutes; tracking every 5.",
    "Replies are exact for this mailbox. A bounce counts only when a notice arrives.",
    "Only emails this system drafted with tracking on can be tracked: hand-written ones never.",
    "Opens are an estimate: Apple Mail loads images by itself, Outlook often blocks them, and "
    "opening your own Sent copy counts.",
    "A click in the first minute after sending, or a HEAD request, is taken as a mail scanner "
    "and not counted.",
]


def column(tab, header):
    """The whole column under `header` in a lead tab, from row 3 down."""
    found = f'MATCH("{header}",\'{tab}\'!$2:$2,0)'
    return f'INDIRECT("\'{tab}\'!R3C"&{found}&":C"&{found},FALSE)'


def where(tab, header, formula):
    """`formula` where the column exists, else 0. Checked first, because a count of non-empty
    cells given a missing column counts the lookup's error as one filled cell (found on the live
    B tab, 2026-09-28: "Leads emailed" read 1 with no one emailed)."""
    return f'IFERROR(IF(ISNUMBER(MATCH("{header}",\'{tab}\'!$2:$2,0)),{formula},0),0)'


def _positive(tab, header):
    """How many leads have a number above zero under `header` (the Sheet stores them as text)."""
    return where(tab, header,
                 f'SUMPRODUCT(ARRAYFORMULA(--(IFERROR(VALUE({column(tab, header)}),0)>0)))')


def _status(tab, value):
    return where(tab, "Outreach status", f'COUNTIF({column(tab, "Outreach status")},"{value}")')


def rows():
    """The tab's cells, row by row. Rates refer to the count rows above them."""
    def per_tier(build):
        return [build(tab, prefix) for tab, prefix, _ in TIERS]

    def rate(top, bottom):
        return [f'=IFERROR(TEXT({c}{top}/{c}{bottom},"0%"),"-")' for c in "BCD"]

    def both(row):
        return f"=B{row}+C{row}"

    table = [
        ("Leads emailed",
         per_tier(lambda t, p: "=" + where(t, "Sent at", f'COUNTIF({column(t, "Sent at")},"<>")'))),
        ("Emails sent, initial and follow-ups",
         per_tier(lambda t, p: f'=IFERROR(COUNTIFS(\'{EVENTS_TAB}\'!$C:$C,"SENT",'
                               f'\'{EVENTS_TAB}\'!$B:$B,"{p}*"),0)')),
        ("Replied, including asked to stop",
         per_tier(lambda t, p: f'={_status(t, "REPLIED")}+{_status(t, "OPTED_OUT")}')),
        ("Reply rate", None, (5, 3)),
        ("Asked to stop", per_tier(lambda t, p: f'={_status(t, "OPTED_OUT")}')),
        ("Bounced", per_tier(lambda t, p: f'={_status(t, "BOUNCED")}')),
        ("Emailed, match to check", per_tier(lambda t, p: f'={_status(t, "REVIEW_NEEDED")}')),
        ("Leads with a tracked email", per_tier(lambda t, p: f"={_positive(t, 'Tracked sends')}")),
        ("Tracking coverage", None, (10, 3)),
        ("Opened (est.)", per_tier(lambda t, p: f"={_positive(t, 'Opens (est.)')}")),
        ("Open rate (est.)", None, (12, 10)),
        ("Clicked", per_tier(lambda t, p: f"={_positive(t, 'Clicks')}")),
        ("Click rate", None, (14, 10)),
    ]
    out = [[TITLE], ["Metric", *[label for _, _, label in TIERS], "A and B"]]
    for number, entry in enumerate(table, start=3):
        if entry[1] is None:
            out.append([entry[0], *rate(*entry[2])])
        else:
            out.append([entry[0], *entry[1], both(number)])
    out += [[""], *[[note] for note in NOTES]]
    return out


def write(api=None):
    """Create the tab, or refresh its formulas. Refuses a tab of the same name that is not this one."""
    api = api or _api()
    tabs = {s["properties"]["title"]: s["properties"]["sheetId"]
            for s in api.get(spreadsheetId=SHEET_ID).execute()["sheets"]}
    if TAB in tabs:
        first = api.values().get(spreadsheetId=SHEET_ID, range=f"'{TAB}'!A1").execute().get("values", [[""]])
        if first[0][0] != TITLE:
            raise RuntimeError(f"a tab named {TAB} exists and is not this dashboard; nothing written")
    else:
        api.batchUpdate(spreadsheetId=SHEET_ID, body={"requests": [{"addSheet": {"properties": {
            "title": TAB}}}]}).execute()
    table = rows()
    api.values().update(spreadsheetId=SHEET_ID, range=f"'{TAB}'!A1", valueInputOption="USER_ENTERED",
                        body={"values": table}).execute()
    shown = api.values().get(spreadsheetId=SHEET_ID, range=f"'{TAB}'!A1:D{len(table)}").execute()
    return shown.get("values", [])


if __name__ == "__main__":
    print(json.dumps(write(), indent=2))
