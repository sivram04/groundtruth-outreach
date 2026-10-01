# Independent review of post-call candidate

2026-10-01T03:06:55Z [TOOL] Reviewed local commit `d107e01`. Current source
mounted read-only in network-disabled containers: `test_post_call.py` and
`test_console_calls.py`: **41 passed in 2.03s**;
`PostCallCandidate.test.tsx`: **5 passed**. Full-suite, build and browser claims
from the implementation report were not independently rerun. No live operations.

The read-only candidate flow exists, but the following user-visible cases fail:

1. **A recorded DO_NOT_CONTACT can still produce an email candidate.** Real Flask
route with synthetic Store: record DO_NOT_CONTACT for A-0002 while its redundant
Suppression append raises; the call is stored and `suppression_written:false`.
Record a later NO_ANSWER. `calls.outreach_effect` remains STOP and the later
call response says STOP; GET `/api/calls/A-0002/candidate` nonetheless returns a
candidate because it checks the latest outcome only and the Suppression list is
empty. No email was sent. The offer of copy itself violates the sticky DNC rule.
2. **Unapproved offer wording appears.** With synthetic settings
`offer_approved:false`, an INTERESTED outcome and a stub handbook,
GET candidate returns a body. `post_call.offer_configured` checks presence of
signature fields but not the existing offer-approval flag. The handbook object is
used for its name/hash only; its text does not supply the wording. Describe this
source accurately and require approval of the settings-derived offer before
displaying it.
3. **Historical calls are described as happening today.** A saved NO_ANSWER at
2026-09-28T13:00:00Z yields “I tried to reach you by phone today” when candidate
is composed later. The same fixed “today” appears for INTERESTED and CALLBACK.
The pure builder has no current date parameter and does not compare it to the
saved call time. Never assert timing absent from the record/current date.
4. **The lead page retains a stale candidate after a call change.** Inspection:
`PostCallCandidate` reloads only when `[leadId, load]` changes. `LeadPage` passes
the same `lead.id` after `CallPanel.onChanged` refreshes the snapshot. Thus an
open page can keep an old editable candidate after a later STOP, suppression, or
new call. This last finding is code-path analysis, not a browser reproduction;
add a component regression through a parent refresh.

The first three were reproduced with current code and synthetic data in the
network-disabled container. Preserve candidate-only behavior and the working
no-email/suppression/unreadable gates while correcting these four cases. This
review edited only this evidence file and continuity; no product-code change.

## Remediation (2026-10-01, product-code change)

All four gaps are fixed; the read-only candidate design, manual editing, no-email,
opt-out and unavailable states are preserved. Containers, no network: Python
**958 passed**, frontend **92 passed**, typecheck and build clean.

1. **The effective call decision is honoured.** The endpoint computes
   `calls.outreach_effect(events)` and refuses with reason `call_stop` when it is
   STOP; `post_call.candidate` also takes that `effect` and raises for STOP. So a
   DO_NOT_CONTACT followed by a later NO_ANSWER yields no candidate even when the
   redundant Suppression write failed and the list is empty. The ordinary
   `suppression.covers` check is kept. *Regressions:* `test_post_call.py`
   (sticky-DNC effect → `call_stop`); `test_console_calls.py` (the exact saved
   sequence through the real route, with a failing suppression append, asserts the
   empty Suppression list and `call_stop`).
2. **The offer must be approved.** `post_call.offer_approved` requires the existing
   `offer_approved` flag (the same one the initial email requires); the builder
   raises `offer_not_approved` otherwise. The module and the candidate no longer
   call the wording "handbook-approved": the wording is composed in code from
   settings, and the handbook's name/hash are recorded only to tie the candidate to
   a version (its text is not read). *Regressions:* pure and route tests with
   `offer_approved:false`.
3. **No false "today".** `candidate` takes `now`; it says "today" only when the
   saved call's New York date equals the current New York date, and words an older
   call without a timing claim, for NO_ANSWER, INTERESTED and CALLBACK.
   *Regressions:* pure (today vs an older `now` per outcome) and a route test for an
   older call.
4. **A stale candidate is withdrawn on a call change.** `PostCallCandidate` takes a
   `reloadKey` (derived by `LeadPage` from the lead's call history length, effect
   and task id) and re-fetches when it changes, so a parent refresh after a
   `CallPanel` save withdraws an old candidate or loads the new one. *Regression:*
   a component test drives reloadKey changes (candidate → `call_stop` → a new
   eligible candidate). **Browser-verified** (local harness, real built pages): a
   NO_ANSWER candidate visible on the lead page → record DO_NOT_CONTACT through the
   CallPanel → the post-call section disappears with no manual reload.

Local browser checks are distinguished from the synthetic route tests above:
gap 4's live withdrawal was seen in the browser; gaps 1-3 are proved by the
network-disabled route/pure tests (the handbook is stubbed locally, `enable_calls`
is off in deploy). No sending, no Gmail draft, no deploy, no live Sheet.
