# Chat call logging review — 2026-10-01

Scope: local code review of `ba10c11` only. No live Sheet/Gmail access, deployment, activation or product-code edit. Fresh container checks were attempted but could not run: the Docker Desktop Linux Engine pipe was unavailable. Claude's reported 978 Python / 101 frontend passes and browser journeys are prior evidence, not independently re-run here.

1. **Candidate freshness remains incomplete for in-place changes.** `postCallReloadKey` in `console/src/pages/LeadPage.tsx` includes `approvals.offer` as a boolean and `links.handbook` as a document URL. The snapshot model exposes those values as a boolean and a URL. Editing the handbook *at the same URL*, or changing approved offer wording while approval remains true, leaves the key unchanged after a snapshot refresh. `PostCallCandidate` only re-fetches when that key changes. The current test changes the handbook URL, so it does not cover an in-place edit. Claiming refresh for every handbook/offer change is unsupported.
2. **Chat confirm hides a partial stop-list write.** `outreach/console.py` returns HTTP 200 with `suppression_written:false` and `warning` if the call's STOP is recorded but the Suppression append fails. `console/src/pages/CallPanel.tsx` preserves the submission and displays this partial result. `CallLogChat.confirm` ignores the result, shows a clean “Saved,” clears the proposal/submission ID, and gives no repair path. The Call log STOP remains enforced; the inaccurate UI and missing suppression-list repair are the gap. This is code-path evidence, not a fresh runtime reproduction.
3. **Previewed due date can differ from saved due date.** `call_log_chat.interpret` computes the no-answer due date from the interpretation clock. `CallLogChat.confirm` posts no `called_at`; the outcome route stamps a new clock time and computes the task date again. If the founder previews before midnight New York time and confirms after midnight, the displayed three-business-day due date can differ from the saved task. A controlled-clock route regression is needed. This is code-path evidence, not a fresh runtime reproduction.

The intended core flow is present: a read-only interpretation, explicit founder confirmation, the existing outcome write route and a sticky STOP. The three findings above constrain the completion claim. Keep the next change narrow and verify it in containers when the daemon is available.

## Remediation (2026-10-01, product-code change)

All three findings are closed; the interpreter stays read-only and the confirm stays routed through the
existing `POST /api/calls/<lead>/outcome`. Containers were available for this change (Docker Desktop
restarted): Python **980 passed**, frontend **104 passed**, typecheck and build clean.

1. **In-place handbook/offer freshness.** `postCallReloadKey` now includes `data.read_at`, so the open lead
   page re-fetches its candidate on every snapshot refresh — which catches an in-place handbook edit (same
   URL) or approved offer wording changing while approval stays true, because the candidate endpoint rebuilds
   from the live handbook and settings. `PostCallCandidate` keeps a signature of the last fetched pristine
   candidate: a re-fetch that returns the same candidate **preserves the founder's edits**, a changed one
   replaces them, and a now-ineligible result withdraws the candidate. *Regressions:* `LeadPage.test.tsx`
   (the key changes on `read_at`, and on suppression/offer/handbook; stable when nothing changes);
   `PostCallCandidate.test.tsx` (edits preserved on an unchanged refresh, replaced on a changed candidate,
   withdrawn when gone).
2. **Chat confirm shows a partial stop-list write.** `CallLogChat.confirm` now reads the result: on
   `suppression_written:false` or a `warning` (HTTP 200) it shows the warning, keeps the proposal and its
   submission id, and offers "Retry the suppression write", which re-posts the same submission id — repairing
   the Suppression entry without recording a second call — matching `CallPanel`. *Regression:*
   `CallLogChat.test.tsx` drives the real partial-success response shape and asserts the retry reuses the
   submission id.
3. **Previewed due date equals the saved due date.** `call_log_chat.interpret` now returns `called_at` (the
   interpretation clock), and `CallLogChat.confirm` posts it, so the outcome route computes the task date from
   the same call time — a preview before New York midnight and a confirm after it no longer disagree.
   *Regression:* a controlled-clock route test interprets at 23:59 ET and confirms at 00:30 ET the next day;
   the saved due equals the previewed `2026-10-01`, where an un-pinned confirm would have drifted to
   `2026-10-02`. (Pinning the call time makes the preview deterministic, so a separate stale-preview guard is
   not needed for due-date correctness.)

**Browser:** a regression smoke was run (local harness, rebuilt pages) — the chat flow still interprets,
confirms and writes a task whose due matches the preview, and the post-call candidate still renders after its
effect refactor. The three fixes themselves were **not** reproduced in the browser: the harness has no
controlled clock, no way to inject a Suppression-write failure, and no out-of-band handbook/offer change — so
they are proved by the network-disabled route, component and pure tests above. No sending, no Gmail draft, no
deploy, no live Sheet.
