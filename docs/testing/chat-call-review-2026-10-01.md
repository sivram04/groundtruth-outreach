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

## Independent recheck of `e52c221` (2026-10-01)

In network-disabled containers, 55 focused Python tests and 18 focused frontend tests passed. Code review
supports the partial-suppression UI handling and the midnight due-date pin. The in-place freshness claim is
still incomplete:

1. `console_model.build` formats `read_at` to **minute** precision (`%Y-%m-%d %H:%M ET`). Two snapshot
   refreshes in the same minute return the same `postCallReloadKey` when all other listed fields are unchanged.
   `PostCallCandidate` therefore does not re-fetch after a same-minute handbook edit at the same URL or a
   still-approved offer-wording edit. The added test changes `read_at` by five minutes; it misses this case.
2. `PostCallCandidate.serverSig` compares only lead ID, subject and body. If a re-fetch does happen and the
   handbook hash or cited evidence changes while the generated text remains identical, the founder's edits
   are preserved under the newly displayed basis. The candidate result already includes `handbook_hash` and
   evidence. Treating these as an unchanged candidate is narrower than the stated “underlying candidate
   unchanged” condition. This is a code-path finding; no browser reproduction was attempted.

The previous review's chat partial-success and due-date findings are addressed at the tested scope. No
product code or live service was changed by this recheck.

## Remediation of the recheck (2026-10-01, product-code change)

Both residual sub-gaps in finding 1 are closed. Containers available: Python **980 passed**, frontend
**105 passed**, typecheck and build clean.

1. **Re-fetch no longer depends on `read_at` minute precision.** `App` now keeps a `generation` counter that
   increments on every successful snapshot load and passes it to `LeadPage`; `postCallReloadKey` folds it in,
   so the candidate is re-fetched on every refresh even two within the same clock minute. *Regression:*
   `LeadPage.test.tsx` — the key changes when `generation` increments with `read_at` and all listed facts
   unchanged, and is stable when `generation` is unchanged.
2. **The signature is the full basis.** `PostCallCandidate`'s "unchanged candidate" signature now includes
   `handbook_hash` and the cited `evidence`, not just lead id + subject + body. A re-fetch whose handbook
   version or evidence changed is treated as a changed candidate (the founder's edits are replaced), matching
   the "underlying candidate unchanged" condition. *Regression:* `PostCallCandidate.test.tsx` — identical
   subject/body with a changed handbook hash discards the edit.

These are internal refresh-timing and signature refinements, verified by the network-disabled frontend
component tests and the unit key test; they were not browser-reproduced (the harness cannot make a
same-minute in-place handbook edit). No sending, no Gmail draft, no deploy, no live Sheet.
