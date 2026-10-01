# Independent call-task review

## Independent queue remediation check of 8d8d278

2026-10-01T02:47:29Z [TOOL] Reviewed current commit `8d8d278` and ran
`tests/test_console_calls.py tests/test_console_model.py` against read-only mounted
source in the network-disabled Python container: **50 passed in 6.14s**. The
network-disabled frontend container ran `CallQueue.test.tsx`: **8 passed**.
Inspection confirms the queue excludes leads marked suppressed, marks unreadable
suppression unavailable, offers Reload after an action error, and includes contact
and note in upcoming items. These are the three previously identified queue gaps.
The reported local browser Snooze/reload journey is from Claude's run; this review
did not independently rerun the browser, full suite, typecheck or build. The
dashboard queue is accepted as a local milestone under these limits. No live
Sheet/Gmail or deployment verification. No product-code changes in this review.

## Post-call email candidate (2026-10-01, product-code change)

Built as candidate creation and review only — no sending, no Gmail draft, no persistence. A new pure
module `outreach/post_call.py` composes a post-call email candidate from already-saved facts: the latest
call outcome and note, the company's own cited words on the lead row, the handbook-approved offer
(settings), tied to the current Drive handbook's content hash. A flag-gated endpoint
`GET /api/calls/<lead>/candidate` (under `enable_calls`) builds it on demand and the lead page shows it
beside its evidence with editable fields and a Discard action.

Rules enforced: a candidate is offered only for NO_ANSWER, INTERESTED and CALLBACK; NO_ANSWER wording
never claims a conversation and no wording invents the recipient's words; a CALLBACK uses only the
recorded callback time; DO_NOT_CONTACT, NOT_INTERESTED and WRONG_NUMBER get none; a lead with no email
gets none (a phone-only lead keeps its task and history); a suppressed lead gets none; an unreadable call
log, suppression list or handbook makes it unavailable, not silently produced. The body always carries the
opt-out footer. It does not authorise anything: a HOLD still blocks the ordinary email sequence, and
showing the candidate writes nothing (no call event, no suppression). Suppression, signing and review
gates are untouched (this path never reaches Gmail-draft creation).

*Regressions:* `test_post_call.py` (pure: each outcome's wording, no-conversation after NO_ANSWER, no
invented recipient words, callback uses only the recorded time, the internal note is context not pasted,
the company evidence is the company's own verbatim words, no candidate for a stop/wrong-number/no-email/
no-handbook/offer-not-configured, latest-outcome selection); `test_console_calls.py` (the real Flask
endpoint: candidate for each eligible outcome; no_email; outcome_not_eligible; suppressed; unreadable
suppression and unreadable call log → unavailable; handbook unavailable; showing it writes nothing and the
HOLD effect is unchanged); `PostCallCandidate.test.tsx` (renders candidate + evidence + discard; nothing
for no_email/outcome_not_eligible; the suppressed and unavailable states; the recorded callback time).
Containers, no network: Python **952 passed**, frontend **91 passed**, typecheck and build clean.
**Browser journey** (local harness extended with a stub handbook + offer settings, real built pages, actual
API): record NO_ANSWER on an email lead → the "Post-call email" candidate appears with its subject, editable
body, the opt-out footer, the cited company evidence, the note, the outcome and the handbook → reload shows
it again; a phone-only lead shows no candidate section. **Unverified live:** a real Drive handbook, a
signed-in browser and real API latency - the handbook is stubbed locally and `enable_calls` is off in
deploy. No sending, no Gmail draft, no deploy, no live Sheet.

## Remediation of the dashboard-queue review (2026-10-01, product-code change)

The three acceptance gaps are closed and the verification narrowed to what was actually exercised.
Containers, no network: Python **933 passed**, frontend **86 passed**, typecheck and build clean; demo
`snapshot.json` regenerated. Flag-gated (`enable_calls`, off by default and in deploy); synthetic only.

1. **The queue honours suppression.** `console_model.build` now leaves a suppressed (opted-out) lead out
   of `call_tasks` - its call history still shows on the lead page - and, when the Suppression list cannot
   be read (`entries is None`), empties the queue and flags it: the snapshot carries `suppression_unreadable`,
   and the dashboard shows the unavailable state (never "no calls due"). *Regressions
   (`test_console_calls.py`, real Flask snapshot):* an opted-out A-0002 is excluded while a non-suppressed
   A-0001 stays and A-0002 keeps its history; unreadable suppression → `suppression_unreadable: true` with an
   empty queue.
2. **Stale-action recovery is implemented.** `QueueItem`'s refusal keeps the server's message on screen and
   shows a **"Reload the queue"** action that calls `onChanged`; after the dashboard re-reads and passes the
   newer task, a subsequent action targets the refreshed `task_id`. *Regression (`CallQueue.test.tsx`):* a
   409 shows the message, Reload calls `onChanged`, and after a re-render with a new id the next Complete
   uses the new id (STALE → FRESH).
3. **Upcoming items now carry contact and the recorded note**, alongside company (linked), phone, due time
   and reason. *Regression:* an upcoming item shows the contact and note.

**Verification, narrowed.** Dashboard actions covered through the component against the real
snapshot/API shape: Complete, Cancel (both bound to the exact `task_id`, then refresh), Snooze (SNOOZE +
`snooze_to`, bound to the id), and stale-action recovery. **Browser journey** (local harness, real built
pages, actual API): an overdue past-callback → **Snooze to 2026-12-01 via the UI** → it moves out of
overdue → **reload** shows it under "1 upcoming" (persisted). The Complete-removes-and-reload journey was
shown in the previous round. The clock-advance overdue transition remains covered by the controlled-clock
route tests, not the browser (the harness runs on a fixed real clock) - browser evidence and route-test
evidence are kept distinct.

## Independent dashboard queue review of f509dbb

2026-10-01T02:31:57Z [TOOL] Current source mounted read-only in network-disabled
containers: `test_calls.py`, `test_console_calls.py`, `test_console_model.py`:
**64 passed in 3.92s**; `CallQueue.test.tsx` and `CallPanel.test.tsx`: **13 passed**.
Full-suite/build/browser claims were not independently rerun.

The dashboard queue exists with server-computed buckets, task-bound actions and
a Call-log-unavailable state. Remaining acceptance gaps:

1. **Opt-out suppression is not honoured by the queue.** Real Flask snapshot with
   the existing synthetic test fixtures: record NO_ANSWER for A-0002, then append
   a suppression entry for its email with Reason `opt-out`. Snapshot lead has
   `suppressed:true` but `call_tasks` still contains A-0002; `calls_unreadable:false`.
   Set `store.entries=None` to simulate unreadable suppression: the actionable
   queue still contains A-0002 and is not marked unavailable. `call_state` handles
   call-recorded DNC, but does not consume the separate suppression list. The
   queue builder appends any scheduled call task without checking suppression.
2. **Stale-action refresh is claimed but not implemented.** Code inspection:
   `QueueItem.run`'s rejection callback sets the error only. It does not call
   `onChanged` or offer a queue-local Reload action. The test asserts the message
   only; it does not verify refreshed task identity. Server stale rejection is
   preserved and is not the failing part.
3. **Upcoming items omit requested details.** Code inspection: the upcoming
   section shows company/link, due time, reason and phone, but not contact or
   the recorded note. Due/overdue QueueItem shows both.

Evidence wording also needs narrowing: the detailed browser trace covers Complete
and reload, not dashboard Snooze/Cancel. Existing CallPanel action tests are not
dashboard action tests. Add the requested dashboard snooze/reload verification,
plus cancel and stale-refresh tests, rather than claiming this journey complete.

No product-code changes or live operations. Evidence and continuity only, left
uncommitted. Keep the next patch confined to queue eligibility, recovery, missing
details and verification; do not reopen import or the accepted call-history fixes.

## Independent contract-fix verification of 7053b63

2026-10-01T02:18:28Z [TOOL] Current source mounted read-only in a network-disabled
container: `tests/test_draft_pipeline.py` and `tests/test_sheet_append.py`,
**95 passed in 6.96s**. Inspection confirms the present-empty-tab CONTINUE branch
was removed. Accept the scoped reader-contract alignment; dashboard call queue
remains unimplemented. Full-suite/build/browser/live behavior not rerun here.
No product changes or live operations; this evidence update is uncommitted.

## Independent verification of 0a85b45

2026-10-01T00:05:25Z [TOOL] Rechecked current commit `0a85b45` in
network-disabled containers with current source mounted read-only:
`test_calls.py`, `test_console_calls.py`, `test_followup.py`, `test_drafts.py`,
`test_draft_pipeline.py`: **196 passed in 4.66s**; `CallPanel.test.tsx`:
**8 passed**. No full-suite, build or browser rerun by this reviewer.

The previously reproduced valid-approval STOP/HOLD bypass and missing-task-id
fallback are addressed in these local tests. The warning now renders, and the
component preserves submission identity for Retry the rest. An additional real
Flask-route probe using the existing synthetic call fixtures failed the first
suppression append, restored it, and repeated the same submission: first response
`suppression_written:false`, second `true`, one call row, one suppression row,
effect STOP. No live Gmail or Sheets were contacted.

One narrow reader-contract discrepancy remains: seed `FakeSheets.tabs['Call log']`
as an existing empty list. `Store(api).call_events()` refuses the missing header,
but `job_draft._call_effect(api, 'A-0001')` returns CONTINUE at `if not values`.
This differs from the claimed shared header contract. Distinguish an absent tab
(allowed no-call history), a valid header with zero rows (allowed), and a present
tab without its header (blocked). This probe tested the readers, not a further
Gmail creation attempt. Correct with a focused regression; no wider redesign is
needed.

Accept the fixes for the three specifically reproduced gaps under these local
conditions. Live behavior remains unverified. After that small contract alignment,
the next useful milestone is the dashboard's due/overdue call queue, already listed
as missing in MVP_DELIVERY.md. Review evidence/continuity only changed here; left
uncommitted. Product code, services and feature flags untouched.

2026-09-30T22:45:34Z [TOOL] Reviewed commit
`52bebbd7a552e3ebaaf77178f5615351dfadc4cf`. Scope: the new call-task milestone,
not import architecture or the full MVP. Product code was not changed.

## Existing tests: PASS, narrow local scope

Current source mounted read-only at `/repo` in `outreach-tests`, with network
disabled, `PYTHONDONTWRITEBYTECODE=1`, `PYTHONPATH=/repo:/repo/tests`:

`python -m pytest -q -p no:cacheprovider tests/test_calls.py tests/test_console_calls.py`

Result: **23 passed in 1.19s**. Full suites, browser and live Sheets behavior were
not independently rerun. Claude's reported browser journey is not new evidence
from this review.

## Additional probes: required behavior FAILS

Probes used the real Flask routes with `test_console_calls.make`, `a_store`,
`outcome`, `act`, a temporary static directory, signed synthetic test identity,
and the same network-disabled container. No Google API calls.

1. **STOP is not reliably enforced.** Replace the synthetic store's
   `append_suppression` with a function raising RuntimeError; record DO_NOT_CONTACT
   for email+phone lead A-0002. Response: HTTP 200, `recorded:true`, `effect:STOP`,
   task null; suppression remains empty. The route catches the error as best-effort.
   Inspection: `followup.run`/`pending_reviews` read suppression, not call events.
   This proves an unenforced call stop, not that an email was sent or that other
   independent drafting gates would pass. HOLD is also not read by that worker,
   as the implementation report acknowledges.
2. **Phone-only DNC can be undone by a routine outcome.** Record DO_NOT_CONTACT
   for A-0001, then NO_ANSWER. Both return 200; second response has
   `effect:CONTINUE` and a scheduled call due 2026-10-01. Explicit DNC therefore
   does not remain a per-lead block. Logging history and scheduling new outreach
   need distinct permission decisions.
3. **A stale task action closes the newer callback.** Record NO_ANSWER, retain
   its event ID, then record CALLBACK for 2026-10-02T14:00:00Z. Submit COMPLETE
   with the old `task_id`. The route ignores that ID, returns 200 and marks the
   CALLBACK task done. Current UI does not send an ID at all; its task view omits
   it. `action_event` hashes the target but does not persist it; replay applies
   any action to the currently scheduled task, so route checking alone is not
   sufficient for delayed/interleaved events.
4. **The actual UI payload is not retry-stable.** Submit
   `{outcome: NO_ANSWER, note: rang out}` twice with a clock advanced five seconds.
   Two different event IDs and two history rows result. `CallPanel.save` omits
   `called_at`; the route inserts a fresh time, which participates in the hash.
   Existing duplicate test supplies a fixed timestamp and misses this path.
   There is still only one *current* task, since replay replaces it; the defect
   is duplicate call history/task replacement, not two concurrent open tasks.

The first probe script stopped at `KeyError: id` when attempting to extract the
task identifier from the API view. The corrected stale-action and retry probes
used persisted Event IDs and completed successfully; the missing view ID is part
of finding 3, not a product exception.

## Next bounded work

Complete enforcement of persisted call STOP/HOLD in the existing eligibility
paths, including unreadable call state and partial suppression failure. Keep DNC
effective for phone-only leads. Bind task actions through UI, API and stored
events to their target. Preserve one logical submission identity across retries
while allowing a genuinely new call. Test these paths before expanding to chat
logging, post-call email candidates or dashboard task lists.

No provisioning, deployment, activation, Gmail drafts, sending, live Sheet writes,
or product-code edits. Review evidence and continuity only; left uncommitted.

## Remediation (2026-09-30, product-code change)

All four findings are fixed and regression-tested through the real Flask routes and the pure state
machine (`outreach/calls.py`), not component mocks alone. Verified in containers with no network:
Python **920 passed** (was 906; +14), frontend **76 passed** (was 74; +2), typecheck and build clean.
Browser-verified through the actual local API and the real built pages (`tools/local_import_console.py`,
port 8139). Still flag-gated (`enable_calls`, off by default and in deploy); no live Sheet, no send, no
deploy. Synthetic verification only; live verification remains a separate, not-done milestone.

1. **STOP/HOLD is now enforced in the eligibility paths.** `calls.outreach_effect` / `blocks_outreach`
   derive a lead's email effect from its call events alone (no clock). `drafts.first_draft_blockers` and
   `followup.due_now` take the lead's call events and refuse a first draft / a follow-up on a STOP
   (do-not-contact / not-interested) or HOLD (interested / callback) — so offline HOLD enforcement now
   exists. **Unreadable call history fails closed:** `drafts.plan`, `followup.pending_reviews`/`run` and
   `console_model.snapshot`/`build` block rather than treat it as unrestricted outreach. The outcome route
   returns `suppression_written: false` and a `warning` when the redundant Suppression entry cannot be
   written; the STOP is still enforced by the recorded call event, so a failed suppression append no longer
   leaves a do-not-contact unenforced. *Regressions:* `test_followup.py` (worker skip on STOP/HOLD,
   unreadable-log fail-closed, run/reviews fail-closed, first-draft blocked by a call stop),
   `test_console_calls.py::test_a_suppression_write_failure_still_enforces_the_stop_and_reports_it`.

2. **Do-not-contact is sticky for phone-only and email+phone leads.** `call_state` carries a
   `do_not_contact` flag: once recorded, the effect stays STOP and no later routine outcome (a no-answer)
   reopens a task or lifts it; history is still logged (recording history is separate from permission to
   schedule). Not-interested stays a distinct outcome. *Regressions:* `test_calls.py::test_do_not_contact_is_sticky…`,
   `test_console_calls.py::test_do_not_contact_stays_effective_through_a_later_no_answer`.

3. **A task action is bound to the exact task shown.** A **Task ID** column persists the action's target
   (`sheet.py CALLS_HEADER`, `calls.action_event`); `call_state` applies an action only to the task it named,
   so a stale/interleaved action cannot close a newer task (the `KeyError: id` is gone — `call_task_view`
   now exposes `id`). The CallPanel sends `task_id`; the route refuses a mismatched id (409) without touching
   the newer task. *Regressions:* `test_calls.py::test_a_stale_action_cannot_close_a_newer_task`,
   `test_console_calls.py::test_a_stale_task_action_is_refused_and_the_newer_task_is_untouched`,
   `CallPanel.test.tsx` ("names the exact task…").

4. **A call submission is retry-stable through the UI.** The CallPanel keeps one `submission_id` across
   retries (cleared on success or when the form is edited); `calls.outcome_event` uses it as the Event ID,
   so a retry — including after a lost response following a successful write — makes no duplicate, while a
   genuinely new call is still recorded. A programmatic caller supplying a fixed `called_at` keeps the old
   content-hash idempotency. *Regressions:* `test_calls.py::test_a_ui_shaped_retry_is_one_event_though_the_clock_advanced`,
   `test_console_calls.py::test_a_ui_shaped_retry_with_an_advancing_clock_makes_one_event`,
   `CallPanel.test.tsx` ("keeps one submission identity across a retry…").

## Independent recheck of 829c309

2026-09-30T23:42:59Z [TOOL] Commit
`829c3097affe74d210df45c5344180b898b92a38`, current source mounted read-only in
network-disabled containers. `test_calls.py`, `test_console_calls.py`,
`test_followup.py`, `test_drafts.py`: **115 passed in 4.36s**.
`console/src/pages/CallPanel.test.tsx`: **6 passed**. These independently confirm
the tested sticky-DNC, explicit-target, sequential-retry and selection behavior;
the full-suite/build/browser claims above were not independently rerun.

The remediation is incomplete at two enforcement boundaries:

1. **Initial Gmail draft creation bypasses call STOP/HOLD.** Using
   `test_draft_pipeline.ready.__wrapped__` with pytest.MonkeyPatch, its valid signed
   review and approved candidate, plus `test_sheet_append.FakeSheets` with a real
   Call log header/row: `Store(api).call_events()` reads DO_NOT_CONTACT as STOP, or
   CALLBACK as HOLD. Pass this same API to `job_draft.create`; each case returns
   `CREATED` and invokes the fake Gmail creator once. `_read` and `_suppressed`
   use the existing happy-path fixture (suppression false, representing the failed
   redundant suppression write); candidate/review checks remain real. The create
   function never consults the stored call event. This is the function called by
   the worker create route; protecting `drafts.plan` alone does not protect a
   candidate approved before the call. No real Gmail or Sheet operation occurred;
   the test's enable flag exists only inside the isolated process.
2. **Missing task identity still selects the current task.** Through the real
   Flask route with synthetic MemoryStore: NO_ANSWER task A, then CALLBACK task B,
   then POST COMPLETE without `task_id` (the previous UI's payload). Returns HTTP
   200 and marks B done. Explicit stale IDs now correctly reject, but omission
   still bypasses binding. The typed API keeps task_id optional, and the route
   uses `client_task_id or task["id"]`.

Additional inspected UI gap: the outcome API now returns a partial-success
`warning` and `suppression_written:false`, but CallPanel's success callback ignores
the result, clears the form/submission ID and renders no warning. The backend
warning is therefore not communicated to the founder. This observation is from
code inspection, not a new browser run.

Verdict: accept the verified improvements, but do not mark all four original
findings closed yet. Add the call decision check at the actual initial draft
creation boundary, require task identity for new actions, and display partial
success with a truthful retry path. Keep import and other milestones out of scope.
No product-code edits, deployment, live writes, activation or sending. Evidence
and continuity updates only, left uncommitted.

## Remediation of the recheck (2026-09-30, product-code change)

The three gaps the recheck named are closed; the working sticky-DNC, retry-identity
and explicit-target fixes are preserved unchanged. Verified in containers, no
network: Python **925 passed** (+5), frontend **78 passed** (+2), typecheck and
build clean. Still flag-gated (`enable_calls`, off by default and in deploy); no
live Sheet, no send, no deploy; synthetic verification only.

1. **Call STOP/HOLD enforced at the real initial-draft boundary.** `job_draft.create`
   — the only path that turns an approved candidate into a Gmail draft, and the one
   the worker create route calls — now re-reads the Call log through
   `job_draft._call_effect(api, lead_id)` (the same header contract as
   `sheet.Store.call_events`) and refuses STOP, HOLD or unreadable history *before*
   any reservation or Gmail write. It is read at the boundary, not cached, so an
   approval granted before a later do-not-contact / interested / callback cannot
   bypass it; a missing Call log tab is CONTINUE (a company without calls still
   drafts); signing and all existing gates are unchanged. *Regressions
   (`test_draft_pipeline.py`, real reader over `test_sheet_append.FakeSheets` and a
   valid approved candidate):* DO_NOT_CONTACT with **no** suppression entry,
   CALLBACK/HOLD, and unreadable (changed-header) history each raise `DraftBlocked`
   with **no** Gmail create; a lead with no call history still reaches `CREATED`.

2. **A task action requires a nonempty `task_id`.** The `client_task_id or task["id"]`
   fallback is removed: the route refuses a missing (400) or blank (400) id and a
   stale id (409); the typed `actOnCallTask` makes `task_id` required. *Regressions:*
   `test_console_calls.py::test_a_task_action_without_a_task_id_is_refused` (missing,
   blank and stale after a newer task replaces the original — none modifies the newer
   task); browser-verified through the real API (missing/blank → 400, task stays
   scheduled, correct id completes it).

3. **CallPanel displays the partial success.** The success callback reads the result;
   on `suppression_written:false` (or a `warning`) it shows what was saved and what
   remains, keeps the submission identity and the form, and offers "Retry the rest",
   which re-sends the **same** submission id (no second call recorded) to re-attempt
   the suppression write. *Regressions (`CallPanel.test.tsx`):* the warning renders and
   Retry reuses the submission id; a separate test runs the **real** `recordCallOutcome`
   parser over the actual partial JSON response shape. The create-boundary gate has no
   UI and the partial-success warning needs a suppression failure the synthetic harness
   cannot inject, so these are covered by component-render, parser and server-route
   tests rather than a browser run.

## Call-history contract aligned (2026-09-30, product-code change)

`job_draft._call_effect` and `sheet.Store.call_events` now agree on the three cases: an **absent** Call
log tab is no call history (CONTINUE / []); a **valid header with no event rows** is no call history; a
**present tab without the required header** (including an empty, headerless tab) is unreadable and blocks
drafting (fail closed). `_call_effect` previously returned CONTINUE for a present-but-headerless tab while
`Store.call_events` raised; the early `if not values: return CONTINUE` is removed so the header check
governs (an empty tab has no header → block). *Regressions:* `test_sheet_append.py::test_call_events_contract_absent_valid_header_and_missing_header`
(Store, all three cases); `test_draft_pipeline.py` — a valid header with no events still reaches CREATED,
and a present headerless tab raises `DraftBlocked` with **no** Gmail create. Containers, no network: Python
**928 passed**. Still flag-gated; synthetic only.

## Dashboard call queue (2026-09-30, product-code change)

Built. The dashboard now shows a "Calls to make" queue (only when `enable_calls` is on): overdue first,
then due today, with upcoming kept in a separate, collapsed section. `console_model.build` gives each open
task a `when` bucket (OVERDUE / TODAY / UPCOMING) worked out from the New York date (same clock as
`overdue`), carries the task `id`, and the snapshot adds `calls_due_today` and `calls_unreadable`. Each
item shows company (link to the lead), contact, phone, due date/time and the recorded reason/note, and
reuses the existing task identity + Complete/Snooze/Cancel API (`actOnCallTask`, `task_id` required); a
stale action shows the server's message and refreshes. An unreadable Call log shows an **unavailable**
state ("the call log could not be read … do not assume there are no calls due"), never "no calls due".
Phone-only and email+phone leads both appear.

*Regressions:* `test_console_calls.py` — the queue buckets overdue/today/upcoming through the real
snapshot (controlled clock), an upcoming call is separate, and an unreadable Call log is `calls_unreadable`
with an empty `call_tasks` (not "no calls due"); `CallQueue.test.tsx` — overdue+today listed together and
upcoming separate, the unavailable state vs a genuinely empty queue, Complete bound to the exact `task_id`
with a refresh, and a stale 409 showing the server message. Containers, no network: Python **931 passed**,
frontend **83 passed**, typecheck and build clean. **Browser journey** through the actual local API and
the real built pages: a no-answer and a past-callback appear in the queue (1 overdue, 1 upcoming, phone and
reason shown); Complete removes the overdue task and the queue auto-refreshes; a reload confirms it stayed
gone (only the upcoming one remains). The clock-advance overdue transition is covered by the
controlled-clock route tests (`test_a_task_becomes_overdue_on_a_later_clock`, `test_the_queue_buckets_…`),
since the local harness runs on a fixed real clock. Snooze is covered by `CallQueue.test.tsx` and the
existing `test_complete_snooze_and_cancel`. Synthetic only; `enable_calls` off in deploy; no live Sheet,
no send, no deploy.
