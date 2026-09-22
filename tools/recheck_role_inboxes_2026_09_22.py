"""One-off: re-check only rows whose address is one of the role inboxes added 2026-09-22
(checks.ROLE_INBOXES). Only OK/RISKY rows can change; only system columns are written.

    python -m tools.recheck_role_inboxes_2026_09_22            # dry run
    python -m tools.recheck_role_inboxes_2026_09_22 --apply
"""

import sys
from collections import Counter

from outreach import checks
from outreach.job_check import read_leads, write_all
from outreach.sheet import _api, append_run, now_utc


def main(apply):
    api = _api()
    tabs, pending, first_seen = read_leads(api)
    matching = [(t, r, l, v) for t, r, l, v in pending
                if v.get("Email check") in (checks.OK, checks.RISKY)
                and l["email"].split("@")[0].lower() in checks.ROLE_INBOXES]
    mx, live, published = checks.lookups([l for _, _, l, _ in matching])

    updates, moves = {t.name: {} for t in tabs}, Counter()
    stamp = now_utc()
    for tab, row, lead, v in matching:
        result, reason = checks.check(lead, first_seen, mx, live, published)
        print(f"{v['Lead ID']:7} {v['Email check']:6} -> {result:6} {lead['email']:38} {reason[:110]}")
        if (result, reason) == (v["Email check"], v["Reason"]):
            continue
        moves[f"{v['Email check']} -> {result}"] += 1
        updates[tab.name][row] = {"Email check": result, "Reason": reason, "Checked at": stamp}

    print(f"\nmatching rows: {len(matching)}; changes: {dict(moves) or 'none'}")
    if not apply:
        print("dry run: nothing written")
        return
    written, skipped = write_all(tabs, updates)
    detail = (f"role inboxes: {len(matching)} matching rows, {written} rewritten "
              f"({', '.join(f'{k} {n}' for k, n in moves.items()) or 'no change'})")
    if skipped:
        detail += f"; skipped {len(skipped)}: " + "; ".join(skipped[:5])
    append_run(api, "recheck-role-inboxes", "local", "OK" if not skipped else "PARTIAL", detail)
    print(detail)


if __name__ == "__main__":
    main("--apply" in sys.argv)
