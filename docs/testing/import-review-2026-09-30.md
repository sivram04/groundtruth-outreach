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
