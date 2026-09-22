"""One-off: re-evaluate the 30-lead research sample under the specific-evidence rule, from the
quotes already stored for each lead's current run. No site is read and no model is called, so
the result depends only on the rule. Unreadable leads have no quotes and cannot change.

Only leads whose Fit, Work mix or Fit reason changes are written: their research columns are
updated, and their re-categorised quotes are appended to the Research tab under a new
`Researched at`, so the lead row and the Research tab stay consistent. BEST EMAIL and every
other founder column are untouched.

    python -m tools.refit_sample_2026_09_22 <ids-file>            # dry run
    python -m tools.refit_sample_2026_09_22 <ids-file> --apply
"""

import re
import sys

from outreach import research
from outreach.job_research import RESEARCH_HEADER, RESEARCH_TAB
from outreach.sheet import (LEAD_TABS, SHEET_ID, SYSTEM_COLUMNS, Tab, _api, append_run, ensure_tab,
                            now_utc)

DISCARDED = re.compile(r"; \d+ proposed quote\(s\) discarded as not found word for word$")


def main(ids_file, apply):
    ids = set(open(ids_file).read().strip().split(","))
    api = _api()
    tabs = [Tab(api, name, SYSTEM_COLUMNS) for name in LEAD_TABS]
    stored = api.values().get(spreadsheetId=SHEET_ID, range=f"'{RESEARCH_TAB}'").execute()["values"][1:]

    stamp = now_utc()
    updates, research_rows, changes = {t.name: {} for t in tabs}, [], []
    for tab in tabs:
        for row, v in tab.rows:
            if v.get("Lead ID") not in ids or not v.get("Fit") or v.get("Work mix") == "UNREADABLE":
                continue
            quotes = [{"category": r[3], "quote": r[4], "url": r[5]} for r in stored
                      if r[1] == v["Lead ID"] and r[0] == v["Researched at"]]
            kept = research.downgrade_unsupported(quotes)
            fit, mix, reason = research.verdict(kept, pages_read=1)
            suffix = DISCARDED.search(v["Fit reason"])
            if suffix:
                reason += suffix.group(0)
            moved = [f'{q["category"]}->{k["category"]}: "{k["quote"][:70]}"'
                     for q, k in zip(quotes, kept) if q["category"] != k["category"]]
            # Affected = the verdict changes, or a quote is re-categorised. A reason that differs
            # only in wording is not an effect of the rule and is left as it is.
            if (fit, mix) == (v["Fit"], v["Work mix"]) and not moved:
                continue
            changes.append((v["Lead ID"], v["Company"], f'{v["Fit"]}/{v["Work mix"]}', f"{fit}/{mix}", reason, moved))
            updates[tab.name][row] = {"Fit": fit, "Work mix": mix, "Fit reason": reason,
                                      "Fit evidence": research.evidence_cell(kept), "Researched at": stamp}
            research_rows += [[stamp, v["Lead ID"], v["Company"], k["category"], k["quote"], k["url"]] for k in kept]

    for lead_id, company, old, new, reason, moved in changes:
        flag = "  <-- VERDICT CHANGE" if old.split("/")[0] != new.split("/")[0] else ""
        print(f"\n{lead_id} {company}: {old} -> {new}{flag}\n   reason: {reason}")
        for m in moved:
            print(f"   re-categorised {m}")
    verdicts = sum(1 for c in changes if c[2].split("/")[0] != c[3].split("/")[0])
    print(f"\nrows changing: {len(changes)} ({verdicts} change Fit; the rest change only Work mix or reason)")
    if not apply:
        print("dry run: nothing written")
        return
    written, skipped = 0, []
    for tab in tabs:
        r = tab.write(updates[tab.name])
        written += r["written"]
        skipped += [f"{tab.name} row {row}: {why}" for row, why in r["skipped"]]
    if research_rows:
        ensure_tab(api, RESEARCH_TAB, RESEARCH_HEADER)
        api.values().append(spreadsheetId=SHEET_ID, range=f"'{RESEARCH_TAB}'!A1", valueInputOption="RAW",
                            insertDataOption="INSERT_ROWS", body={"values": research_rows}).execute()
    detail = f"specific-evidence re-evaluation of the sample: {written} rows updated, {verdicts} Fit changes"
    if skipped:
        detail += f"; skipped {len(skipped)}: " + "; ".join(skipped[:5])
    append_run(api, "refit-sample", "local", "OK" if not skipped else "PARTIAL", detail)
    print(detail)


if __name__ == "__main__":
    main(sys.argv[1], "--apply" in sys.argv)
