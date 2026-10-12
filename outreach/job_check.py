"""Stage 1 job: give each lead a Lead ID and check its BEST EMAIL.

Only rows whose `Email check` is blank are checked. Clear that cell to re-check a row.
Tabs are processed in order A then B, so the earlier row keeps an address that appears twice.

    python -m outreach.job_check          # run locally
"""

import re
from collections import Counter

from outreach import checks
from outreach.sheet import (CHECK_COLUMNS, LEAD_TABS, SHEET_ID, SYSTEM_COLUMNS, Tab, _api,
                            append_run, now_utc)

ID_RE = re.compile(r"^([A-Z])-(\d{4,})$")


def read_leads(api, sheet_id=SHEET_ID):
    """Read A and B, add missing system columns, and describe every lead.
    Returns (tabs, pending, first_seen); pending holds (tab, sheet_row, lead, row_values)."""
    tabs = [Tab(api, name, SYSTEM_COLUMNS, sheet_id) for name in LEAD_TABS]
    for tab in tabs:
        tab.ensure_columns(CHECK_COLUMNS)

    pending, first_seen = [], {}
    for tab in tabs:
        prefix = LEAD_TABS[tab.name]
        used = [int(m.group(2)) for _, v in tab.rows if (m := ID_RE.match(v.get("Lead ID", "")))]
        next_n = max(used, default=0) + 1
        for sheet_row, v in tab.rows:
            lead_id = v.get("Lead ID", "")
            if not lead_id:
                lead_id = f"{prefix}-{next_n:04d}"
                next_n += 1
            lead = {
                "id": lead_id,
                "email": v.get("BEST EMAIL", ""),
                "website": v.get("Website", ""),
                "warning": v.get("Warning", ""),
                "sent_by_hand": v.get("Sent by hand", ""),
            }
            key = lead["email"].lower()
            if key and key not in first_seen:
                first_seen[key] = lead_id
            pending.append((tab, sheet_row, lead, v))
    return tabs, pending, first_seen


def write_all(tabs, updates):
    """updates: {tab_name: {sheet_row: cells}}. Returns total written and skipped reasons."""
    written, skipped = 0, []
    for tab in tabs:
        r = tab.write(updates.get(tab.name, {}))
        written += r["written"]
        skipped += [f"{tab.name} row {row}: {why}" for row, why in r["skipped"]]
    return written, skipped


def run(where, *, api=None, sheet_id=SHEET_ID):
    api = api or _api()
    tabs, pending, first_seen = read_leads(api, sheet_id)

    to_check = [(t, r, l, v) for t, r, l, v in pending if not v.get("Email check")]
    mx, live, published = checks.lookups([l for _, _, l, _ in to_check])

    counts = Counter()
    updates = {tab.name: {} for tab in tabs}
    stamp = now_utc()
    for tab, sheet_row, lead, v in pending:
        cells = {}
        if not v.get("Lead ID"):
            cells["Lead ID"] = lead["id"]
        if not v.get("Email check"):
            result, reason = checks.check(lead, first_seen, mx, live, published)
            cells.update({"Email check": result, "Reason": reason, "Checked at": stamp})
            counts[result] += 1
        if cells:
            updates[tab.name][sheet_row] = cells

    written, skipped = write_all(tabs, updates)
    detail = (f"checked {sum(counts.values())}: " + ", ".join(f"{k} {n}" for k, n in sorted(counts.items()))
              if counts else "no new rows to check")
    if skipped:
        detail += f"; skipped {len(skipped)} rows that changed during the run: " + "; ".join(skipped[:5])
    append_run(api, "check", where, "OK" if not skipped else "PARTIAL", detail, sheet_id)
    return {"results": dict(counts), "written": written, "skipped": skipped}


if __name__ == "__main__":
    print(run("local"))
