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
