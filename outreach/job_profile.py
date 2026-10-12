"""Collect verified offerings and markets for a small Gmail-draft pilot.

This job neither drafts nor sends email. It does not change the existing fit verdict.
"""

from collections import Counter
from concurrent.futures import ThreadPoolExecutor

from outreach import company_profile, eligibility, gemini
from outreach.sheet import (LEAD_TABS, PROFILE_COLUMNS, SYSTEM_COLUMNS, SHEET_ID,
                            Tab, _api, append_run, ensure_tab, now_utc)

PROFILE_TAB = "Research"
PROFILE_HEADER = ["Researched at", "Lead ID", "Company", "Category", "Quote", "Page URL"]
MAX_LIMIT = 5


def select(tabs, limit=MAX_LIMIT, ids=None):
    chosen = []
    for tab in tabs:
        for row, values in tab.rows:
            if ids is not None and values.get("Lead ID") not in ids:
                continue
            if values.get("Profile status"):
                continue
            eligible, _ = eligibility.draft_eligible(values)
            if eligible:
                chosen.append((tab, row, values))
    return chosen[:limit]


def run(where, limit=MAX_LIMIT, ids=None, dry_run=False, model=gemini.generate_json, *,
        api=None, sheet_id=SHEET_ID):
    if not 1 <= limit <= MAX_LIMIT:
        raise ValueError(f"limit must be between 1 and {MAX_LIMIT}")
    api = api or _api()
    tabs = [Tab(api, name, SYSTEM_COLUMNS, sheet_id) for name in LEAD_TABS]
    if not dry_run:
        for tab in tabs:
            tab.ensure_columns(PROFILE_COLUMNS)
    chosen = select(tabs, limit, ids)

    def one(item):
        tab, row, values = item
        try:
            return item, company_profile.profile(values.get("Website", ""), model), None
        except Exception as exc:
            return item, None, f"{values.get('Lead ID')}: {type(exc).__name__}"[:100]

    with ThreadPoolExecutor(max_workers=3) as pool:
        results = list(pool.map(one, chosen))

    stamp = now_utc()
    updates = {tab.name: {} for tab in tabs}
    records = []
    counts, tokens, failures = Counter(), Counter(), []
    preview = []
    for (tab, row, values), result, error in results:
        if error:
            failures.append(error)
            continue
        lead_id = values.get("Lead ID", "")
        counts[result["status"]] += 1
        for key in ("promptTokenCount", "candidatesTokenCount", "thoughtsTokenCount"):
            tokens[key] += result["usage"].get(key, 0)
        updates[tab.name][row] = {
            "Profile status": result["status"],
            "Offerings evidence": company_profile.evidence_cell(result["evidence"], company_profile.OFFERING),
            "Markets evidence": company_profile.evidence_cell(result["evidence"], company_profile.MARKET, 2),
            "Profile reason": result["reason"],
            "Profiled at": stamp,
        }
        records.append((tab.name, row, [[stamp, lead_id, values.get("Company", ""), fact["category"],
                                         fact["quote"], fact["url"]] for fact in result["evidence"]]))
        preview.append({"lead_id": lead_id, "status": result["status"],
                        "offerings": [{"quote": f["quote"], "url": f["url"]}
                                      for f in result["evidence"] if f["category"] == company_profile.OFFERING],
                        "markets": [{"quote": f["quote"], "url": f["url"]}
                                    for f in result["evidence"] if f["category"] == company_profile.MARKET]})

    if dry_run:
        return {"dry_run": True, "results": dict(counts), "preview": preview,
                "failed": failures, "tokens": dict(tokens)}

    written, skipped, skipped_keys = 0, [], set()
    for tab in tabs:
        outcome = tab.write(updates[tab.name])
        written += outcome["written"]
        skipped += [f"{tab.name} row {row}: {why}" for row, why in outcome["skipped"]]
        skipped_keys.update((tab.name, row) for row, _ in outcome["skipped"])
    rows = [fact for tab_name, row, facts in records if (tab_name, row) not in skipped_keys for fact in facts]
    if rows:
        ensure_tab(api, PROFILE_TAB, PROFILE_HEADER, sheet_id)
        api.values().append(spreadsheetId=sheet_id, range=f"'{PROFILE_TAB}'!A1", valueInputOption="RAW",
                            insertDataOption="INSERT_ROWS", body={"values": rows}).execute()
    detail = (f"profiled {written}: " + ", ".join(f"{k} {v}" for k, v in sorted(counts.items()))
              + f"; quotes stored {len(rows)}; tokens in {tokens['promptTokenCount']}, "
              f"out {tokens['candidatesTokenCount']}, thinking {tokens['thoughtsTokenCount']}")
    if failures:
        detail += f"; failed {len(failures)} (left blank)"
    if skipped:
        detail += f"; skipped {len(skipped)} changed rows"
    append_run(api, "profile", where, "OK" if not (failures or skipped) else "PARTIAL", detail, sheet_id)
    return {"dry_run": False, "results": dict(counts), "written": written,
            "failed": failures, "skipped": skipped, "tokens": dict(tokens)}
