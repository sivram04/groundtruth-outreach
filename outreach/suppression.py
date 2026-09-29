"""The one reading of the Suppression tab: absent, unreadable or malformed is unknown, never empty.

Four jobs decide from this list whether an address may be written to, and each used to read the tab
its own way. One accepted three spellings of the address column, one insisted on a single spelling,
and the sync treated a tab it could not read as a tab with nobody on it. They now share this module,
so one header, one normalisation and one test serve all of them.

An empty tab that still has its header is a valid empty list: nobody is suppressed, and work may go
on. Anything else - no tab, no header, no address column, two address columns, a row with nothing in
its address - is unknown. Every caller that would act on the answer must stop rather than guess.

An alias in the header is normalised here, once, so no caller reads a row and then silently ignores
the address in it: every entry this module returns carries `FIELD`, whatever the tab calls it.
"""

FIELD = "Address or domain"
"""The canonical column of the tab, and the key every entry returned from here carries."""

ALIASES = (FIELD, "Address", "Domain")
"""Header spellings that mean `FIELD`. A tab may use exactly one of them, never two."""


class Unreadable(Exception):
    """The tab is not a readable suppression list. `reason` is written for a person to act on."""

    def __init__(self, reason):
        super().__init__(reason)
        self.reason = reason


def address_column(header):
    """The one column of `header` holding the address. Raises `Unreadable` when it is not certain."""
    named = [str(cell).strip() for cell in header if str(cell).strip() in ALIASES]
    if not named:
        shown = ", ".join(str(cell).strip() for cell in header if str(cell).strip()) or "nothing"
        raise Unreadable(f"the Suppression tab has no {FIELD} column: its header reads {shown}")
    if len(named) > 1:
        raise Unreadable(f"the Suppression tab has more than one address column ({', '.join(named)}), "
                         "so which one holds the address is not stated")
    return named[0]


def of_values(values):
    """Entries from the tab's own rows, each carrying `FIELD`. Raises `Unreadable`; [] is valid."""
    if not values:
        raise Unreadable("the Suppression tab is empty: it has not even a header row")
    header = list(values[0])
    column = address_column(header)
    entries = []
    for number, row in enumerate(values[1:], start=2):
        cells = {name: (row[i] if i < len(row) else "") for i, name in enumerate(header) if name}
        if not any(str(value).strip() for value in cells.values()):
            continue  # a wholly blank line: the Sheet keeps them and they say nothing
        address = str(cells.get(column, "")).strip()
        if not address:
            raise Unreadable(f"row {number} of the Suppression tab has nothing in its {column} "
                             "column, so who it suppresses is not stated")
        entries.append({**cells, FIELD: address})
    return entries


def covers(entries, address):
    """True when the address, or its whole domain, is on the list. One test for every caller."""
    address = str(address or "").strip().lower()
    if not address:
        return False
    domain = address.rpartition("@")[2]
    for entry in entries:
        value = str(entry.get(FIELD) or "").strip().lower()
        if value and (value == address
                      or ("@" not in value.lstrip("@") and value.lstrip("@") == domain)):
            return True
    return False


def cell(entry, column):
    """What belongs under `column` when a new entry is written to a tab with that header.

    The address is carried on `FIELD`, so a tab whose own header uses an alias still receives it
    rather than a blank."""
    if str(column).strip() in ALIASES:
        value = entry.get(column, "")
        return value if str(value).strip() else entry.get(FIELD, "")
    return entry.get(column, "")
