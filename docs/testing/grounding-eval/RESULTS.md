# Grounding check, item 2: adversarial sets, a review outcome, and what it does and does not close

## THIRD-REVIEW CORRECTION, 2026-09-29 (supersedes everything below; originals kept for the record)

A third review corrected two overclaims in the SECOND-REVIEW section and chose the acceptance
contract. Both corrections are also applied inline lower down, marked.

1. **The "theorem" is withdrawn.** The SECOND-REVIEW section said the three word-gate experiments
   *established a theorem* that "there is no word-based sweet spot." That is an overclaim. Three
   heuristics tried at particular settings, each too blunt on the real drafts, is **evidence that
   those three designs are inadequate — not a proof that no word-based approach can work.** No
   search over methods was run and no lower bound was proved. The corrected, narrower conclusion:
   these particular gates are too blunt, so the control chosen is a human evidence review, not more
   regex. (Corrected inline at point 2 of the section below.)

2. **"Supported sentences" is withdrawn as a label for the real drafts.** The measurements counted
   sentences from **drafts that currently pass the validator**. A previously accepted production
   draft is **not** automatically a ground-truth "supported" example — word overlap passing it is
   exactly what cannot certify faithfulness. So "21 of 36 real *supported* sentences" was wrong; it
   is "21 of 36 currently-*passing* sentences," and the figure is a review-burden/churn measure, not
   a false-positive rate against known-good text. Denominators are explained inline. The same
   mislabel is corrected in `docs/AS_BUILT.md`, `docs/ARCHITECTURE_REVIEW_2026-09-29.md` and
   `tests/test_writer.py`. The measurement evidence itself (the numbers and method) is preserved.

3. **The decision: option (B) — an enforced, content-bound human evidence review before final
   approval.** For this single-founder pilot the review burden is accepted: **this contract requires
   a human evidence review for every draft before it can become approval-ready.** Generation is NOT
   constrained to fixed handbook copy in this change (option A is not taken). The two measured
   validator false accepts are **not** treated as acceptable residual risk (option C is not taken);
   instead every draft — those two included — is blocked from a final approval hash until a valid,
   content-bound human review of the current candidate exists.

**What this contract does and does not do.** It gates approval on a human's judgment bound to the
exact candidate and its cited evidence; it does **not** fix entailment, does **not** make the
validator semantically correct, and does **not** touch quote freshness. The raw validator false
accepts remain visible and unchanged in the grounding evaluation below — the human gate is a
*control on approval*, not an improvement in the validator's accuracy, and is not relabelled as one.

Enforcement evidence, the storage/migration design, and the honest burden statement are recorded in
`docs/AS_BUILT.md` (this pass's change-log entry) and proven by `tests/test_review.py` and
`tests/test_draft_pipeline.py`. Item 1's authenticated dashboard check stays separately pending.

---

## SECOND-REVIEW CORRECTION, 2026-09-29 (superseded by the THIRD-REVIEW correction above)

A second review made three points that this section corrects. **The validator (`outreach/writer.py`)
was NOT changed in this pass** — it is frozen at commit `597bfcc`; only the record, the tests, and
one enforcement test changed.

1. **The two remaining false accepts are UNRESOLVED, not "left to human review."** "Left to review"
   is only true if the application requires that review; the validator does not detect these two, so
   nothing routes them anywhere. They are:
   - the **same-clause recombination** ("Example Product uses your bank balance to explain
     recommended payroll" — every word in one handbook clause), and
   - the **shared-subject stitch** ("... is still being finished, and it already compares scenarios
     ..." — two clauses sharing the subject, so both localise to one clause and the stitch check's
     different-cluster requirement does not fire).

2. **Three word-based gate designs were tried against the real drafts and each held back a large
   share of the drafts that currently pass. This is measured evidence that these three designs are
   too blunt — it is NOT a proof that no word-based approach can work** (see the THIRD-REVIEW
   correction at the very top, which withdraws the "theorem" language). Each was a one-off,
   read-only probe against the live handbook and the real Drafts-tab rows; the probe scripts were
   not committed (the handbook is not in the repo), so only these figures and their method survive.
   The denominators: **36** = the distinct product-claim sentences across the real drafts;
   **21** = the distinct company-description sentences across the same drafts. These sentences are
   **drafts that currently pass the validator — not independently verified-faithful examples**, so
   the counts below are a *review-burden / churn* figure ("how many currently-passing sentences this
   gate would newly hold"), NOT a false-positive rate against known-good text.
   - A content-bigram "tight restatement" auto-pass gate would newly hold **21 of 36** currently-passing
     product sentences and **10 of 21** currently-passing company sentences — including the founder's
     own template product line.
   - A verbatim-span gate would newly hold **21 of 36** currently-passing product sentences and even
     hold a genuine handbook quote (any added word like "building" breaks contiguity).
   - Relaxing the stitch check to fire on any two predicate-bearing clauses would newly hold **23**
     currently-passing sentences, including legitimate compound-predicate company sentences
     ("... designs, builds, installs, services, and maintains ...") and the founder's own product line.

   What these three experiments show, and their limits: the two designs that preserve word order
   hold honest paraphrases (which reorder the enumerated middle items of a handbook clause), and the
   order-free design lets the single-clause recombination through (all its words co-occur in one
   clause). That is a real tension for *these three designs*. It is **not** a demonstration that some
   other word-based, structural or shallow-semantic method could not do better — no such search was
   run, and no lower bound was proved. The honest conclusion is narrower than the earlier draft
   claimed: **these particular gates are too blunt at the settings tried, so the chosen control is a
   human evidence review (option B), not more regex.**

3. **The enforcement the founder demanded IS real for what the validator flags:** a review/blocking
   outcome (delegation, cross-paragraph stitch) makes `verify()` return no draft, so no approval
   hash is minted — now proven end to end through the real write→verify→assemble pipeline, not just
   `verify()` (`tests/test_draft_pipeline.py`), even with `offer_approved=True`. The two unresolved
   false accepts are pinned as **strict-xfail** regression tests (company and subject variations)
   that assert the correct outcome and currently fail — so the day either is closed, the suite goes
   red and forces this record to be updated. No test asserts that their acceptance is acceptable.

**The acceptance-contract decision, put to the founder (criterion 2).** The validator's PASS
certifies *mechanical consistency* with the source (grounded words, and the specific added-signal
patterns it checks — not "no added negation" in general, only the negation/scope/qualifier/number
patterns coded), **never faithfulness**. Because word overlap cannot certify a product self-
description claim, three real options exist, and this is a decision, not something to ship silently:

- **(A) Constrain product-claim generation to approved statements** — the model reuses the founder's
  approved product/ask sentences rather than paraphrasing freely; a novel product claim (which a
  recombination is) then fails to match and is held. This eliminates the recombination class and is
  the recommended fix. It is a generation change, not built.
- **(B) Require a per-draft human review record bound to the exact draft hash** before any approval
  hash — review-all, which matches the current reality (the founder sends every email by hand). The
  hash already binds claim/evidence/recipient/handbook and any edit voids it; what is missing is that
  the hash is minted from a global `offer_approved` flag, not a per-draft claim review.
- **(C) Accept the two measured false accepts** under founder-in-the-loop sending (nothing sends
  automatically; drafting is disabled).

Until the founder chooses, **item 2 is not complete**: the two false accepts stand, unresolved and
pinned. What follows is the original write-up (kept visible), with its own now-corrected phrasing.

---

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

### The reserved fresh set — its real run history (not "run once")

`tests/grounding_eval_fresh.py`: 18 cases (new companies, quotes and sentences that appear nowhere
in development). Its history, recorded separately rather than collapsed into "run once" (the
second review's criterion 5), validator frozen throughout:

- **Run 1 (raw):** 15/18. It surfaced two problems that were NOT validator faults: a **harness bug**
  (the runner's filler company sentence was hardcoded to "Example Electric" while a fresh case named
  "Summit Roofing", so the filler failed grounding) and a **mis-authored case** (`fresh-subject`
  used "short", not a handbook word, so the validator *correctly* rejected an ungrounded word).
- **Run 2 (harness fixed):** 15/18 — the harness bug gone, `fresh-subject` still (correctly)
  rejecting "short".
- **Run 3 (mis-authored case corrected to a grounded subject):** 16/18 — the final figure.

Both corrections were to the harness and one bad case, never to `writer.py`; both are disclosed
here rather than hidden behind "run once". The final (run 3) outcome:

| outcome | count | cases |
|---|---|---|
| correct | 16/18 | — |
| plainly rejected | 6 | negation, wrong number, wrong date, scope, dropped qualifier, invented capability |
| held for review | 2 | `fresh-delegation-possessive`, `fresh-delegation-verb` |
| **false accept** | 2 | `fresh-stitch-product`, `fresh-residual-recombination` (both unresolved; see the correction at the top) |
| **false reject** | 0 | — |

Every supported claim was accepted (baseline 8/8) — the cardinal requirement holds on unseen data.
Delegation review generalised (2/2). **Supported claims that require review: 0 on the fresh set**
(the two reviews are both delegation cases, i.e. genuinely uncertain, not supported). This is the
"how many supported claims require review" figure the second review asked for, on this set. (Full
rows in `docs/testing/grounding-eval-fresh.json`.) The validator was not changed after run 3, so no
new reserved set is needed this pass; if the founder's contract decision changes the validator, a
new reserved set will be written and this one becomes development evidence.

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
   adjacency-novelty rule flags both. The validator still accepts it (a visible false accept in the
   eval); approval of it is blocked by the human evidence-review gate (option B), not by a word rule.
2. **A stitch the detector misses (`fresh-stitch-product`), found on fresh data.** "Example Product
   is still being finished, and it already compares scenarios for construction subcontractors" — a
   genuine two-clause stitch, but both halves share the subject "Example Product", which pulls both
   to the same handbook clause, so the different-cluster test does not fire. The stitch detector
   catches stitches whose halves point at different source clauses; it **misses those whose halves
   share a dominant subject noun.** Reported as a measured limitation, not fixed.

## What this establishes, and what still needs a person

- **Establishes (mechanically), for the specific patterns it codes — not in general:** every content
  word and digit in a sentence is present in its cited source; the sentence does not contain one of
  the coded negation words, one of the coded absolute-scope phrases, or drop one of the coded
  qualifier phrases the localised source has (these are finite word/phrase lists, not a guarantee
  against every negation or scope shift); a company sentence does not lead with one of the coded
  alternative-actor words; and two visible structural shapes — a third party credited with the work,
  and two clauses stitched across different source clauses — are blocked from an approval hash.
- **Does not establish (needs human judgment):** that any claim is *true*; a reversal kept under the
  company's own name where the actor is not a listed third-party word; a single-clause recombination
  of co-occurring words (the residual); a stitch whose halves share a subject; a subtle scope
  widening using no absolute word. The founder reviews the exact words of every draft; the approval
  hash binds them.

## Acceptance criteria status (item 2) — the approval control (option B) is built; see the top

- Correct the report (theorem overclaim; "supported" denominators) — **done** (top of this document,
  applied inline, and in `docs/AS_BUILT.md`, `docs/ARCHITECTURE_REVIEW_2026-09-29.md`,
  `tests/test_writer.py`); the measurement evidence is preserved.
- Separate draft identity / evidence review / final approval; candidate fingerprint before review, no
  approval hash needed to create the review record — **done** (`outreach/review.py`
  `candidate_fingerprint`, `record_confirmation`/`record_rejection`; `test_review.py`).
- Review covers company/product claims and the subject vs their cited evidence; records reviewer /
  decision / timestamp / fingerprint; missing / unreadable / malformed / rejected / stale block; the
  model cannot create or approve its own review — **done** (`review.enforce`; the reviewer must be an
  authorized human, supplied by an authenticated caller; `test_review.py`).
- Bind the review to recipient / subject / body / cited quote text+IDs / source URLs / handbook
  identity+version / offer settings; changes invalidate it; recheck at the action boundary — **done**
  (the fingerprint binds these and is recomputed inside `job_draft.create`; the "edit between review
  and action" test and the console changed-candidate refusal prove it).
- Console review flow (candidate beside evidence, confirm/reject, confirmation is human judgment not
  proof, sending/drafting disabled, no live-Sheet writes) — **done** behind `enable_review`
  (`outreach/console.py`; `test_console_api.py`); the deployed console keeps it off and read-only.
- Cover every consuming path; a direct API/lower-level call cannot bypass — **done**: the gate is in
  `job_draft.create` (the only path to a Gmail draft, and the one the HTTP create route calls); the
  follow-up path carries no cited-evidence claims and only follows an already-gated initial. Existing
  suppression / handbook / eligibility / approval checks are preserved.
- Replace the four strict-xfail cases with passing tests that those candidates cannot be approved
  without a valid review, WITHOUT relabelling human gating as validator accuracy — **done**: the raw
  false accepts stay visible in this eval (still in `_UNRESOLVED_FALSE_ACCEPTS`); the enforcement
  tests do not depend on the validator's verdict. Forged / stale / rejected reviews, changed
  evidence/content/recipient, and an edit between review and action are all tested; disabling the gate
  is caught by a deliberate break.
- Fresh set kept separate, run history recorded (not "run once"), false accepts / rejects / reviews /
  supported-claims-requiring-review reported separately — **done** (above and the JSON). The validator
  was not changed this pass, so no new reserved set is needed; one will be written if the validator
  changes.
- Honest burden — **stated**: this contract requires a human evidence review of every draft; it does
  not fix entailment or quote freshness.
- Item-1's authenticated dashboard check — **pending**, separate from item 2.

## Proof

- `tests/grounding_eval.py` (development), `tests/grounding_eval_fresh.py` (reserved),
  `tests/grounding_eval_runner.py` (harness). Reproduce with
  `python -m tests.grounding_eval_runner` and `python -m tests.grounding_eval_fresh`.
- `tests/test_review.py` — the review contract (fingerprint stability and sensitivity, every
  enforce block/pass, reviewer allow-list, the stores, the review view).
- `tests/test_draft_pipeline.py` — the gate at the create boundary: no-review / fail-closed default /
  rejected / stale / forged / malformed / unreadable, an offer edit between review and action, and
  the worker create route funnelling through the gated create.
- `tests/test_console_api.py` — the console review endpoints, reviewer attribution, the
  changed-candidate refusal, and that the routes are absent unless enabled.
- `tests/test_writer.py` — the two measured false accepts (product + subject variations) cannot be
  approved without a valid review, proven WITHOUT depending on the validator's verdict; the four
  strict-xfail cases are removed.
- **11 deliberate breaks of the gate and every guarantee, all caught** (disable the gate; enforce
  never blocks; accept a rejected / stale / non-human / malformed review; record without a reviewer;
  drop the body from the fingerprint; the sheet store stops refusing writes; the default store is no
  longer fail-closed; the console ignores a changed candidate).
- Whole suite: **761 Python passed (0 xfailed)**, React unchanged.

## What this does not establish (limits of the evidence itself)

- The human review is a control on *approval*, not a check of truth. It requires a person to judge
  every draft; it does not verify entailment, does not make the word-overlap validator faithful, and
  does not touch quote freshness.
- The three word-gate experiments are three specific designs at specific settings, measured once,
  read-only, against one handbook and its real drafts (the probe scripts were not committed). They
  show those designs are too blunt; they are **not** a proof that no word-based method could work.
- The "currently-passing" denominators (36 product, 21 company sentences) are drafts the validator
  passes today, not verified-faithful examples — so those figures are review-burden, not accuracy.
- The fresh set is 18 cases authored by the same person who wrote the fix; unseen while iterating,
  but not an independent or statistically powered benchmark.
- **Nothing here is deployed.** The review store's Sheet migration is documented but not applied, so
  nothing writes to the live Sheet; `outreach-worker`/`outreach-console` are not rebuilt; Gmail
  drafting stays disabled.
