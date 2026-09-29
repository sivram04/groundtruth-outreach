# Grounding check, item 2: an adversarial set, a baseline, a bounded fix, and what remains open

2026-09-29. `outreach/writer.py`'s grounding check screens what Gemini writes before it can ever
become a draft: every content word in a sentence must appear in the source it cites. The audit
(`docs/ARCHITECTURE_REVIEW_2026-09-29.md` §3.1) confirmed a specific hole — a sentence that
reverses its quote's meaning can still pass, because word overlap does not see negation. This
work follows the order an external review set: write the adversarial set before touching the
validator, run the unmodified code against it and record the baseline, implement a bounded fix,
measure again, and keep a held-out set the implementation was not tuned against.

## The method

`tests/grounding_eval.py` holds every case: the source (a quote or a handbook), the candidate
sentence, which part of the email it exercises, the expected verdict, and why. `TUNING_CASES`
were read while the checks below were written; `HELD_OUT_CASES` were set aside and looked at only
once, after the implementation was finished. Both lists were written in full before
`outreach/writer.py` was touched. `tests/grounding_eval_runner.py` runs a case through the real
`writer.verify()`, filling the three untested parts of the email with sentences already known to
pass, and reports not only accept/reject but, for a reject, whether the reason actually names the
part under test — a reject for the wrong reason is reported separately, not folded into a correct
one.

## The baseline (unmodified `writer.py`, before any change)

| | correct | false accept (unsupported, wrongly accepted) | false reject (supported, wrongly rejected) |
|---|---|---|---|
| Tuning (22 cases) | 15/22 | 7 | 0 |
| Held-out (13 cases) | 7/13 | 6 | 0 |

Zero false rejects on either set at baseline: the existing checks were conservative, not broken —
they just missed a specific, real family of claims. The seven tuning misses were exactly the
categories the audit named: an added negation, a wrong count, a wrong date, a dropped qualifier.
Running the baseline also **corrected the case-authoring itself**, before any code changed: two
"reversed subject" cases (`reversed-subject-customers`, `reversed-subject-your-team`) turned out
to already be rejected today — not because anything notices a reversed subject, but because an
unrelated word ("customers", "team") simply is not in the quote. Both were kept as easier control
cases and replaced as the primary tests with sentences built entirely from the quote's own
vocabulary, so a pass can only mean the subject was actually checked. `tests/grounding_eval.py`'s
own comments record this correction inline, case by case.

## What was built

Four checks, added to `outreach/writer.py` alongside the existing word-overlap grounding, applied
to the company sentence, every product and ask sentence, and the subject line alike:

1. **A negation the source does not carry.** "does not install" against a purely positive quote.
2. **An absolute scope word the source does not use.** "every state" against a quote naming one
   region.
3. **A qualifier the source states that the sentence drops.** "on a pilot basis" quietly
   generalised into a standing claim.
4. **A digit run with no match anywhere in the source.** A wrong count, a transposed year — never
   checked before, because `_words`' pattern never matches a digit.

Plus one narrow subject check: a company sentence that leads (once the company's own name is
removed) with an explicit alternative actor — "you", "your", "we", "customers" — rather than the
company itself.

**What this establishes**, precisely, per module: each of the four is a plain word-presence
comparison against the one quote (a company sentence) or the clauses of the handbook sharing the
most words with the sentence (a product, ask, or subject sentence) — not the source's meaning. A
negation restated from the matching clause, however worded, is credited and never flagged.

**What remains uncertain, named in the module docstring, not hidden:**

- A reversal that keeps the company's own name as the subject while changing who performs the
  verb ("Example Electric relies on subcontractors to install...") is not caught.
- A fabricated claim built entirely from words that already sit together in the one clause a
  sentence is checked against is not caught; localising narrows this from "anywhere in the whole
  handbook" to "the clauses that share a word with this sentence", nothing more.
- A subtle scope widening using no absolute word ("across the region" against a source naming one
  city) is not caught.

## Two real bugs the real handbook found — not the synthetic fixture

Once the checks passed the synthetic fixture cleanly, they were run **read-only** against all 25
real Drafts-tab rows and the founder's actual live handbook (never against the live Sheet
write-path; nothing was changed there). The first attempt **flagged 21 of 21** real drafts that
were previously WAITING — a severe false-positive regression, caught before anything was
committed:

1. **Localisation was a complete no-op on the real document.** The real handbook, exported from
   Drive, has no blank lines — it is one continuous block. The first version of localisation split
   on blank lines, so it always fell back to the *whole* 5,521-character document as the "local"
   window for every sentence, making the new checks no more targeted than plain grounding.
   Fixed by splitting on sentence punctuation and line breaks instead (the same split
   `_polarity_reversed`'s existing STATE-clause logic already trusted), then narrowed again after
   discovering that a bare mid-sentence line wrap — present in the real handbook *and* in this
   repo's own `examples/synthetic_handbook.txt` — is not a real boundary and was cutting a phrase
   like "planned for later" in half; a wrapped line is now joined back before splitting.
2. **The company's own name collided with a trigger word.** "All Phase Power & Lighting" tripped
   the scope check on the bare word "All" in its own name, before the name was stripped first —
   exactly the protection `names_specific_work` already has, which the new checks had not been
   given. Every new check now strips the company's own name before matching, and `SCOPE_EXPANSION`
   was narrowed to require a following noun ("all states", not bare "all") as a second, independent
   safeguard.
3. **A single common word pulled in an unrelated clause.** An early version of localisation kept
   *every* clause sharing even one word with the sentence; a sentence asking about "payroll dates"
   shared the word "use" with an entirely unrelated clause about never promising a result, which
   carried a negation of its own — that unrelated negation then wrongly excused a sentence that
   should have needed one of its own. Localisation now keeps only the clause(s) tied for the
   *highest* word overlap, using the same stemmed comparison `ungrounded()` already uses (a
   literal-string comparison had also been scoring "systems" and "system" as unrelated words).
4. **The qualifier-word list itself was too generic.** `specific`, `certain`, `particular`,
   `limited`, `some`, bare `select`/`selected`/`pilot`/`currently` are all common enough in
   ordinary prose ("sender-specific values", a genuinely unrelated compound) that they are unsafe
   single-word triggers. The list now holds only distinctive, largely unambiguous phrases: "on a
   pilot basis", "select clients/customers/markets", "a subset of", "early-access", "planned for
   later", "not yet available/supported", "for now", "at this time", "currently only".

After all four fixes, the same read-only check against the same 25 real drafts (21 with stored
sentences) found **0 newly rejected**.

## The result, after the fix

| | correct | false accept | false reject |
|---|---|---|---|
| Tuning (22 cases) | 22/22 | 0 | 0 |
| Held-out (13 cases) | 10/13 | 3 | 0 |
| Real drafts (21, read-only, live handbook) | — | 0 newly rejected | 0 (none were previously HELD) |

Zero false rejects throughout — the fix did not make the check more likely to block a legitimate
claim, on either the written set or the real production data. The three held-out misses are
exactly the three the case comments predicted, in advance, as architecturally out of scope for a
word-presence check:

- `held-reversed-subject-delegation-kept-under-name` — the company's own name stays the subject.
- `held-combination-cross-paragraph` and `held-combination-same-paragraph` — a fabricated claim
  built from words that genuinely co-occur in the source, one across two paragraphs (also
  independently caught by `BANNED` in this instance) and one within a single sentence, which no
  word-overlap check, localised or not, can tell from a true one.

None of the three misses were patched after being seen — doing so would tune the implementation to
the held-out set rather than measure it. `tests/test_writer.py`'s
`test_held_out_case_matches_its_expected_verdict_or_is_a_named_gap` pins all three as expected
misses, so a future change that silently narrows coverage further, or that accidentally fixes one
of them, is visible either way.

## Proof

- `tests/grounding_eval.py` — every case, with its evidence and reasoning, unchanged in intent
  since before the code was touched.
- `tests/grounding_eval_runner.py` — the harness; `.venv/Scripts/python.exe -m
  tests.grounding_eval_runner` reproduces the table above.
- `tests/test_writer.py` — 117 tests (was 54): every existing test unchanged and passing, all 22
  tuning and 13 held-out cases run as permanent regression tests, plus targeted unit tests for
  each new function and each of the two real bugs found.
- **19 deliberate breaks of the new code, all 19 caught by `tests/test_writer.py` alone** —
  disabling each of the four checks individually, on each of the three sentence kinds and the
  subject line; reverting the company-name stripping in each of the three new functions; reverting
  the qualifier-word narrowing and the scope-word narrowing (both reintroduce the exact real
  bugs above); disabling the mid-sentence line-wrap join; and widening or breaking the
  best-clause-only localisation. The first run of this left 6 alive — not defects, but tests that
  looked like they exercised a protection without actually requiring it (the company-name
  collision test no longer needed stripping once `SCOPE_EXPANSION` was narrowed, for one); each
  was replaced with a case that genuinely requires the protection, and the second run left 0 alive.
- Whole suite: 678 Python (was 615), 46 React, unaffected.

## What this does not establish

- **This is not entailment.** Every check here is a word-presence or clause-overlap comparison.
  None of it proves a sentence is *true*; the module's own opening line has said so since before
  this work and still does.
- **The 21 real drafts checked clean, not zero.** They are 21 drafts one founder's handbook and
  one batch of research quotes produced; they are evidence the fix does not obviously break real
  production data, not a measured false-reject rate on a representative sample.
- **The held-out set is small (13 cases) and authored by the same person who wrote the fix.** Its
  value is that it was not looked at while iterating, not that it is an independent or
  statistically powered benchmark.
- **Quote freshness is untouched**, as the reviewer's instruction asked. §3.3 of the audit still
  applies unchanged.
- **Nothing here is deployed.** `outreach/writer.py` runs inside both `outreach-worker` and
  `outreach-console`, and neither image has been rebuilt with this change.
