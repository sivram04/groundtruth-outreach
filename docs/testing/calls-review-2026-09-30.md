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
