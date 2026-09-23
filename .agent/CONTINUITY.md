# Outreach continuity

## [PLANS]

- 2026-09-22T20:24:00-04:00 [ASSUMPTION] Stage 3 proceeds locally: review four real
  company-profile previews after the founder fills the handbook, then a
  controlled Gmail-draft pilot. Stage 4 sent/reply sync and follow-ups are
  separate; bulk research and all schedules remain paused.

## [DECISIONS]

- 2026-09-22T20:24:00-04:00 [USER] The MVP is unfinished this week; outreach may
  invite next-week conversations but must not promise a live trial today.
- 2026-09-22T20:24:00-04:00 [USER] Asked Claude Code to build the missing automated
  drafting pipeline. [TOOL] Its local OAuth session was expired and could not
  refresh, so Codex continued the authorized local build.

## [PROGRESS]

- 2026-09-22T20:24:00-04:00 [CODE] Local Stage 3 code now renders evidence-backed
  initial-email previews, requires exact date-bound hash approval, and has a
  disabled-by-default Gmail draft creation path with Sheets reservation and
  conservative reconciliation. No deployment or live Google write occurred.

## [DISCOVERIES]

- 2026-09-22T20:24:00-04:00 [CODE] The Cloud Run source ignores `docs/`, so the
  runtime initial-email template lives under `outreach/handbook/` while the
  review handbook stays in `docs/`.

## [OUTCOMES]

- 2026-09-22T20:24:00-04:00 [ASSUMPTION] Real pilot remains UNVERIFIED until the
  founder supplies the offer, sender details, and postal address and approves
  actual preview hashes. See `docs/AS_BUILT.md` for current verification.
