"""A FRESH evaluation set for `outreach.writer`'s grounding check, written AFTER it was frozen.

The founder's criterion 4: keep the development cases (`grounding_eval.py`, which the eval runner
was run against repeatedly while the checks were iterated) separate from a reserved evaluation set
looked at only once. This is that set. It was written after `writer.py`'s detectors were frozen for
this work, uses companies, quotes and candidate sentences that appear nowhere in development, and
is run ONCE. If any case here later drives a code change, this file becomes development evidence and
a new fresh set must be reserved - that rule is the whole point of keeping it apart.

Same shape as `grounding_eval.py`: id, category, kind, source, text, company, expect
("accept" | "reject" | "review"), because. It deliberately includes one case of the residual class
the validator cannot close (a single-clause same-source recombination) so the fresh run measures
that gap honestly rather than hiding it.
"""

RQUOTE = "We provide commercial roofing installation and repair for warehouses and retail centers."
RQUOTE_HISTORY = "Our crews have completed more than 350 roofing projects across the Midwest since 2005."
RQUOTE_REGIONAL = "We install commercial roofing for warehouses throughout the Chicago metro area."
RQUOTE_PILOT = "We are currently onboarding a select group of early-access clients on a pilot basis."
RQUOTE_LIST = "Installation, repair, and maintenance of commercial roofing, gutters, and skylights."
RQUOTE_DELEGATION = ("We install and service commercial roofing systems, working alongside trusted "
                     "subcontractors and vendors.")
RCOMPANY = "Summit Roofing"

# The product handbook is a production constant, not something to invent per test; freshness here is
# in the candidate SENTENCES judged against it, none of which appear in development.
HANDBOOK = """What Example Product is
Example Product is a cash-flow decision tool for construction subcontractors. It is designed
to use bank balances, open invoices and bills, payroll dates, fixed costs and upcoming job
billings to compare scenarios and explain recommended next steps.

What to say about its state
Say plainly that the MVP is still being finished. Never say it is ready, never promise a
result, a saving or a faster payment, and never claim other contractors already use it.

What to say about the company
Open with one sentence about what the company does, resting on a quote from its own site.
Never mention their money, payment timing, problems or software.

What to ask for
Ask whether they would be open to a twenty minute conversation next week about the early
preview. Ask it as a question. Ask for nothing else."""


FRESH_CASES = [
    # --- supported: must stay accepted (no false rejects) ---------------------------------------
    {"id": "fresh-company-verbatim", "category": "baseline", "kind": "COMPANY", "source": RQUOTE,
     "text": f"{RCOMPANY} provides commercial roofing installation and repair for warehouses and "
             "retail centers.", "company": RCOMPANY, "expect": "accept",
     "because": "restates the quote's own claim"},
    {"id": "fresh-company-paraphrase", "category": "baseline", "kind": "COMPANY", "source": RQUOTE,
     "text": f"I noticed {RCOMPANY} installs and repairs commercial roofing for warehouses.",
     "company": RCOMPANY, "expect": "accept", "because": "a paraphrase using only the quote's words"},
    {"id": "fresh-oxford-list", "category": "baseline", "kind": "COMPANY", "source": RQUOTE_LIST,
     "text": f"{RCOMPANY} provides installation, repair, and maintenance of commercial roofing, "
             "gutters, and skylights.", "company": RCOMPANY, "expect": "accept",
     "because": "a faithful Oxford-comma list; the ', and' before the last item is not a second "
                "claim, and must not be split (the real-draft false positive this guards against)"},
    {"id": "fresh-product-paraphrase", "category": "baseline", "kind": "PRODUCT", "source": HANDBOOK,
     "text": "Example Product compares scenarios from your open invoices and bills.",
     "expect": "accept", "because": "one grounded claim, single clause"},
    {"id": "fresh-negative-restated", "category": "baseline", "kind": "PRODUCT", "source": HANDBOOK,
     "text": "Example Product never promises a saving.", "expect": "accept",
     "because": "restates the handbook's own negation"},
    {"id": "fresh-numbers-kept", "category": "baseline", "kind": "COMPANY", "source": RQUOTE_HISTORY,
     "text": f"{RCOMPANY} has completed more than 350 roofing projects across the Midwest since 2005.",
     "company": RCOMPANY, "expect": "accept", "because": "both figures exactly as the quote gives them"},
    {"id": "fresh-qualifier-kept", "category": "baseline", "kind": "COMPANY", "source": RQUOTE_PILOT,
     "text": f"{RCOMPANY} is currently onboarding a select group of early-access clients on a pilot "
             "basis.", "company": RCOMPANY, "expect": "accept",
     "because": "keeps every one of the quote's qualifiers"},
    # First run of this set, this case read "A short conversation about Example Product next week"
    # and the validator rejected it - correctly: "short" is not a handbook word, so the case was a
    # mis-authored (mildly unsupported) claim, not the supported control it was meant to be. The
    # case text is corrected to a genuinely grounded subject; the validator was NOT changed and its
    # behaviour (rejecting an ungrounded word) is exactly right. Recorded in the results doc.
    {"id": "fresh-subject", "category": "baseline", "kind": "SUBJECT", "source": HANDBOOK,
     "text": "A conversation about Example Product next week", "company": RCOMPANY,
     "expect": "accept", "because": "names the product and the ask in the handbook's own words"},

    # --- unsupported, words wrong: must reject --------------------------------------------------
    {"id": "fresh-negation", "category": "negation", "kind": "COMPANY", "source": RQUOTE,
     "text": f"{RCOMPANY} does not provide commercial roofing installation for warehouses.",
     "company": RCOMPANY, "expect": "reject", "because": "denies a purely positive quote"},
    {"id": "fresh-wrong-number", "category": "wrong_number", "kind": "COMPANY", "source": RQUOTE_HISTORY,
     "text": f"{RCOMPANY} has completed more than 500 roofing projects since 2005.",
     "company": RCOMPANY, "expect": "reject", "because": "500 is not the quote's 350"},
    {"id": "fresh-wrong-date", "category": "wrong_date", "kind": "COMPANY", "source": RQUOTE_HISTORY,
     "text": f"{RCOMPANY} has completed more than 350 roofing projects since 1995.",
     "company": RCOMPANY, "expect": "reject", "because": "1995 is not the quote's 2005"},
    {"id": "fresh-scope", "category": "exaggerated_scope", "kind": "COMPANY", "source": RQUOTE_REGIONAL,
     "text": f"{RCOMPANY} installs commercial roofing for warehouses in every state.",
     "company": RCOMPANY, "expect": "reject", "because": "the quote scopes to one metro; this claims every state"},
    {"id": "fresh-dropped-qualifier", "category": "removed_qualifier", "kind": "COMPANY",
     "source": RQUOTE_PILOT, "text": f"{RCOMPANY} onboards commercial clients.",
     "company": RCOMPANY, "expect": "reject",
     "because": "drops 'currently', 'select', 'early-access' and 'on a pilot basis'"},
    {"id": "fresh-invented-capability", "category": "unsupported_combination", "kind": "PRODUCT",
     "source": HANDBOOK, "text": "Example Product files your quarterly taxes automatically.",
     "expect": "reject", "because": "files, quarterly, taxes, automatically are not in the handbook"},

    # --- outside the validator's scope: must hold for review ------------------------------------
    {"id": "fresh-delegation-possessive", "category": "delegated_actor", "kind": "COMPANY",
     "source": RQUOTE_DELEGATION,
     "text": f"{RCOMPANY}'s trusted subcontractors install and service commercial roofing systems.",
     "company": RCOMPANY, "expect": "review",
     "because": "every word is in the quote, but the company's possessive makes the subcontractors, "
                "not the company, the ones who install; who performs it is for a person to confirm"},
    {"id": "fresh-delegation-verb", "category": "delegated_actor", "kind": "COMPANY",
     "source": RQUOTE_DELEGATION,
     "text": f"{RCOMPANY} relies on outside subcontractors to install commercial roofing systems.",
     "company": RCOMPANY, "expect": "review",
     "because": "a delegation verb naming a third-party performer; who installs is for a person"},
    {"id": "fresh-stitch-product", "category": "unsupported_combination", "kind": "PRODUCT",
     "source": HANDBOOK,
     "text": "Example Product is still being finished, and it already compares scenarios for "
             "construction subcontractors.",
     "expect": "review",
     "because": "two independent claims, each grounded, joined by ', and' and pointing at "
                "different handbook clauses (the state clause and the 'what it is' clause)"},

    # --- the residual the validator cannot close: expected to remain wrongly accepted ----------
    {"id": "fresh-residual-recombination", "category": "unsupported_combination", "kind": "PRODUCT",
     "source": HANDBOOK,
     "text": "Example Product uses payroll dates to explain recommended invoices.",
     "expect": "reject",
     "because": "THE RESIDUAL CLASS on fresh data: payroll, dates, explain, recommended, invoices "
                "all sit in the one handbook clause, single clause, no joiner - a fabricated "
                "input/output pairing no word-overlap check can tell from a true paraphrase. "
                "EXPECTED to be wrongly ACCEPTED; reported as the honest gap"},
]


if __name__ == "__main__":
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from grounding_eval_runner import run, summarize

    summarize(run(FRESH_CASES), "FRESH_CASES (reserved, run once)")
