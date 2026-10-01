# Independent call-task review

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
