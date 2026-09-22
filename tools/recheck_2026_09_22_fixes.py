"""One-off: re-check only the rows affected by the 2026-09-22 review fixes.

Affected means an OK or RISKY row where either
  - the address is a personal mailbox (the rule now requires finding it on the company's
    site instead of trusting the `Where it came from` label), or
  - the website probe is not a clean load under the new rule (HTTP 404 and other 4xx no
    longer count as loading).
Of those, only rows whose result or reason actually changes are written. SENT BY HAND,
DUPLICATE and INVALID rows do not depend on either rule and are not touched.

    python -m tools.recheck_2026_09_22_fixes            # dry run, prints every change
    python -m tools.recheck_2026_09_22_fixes --apply
"""

import sys
from collections import Counter

from outreach import checks
from outreach.job_check import read_leads, write_all
from outreach.sheet import _api, append_run, now_utc


def main(apply):
    api = _api()
    tabs, pending, first_seen = read_leads(api)
    candidates = [(t, r, l, v) for t, r, l, v in pending if v.get("Email check") in (checks.OK, checks.RISKY)]
    mx, live, published = checks.lookups([l for _, _, l, _ in candidates])

    updates, moves = {t.name: {} for t in tabs}, Counter()
    stamp = now_utc()
    for tab, row, lead, v in candidates:
        loads, detail = live.get(lead["website"], (False, "no website"))
        if not (checks.is_personal(lead["email"]) or not loads or detail):
            continue
        result, reason = checks.check(lead, first_seen, mx, live, published)
        if (result, reason) == (v["Email check"], v["Reason"]):
            continue
        moves[f"{v['Email check']} -> {result}"] += 1
        print(f"{v['Lead ID']:7} {v['Email check']:6} -> {result:6} {lead['email']:40} {reason}")
        updates[tab.name][row] = {"Email check": result, "Reason": reason, "Checked at": stamp}

    print("\nchanges:", dict(moves) or "none")
    if not apply:
        print("dry run: nothing written")
        return
    written, skipped = write_all(tabs, updates)
    detail = f"review fixes: rechecked {written} affected rows ({', '.join(f'{k} {n}' for k, n in moves.items())})"
    if skipped:
        detail += f"; skipped {len(skipped)}: " + "; ".join(skipped[:5])
    append_run(api, "recheck-fixes", "local", "OK" if not skipped else "PARTIAL", detail)
    print(detail)


if __name__ == "__main__":
    main("--apply" in sys.argv)
