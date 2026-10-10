# Multi-tenant foundation: what this branch is and isn't

Status: **engineering started 2026-10-10, in parallel with the founder starting Google's OAuth
verification clock** (see `docs/OAUTH_VERIFICATION_CHECKLIST.md` on `main`). Isolated on branch
`multi-tenant`, worktree `D:\lakshyaa-outreach-tenant`. Nothing here is merged into `main` or
deployed. `main` stays the live, working, single-tenant product throughout.

## Why this branch exists, and why it isn't starting from zero

`docs/MULTI_TENANT_PLAN.md` (on `main`) lays out what multi-tenant actually requires: an account
system (replacing IAP), per-user Google OAuth with its ~6-week verification clock, per-tenant data
isolation, and per-tenant secrets. That plan was written before any of it was built.

Separately, a full architecture rewrite was already attempted on another line of work
(`codex/full-outreach-product`, worktree `D:\lakshyaa-outreach-full`, 213 commits) - a genuine,
substantial multi-tenant Postgres implementation: 37+ migrations, row-level security, KMS-
encrypted OAuth tokens, a public SaaS entrance. It diverged from `main` 100+ commits ago on each
side (204 files, +27,657/-3,971 lines) - too far to merge as a whole without an unreviewable wall
of conflicts, and it never got Google's real OAuth sign-in working (confirmed in its own
`AS_BUILT.md`: "Actual Google sign-in and signed-in onboarding are blocked").

Rather than design the account/tenant schema from scratch, **this branch starts by porting the
two self-contained foundation migrations from that work** (`migrations/tenant/0001_registry_and_
projects.sql`, `0002_google_connections.sql`) - they define exactly `tenant.accounts`,
`tenant.identities` (a signed-in Google identity resolves to an account), `tenant.projects`
(row-level-security-enforced per account), and `tenant.google_connections` (encrypted OAuth
refresh tokens, one per account+kind+Google-subject, RLS-enforced). This is sound, already-
reviewed design; re-deriving it here would just recreate the same shape more slowly.

**What this branch does NOT inherit from that work**: its application code, its public SaaS
site, its 35+ later migrations building out projects/calls/replies/A-B on top of the tenant
schema, or its staging deployment. Those are far more entangled with that branch's own parallel
rewrite of drafting/sending/tracking, which `main` has since evolved independently and
incompatibly (auto-send, batch-approve, company-settings-via-chat, auto-research, multi-project -
none of which existed when the two branches diverged). Building those features on the NEW tenant
foundation, reusing `main`'s current logic, is deliberately treated as separate, later work.

## What exists after this slice

- `migrations/tenant/0001_registry_and_projects.sql`, `0002_google_connections.sql` (ported,
  unmodified).
- `outreach/tenancy.py`: the Python data-access layer over that schema - resolve a signed-in
  Google identity to an account (creating one on first sign-in), and read/write a Google
  connection's encrypted refresh token. Dependency-injected (a `conn`/cursor is always passed
  in, never constructed internally), matching this repo's existing testing convention
  everywhere else - so it's fully testable offline with a fake cursor, no real Postgres needed
  for the logic tests.
- Token encryption is **not** implemented yet - `tenancy.py` takes an injectable `encrypt`/
  `decrypt` pair and raises `NotImplementedError` if neither is supplied, rather than silently
  storing a token in plain text. Wiring real Cloud KMS is the next slice, once a real Postgres
  connection exists to test against.

## What's still needed before this is usable

1. **A real Postgres connection.** The GCP project `lakshyaa-outreach` already has a Cloud SQL
   instance from the codex work (`outreach-staging`, currently **STOPPED** - no compute cost
   while stopped, small storage cost). Reusable rather than provisioning a new one, once this
   schema is applied there under its own `tenant` schema (keep it separate from any schema the
   codex branch may have put there, to avoid cross-contamination of two different designs in the
   same database).
2. **Real Cloud KMS wiring** for the refresh-token ciphertext (the codex branch's own KMS
   provisioning work, `docs/testing/staging-oauth-kms-2026-10-04.md` on that branch, is a
   reference for how to do this - it got as far as "exact-key runtime access... with 90-day
   rotation" before being blocked on the OAuth client itself).
3. **An actual OAuth consent screen + client**, which needs the founder's own verification
   submission (`docs/OAUTH_VERIFICATION_CHECKLIST.md`) - the ~6-week clock. The connect-flow
   code (state/PKCE handling against `tenant.google_auth_attempts`) is the next slice after
   `tenancy.py`, but it cannot be exercised against real Google sign-in until that clock
   finishes.
4. **A new, separate console entry point** (or a mode switch on the existing one) that resolves
   the caller's account from the chosen auth system instead of IAP's single hardcoded identity -
   not started.
