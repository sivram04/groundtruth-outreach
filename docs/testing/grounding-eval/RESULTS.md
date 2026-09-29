# Grounding check, item 2: adversarial sets, a review outcome, and what it does and does not close

2026-09-29. `outreach/writer.py`'s grounding check screens what Gemini writes before it can become
a draft: every content word in a sentence must appear in the source it cites. The audit
(`docs/ARCHITECTURE_REVIEW_2026-09-29.md` §3.1) confirmed a hole — a sentence that reverses its
quote's meaning could still pass, because word overlap does not see negation. This document records
the whole item-2 effort against written adversarial sets, **with the corrections an external review
required**, and states plainly what the validator establishes and what still needs a person.

## Corrections to the earlier version of this document (on the founder's review)

1. **"Held-out cases looked at only once" — withdrawn.** An earlier version said the
   `HELD_OUT_CASES` in `tests/grounding_eval.py` were set aside and inspected only once, after the
   implementation was finished. That is false: the eval runner runs the tuning and held-out lists
   together, and it was run repeatedly while the checks were iterated. **Both lists in
   `grounding_eval.py` are development evidence.** The genuinely reserved measurement is the new
   `tests/grounding_eval_fresh.py`, written after the code was frozen and run once (below).
2. **"Zero false rejects throughout" — replaced with the real sequence.** There was an
   intermediate stage with **21 false rejects on real data**, corrected before commit; the
   before/after/intermediate numbers are all stated below rather than a single flattering summary.
3. **The 21-draft recheck is compatibility evidence, not proof of factual correctness.** It shows
   the shipped checks do not newly block real drafts; it says nothing about whether those drafts'
   claims are true.
4. **Item 1's authenticated console dashboard check remains PENDING** (a separate task) — no
   authorised signed-in session was available; left for the founder's sign-in. Recorded here only
   so this document is not read as claiming the whole item stack is verified.

## Method

`tests/grounding_eval.py` holds the development cases (tuning + held-out); `tests/grounding_eval_fresh.py`
holds the reserved set. `tests/grounding_eval_runner.py` runs a case through the real
`writer.verify()`, filling the three untested parts of the email with known-good sentences, and
classifies the outcome as **accept**, **reject** (the words are wrong), or **review** (the validator
cannot tell; the sentence is held for a person and no approval hash can be minted). False accepts,
false rejects and reviews are counted separately.

A **review** is realised as a blocking problem carrying `writer.REVIEW_PREFIX`: like every problem
it makes `verify()` return no draft, so no approval hash is ever minted for a flagged sentence (the
property the founder asked to be able to verify). It is distinct from a plain rejection only in its
marker and its wording; surfacing the exact words in an on-screen review state, rather than blocking,
is recorded as not built.

## The sequence of results

### Baseline — the unmodified validator, before any item-2 change

| set | correct | false accept | false reject |
|---|---|---|---|
| Tuning (22) | 15/22 | 7 | 0 |
| Held-out (13) | 7/13 | 6 | 0 |

The seven tuning misses were exactly the categories the audit named: an added negation, a wrong
count, a wrong date, a dropped qualifier. (`docs/testing/grounding-eval-baseline.json`.)

### Intermediate — the real false rejects that "zero false rejects throughout" had hidden

The first version of the new word-level checks was run **read-only against the founder's real
handbook and all 25 real Drafts-tab rows**. It **flagged 21 of 21 real drafts that were previously
fine** — a severe false-reject regression, caught before commit. Two real bugs, neither visible in
the synthetic fixture:

- Localisation split the source on blank lines; the real handbook is one blank-line-free block, so
  every check ran against the whole 5,521-character document instead of a local window.
- The company's own name collided with a trigger word ("All" in "All Phase Power & Lighting" tripped
  the scope check before the name was stripped).

Both were fixed (sentence/line-clause localisation with a mid-line-wrap join; every check strips the
company name first; the qualifier and scope word-lists narrowed to distinctive phrases). This is the
"actual intermediate result" — the checks did over-reject real drafts at one stage.

### After the word-level fixes (prior session)

| set | correct | false accept | false reject |
|---|---|---|---|
| Tuning (22) | 22/22 | 0 | 0 |
| Real drafts (21 with sentences) | — | — | **0 newly blocked** |

### This session — a review outcome for two classes the word checks cannot adjudicate

Two structural detectors were added and routed to **review** (blocking, marked), addressing two of
the three claims that the earlier version merely documented as limitations:

- **`delegated_actor`** — work credited to a third party under the company's own name
  ("<Company>'s subcontractors install ...", "... relies on subcontractors to install ..."). Reads
  the grammatical shape, never the meaning.
- **`stitched_claim`** — two independent claims (each with its own verb, so a list's final ", and X"
  tail does not count) joined by a coordinating conjunction whose closest source clauses differ.

Development sets, after:

| set | correct | reject | review | false accept | false reject |
|---|---|---|---|---|---|
| Tuning (22) | 22/22 | 14 | 0 | 0 | 0 |
| Held-out (13) | 12/13 | 7 | 2 | 1 | 0 |

The two held-out reviews are the delegation case and the cross-paragraph stitch — both were open
gaps in the earlier version and are now held for review. The one held-out false accept is the
residual named below. (`docs/testing/grounding-eval-after.json`.)

Real drafts, after (read-only, live handbook): **0 of 21 newly rejected, 0 newly sent to review.**
This is compatibility evidence — the shipped checks do not block real drafts — not proof the drafts'
claims are true.

### The reserved fresh set — written after the freeze, run once

`tests/grounding_eval_fresh.py`: 18 cases (new companies, quotes and sentences that appear nowhere
in development), run once against the frozen validator.

| outcome | count | cases |
|---|---|---|
| correct | 16/18 | — |
| plainly rejected | 6 | negation, wrong number, wrong date, scope, dropped qualifier, invented capability |
| held for review | 2 | `fresh-delegation-possessive`, `fresh-delegation-verb` |
| **false accept** | 2 | `fresh-stitch-product`, `fresh-residual-recombination` |
| **false reject** | 0 | — |

Every supported claim was accepted (baseline 8/8) — the cardinal requirement holds on unseen data.
Delegation review generalised (2/2). (`docs/testing/grounding-eval-fresh.json`.)

**Two things the first fresh run surfaced, handled with the validator frozen throughout:**

- A **harness bug** (not the validator): the runner's filler company sentence was hardcoded to
  "Example Electric" while a fresh case named "Summit Roofing", so the *filler* failed grounding.
  Fixed the runner to keep the filler internally consistent; re-ran.
- A **mis-authored case** (not the validator): `fresh-subject` originally read "A **short**
  conversation about Example Product next week" — "short" is not a handbook word, so the validator
  **correctly** rejected an ungrounded word. The case text was corrected to a genuinely grounded
  subject; the validator's behaviour (rejecting ungrounded words) is right and unchanged.

Neither was a code change to `writer.py`. Both are disclosed rather than silently fixed.

## The false accepts, named

Both surviving false accepts are the same family — a claim built from words that legitimately belong
together in one source clause — and **neither was iterated on after the fresh run, to keep the fresh
measurement honest and avoid overfitting**:

1. **The residual (`held-combination-same-paragraph`, `fresh-residual-recombination`).** A
   single-clause recombination — "Example Product uses your bank balance to explain recommended
   payroll" — whose every word sits in the one handbook clause, no joiner, no delegation. **No
   word-overlap method can catch this without also rejecting honest paraphrases** that skip
   enumerated middle items ("uses bank balances to compare scenarios") — verified: an
   adjacency-novelty rule flags both. It is left to human review, pinned as the sole residual by
   `_KNOWN_RESIDUAL` in `test_writer.py`, and not claimed as closed.
2. **A stitch the detector misses (`fresh-stitch-product`), found on fresh data.** "Example Product
   is still being finished, and it already compares scenarios for construction subcontractors" — a
   genuine two-clause stitch, but both halves share the subject "Example Product", which pulls both
   to the same handbook clause, so the different-cluster test does not fire. The stitch detector
   catches stitches whose halves point at different source clauses; it **misses those whose halves
   share a dominant subject noun.** Reported as a measured limitation, not fixed.

## What this establishes, and what still needs a person

- **Establishes (mechanically):** every content word and digit in a sentence is present in its cited
  source; the sentence does not add a negation, an absolute scope word, or drop a qualifier the
  localised source has; a company sentence does not lead with an alternative actor; and two visible
  structural shapes — a third party credited with the work, and two clauses stitched across source
  clusters — are blocked from an approval hash and held for review.
- **Does not establish (needs human judgment):** that any claim is *true*; a reversal kept under the
  company's own name where the actor is not a listed third-party word; a single-clause recombination
  of co-occurring words (the residual); a stitch whose halves share a subject; a subtle scope
  widening using no absolute word. The founder reviews the exact words of every draft; the approval
  hash binds them.

## Acceptance criteria status (item 2)

- Corrections to the report/audit/AS_BUILT — **done** (this document; §3.1; the change log).
- A review/blocking outcome for out-of-scope claims — **done for two of three** classes (delegation,
  cross-paragraph stitch). The third (single-clause recombination) is **not closed**; it is measured,
  named, and left to review, because no word-based rule closes it without false rejects. Item-1's
  authenticated dashboard check is **pending**.
- Tests requiring rejection/review, and no approval hash for uncertain claims — **done** (company
  sentences and subject lines; `test_writer.py`).
- Fresh set kept separate and run once — **done** (`grounding_eval_fresh.py`).
- False accepts / false rejects / reviews reported separately — **done** (above and the JSON).

## Proof

- `tests/grounding_eval.py` (development), `tests/grounding_eval_fresh.py` (reserved),
  `tests/grounding_eval_runner.py` (harness). Reproduce with
  `python -m tests.grounding_eval_runner` and `python -m tests.grounding_eval_fresh`.
- `tests/test_writer.py` — 706-test suite includes every eval case as a permanent regression, the
  delegation/stitch/review unit tests, and the "review flags mint no approval hash" tests for
  company sentences and subjects.
- **10 deliberate breaks of the review machinery, all caught** (delegation and stitch each disabled,
  loosened, and removed from each sentence path; the review marker emptied), on top of the 19
  word-level breaks from the prior session.
- Whole suite: 706 Python, 46 React.

## What this does not establish (limits of the evidence itself)

- The fresh set is 18 cases authored by the same person who wrote the fix; unseen while iterating,
  but not an independent or statistically powered benchmark.
- The real-draft checks are 21 drafts from one handbook and one research batch — compatibility, not a
  measured false-reject rate.
- **Nothing here is deployed.** `outreach/writer.py` runs inside both `outreach-worker` and
  `outreach-console`; neither image is rebuilt with this change.
- Quote freshness (§3.3 of the audit) is untouched, as instructed.
