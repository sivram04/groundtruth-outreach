# Decision: durable, Drive-backed playbook selection (deferred)

**Date:** 2026-10-01
**Status:** Deferred — not built. The local playbook preview is proven; durable selection is separate work.

## Context

The flag-gated, local playbook flow (`enable_playbook`, off by default and in deploy) now has a real
server boundary between three steps:

- `POST /api/playbook/review` — parse an uploaded PDF/DOCX and return the extracted text, the identified
  initial-email / follow-up / timing rules, and a **review token** (HMAC proof the server read this
  founder's exact text; not a selection, not an approval).
- `POST /api/playbook/select` — the founder's explicit Select action exchanges a valid review token for a
  time-bounded **selection token** bound to that exact reviewed content hash and founder.
- `POST /api/playbook/preview` — renders a candidate follow-up only for a verified selection token.

All of this is **in-session and non-durable**: the signing secret is generated per process, so no token
survives a restart. Selection is read-only and is not connected to production drafting.

## The blocker for durable selection

A durable selection would have to persist the selected playbook's text (or an authoritative reference to
it) so that a selection outlives a process and can be read back on another request or device.

- **Google Sheets is the only record** in this system (no database — see `CLAUDE.md`). A single Sheets
  cell holds at most ~50,000 characters, but a playbook may be up to `MAX_CHARS` (60,000). Playbook text
  therefore cannot be stored safely in one cell, and splitting a handbook across cells to dodge the limit
  would be a fragile, invented representation.
- **The production handbook already lives in Drive** and is authoritative (`CLAUDE.md`,
  `docs/ARCHITECTURE.md`). The founder has not yet placed the final handbook in Drive. Drafting must read
  that Drive document, record its version/content hash, and stop if it cannot be read or its version
  changes after approval.

## What a future durable design must decide (open)

1. **Representation.** How an approved, Drive-backed playbook version and its content hash are stored and
   referenced — a Drive file id + content hash recorded in the Sheet, rather than raw text in a cell.
2. **Authority.** It must not silently change which document is authoritative for production drafting. The
   Drive handbook stays the production source; a "selected playbook" for the local preview is a different,
   non-production artifact until a deliberate design unifies them.
3. **Approval vs selection vs review.** Keep the three distinct: review (the server read the text),
   selection (the founder chose this exact version for a local preview), and the production
   **approval hash** that gates real drafting (`outreach/review.py`, `job_draft.create`). A local selection
   must never mint or stand in for a production approval.

## Decision

Keep selection **local and time-bounded** for now. Do not persist playbook text, do not connect selection
to production drafting, and do not request a Drive link or turn on drafting before the founder's final
handbook exists in Drive. Revisit durable selection as its own milestone once the Drive handbook is in
place and the representation/authority questions above are answered.
