# Import acceptance review: 03a29c7

2026-09-30T17:26Z [TOOL] Codex verified three counterexamples against
`03a29c78262782ecf4fadf09268dddd332859f78`. This is a local acceptance review,
not a full suite rerun or live verification. Verdict: import milestone incomplete.

Environment: existing Python test image
`sha256:93b5d8a061ceab94bf1b10a3744c921615c734503d701f3fd711edc3789bf6e7`,
network disabled; current repository mounted read-only at `/repo`, bytecode disabled.
Only synthetic data and simulated Sheets API from `tests/test_sheet_append.py`.

1. **Changed destination loses data.** Through real Flask preview/commit routes with
   `store=lambda: Store(api=FakeSheets())`, preview Company=Redwood,
   Phone=614-555-0142 into A. Remove Phone from the simulated destination header and
   existing rows before commit. Submit the previewed rows and fingerprint unchanged.
   Expected: refuse stale destination, no append. Actual: HTTP 200,
   `written: 1`, `lead_ids: [A-0002]`; phone absent from appended values.
   The fingerprint binds rows/prefix, not destination schema; commit never compares
   current columns with the preview. `Store.append_leads` silently omits unknown fields.

2. **Concurrent applications reuse a Lead ID.** Create two Flask app instances over
   the same FakeSheets. In each real Store subclass, capture `super().leads()` then
   wait on a shared two-party threading.Barrier before returning that snapshot.
   Concurrently commit distinct synthetic companies/emails through the real routes.
   Expected: distinct IDs or refusal of one competing write. Actual: both HTTP 200,
   both `written: 1`, both `lead_ids: [A-0002]`; two appended rows carry A-0002.
   The per-app lock cannot serialize separate applications/processes.

3. **Invalid contact values vanish without validation feedback.** Call
   `import_leads([{'Company':'Synthetic','Email':'wrong-address','Phone':'123'}], {},
   destination_columns=CANONICAL)`. Expected: preserve supplied values in explicit
   validation feedback. Actual: accepted row is only `{'Company':'Synthetic'}`,
   with `unstorable: []` and `skipped: []`.

All three probes completed normally and printed the actual results above. No host
product code or live data was changed. Claude's reported 868/68 full-suite results
were not independently rerun. Browser visual quality and live persistence remain
outside this evidence. Remediation should target these import acceptance failures
before declaring M2 complete or moving on to call tasks.

## Remediation (2026-09-30, after 03a29c7)

All three are fixed, each with a regression that encodes the reviewer's counterexample.

1. **Changed destination.** `importer.fingerprint` now hashes the destination **columns**
   as well as the rows and prefix, and the commit route recomputes it against the tab's
   **current** columns (`import_commit`), so removing Phone after a preview yields a
   fingerprint mismatch → **409**, no append. Defence in depth: `Store.append_leads` now
   **refuses** (`sheet.DestinationMismatch`) a field the tab has no column for instead of
   dropping it. Tests: `test_importer.test_the_fingerprint_binds_the_rows_and_the_destination_schema`,
   `test_console_import.test_a_destination_that_changed_after_the_preview_is_refused`,
   `test_sheet_append.test_append_leads_refuses_field_loss_rather_than_dropping`. The old
   test that expected silent dropping was replaced.

2. **Concurrent Lead ID collisions.** Lead IDs are no longer computed from a pre-read
   `max(existing)+1`. `Store.append_leads` appends with a blank Lead ID, reads the exact
   rows the **atomic** append wrote (`updatedRange`), and derives each ID from its own sheet
   row (`prefix-(row - HEADER_ROW)`). Two instances appending at once are serialized by the
   Sheets append and land on different rows, so they get different IDs. Regression through
   two independent Flask apps over one shared simulated Sheet, synchronised on a
   `threading.Barrier` at `leads()`:
   `test_console_import.test_concurrent_imports_from_two_apps_get_distinct_ids` (distinct
   companies → distinct ids) and `test_concurrent_duplicate_submissions_do_not_collide_on_an_id`.
   `test_sheet_append.test_the_id_is_the_row_not_the_existing_maximum` pins that the id is the
   row, not the max.

3. **Invalid contact values.** `importer` now records each supplied-but-unusable contact
   value with a reason (`_invalid_contacts`); `import_leads` carries `invalid` on every
   accepted row and on skipped rows, and the summary counts them. A company-only lead is still
   accepted, with the bad email/phone shown, never stored. Tests:
   `test_importer.test_invalid_contact_values_are_preserved_in_the_feedback_not_discarded`,
   `test_importer.test_invalid_values_on_a_row_with_nothing_to_key_on_are_still_reported`,
   `test_console_import.test_invalid_contact_values_show_in_the_preview`, and the Import page
   test renders the "cannot use" feedback.

Verified in containers (`--network none`): Python **875 passed**, frontend **68 passed**,
typecheck and build clean. Browser-verified through the actual local API
(`tools/local_import_console.py`): the invalid-values preview and the stale-destination 409
(restarting the harness with the Phone column removed → "This preview is out of date … Preview
again", preview cleared, nothing written).

**Remaining limits (honest).** Row-based IDs prevent *ID* collision across instances; cross-
instance **dedupe** is still best-effort (two processes committing the same lead at the exact
same moment can create two rows with **distinct** ids — a known append-only-Sheets limit, not an
ID collision). The row-derived id can, in principle, equal a pre-existing **sparse** legacy id
(e.g. a legacy `A-0500` when row 502 is reached); the field-loss refusal and a fresh read guard
against loss but not this rare legacy clash. All verification remains synthetic/simulated: **no
live Sheet write** has been performed, and `enable_import` is off in deployment.

## Independent follow-up on e1f8eb2 (2026-09-30)

Codex ran the current checkout read-only in the Python test container, network disabled,
with synthetic fixtures. `pytest -q -p no:cacheprovider tests/test_importer.py
tests/test_console_import.py tests/test_sheet_append.py`: **35 passed in 13.36s**.
This confirms the targeted regression tests, not the reported full suite or browser run.

Three additional allocator probes drove the real `Store.append_leads` with the existing
simulated Sheets API. They show that the new two-operation allocator is not reliable:

1. **Existing-ID collision:** change the fixture's existing row ID from A-0001 to
   A-0002 (one gap); append a distinct lead. Returned ID A-0002; both rows now have
   A-0002. This does not require a large or unusually sparse dataset.
2. **Partial write and retry:** allow append to commit, then raise from the ID
   `batchUpdate`. Two physical leads exist but `Store.leads()` shows only A-0001.
   Restore the ID write, run `prepare_commit` against those visible leads and retry.
   The retry returns A-0003; the new contact now has two physical copies, one with
   no ID. Reading visible leads cannot reconcile the original partial write.
3. **Sort between operations:** swap the appended row and the existing fixture row
   immediately before ID `batchUpdate`. The adapter returns A-0002, but assigns it
   to Example Electric (formerly A-0001); the newly imported lead remains without
   an ID. This violates preservation of existing IDs and uses a stale row position.

Verdict: destination binding and invalid-contact feedback have passing targeted
regressions; ID allocation and retry safety remain incomplete. The concurrent duplicate
test also explicitly permits two rows for the same submission, so it does not establish
duplicate prevention. No live operations or product-code changes in this follow-up.

## Remediation of the allocator follow-up (2026-09-30)

The append-with-blank-id → write-id-by-row-position allocator is **removed**. Replaced with:

- **A stable, immutable Lead ID assigned before the write, in the row.** `importer.stable_lead_id`
  derives `{prefix}-{12 hex}` from the lead's identifying content (email, else phone, else
  company+website). The preview assigns it and puts it in the row; `Store.append_leads` writes the
  row - id and all - in a **single append**. Consumer survey done first (all read the prefix before
  the first `-` or fall back safely for a non-numeric suffix; `job_check` numbers only numeric ids),
  and the hex namespace is disjoint from the legacy `{prefix}-NNNN`, so:
  - **(1) no collision with an existing id** - the appended id is hex, never a legacy number, even the
    "one-gap" A-0002 case (`test_console_import.test_a_new_id_never_collides_with_an_existing_numeric_id`,
    `test_importer.test_the_stable_id_is_deterministic_and_cannot_collide_with_a_legacy_numeric_id`);
  - **(3) no second, position-based write**, so a sort between operations cannot move an id
    (`test_sheet_append.test_a_sort_cannot_move_an_id_because_there_is_no_second_write`); existing ids
    and founder data are untouched (`test_append_leads_leaves_existing_rows_and_ids_untouched`).
- **Retry safety by identity.** `prepare_commit` skips a row whose id (or content) is already present;
  the commit reconciles an uncertain append by **re-reading and checking which ids landed**, never
  assuming a failed response means no write. **(2)** a partial write is reconciled and a retry adds no
  second copy (`test_console_import.test_an_append_whose_response_is_lost_is_reconciled_not_double_written`);
  a genuinely failed write says so and is safe to retry
  (`test_a_failed_append_that_wrote_nothing_says_so_and_is_safe_to_retry`);
  re-confirming the same import adds nothing (`test_retrying_the_same_confirmed_import_adds_nothing`).
- **Cross-instance duplicate prevention via a claim ledger.** `Store.claim_leads` appends each intended
  lead id (with the commit's idempotency key) to an append-only `Import claims` tab, reads it back, and
  the **earliest claim per lead wins**; only the winner writes it. Two independent applications
  submitting the same list (distinct keys, a shared simulated Sheet, synchronised on a barrier) write
  **each lead exactly once** - not two rows
  (`test_console_import.test_two_independent_applications_importing_the_same_list_write_each_lead_once`,
  `test_sheet_append.test_claim_leads_earliest_claim_wins`). A commit with no idempotency key is refused.

Verified in containers (`--network none`): Python **877 passed**, frontend **68 passed**, typecheck and
build clean. Browser sanity-checked through the actual local API (preview shows the stable id →
"Imported 2 leads (A-…, A-…)" → reload shows them with the existing A-0001 preserved).

**Remaining bounded limitations (documented, not worked around).** Google Sheets has no atomic unique
constraint, so a few narrow cases persist:
- **Claim by content, not the whole import.** The ledger prevents two rows for the SAME lead across
  instances. Two *different* imports that happen to share a lead are each prevented per-lead by the same
  ledger; but a lead's content-hash id is shared, so if two instances win different leads of an
  overlapping set the non-overlapping leads are added by each - correct. No duplicate of any single
  lead arises.
- **Winner failure without retry.** If the instance that wins a claim then fails to write and never
  retries, that lead is not written until it is re-imported (the claim is not a durable reservation).
  Bounded solution if needed: a claim TTL and a sweep that re-opens claims older than the TTL whose lead
  is absent. Not built; import is off in deployment and, in practice, the console is a single service.
- **No live verification.** All of the above is proven against synthetic data and the simulated Sheets
  API; **no live Sheet write** has been performed, and `enable_import` is off in deploy.

## Independent retry/claim review of b49226c

2026-09-30T21:35Z [TOOL] Codex ran the current source read-only with network disabled
in test image `sha256:2157221df8accddedd740aa0cee79e57f6a7fe2b089027020ba86c03fbed038c`.
The importer, console-import and sheet-append test files passed: **37 passed in 3.90s**.
No full-suite or browser rerun. Single-append identities remove the old blank-ID and
second-position-write defects. The stronger retry/claim guarantees remain incomplete:

1. **Same-key overlapping retry:** two independent Flask apps share FakeSheets; their
   real Store subclasses wait at a barrier after reading existing leads. Both submit
   the same rows/fingerprint AND the same idempotency key. Both HTTP 200 responses
   report written=1, same Lead ID; the simulated Sheet contains **two physical copies**.
   The existing test uses distinct keys and therefore misses this case. A shared
   operation key currently authorizes both concurrent execution attempts.
2. **Lost response plus unreadable reconciliation:** real Store.append_leads writes
   the row; an injected exception loses its response, and the subsequent store read
   is made unavailable. HTTP 502 says **Nothing was written; confirming again is safe**,
   but the simulated Sheet contains **one copy**. The handler turns a failed read into
   an empty dict and cannot distinguish absence from unknown outcome.
3. **Abandoned claim cannot be recovered by re-import:** an initial request wins the
   claim but fails before appending. A subsequent healthy app submits the same lead
   with a new preview key. HTTP 200 returns written=0, claimed_elsewhere=1 and zero
   physical copies. Earliest claim persists; re-import does not reclaim it. Frontend
   source inspection shows claimed_elsewhere is not displayed in the result.

These probes used the real Flask routes and Store adapter, simulated Sheets, stub
authentication and synthetic contacts only. They supersede the claims above that
the ledger prevents every concurrent duplicate and that re-import recovers a failed
claim owner. A timeout alone would not prove an old writer stopped; any recovery design
must address late completion before allowing another writer. No live operations or
product-code changes were made during this review.

## Remediation of the retry/claim review (2026-09-30)

The coordination model now separates the **operation** from each **attempt**, preserves an explicit
**unknown** outcome, and provides durable **resume** with honest states.

- **Operation vs attempt (failure 1).** The claims ledger records `[Lead ID, Op key, Attempt, Claimed
  at]`. `Op key` is the durable idempotency key of the logical import; `Attempt` is a fresh token the
  server mints per request. `Store.claim_leads(lead_ids, op_key, attempt)` returns, per lead, `won`
  (this attempt is the earliest claim), `mine_prior` (an earlier attempt of the SAME op is earliest),
  or `other` (a different op is earliest). A request writes only `won` leads, so two attempts sharing
  one op key resolve to a single writer - the other gets `mine_prior` and does not write. Regressions:
  `test_console_import.test_same_key_concurrent_attempts_write_each_lead_once` (two apps, one shared
  Sheet, SAME key -> one physical copy per lead), `test_sheet_append.test_two_attempts_of_the_same_
  operation_resolve_to_a_single_writer`.
- **Unknown is not "nothing written" (failure 2).** On an append exception the handler re-reads to
  reconcile; only a **successful** read showing absence is reported as "nothing written (safe to
  retry)". If the reconciliation read itself fails, the outcome is an explicit `uncertain` (HTTP 200,
  `outcome: "uncertain"`, `written: null`) that says it may or may not have saved and to reload -
  never "nothing written". Regression:
  `test_console_import.test_a_lost_response_with_an_unreadable_reconciliation_is_uncertain_not_nothing`
  (the write landed; one physical copy; outcome uncertain).
- **Durable resume + honest states + bounded late completion (failure 3).** The commit returns
  `outcome`: `done` / `pending` (an earlier attempt of THIS op owns leads and has not finished) /
  `blocked` (another op owns them) / `uncertain`. The client keeps the op key per preview fingerprint
  in `localStorage`, so a reload resumes the SAME operation. A resume (`resume: true`, same op key)
  deliberately takes over its own operation's `mine_prior` leads. `append_leads` **rechecks presence
  from a fresh read immediately before writing and skips ids already present**, so a late-completing
  earlier attempt of the same op adds no second copy. Regressions:
  `test_an_abandoned_claim_is_recovered_by_a_same_key_resume`,
  `test_a_late_completion_after_a_resume_adds_no_duplicate`, and the frontend exercises `done`,
  `pending`, `blocked` and `uncertain` with the resume/check actions
  (`console/src/pages/Import.test.tsx`). The UI now shows `claimed_elsewhere`/pending/uncertain and
  never presents them as a completed import.

Verified in containers (`--network none`): Python **882 passed**, frontend **70 passed**, typecheck and
build clean. Browser sanity-checked through the actual local API (happy path: preview -> "Imported 1
lead").

**Precise coordination constraint (bounded, documented).** Google Sheets has no atomic
compare-and-swap or unique constraint, so **exactly-once is not claimed**. What holds:
- **Single writer per concurrent round.** Among claims present when a commit reads the ledger, the
  earliest attempt wins, so simultaneous attempts (same or different op key) do not both write.
- **Bounded late completion.** The pre-append presence recheck means a straggler that appends after a
  resume/another writer skips the already-present id. The only unbounded-in-theory window is two writers
  whose *fresh reads and appends fully interleave in the microseconds between recheck and append*; this
  is not reachable through the console (its per-process lock serializes its own requests, and import is
  off in deployment / single service). It is documented rather than claimed away.
- **Abandoned pre-write claim.** Recovered by resuming the SAME operation (the durable op key). A
  *different-key* re-import is deliberately told `blocked` (not silently duplicated, not falsely
  "done"); the operator resumes the original operation to finish it. We do **not** use a TTL to let a
  different writer take over, because expiry does not prove the original stopped.
- **No live verification.** All of the above is against synthetic data and the simulated Sheets API;
  **no live Sheet write** has been performed, and `enable_import` is off in deploy.

### Local import milestone — acceptance

The local acceptance criteria (destination binding; invalid-contact feedback; single-append immutable
identity with no existing-id collision, no invisible row, no sort overwrite; same-key and distinct-key
concurrency writing each lead once; unknown-not-nothing reconciliation; durable resume/recovery with
honest states) **pass in containers**. **Live verification remains separate and NOT done**: a real
Google Sheet write, a real signed-in browser, and behaviour under real Google API latency/errors are
unverified, and `enable_import` stays off in deployment.

## Independent overlapping-resume review of ce9cc4b

2026-09-30T22:05Z [TOOL] Codex ran the importer, console-import and sheet-append
tests against the current source in a network-disabled Python container, repository
mounted read-only: **42 passed in 2.15s**. No full-suite or browser rerun.

One deterministic real-route/real-adapter probe contradicts the local acceptance
and unreachable-race claims above. Use two independent Flask application instances,
one shared FakeSheets, and the same operation key. Pause the first request inside
the simulated lead append, AFTER `Store.append_leads` has completed its fresh read.
Send `resume=true` through the second instance. Pause that lead append too, then
release both with a two-party barrier. Claims appends are not paused.

Actual result: **both HTTP 200, outcome=done, written=1, same Lead ID; two physical
copies**. Synthetic lead: Synthetic slow, slow@example.test. The test injects a slow
in-flight write; no microsecond timing is required. No live storage or credentials.

Cause: resume unconditionally makes `mine_prior` writable, despite the previous
attempt still being active. Both presence checks can observe absence before either
append commits. A per-app/process lock cannot serialize these independent instances.
The existing late-completion test performs resume and the old writer sequentially
using MemoryStore; it does not exercise this overlap.

The explicit unreadable-reconciliation result has a passing targeted regression.
The remaining local blocker is exclusive write ownership during recovery. Disabling
import in deployment prevents live exposure; it does not satisfy the local concurrency
acceptance criterion. Any new decision to restrict the supported execution model or
leave automatic recovery blocked should be documented explicitly. No product-code
changes or live operations were made during this review.

## Remediation of the overlapping-resume review (2026-09-30)

**Write-taking Resume is removed.** This supersedes the "durable resume takes over its own
operation's `mine_prior` leads" behaviour above, which caused the overlap: an original owner and a
resume could both pass their presence check before either committed its append, and both wrote.

**Exact ownership guarantee now:** for any lead, **only the request whose claim is the earliest in the
append-only ledger (`won`) ever appends it.** Every other request - a concurrent attempt of the same
operation, a resume, or a different operation - is `mine_prior` or `other` and does **read-only
reconciliation only**; it never appends a lead it does not own. Because the ledger is append-only with a
total order and each request reads it *after* appending its own claim, exactly one request is `won` per
lead. So two requests can never both append the same lead - no pause, delay or overlap changes this
(`commit` sets `writable = won`; `mine_prior` is reported `pending`, never written).

Reproduced and fixed (`tests/test_console_import.py`):
- `test_overlapping_original_and_resume_write_the_lead_once`: the original's lead append is paused
  **after its presence recheck** (a one-shot pause in the simulated Sheet, outside its lock); a resume
  of the same operation runs through an independent app to completion while the original is in flight;
  the original is released. **One physical row.** The resume wrote nothing (`outcome: "pending"`). This
  fails on `ce9cc4b` (two rows) and passes now.
- `test_simultaneous_resumes_of_an_abandoned_claim_write_nothing`: two resumes of an operation whose
  owner claimed then died - neither writes; **no duplicate** (and the lead is not recovered).
- Kept: same-key and distinct-key concurrency each write a lead once; the unknown-not-nothing
  reconciliation; destination binding; invalid-contact feedback; single-append identity.

The frontend shows the outcomes through the real parser/component: `done` / `pending` (with an honest
"cannot be completed automatically yet" note and a read-only **Check again**) / `blocked` / `uncertain`
(`console/src/pages/Import.test.tsx`). Verified in containers: Python **883 passed**, frontend **70
passed**, typecheck and build clean.

**Remaining recovery requirement (unmet, stated plainly).** Automatic recovery of a lead whose owning
request **failed before writing** (an abandoned pre-write claim) is **not available**. A resume reports
it `pending` and does not write it; a different-key re-import is told `blocked`. Safe automatic takeover
needs exclusive-ownership coordination stronger than append-only Google Sheets provides (a lease with
fencing, or compare-and-swap). Adding that is a **separate storage/architecture decision**, not made
here. Until then, such a lead stays pending and must be completed by the original operation finishing,
or recovered by a deliberate future mechanism.

### Local import milestone — corrected record

- **Duplicate prevention / concurrency (incl. overlapping original vs resume): PASSES** locally in
  containers, by the ownership guarantee above.
- **Automatic recovery of an abandoned pre-write claim: NOT AVAILABLE** (documented requirement above);
  local recovery is therefore **incomplete** for that case, by an explicit design decision to prefer no
  duplicate over an unsafe takeover.
- **Disabling import in deployment prevents live exposure; it does NOT prove concurrency safety** - the
  concurrency evidence is the container tests over the simulated Sheets API, not the live service.
- **Live verification remains a separate milestone**: a real Google Sheet write, a signed-in browser,
  and behaviour under real Google API latency/errors are unverified; `enable_import` stays off in deploy.
