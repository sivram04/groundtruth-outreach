"""Stage 2 job: research company fit for OK and RISKY leads that have no Fit yet.

Fit is independent of the email check; RISKY leads are researched too, so the founder can see
whether a company is worth finding a better address for. Drafting (stage 3) needs both an OK
address and a QUALIFIED fit - see outreach/eligibility.py.

Clear a lead's `Fit` cell to research it again.

    python -m outreach.job_research --limit 30 --ids A-0019,B-0162   # run locally
"""

import sys
from collections import Counter
from concurrent.futures import ThreadPoolExecutor

from outreach import checks, gemini, research
from outreach.sheet import (LEAD_TABS, RESEARCH_COLUMNS, SYSTEM_COLUMNS, Tab, _api, append_run,
                            ensure_tab, now_utc, SHEET_ID)

RESEARCH_TAB = "Research"
RESEARCH_HEADER = ["Researched at", "Lead ID", "Company", "Category", "Quote", "Page URL"]
DEFAULT_LIMIT = 40  # companies per run; keeps one run well inside Cloud Run's 600 s


def select(tabs, limit, ids=None):
    chosen = []
    for tab in tabs:
        for row, v in tab.rows:
            if ids is not None:
                if v.get("Lead ID") in ids:
                    chosen.append((tab, row, v))
            elif v.get("Email check") in (checks.OK, checks.RISKY) and not v.get("Fit"):
                chosen.append((tab, row, v))
    return chosen if ids is not None else chosen[:limit]


def run(where, limit=DEFAULT_LIMIT, ids=None, model=gemini.generate_json, *, api=None, sheet_id=SHEET_ID):
    api = api or _api()
    tabs = [Tab(api, name, SYSTEM_COLUMNS, sheet_id) for name in LEAD_TABS]
    for tab in tabs:
        tab.ensure_columns(RESEARCH_COLUMNS)
    chosen = select(tabs, limit, ids)

    def one(item):
        tab, row, v = item
        try:
            return item, research.research(v.get("Website", ""), model), None
        except Exception as e:  # model or network failure: leave blank, retry next run
            return item, None, f"{v.get('Lead ID')}: {type(e).__name__}: {e}"[:200]

    with ThreadPoolExecutor(max_workers=6) as pool:
        results = list(pool.map(one, chosen))

    stamp = now_utc()
    updates = {t.name: {} for t in tabs}
    research_rows, counts, failures, tokens = [], Counter(), [], Counter()
    for (tab, row, v), res, err in results:
        if err:
            failures.append(err)
            continue
        counts[res["fit"]] += 1
        for k in ("promptTokenCount", "candidatesTokenCount", "thoughtsTokenCount"):
            tokens[k] += res["usage"].get(k, 0)
        updates[tab.name][row] = {
            "Fit": res["fit"], "Work mix": res["work_mix"], "Fit reason": res["reason"],
            "Fit evidence": research.evidence_cell(res["evidence"]), "Researched at": stamp,
        }
        research_rows += [[stamp, v.get("Lead ID"), v.get("Company"), k["category"], k["quote"], k["url"]]
                          for k in res["evidence"]]

    written, skipped = 0, []
    for tab in tabs:
        r = tab.write(updates[tab.name])
        written += r["written"]
        skipped += [f"{tab.name} row {row}: {why}" for row, why in r["skipped"]]
    if research_rows:
        ensure_tab(api, RESEARCH_TAB, RESEARCH_HEADER, sheet_id)
        api.values().append(spreadsheetId=sheet_id, range=f"'{RESEARCH_TAB}'!A1", valueInputOption="RAW",
                            insertDataOption="INSERT_ROWS", body={"values": research_rows}).execute()

    detail = (f"researched {sum(counts.values())}: " + ", ".join(f"{k} {n}" for k, n in sorted(counts.items()))
              + f"; quotes stored {len(research_rows)}; tokens in {tokens['promptTokenCount']}, "
              f"out {tokens['candidatesTokenCount']}, thinking {tokens['thoughtsTokenCount']}")
    if failures:
        detail += f"; failed {len(failures)} (left blank): " + "; ".join(failures[:3])
    if skipped:
        detail += f"; skipped {len(skipped)} changed rows"
    append_run(api, "research", where, "OK" if not (failures or skipped) else "PARTIAL", detail, sheet_id)
    return {"results": dict(counts), "written": written, "failed": failures, "skipped": skipped,
            "tokens": dict(tokens)}


if __name__ == "__main__":
    args = dict(zip(sys.argv[1::2], sys.argv[2::2]))
    ids = set(args["--ids"].split(",")) if "--ids" in args else None
    print(run("local", int(args.get("--limit", DEFAULT_LIMIT)), ids))
