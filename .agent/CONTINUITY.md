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

- 2026-09-22T20:24:00-04:00 [ASSUMPTION] Real pilot remains UNVERIFIED until the
  founder supplies the offer, sender details, and postal address and approves
  actual preview hashes. See `docs/AS_BUILT.md` for current verification.
