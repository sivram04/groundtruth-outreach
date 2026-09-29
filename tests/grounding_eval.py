"""An adversarial set for `outreach.writer`'s grounding check, written BEFORE it was changed.

Every case here was written before `writer.py` was touched for this work, from reading the
module's own code and the founder's real fixture (`examples/synthetic_handbook.txt`, the same
quote `test_writer.py` uses) — never from watching what a draft candidate rule already does or
does not catch. `TUNING_CASES` were the ones read while the new checks were being written;
`HELD_OUT_CASES` were set aside and looked at only once, after the implementation was finished,
to measure it rather than to shape it. Both lists are recorded before the code change so the
"before" and "after" runs are honest: the case, its evidence, its expected verdict and the reason
for that verdict are fixed points nothing in this file's history was allowed to move.

Each case is one dict:
  id        a short, stable name
  category  one of the seven kinds the audit named: baseline, negation, reversed_subject,
            wrong_number, wrong_date, exaggerated_scope, removed_qualifier, unsupported_combination
  kind      "COMPANY", "PRODUCT", "ASK" or "SUBJECT" — which part of the email this exercises
  source    the quote (COMPANY) or handbook text (everything else) the sentence is judged against
  text      the candidate sentence (or subject line)
  company   the company name, when a COMPANY sentence needs one to be stripped before judging
  expect    "accept" or "reject" — the fact of the matter, decided independently of the code
  because   why a person would call it that, in one sentence

A case with expect="reject" and a category is not a claim that today's code, or even the
improved one, catches it: `docs/testing/grounding-eval/RESULTS.md` records exactly which do and
do not, both before and after, and says so where a case is expected to remain uncaught.
"""

QUOTE = "We install electrical distribution systems for commercial buildings."
QUOTE_HISTORY = "We have installed systems in over 200 buildings since 1998."
QUOTE_REGIONAL = "We install electrical distribution systems for commercial buildings in central Ohio."
QUOTE_PILOT = "We currently serve select commercial clients in central Ohio on a pilot basis."
COMPANY = "Example Electric"

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

# A second, invented handbook fragment used only for the two cases that need a source carrying
# a scoped integration claim; the shared HANDBOOK above states no such thing, so extending it
# for these two cases alone (rather than editing the whole fixture other tests already read)
# keeps the rest of this file working against the same text `test_writer.py` uses.
INTEGRATION_HANDBOOK = HANDBOOK + """

What to say about integrations
Example Product currently reads QuickBooks Online only. Other accounting systems are planned
for later, and none of them may be named as supported yet."""


TUNING_CASES = [
    # --- baseline: supported claims a bounded check must keep passing ------------------------
    {"id": "baseline-company-verbatim", "category": "baseline", "kind": "COMPANY",
     "source": QUOTE, "text": f"{COMPANY} installs electrical distribution systems for commercial buildings.",
     "company": COMPANY, "expect": "accept",
     "because": "restates the quote's own claim with no addition"},
    {"id": "baseline-company-paraphrase", "category": "baseline", "kind": "COMPANY",
     "source": QUOTE, "text": f"I noticed {COMPANY} installs distribution systems for commercial buildings.",
     "company": COMPANY, "expect": "accept",
     "because": "a light paraphrase using only the quote's own words"},
    {"id": "baseline-product-state", "category": "baseline", "kind": "PRODUCT",
     "source": HANDBOOK, "text": "The MVP is still being finished.",
     "expect": "accept", "because": "the handbook's own qualified state, kept qualified"},
    {"id": "baseline-subject", "category": "baseline", "kind": "SUBJECT",
     "source": HANDBOOK, "text": "A conversation about Example Product next week",
     "company": COMPANY, "expect": "accept", "because": "names the product and the ask, nothing more"},
    {"id": "baseline-negative-quote-verbatim", "category": "baseline", "kind": "COMPANY",
     "source": f"{COMPANY} does not install HVAC or refrigeration systems.",
     "text": f"{COMPANY} does not install HVAC or refrigeration systems.",
     "company": COMPANY, "expect": "accept",
     "because": "a negative quote repeated exactly is still grounded; a check that blocks "
                "every negation word would wrongly reject this"},

    # --- negation: a claim the source never made, added by the model -------------------------
    {"id": "negation-company-does-not", "category": "negation", "kind": "COMPANY",
     "source": QUOTE, "text": f"{COMPANY} does not install electrical distribution systems for commercial buildings.",
     "company": COMPANY, "expect": "reject",
     "because": "the quote is a positive claim; the candidate reverses it to a denial the "
                "company's own site never states"},
    {"id": "negation-company-never", "category": "negation", "kind": "COMPANY",
     "source": QUOTE, "text": f"{COMPANY} never installs electrical distribution systems for commercial buildings.",
     "company": COMPANY, "expect": "reject",
     "because": "same reversal, a different negation word"},
    {"id": "negation-company-cannot", "category": "negation", "kind": "COMPANY",
     "source": QUOTE, "text": f"{COMPANY} cannot install electrical distribution systems for commercial buildings.",
     "company": COMPANY, "expect": "reject",
     "because": "states an incapacity the quote does not claim"},
    {"id": "negation-company-fabricated-exclusion", "category": "negation", "kind": "COMPANY",
     "source": QUOTE, "text": f"{COMPANY} installs electrical distribution systems for commercial "
                              "buildings, but not for residential ones.",
     "company": COMPANY, "expect": "reject",
     "because": "the quote is silent on residential work either way; the candidate invents an "
                "exclusion the source never stated"},
    {"id": "negation-product-explains-nothing", "category": "negation", "kind": "PRODUCT",
     "source": HANDBOOK, "text": "Example Product does not explain recommended next steps.",
     "expect": "reject",
     "because": "the handbook says it does explain recommended next steps; this reverses it"},

    # --- reversed subject: who does the work has changed ---------------------------------------
    # A first pass authored "Customers install..." and "Your team installs..." here. Running the
    # unmodified baseline (recorded below, before writer.py was touched) showed both already
    # rejected today — not because anything notices the subject is wrong, but because "customers"
    # and "team" simply are not words the quote uses, so ordinary word-overlap grounding already
    # flags them for an unrelated reason. Kept as `reversed-subject-easy-*` (still a real pattern,
    # still worth a passing regression control) and replaced as the PRIMARY cases with ones built
    # entirely from the quote's own vocabulary, so a pass here can only mean the subject was
    # actually checked, not a coincidence of an unrelated word.
    {"id": "reversed-subject-easy-customers", "category": "reversed_subject", "kind": "COMPANY",
     "source": QUOTE, "text": "Customers install their own electrical distribution systems for "
                              f"commercial buildings, and {COMPANY} supports the process.",
     "company": COMPANY, "expect": "reject",
     "because": "the quote says the company installs; the candidate makes the customer the "
                "installer — already rejected today, but only because 'customers' is not in "
                "the quote, not because anything notices the subject changed"},
    {"id": "reversed-subject-we-for-them", "category": "reversed_subject", "kind": "COMPANY",
     "source": QUOTE, "text": f"We install electrical distribution systems for commercial "
                              f"buildings for {COMPANY}.",
     "company": COMPANY, "expect": "reject",
     "because": "every content word — install, electrical, distribution, systems, commercial, "
                "buildings — is already in the quote, so word-overlap grounding alone cannot "
                "tell this from a correct restatement; only noticing that the sentence's own "
                "subject is 'we' (the founder's voice), not the lead company, catches it"},

    # --- wrong quantities or dates -------------------------------------------------------------
    {"id": "wrong-number-count", "category": "wrong_number", "kind": "COMPANY",
     "source": QUOTE_HISTORY, "text": f"{COMPANY} has installed systems in over 500 buildings since 1998.",
     "company": COMPANY, "expect": "reject",
     "because": "the quote says over 200 buildings, not 500"},
    {"id": "wrong-date-year", "category": "wrong_date", "kind": "COMPANY",
     "source": QUOTE_HISTORY, "text": f"{COMPANY} has installed systems in over 200 buildings since 1988.",
     "company": COMPANY, "expect": "reject",
     "because": "the quote says since 1998, not 1988"},
    {"id": "wrong-number-added", "category": "wrong_number", "kind": "COMPANY",
     "source": QUOTE_HISTORY, "text": f"{COMPANY} has installed systems in over 200 buildings across "
                                      "12 states since 1998.",
     "company": COMPANY, "expect": "reject",
     "because": "12 states is a figure the quote never gives"},
    {"id": "correct-numbers-verbatim", "category": "baseline", "kind": "COMPANY",
     "source": QUOTE_HISTORY, "text": f"{COMPANY} has installed systems in over 200 buildings since 1998.",
     "company": COMPANY, "expect": "accept",
     "because": "restates both figures exactly as the quote gives them"},

    # --- exaggerated scope ----------------------------------------------------------------------
    {"id": "exaggerated-scope-every-state", "category": "exaggerated_scope", "kind": "COMPANY",
     "source": QUOTE_REGIONAL, "text": f"{COMPANY} installs electrical distribution systems for "
                                       "commercial buildings in every state.",
     "company": COMPANY, "expect": "reject",
     "because": "the quote scopes the work to central Ohio; the candidate claims every state"},
    {"id": "exaggerated-scope-nationwide-any", "category": "exaggerated_scope", "kind": "COMPANY",
     "source": QUOTE_REGIONAL, "text": f"{COMPANY} installs electrical distribution systems for "
                                       "any commercial building nationwide.",
     "company": COMPANY, "expect": "reject",
     "because": "two absolute scope words, neither in the regional quote"},
    {"id": "correct-scope-kept", "category": "baseline", "kind": "COMPANY",
     "source": QUOTE_REGIONAL, "text": f"{COMPANY} installs electrical distribution systems for "
                                       "commercial buildings in central Ohio.",
     "company": COMPANY, "expect": "accept",
     "because": "keeps the quote's own regional scope"},

    # --- removed qualifications -----------------------------------------------------------------
    {"id": "removed-qualifier-pilot", "category": "removed_qualifier", "kind": "COMPANY",
     "source": QUOTE_PILOT, "text": f"{COMPANY} serves commercial clients in central Ohio.",
     "company": COMPANY, "expect": "reject",
     "because": "drops 'currently', 'select' and 'on a pilot basis', generalising a limited, "
                "provisional claim into a standing one"},
    {"id": "correct-qualifier-kept", "category": "baseline", "kind": "COMPANY",
     "source": QUOTE_PILOT, "text": f"{COMPANY} currently serves select commercial clients in "
                                    "central Ohio on a pilot basis.",
     "company": COMPANY, "expect": "accept",
     "because": "keeps every one of the quote's qualifiers"},
    {"id": "removed-qualifier-integration", "category": "removed_qualifier", "kind": "PRODUCT",
     "source": INTEGRATION_HANDBOOK,
     "text": "Example Product works with your accounting system.",
     "expect": "reject",
     "because": "the handbook says QuickBooks Online only, with others planned; this drops the "
                "limit and states a general capability that is not true yet"},
]

HELD_OUT_CASES = [
    # --- baseline: different quotes and handbook lines, never used while building the check --
    {"id": "held-baseline-company-slash", "category": "baseline", "kind": "COMPANY",
     "source": "We serve sewage/wastewater treatment facilities and schools.",
     "text": f"{COMPANY} serves wastewater treatment facilities and schools.",
     "company": COMPANY, "expect": "accept",
     "because": "a slash-alternative already supported the word on its own"},
    {"id": "held-baseline-product-ask", "category": "baseline", "kind": "ASK",
     "source": HANDBOOK, "text": "Would you be open to a twenty minute conversation next week "
                                 "about the early preview?",
     "expect": "accept", "because": "the handbook's own requested ask, as a question"},
    {"id": "held-baseline-negative-restated", "category": "baseline", "kind": "PRODUCT",
     "source": HANDBOOK, "text": "Example Product does not promise a result, a saving or a "
                                 "faster payment.",
     "company": COMPANY, "expect": "accept",
     "because": "restates the handbook's own negative instruction with a different negation "
                "word ('does not' for 'never'); a rule that required the identical negation "
                "word, rather than crediting any negation already present in the matching "
                "clause, would wrongly reject this"},

    # --- negation, held out --------------------------------------------------------------------
    {"id": "held-negation-wont", "category": "negation", "kind": "COMPANY",
     "source": QUOTE, "text": f"{COMPANY} won't install electrical distribution systems for "
                              "commercial buildings without a signed contract.",
     "company": COMPANY, "expect": "reject",
     "because": "adds a denial and a condition the quote never states"},
    {"id": "held-negation-doesnt-handbook", "category": "negation", "kind": "PRODUCT",
     "source": HANDBOOK, "text": "Example Product doesn't use payroll dates to compare scenarios.",
     "expect": "reject",
     "because": "the handbook lists payroll dates among what it uses; this denies it"},

    # --- reversed subject, held out: one built entirely from unrelated words (an easy control),
    # one from the source's own vocabulary with the actor swapped under the company's own name
    # (the class this bounded check is not built to catch, and is expected to miss) -------------
    {"id": "held-reversed-subject-other-contractors", "category": "reversed_subject", "kind": "COMPANY",
     "source": QUOTE, "text": "Other contractors install electrical distribution systems for "
                              f"commercial buildings that {COMPANY} project-manages.",
     "company": COMPANY, "expect": "reject",
     "because": "makes an unnamed third party the installer; 'contractors' and 'project-manages' "
                "are not in the quote, so ordinary grounding is expected to catch this on its own"},
    {"id": "held-reversed-subject-delegation-kept-under-name", "category": "reversed_subject",
     "kind": "COMPANY",
     "source": "We install and maintain electrical distribution systems for commercial "
              "buildings, working with trusted subcontractors and vendors.",
     "text": f"{COMPANY}'s trusted subcontractors install and maintain electrical distribution "
             "systems for commercial buildings.",
     "company": COMPANY, "expect": "reject",
     "because": "every word here — trusted, subcontractors, install, maintain, electrical, "
                "distribution, systems, commercial, buildings — is already in this quote, "
                "because the quote itself mentions working with subcontractors; the candidate "
                "keeps the company's own name as the grammatical subject while quietly making "
                "the subcontractors, not the company, the one who installs. This is the class "
                "of reversal a leading-subject-marker screen cannot see, and it is EXPECTED "
                "still to be wrongly accepted; the results record it as a known open gap, not "
                "a pass"},

    # --- wrong quantities or dates, held out ----------------------------------------------------
    {"id": "held-wrong-number-transposed", "category": "wrong_number", "kind": "COMPANY",
     "source": QUOTE_HISTORY, "text": f"{COMPANY} has installed systems in over 220 buildings since 1998.",
     "company": COMPANY, "expect": "reject",
     "because": "220 is close to 200 but not the quote's own figure"},
    {"id": "held-wrong-date-handbook", "category": "wrong_date", "kind": "PRODUCT",
     "source": HANDBOOK + "\n\nWhen it started\nWork on Example Product began in 2024.",
     "text": "Work on Example Product began in 2019.",
     "expect": "reject", "because": "the (held-out) handbook variant says 2024, not 2019"},

    # --- exaggerated scope, held out -------------------------------------------------------------
    {"id": "held-exaggerated-scope-product-audience", "category": "exaggerated_scope", "kind": "PRODUCT",
     "source": HANDBOOK, "text": "Example Product is a cash-flow decision tool for every "
                                 "contractor and business owner.",
     "expect": "reject",
     "because": "the handbook scopes the tool to construction subcontractors; this widens the "
                "audience to everyone"},

    # --- removed qualifications, held out ---------------------------------------------------------
    {"id": "held-removed-qualifier-still-being-finished", "category": "removed_qualifier",
     "kind": "PRODUCT", "source": HANDBOOK, "text": "The MVP is finished.",
     "expect": "reject",
     "because": "the existing case this module's own tests already cover; kept here as a "
                "held-out control that the refactor must not have broken"},

    # --- unsupported combination of facts, held out: one caught, one honestly not --------------
    {"id": "held-combination-cross-paragraph", "category": "unsupported_combination", "kind": "PRODUCT",
     "source": HANDBOOK, "text": "Example Product is still being finished, and other contractors "
                                 "already promise a faster payment with it.",
     "expect": "reject",
     "because": "stitches the state paragraph's own words with the very claims the state "
                "paragraph says never to make; also independently caught by BANNED, so this "
                "case is a weak test of localisation on its own and is read as informational"},
    {"id": "held-combination-same-paragraph", "category": "unsupported_combination", "kind": "PRODUCT",
     "source": HANDBOOK, "text": "Example Product uses your bank balance to explain recommended payroll.",
     "expect": "reject",
     "because": "'bank', 'balance', 'explain', 'recommended' and 'payroll' all sit in the one "
                "paragraph the handbook uses to describe the product, so no word-overlap check, "
                "localised or not, can tell this fabricated compound claim from a true one; this "
                "case is EXPECTED to remain wrongly accepted, and the results record it as an "
                "open limitation of grounding by word overlap, not a defect introduced here"},
]
