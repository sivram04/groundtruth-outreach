# Outreach continuity

## [PLANS]

- 2026-09-23T02:57Z [USER] Supersedes the local-handbook assumption below:
  before stage 3 begins, the founder will put the final outreach handbook in
  Google Drive. The private drafting worker will run in GCP and read it there.
  The handbook is not in Drive yet; no link or new sign-in is due now. Current
  local template code remains a disabled prototype, not the planned writer.

- 2026-09-22T20:24:00-04:00 [ASSUMPTION] Stage 3 proceeds locally: review four real
  company-profile previews after the founder fills the handbook, then a
  controlled Gmail-draft pilot. Stage 4 sent/reply sync and follow-ups are
  separate; bulk research and all schedules remain paused.

## [DECISIONS]

- 2026-09-28 [USER] Stage 4 decisions: threads the founder started by hand (the 14 of
  2026-09-22) get reminders in Next action, never follow-up drafts; business days skip weekends
  and the major US holidays (New Year's, Memorial Day, July 4, Labor Day, Thanksgiving and the
  day after, Christmas); follow-up wording is approved once per handbook version
  (`followup_approved_handbook_hash` = the Drive document's content hash).

- 2026-09-23T02:19Z [USER] Supersedes the generic "accounting and operational
  data" outreach phrasing below: name the actual inputs in prospective copy.
  The founder has not approved a replacement offer. [CODE] The product's
  founder-decided checklist in `docs/construction/CASH_FLOW_INPUTS_AND_DATA_SOURCES.md`
  names bank balances, open invoices and bills, payroll by pay date, fixed
  costs, upcoming billings by job, plus commitments, retainage and credit-line
  details when applicable. Use a concise, accurate subset in a cold email;
  do not imply current live integrations or a completed MVP.

- 2026-09-23T01:37Z [USER] Corrected the outreach positioning: Lakshyaa is an
  AI-powered cash-flow decision product for construction subcontractors. It is
  intended to combine accounting and operational data, analyze the company's
  situation, compare scenarios, and recommend next steps from that analysis.
  The prior "see cash needs" offer wording was rejected. Replacement wording
  is not yet founder-approved; do not present planned capabilities as live.

- 2026-09-22T20:24:00-04:00 [USER] The MVP is unfinished this week; outreach may
  invite next-week conversations but must not promise a live trial today.
- 2026-09-22T20:24:00-04:00 [USER] Asked Claude Code to build the missing automated
  drafting pipeline. [TOOL] Its local OAuth session was expired and could not
  refresh, so Codex continued the authorized local build.

## [PROGRESS]

- 2026-09-28 [CODE] Stage 4 built locally: `outreach/sync.py` (Gmail read-only -> Events,
  Suppression, lead summary columns), `outreach/followup.py` (the handbook's own follow-up
  wording, drafted in the original thread), `mailbox.py`, `sequence.py`, `business_days.py`.
  390 tests pass offline in the container; 62/62 deliberate breaks caught. Not deployed, not
  scheduled, never run against the live mailbox or Sheet. Next: a read-only `sync --dry-run`
  on the real mailbox, with the founder's go.

- 2026-09-23T03:39Z [CODE] Stage 3 local audit closed the fixed-template Gmail-draft
  bypass: the live preview endpoint always uses the Drive writer, and `create` requires a
  written payload that is revalidated against the handbook. Added conservative polarity
  checks for quote negation and qualified product state. No deployment or remote write.

- 2026-09-22T20:48:00-04:00 [CODE] Local Stage 3 previews now list every current
  verified OFFERING/MARKET quote, allow an explicit quote ID bound to the
  approval hash, avoid weak automatic defaults, and use `Decision maker` for a
  first-name greeting only when `Their email` equals `BEST EMAIL` and is not a
  role inbox. No live write or deployment.

- 2026-09-22T20:24:00-04:00 [CODE] Local Stage 3 code now renders evidence-backed
  initial-email previews, requires exact date-bound hash approval, and has a
  disabled-by-default Gmail draft creation path with Sheets reservation and
  conservative reconciliation. No deployment or live Google write occurred.

## [DISCOVERIES]

- 2026-10-01 [FIX] Dashboard call-queue acceptance gaps (review in docs/testing/calls-review-2026-09-30.md).
  (1) The queue now HONOURS SUPPRESSION: console_model.build skips a lead whose view["suppressed"] is truthy
  (opted out) - call_state only knew call-recorded DNC, not the separate Suppression list - and when
  entries is None (suppression unreadable) empties the queue + sets snapshot `suppression_unreadable`; the
  Dashboard passes unreadable = calls_unreadable || suppression_unreadable to CallQueue, which shows the
  unavailable state ("call log or suppression list could not be read", never "no calls due"). The opted-out
  lead keeps its call history on the lead page. (2) Stale-action recovery: QueueItem's refusal keeps the
  server message AND shows a "Reload the queue" button that calls onChanged; after the dashboard re-reads
  and passes the newer task, the next action targets the refreshed task_id (tested STALE→FRESH via rerender).
  (3) Upcoming items now include contact + note (were company/phone/due/reason only). Python 933 (+2 route
  tests: opt-out excluded while a non-suppressed stays; unreadable suppression → flag+empty), frontend 86
  (+3: Cancel/Snooze bound to id, stale→Reload→refreshed id, upcoming contact+note) + tsc/build; regenerated
  demo snapshot.json (new key suppression_unreadable - the equality test needs the --write regen, RW mount).
  Browser (harness, fixed real clock): overdue past-callback → Snooze to 2026-12-01 via the UI (form_input
  on the datetime-local by ref; clicks need a retry when the pane is hidden) → moved out of overdue → reload
  shows "1 upcoming" (persisted). Browser evidence vs controlled-clock route tests kept distinct. Synthetic
  only; enable_calls off in deploy; committed locally, not pushed.

- 2026-09-30 [BUILD] Dashboard call queue (flag-gated enable_calls). console_model.build gives each open
  task a `when` bucket (OVERDUE/TODAY/UPCOMING, from the NY date, same clock as overdue), carries the task
  `id`, and the snapshot adds `calls_due_today` + `calls_unreadable`. New CallQueue component
  (console/src/pages/CallQueue.tsx) on the Dashboard: overdue first, then due today, upcoming in a separate
  <details>; each item = company (link to lead), contact, phone, due date/time, reason/note; reuses
  actOnCallTask (task_id required) for Complete/Snooze/Cancel; a stale 409 shows the server message +
  refreshes; unreadable Call log → an UNAVAILABLE state, never "no calls due". App passes onChanged=refresh
  to Dashboard. Phone-only + email+phone both appear; complete/cancel remove, snooze moves, survive reload.
  Containers: Python 931 (+3 route tests: buckets on a controlled clock, upcoming separate, unreadable →
  calls_unreadable+empty), frontend 83 (+5 CallQueue.test.tsx) + tsc/build; regenerated demo snapshot.json
  (console_fixture.py --write in a RW-mounted container — the equality test test_the_react_apps_demo_data_is_this_fixture
  would otherwise fail on the new keys). Browser (harness, fixed real clock): no-answer + past-callback → 1
  overdue + 1 upcoming with phone/reason → Complete removes it + auto-refresh → reload confirms gone. Clock-
  advance overdue transition is covered by controlled-clock route tests (harness can't advance its clock).
  Synthetic only; enable_calls off in deploy; committed locally, not pushed.

- 2026-09-30 [FIX] Call-history contract aligned: job_draft._call_effect now matches sheet.Store.call_events
  for all three cases — absent tab = no calls (CONTINUE); valid header + no events = no calls; present tab
  WITHOUT the required header (incl. an empty headerless tab) = unreadable → block (fail closed). Removed
  _call_effect's `if not values: return CONTINUE` early return so the header check governs. Regressions:
  test_sheet_append.py::test_call_events_contract_absent_valid_header_and_missing_header (Store, 3 cases) +
  test_draft_pipeline.py (valid-header-no-events still CREATED; present headerless tab → DraftBlocked, no
  Gmail create). Python 928. NEXT MILESTONE NOT STARTED (usage limit): dashboard call queue — overdue-first/
  due-today/upcoming buckets, reuse task identity + Complete/Snooze/Cancel, unavailable state when call
  history unreadable. build already emits call_tasks (overdue-first) + calls_overdue; needs a `when` bucket
  per task, a `calls_unreadable` flag from the snapshot, a dashboard component, and a browser journey.

- 2026-09-30 [FIX] Call-task recheck (docs/testing/calls-review-2026-09-30.md "Independent recheck" of
  829c309): three enforcement-boundary gaps closed, earlier fixes preserved. (1) STOP/HOLD now enforced at
  job_draft.create (the REAL initial Gmail-draft boundary the worker create route calls; drafts.plan is only
  candidate selection, so a candidate approved BEFORE a call decision bypassed it). New job_draft._call_effect(api,
  lead_id) re-reads the Call log at the boundary with the SAME header contract as sheet.Store.call_events (titles →
  missing tab = CONTINUE so calls-less companies still draft; present+bad-header or read error = DraftBlocked, fail
  closed); create refuses STOP/HOLD/unreadable before any reservation or Gmail write; signing + all gates unchanged.
  (2) task action requires a nonempty task_id — removed the `client_task_id or task["id"]` fallback; route 400 on
  missing/blank, 409 on stale; typed actOnCallTask makes task_id required; CallPanel doAction guards `!task`. (3)
  CallPanel now READS the outcome result: on suppression_written===false (or warning) it shows what saved + what
  remains, KEEPS the submission id + form, and offers "Retry the rest" (re-sends the same submission id → no 2nd
  call). Containers no-net: Python 925 (+5: create blocked by DNC-no-suppression / CALLBACK-HOLD / unreadable, each
  asserting no Gmail create; eligible no-call-history still CREATED; task action missing/blank/stale refused, newer
  task untouched), frontend 78 (+2: partial-warning renders + Retry reuses id; real recordCallOutcome parser
  round-trips the partial shape) + tsc/build. Browser (real API): task action no/blank task_id → 400, task stays
  scheduled, correct id completes. Gap-1 has no UI (Gmail drafting off) and gap-3's warning needs a suppression
  failure the harness store can't inject → covered by component-render + parser + server-route tests, not a browser
  run. Test wiring: ready fixture (test_draft_pipeline) now patches job_draft._call_effect→CONTINUE by default (else
  api=object() crashes); gap-1 tests restore _REAL_CALL_EFFECT (captured before ready patches) + a
  test_sheet_append.FakeSheets seeded with a Call log tab (header row 1, no title row). Synthetic only; live NOT done;
  enable_calls off in deploy; committed locally, not pushed.

- 2026-09-30 [FIX] Call-task correctness, the four findings in docs/testing/calls-review-2026-09-30.md
  (against 52bebbd), all fixed + regressed through the REAL routes and the pure state machine (not mocks
  alone). (1) STOP/HOLD now enforced in eligibility: `calls.outreach_effect`/`blocks_outreach` (no clock);
  `drafts.first_draft_blockers` + `followup.due_now` take call events and skip STOP/HOLD leads (offline HOLD
  enforcement now exists); unreadable call log fails closed in drafts.plan / followup.pending_reviews+run /
  console_model.snapshot+build; the outcome route reports `suppression_written:false` + `warning` and the
  STOP is still enforced via the recorded call event. (2) do-not-contact is STICKY (call_state
  `do_not_contact` flag): a later no-answer never reopens a task or lifts STOP; history still logged;
  not-interested stays distinct. (3) task action bound to the exact task: new "Task ID" column
  (sheet.CALLS_HEADER, calls.action_event) persists the target, call_state applies an action only to the
  named task (stale/interleaved can't close a newer one); call_task_view exposes `id`; CallPanel sends
  task_id; route 409 on mismatch without touching the newer task. (4) retry-stable UI submission: CallPanel
  keeps one submission_id across retries (cleared on success/edit), calls.outcome_event uses it as the Event
  ID (UI omits called_at), so a retry after a lost response makes no duplicate; a fixed-called_at
  programmatic caller keeps content-hash idempotency. Containers: Python 920 (+14), frontend 76 (+2),
  tsc+build clean. Browser (tools/local_import_console.py:8139, real built pages): phone-only DNC then
  no-answer stays "No call scheduled" + STOP + first-draft blocker; stale task_id -> 409, newer task stays
  scheduled; two UI-shaped submits 1s apart -> one history row. Synthetic only; live NOT done; enable_calls
  off in deploy. Gotcha: local host python lacks googleapiclient/flask -> run pytest AND the harness inside
  the outreach-tests image (repo mounted ro); build console/dist via outreach-console-tests with src mounted
  ro + dist mounted rw; the harness needs a network for -p (never --network none), it never calls Google.

- 2026-09-30 [BUILD] First call-task workflow (local, flag-gated `enable_calls`, off by default+deploy).
  `outreach/calls.py` (pure): outcomes (no answer/interested/not interested/callback/wrong number/do not
  contact) + actions (complete/snooze/cancel) as an append-only event log; `call_state` replays to the
  current task + history + email effect. No-answer schedules by `call_no_answer_business_days` (default 3,
  NY dates); callback uses the explicit time; a note is never parsed. Event ID => repeated submission is a
  no-op. `sheet.py` Call log tab (`call_events`/`append_call_events`, idempotent); do-not-contact/not-
  interested also write Suppression (STOP the offline scheduler honours). `console.py` POST
  /api/calls/<lead>/outcome and /task; `console_model` adds per-lead call_task/history/effect + top-level
  call_tasks/calls_overdue. Frontend CallPanel on the lead page (log a call; due/overdue + complete/snooze/
  cancel; effect note; history); api recordCallOutcome/actOnCallTask; datetime-local sent as real instants.
  Containers: Python 906, frontend 74, tsc+build. Browser: log No answer -> task due Mon 2026-10-05 ->
  survives reload -> Complete clears it. Email effect: STOP via suppression (enforced), HOLD persisted+shown
  (offline enforcement a next step). REMAINING in call milestone: post-call email candidate, chat logging,
  offline HOLD enforcement, dashboard overdue list. Live verification separate + NOT done (enable_calls off).
  Ordering gotcha fixed: call_state stable-sorts by Recorded-at only (append order), so an action never
  sorts before its outcome. Regenerate demo snapshot.json + rebuild the test image before the demo test.

- 2026-09-30 [FIX] Import overlapping original-vs-resume duplicate (the review below). Removed
  write-taking Resume: `commit` now sets `writable = won`, so ONLY the request holding the earliest
  ledger claim ever writes a lead; a resume/any other request does read-only reconciliation and reports
  `mine_prior` as `pending`, never writing it. Ownership guarantee: append-only ledger + read-after-own-
  append => exactly one `won` per lead => two requests can never both append it (no pause/overlap breaks
  it). Repro-then-fixed: `test_overlapping_original_and_resume_write_the_lead_once` (pause original's lead
  append after its recheck via a one-shot FakeSheets pause outside the lock; run a same-op resume through
  a second app; release; ONE row). Plus `test_simultaneous_resumes_of_an_abandoned_claim_write_nothing`.
  Frontend shows done/pending("cannot be completed automatically yet" + read-only Check again)/blocked/
  uncertain. Containers: Python 883, frontend 70, tsc+build. REMAINING (documented, unmet): automatic
  recovery of a lead whose owner failed BEFORE writing is not available (resume => pending; different key
  => blocked); safe takeover needs a fenced lease/CAS (separate architecture decision, not made). Milestone
  record corrected: concurrency/dup-prevention PASSES locally; abandoned-pre-write-claim recovery INCOMPLETE
  by design; deploy-off != concurrency-safe; live verification a separate milestone (enable_import off).

- 2026-09-30T22:05Z [TOOL] ce9cc4b targeted importer/routes/adapter tests: 42 passed.
  Deterministic two-app probe pauses original append after its fresh read, starts same-op
  resume, then releases both: both done/written=1, two physical copies of one ID.
  Resume makes mine_prior writable without stopping the old attempt; sequential late
  completion test misses overlap. Supersedes local acceptance/unreachable-race claims
  below. Evidence appended to docs/testing/import-review-2026-09-30.md. No product edits/live writes.

- 2026-09-30 [FIX] Import coordination/recovery (the review below). Claims ledger now carries
  Op key + Attempt; `claim_leads` classifies won/mine_prior/other and a request writes only "won",
  so two attempts sharing an idempotency key resolve to ONE writer (fix 1). An append exception whose
  reconciliation READ also fails is an explicit `outcome:"uncertain"` (never "nothing written"; only a
  successful read showing absence is nothing-written) (fix 2). Commit returns done/pending/blocked/
  uncertain; the client keeps the op key per preview fingerprint in localStorage so a reload resumes the
  SAME operation; `resume` takes over its own op's mine_prior leads; `append_leads` rechecks presence
  before writing so a late straggler adds no dup; the Import page shows pending/blocked/uncertain +
  Resume/Check (fix 3). Constraint documented: no atomic CAS on Sheets => exactly-once NOT claimed;
  single writer per concurrent round + bounded late completion; abandoned claim recovered by same-op
  resume (no TTL takeover). Containers: Python 882, frontend 70, tsc+build; browser happy-path sanity.
  LOCAL import acceptance criteria pass; live verification separate + NOT done; enable_import off in deploy.

- 2026-09-30T21:35Z [TOOL] Reviewed b49226c: 37 targeted container tests pass;
  old two-write allocator removed. Real-route/adapter probes still reproduce same-key
  concurrent duplicate rows, false Nothing was written after a landed append plus
  failed reconciliation read, and abandoned claim blocking a fresh-key re-import.
  Supersedes duplicate-prevention/re-import recovery claims below. Evidence appended
  to docs/testing/import-review-2026-09-30.md. No product edits or live writes.

- 2026-09-30 [FIX] Replaced the import Lead ID allocation + retry mechanism (the follow-up
  below). IDs are now a stable, immutable content hash (`importer.stable_lead_id`, `{prefix}-{12hex}`,
  disjoint from legacy `{prefix}-NNNN`) assigned before the write and written in ONE append, so
  (1) no collision with an existing numeric id and (3) no second position-based write for a sort to
  corrupt. (2) Retries reconcile by id (an uncertain append is re-read, not assumed failed) and
  `prepare_commit` skips ids/content already present. Cross-instance duplicates are prevented by a
  claim ledger (`Store.claim_leads`, append-only `Import claims` tab, earliest claim wins, gated by a
  required client idempotency key): two independent apps importing the same list write each lead once.
  Consumer survey done before choosing the format (tier_of/fresh_lead/_lead_order/job_check all OK).
  Containers: Python 877, frontend 68, tsc+build; browser sanity check via the real local API.
  Bounded limit: a claim winner that fails and never retries needs a re-import (TTL+sweep proposed,
  not built); no live Sheet write; enable_import off in deploy. Evidence: the Remediation-of-the-
  allocator-follow-up section in docs/testing/import-review-2026-09-30.md.

- 2026-09-30T21:07Z [TOOL] Independent follow-up of `e1f8eb2`: 35 targeted import
  tests pass in a network-disabled container. New allocator probes reproduce an
  existing A-0002 collision, invisible ID-less row after the second write fails plus
  duplicate on retry, and overwrite of an existing ID when rows sort between append
  and ID write. Supersedes the collision-free claim below; import remains incomplete.
  Evidence appended to docs/testing/import-review-2026-09-30.md. No product edits/live writes.

- 2026-09-30 [FIX] Remediated the three import acceptance failures from the review
  below. (1) `importer.fingerprint` now covers the destination columns and the commit
  route revalidates them → a changed destination is refused (409); `Store.append_leads`
  refuses field loss (`DestinationMismatch`) instead of dropping. (2) Lead IDs come from
  the atomic append's row (`updatedRange`), not `max+1`, so concurrent instances get
  distinct IDs (regression via two Flask apps on one simulated Sheet + a barrier).
  (3) Invalid contact values are preserved as validation feedback on accepted/skipped
  rows and shown on the Import page. Containers: Python 875, frontend 68, tsc+build.
  Browser-verified through the real local API (validation + stale-destination 409).
  Limits: cross-instance dedupe is best-effort (may create two rows, distinct IDs); a
  row id could clash with a sparse legacy id; no live Sheet write; `enable_import` off in
  deploy. Evidence: docs/testing/import-review-2026-09-30.md (Remediation section).

- 2026-09-30T17:26Z [TOOL] Reviewed import milestone `03a29c7`; three synthetic
  container probes reproduced: removing Phone after preview returns success but loses
  the number; two app instances append the same A-0002 ID; invalid email/phone values
  disappear without validation feedback. Evidence: docs/testing/import-review-2026-09-30.md.
  M2 is incomplete on these acceptance criteria. No product-code edits, live writes,
  deployment or full-suite rerun during this review.

- 2026-09-23T03:39Z [TOOL] Before the fix, an old-template hash could reach the Gmail
  draft path without a Drive handbook. Word overlap also accepted a negated quote as a
  positive company claim and "MVP is finished" from a "still being finished" handbook.
  After the fix, 255 tests pass offline in a network-disabled container. Lexical screening
  remains insufficient to prove semantic support; exact source review is required.

- 2026-09-23T03:00Z [TOOL] Read-only status check: 492 leads have email-check
  outcomes; 69 have fit verdicts, 5 company profiles are READY, 26 are
  OK/QUALIFIED, and no Sheet row has a draft action. Suppression exists with
  only its header. Cloud Run still routes 100% to worker revision 00013 and
  the check schedule is PAUSED. `docs/AS_BUILT.md` summary corrected; the
  planned Drive/Gemini writer remains unbuilt.

- 2026-09-22T20:48:00-04:00 [TOOL] Read-only previews of four READY leads after
  the selection fix choose commercial gas-line work for Monroe, a project
  portfolio for Conti, and the prior Harrington sentence. Cincinnati Air has
  no clean complete-sentence default among its four stored quotes; it remains
  held for an explicit reviewed choice or better source evidence.

- 2026-09-22T20:24:00-04:00 [CODE] The Cloud Run source ignores `docs/`, so the
  runtime initial-email template lives under `outreach/handbook/` while the
  review handbook stays in `docs/`.

## [OUTCOMES]

- 2026-10-01T02:31:57Z [TOOL] Reviewed dashboard queue f509dbb: 64 targeted Python
  and 13 queue/panel UI tests pass offline. Real snapshot probe still queues an
  opted-out/suppressed lead; unknown suppression also leaves queue actionable.
  Inspection: stale error does not refresh; upcoming items omit contact/note.
  Dashboard snooze/cancel verification not established by reported browser trace.
  Evidence: docs/testing/calls-review-2026-09-30.md. No product/live changes.

- 2026-10-01T02:18:28Z [TOOL] Independently verified 7053b63 with 95 targeted
  draft-pipeline/Sheet-adapter tests passing offline. Scoped call-history header
  contract fix accepted. Dashboard queue still not implemented; next milestone
  unchanged. Evidence appended to docs/testing/calls-review-2026-09-30.md.
  No product/live changes, no broader test or browser rerun.

- 2026-10-01T00:05:25Z [TOOL] Rechecked 0a85b45: 196 targeted Python and 8
  CallPanel tests pass offline. Three prior reproduced gaps addressed locally;
  real-route partial-suppression retry leaves one call and one suppression row.
  One narrow discrepancy: existing blank Call log is refused by Store but treated
  CONTINUE by job_draft._call_effect. Align header contract, then advance dashboard
  due/overdue call queue. Evidence: docs/testing/calls-review-2026-09-30.md.
  No product/live changes; build/browser/full-suite not rerun by this reviewer.

- 2026-09-30T23:42:59Z [TOOL] Rechecked 829c309: 115 targeted Python and 6 CallPanel
  tests pass offline. Original retry/sticky-DNC fixes improved, but synthetic
  job_draft.create still calls fake Gmail despite stored STOP/HOLD plus valid prior
  approval; missing task_id still closes the newer task. CallPanel ignores the new
  partial-success warning (inspection). Evidence appended to
  docs/testing/calls-review-2026-09-30.md. All-four-fixed claim not yet supported;
  no product code/live operations changed in this review.

- 2026-09-30T22:45:34Z [TOOL] Independent local review of call milestone 52bebbd:
  23 targeted tests pass in a network-disabled container. Additional real-route
  synthetic probes show STOP reported despite failed suppression write, phone-only
  DNC replaced by NO_ANSWER, stale Complete closing a newer callback, and actual UI
  retry payload recording two call events. Worker HOLD enforcement is still absent.
  Evidence: docs/testing/calls-review-2026-09-30.md. No product-code/live changes;
  finish these call behaviors before expanding the milestone.

- 2026-09-30T22:18Z [TOOL] Independently verified 0b6ed5c with 43 targeted import
  tests in a network-disabled container. Specific original-write/resume overlap now
  writes one row; simultaneous checks of abandoned claims write none. Scoped race fix
  accepted; automatic abandoned-import recovery and live verification remain open.
  Evidence: docs/testing/import-review-2026-09-30.md. No product-code or live changes.

- 2026-09-30T16:24Z [CODE] Continued the narrow review-status task from existing local
  `4c8f896` (descends from requested `f939d4a`). Removed the missing-state permission
  exception; API type, demo and fixtures require explicit state. [TOOL] 63 frontend
  tests, typecheck, production/demo builds and unchanged backend's 832 tests passed
  in network-disabled containers. Original component and missing-state exception each
  failed the relevant regression. Evidence: docs/testing/review-status-2026-09-30.md.
  Signing/gate unchanged; no deployment, activation, permission change or Google writes.

- 2026-09-22T20:24:00-04:00 [ASSUMPTION] Real pilot remains UNVERIFIED until the
  founder supplies the offer, sender details, and postal address and approves
  actual preview hashes. See `docs/AS_BUILT.md` for current verification.
