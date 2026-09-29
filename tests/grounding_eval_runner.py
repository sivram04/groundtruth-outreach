"""Runs `grounding_eval`'s cases against `outreach.writer.verify` and reports what happened.

Every case exercises ONE part of a real email (a company sentence, a product sentence, an ask,
or the subject); the other three parts are filled with sentences already known to pass, taken
from `test_writer.py`'s own fixture, so a case's verdict is driven by the part under test and
nothing else. `judge` reports not only accept/reject but, for a reject, whether a problem
actually names the part being tested — a reject for the WRONG reason (a false positive on one of
the filler parts) is reported as its own outcome, not folded into a correct reject.

    .venv/Scripts/python.exe -m tests.grounding_eval_runner            # both lists, a table
    .venv/Scripts/python.exe -m tests.grounding_eval_runner --json out.json
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from outreach import writer
from grounding_eval import COMPANY, HANDBOOK, HELD_OUT_CASES, QUOTE, TUNING_CASES

DEFAULT_PRODUCT = {"text": "I'm building Example Product, a cash-flow decision tool for "
                          "construction subcontractors. The MVP is still being finished.",
                   "kind": "PRODUCT", "quote_id": ""}
DEFAULT_ASK = {"text": "Would you be open to a twenty minute conversation next week about the "
                      "early preview?", "kind": "ASK", "quote_id": ""}
DEFAULT_SUBJECT = "A conversation about Example Product next week"
DEFAULT_COMPANY_QUOTE_ID = "default-q"


def _company_sentence(source_for_company_default=QUOTE):
    return {"text": f"{COMPANY} installs electrical distribution systems for commercial buildings.",
            "kind": "COMPANY", "quote_id": DEFAULT_COMPANY_QUOTE_ID}


NAME_FOR_KIND = {"COMPANY": "company sentence", "PRODUCT": "product sentence",
                 "ASK": "ask sentence", "SUBJECT": "subject line"}


def judge(case):
    """(verdict, problems) where verdict is accept | reject | review | reject-wrong-reason.

    Only the case's OWN kind of sentence carries the tested text; the other three parts of the
    email are known-good fillers. For a COMPANY case the tested sentence uses the case's own
    company; for a PRODUCT / ASK / SUBJECT case, the tested text stands on the handbook and the
    company name is irrelevant to it, so the WHOLE email (filler company sentence included) uses
    the default company/quote, which keeps the filler internally valid whatever company a fresh
    case happens to name. A first run of the fresh set fed the default filler sentence with the
    case's company and the filler - not the tested subject - failed grounding; that was a harness
    bug, fixed here, with the validator untouched."""
    kind = case["kind"]
    if kind == "COMPANY":
        company = case.get("company", COMPANY)
        handbook_text = HANDBOOK
        facts = [{"quote_id": "q1", "category": "OFFERING", "quote": case["source"], "url": "https://example.test"},
                 {"quote_id": DEFAULT_COMPANY_QUOTE_ID, "category": "OFFERING", "quote": QUOTE,
                  "url": "https://example.test"}]
        sentences = [{"text": case["text"], "kind": "COMPANY", "quote_id": "q1"},
                    DEFAULT_PRODUCT, DEFAULT_ASK]
        subject = DEFAULT_SUBJECT
    elif kind in ("PRODUCT", "ASK"):
        company = COMPANY
        handbook_text = case["source"]
        facts = [{"quote_id": DEFAULT_COMPANY_QUOTE_ID, "category": "OFFERING", "quote": QUOTE,
                  "url": "https://example.test"}]
        company_sentence = _company_sentence()
        if kind == "PRODUCT":
            sentences = [company_sentence, {"text": case["text"], "kind": "PRODUCT", "quote_id": ""},
                        DEFAULT_ASK]
        else:
            sentences = [company_sentence, DEFAULT_PRODUCT,
                        {"text": case["text"], "kind": "ASK", "quote_id": ""}]
        subject = DEFAULT_SUBJECT
    elif kind == "SUBJECT":
        company = COMPANY
        handbook_text = case["source"]
        facts = [{"quote_id": DEFAULT_COMPANY_QUOTE_ID, "category": "OFFERING", "quote": QUOTE,
                  "url": "https://example.test"}]
        sentences = [_company_sentence(), DEFAULT_PRODUCT, DEFAULT_ASK]
        subject = case["text"]
    else:
        raise ValueError(f"unknown kind {kind!r}")

    draft, problems = writer.verify(handbook_text, company, facts, sentences, subject)
    if draft is not None:
        return "accept", problems
    marker = NAME_FOR_KIND[kind]
    named = [p for p in problems if marker in p or (kind == "SUBJECT" and "subject line" in p)]
    if not named:
        return "reject-wrong-reason", problems
    # A "review" outcome is a blocking problem the validator marks as "cannot tell - a person must
    # look" (writer.REVIEW_PREFIX), distinct from a plain rejection where the words are wrong.
    if any(p.startswith(writer.REVIEW_PREFIX) for p in named):
        return "review", problems
    return "reject", problems


def _correct(verdict, expect):
    """accept only satisfies accept; a case that expects rejection is satisfied by a plain reject
    OR a review (both block an approval hash); a case that expects review wants exactly review."""
    if expect == "accept":
        return verdict == "accept"
    if expect == "review":
        return verdict == "review"
    return verdict in ("reject", "review")


def run(cases):
    rows = []
    for case in cases:
        verdict, problems = judge(case)
        rows.append({"id": case["id"], "category": case["category"], "kind": case["kind"],
                    "expect": case["expect"], "verdict": verdict,
                    "correct": _correct(verdict, case["expect"]), "problems": problems})
    return rows


def summarize(rows, label):
    total = len(rows)
    correct = sum(1 for r in rows if r["correct"])
    # False accept / false reject / review reported SEPARATELY (the founder's criterion 5). A
    # review is not a reject: the words may be right; the validator says a person must look.
    false_accept = [r for r in rows if r["expect"] in ("reject", "review") and r["verdict"] == "accept"]
    false_reject = [r for r in rows if r["expect"] == "accept" and r["verdict"] != "accept"]
    reviewed = [r for r in rows if r["verdict"] == "review"]
    rejected = [r for r in rows if r["verdict"] == "reject"]
    wrong_reason = [r for r in rows if r["verdict"] == "reject-wrong-reason"]
    print(f"\n=== {label}: {correct}/{total} correct ===")
    print(f"  plainly REJECTED (words wrong): {len(rejected)}")
    print(f"  held for REVIEW (validator cannot tell; no approval hash): {len(reviewed)}")
    for r in reviewed:
        print(f"    - {r['id']} [{r['category']}]")
    print(f"  unsupported claims wrongly ACCEPTED (false accept): {len(false_accept)}")
    for r in false_accept:
        print(f"    - {r['id']} [{r['category']}]")
    print(f"  supported claims wrongly REJECTED or sent to review (false reject): {len(false_reject)}")
    for r in false_reject:
        print(f"    - {r['id']} [{r['category']}] -> {r['problems']}")
    if wrong_reason:
        print(f"  rejected, but not for a reason naming the tested part (investigate): "
              f"{len(wrong_reason)}")
        for r in wrong_reason:
            print(f"    - {r['id']} -> {r['problems']}")
    by_category = {}
    for r in rows:
        by_category.setdefault(r["category"], []).append(r)
    print("  by category:")
    for category, group in sorted(by_category.items()):
        ok = sum(1 for r in group if r["correct"])
        print(f"    {category:26} {ok}/{len(group)}")
    return {"label": label, "total": total, "correct": correct,
           "rejected": [r["id"] for r in rejected],
           "reviewed": [r["id"] for r in reviewed],
           "false_accept": [r["id"] for r in false_accept],
           "false_reject": [r["id"] for r in false_reject],
           "wrong_reason": [r["id"] for r in wrong_reason]}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", help="write the full row-by-row result here too")
    args = parser.parse_args()
    tuning_rows = run(TUNING_CASES)
    held_out_rows = run(HELD_OUT_CASES)
    tuning_summary = summarize(tuning_rows, "TUNING_CASES")
    held_out_summary = summarize(held_out_rows, "HELD_OUT_CASES")
    all_rows = {"tuning": tuning_rows, "held_out": held_out_rows}
    if args.json:
        Path(args.json).write_text(json.dumps(
            {"tuning_summary": tuning_summary, "held_out_summary": held_out_summary,
             "rows": all_rows}, indent=2), encoding="utf-8")
        print(f"\nwrote {args.json}")


if __name__ == "__main__":
    main()
