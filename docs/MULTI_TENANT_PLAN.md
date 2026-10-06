# Outreach console → multi-user product: what it would actually take

Status: **planning only.** Nothing here is built. This records the real work, cost and time to turn
the single-founder console into a product other people can sign up for and run with their own
Gmail, Drive and handbook — so the founder can decide the fork with the number in front of them.

Written 2026-10-06, after the founder saw the live console and asked for: (1) different users can
log in, (2) on sign-up a user connects their own email + Drive + handbook, (3) better UI, (4) KPIs.

(3) and (4) are the **polish sprint** — done/in progress separately, single-user, no architecture
change. (1) and (2) are this document: a different product.

## Where we are today (the starting point)

- **One shared Google credential.** The worker, the console and every script reach Gmail, the Sheet
  and Drive through a single OAuth refresh token (the founder's account, Secret Manager
  `google-signin-token`). There is no per-user credential.
- **One Sheet, one handbook.** The leads Sheet id and the handbook Drive doc id are configuration
  (env / settings), not per-user. The console is **read-only** by design; a test holds every
  non-review route to GET.
- **One user, gated by IAP.** The console is reachable only by `admin@lakshyaa.ai` through Identity-
  Aware Proxy. There is no account system, no sign-up, no second user.

Everything built so far (import, calls, playbook, replies, A/B, the review gate) assumes this single
tenant. Making it multi-user touches all of it.

## What multi-user self-serve requires

### 1. Accounts and login (replace IAP with a real auth system)
IAP gates one Google identity. A product needs sign-up, sign-in, sessions, password reset and an
accounts table. The Lakshyaa product already uses **Google Identity Platform** for this — the same
pattern can be reused, but it is a new service, a new data store, and a rewrite of how the console
knows who the caller is (today it reads an IAP JWT).

### 2. Each user connects their OWN Gmail and Drive (the hard part)
This is the crux and the long pole. Today the worker holds *one* OAuth token. A product needs each
user to grant access to *their* mailbox and Drive. That means an OAuth connect flow per user, tokens
stored per user, and — because reading a mailbox and creating drafts are **restricted scopes** —
Google's full verification process:

- **OAuth app verification** for restricted scopes (gmail.readonly, gmail.compose, drive): an app
  review that commonly takes **~6 weeks**.
- **A yearly CASA (Cloud Application Security Assessment)** by a Google-authorized third party, with
  an annual cost, for as long as the app uses restricted scopes.
- A published privacy policy, a verified domain, a demo video, and a security questionnaire.

Until this clears, **no one outside the founder's own Workspace org can connect their mailbox.** This
is weeks of calendar time that cannot be compressed by coding faster, and it should start early if
this direction is chosen. (Noted in the outreach research from 2026-09.)

### 3. Per-user data isolation (every "one Sheet" assumption becomes per-tenant)
- The leads **Sheet** becomes per-user (their own, created or linked at onboarding).
- The **handbook** Drive doc becomes per-user.
- The **Store** (today one Sheet behind one credential) becomes per-tenant: every read and write
  carries a tenant id, and one user can never see or write another's rows. This is a change to the
  core persistence boundary that every feature goes through.
- **Secrets and keys** become per-tenant: the review-identity signing key, tracking key, and OAuth
  tokens are all currently single-valued.

### 4. Self-serve onboarding (the founder's point #3)
A new user, after sign-up, needs to:
- **Connect their email** (the OAuth flow from §2).
- **Link their Drive / handbook** — paste or pick the doc; the console verifies it can read it.
- **Link or create their leads Sheet.**
- **Set their offer wording** and approve it.

Only §4's "link the handbook / Sheet from the screen" is small on its own — but it needs a **write
route** the read-only console does not have today, and it is pointless without §1–§3 underneath it.

### 5. The review-identity gate becomes per-tenant
The signed-review gate (shared drive + console-only Ed25519 key + worker read-only) was designed for
one tenant. Multi-tenant means per-user signing keys and per-user review stores, or a redesign.

## Honest effort and sequencing

- §1 (auth) and §3 (per-tenant Store) are **weeks** of focused build, touching every feature.
- §2 (per-user Gmail/Drive) is **~6 weeks of Google calendar time** (verification) **plus** the build
  of the connect flow, **plus** an ongoing yearly CASA cost. This gates every external user.
- §4 is small once §1–§3 exist; meaningless before.
- §5 is a redesign of work already done.

This is a **product rebuild**, not a feature. It also reverses the founder's own standing decision
("build it for myself first; decide on selling only after a proof bar — ~6%+ replies over 100+ system
drafts"), and **no system draft has been sent yet.**

## Recommendation

Do not start the multi-tenant rebuild until the single-user tool has **proven itself by sending real
outreach** (the proof bar). The one piece of §2 that has a long external clock — **Google OAuth
restricted-scope verification + CASA** — is the exception: if the founder is confident about the
product direction, *begin that application early*, because it runs for ~6 weeks regardless of code.

Concretely, in order:
1. Finish the single-user proof: provision the review-identity gate, enable drafting for the founder's
   own account, send real drafts, measure replies against the proof bar.
2. If the bar is met, **then** start the Google verification clock (§2) and build §1/§3 in parallel.
3. §4 self-serve onboarding and §5 per-tenant review last, once the foundation exists.

## Conflicts with current repository rules (not overridden here)
- **"Google Sheets is the only record. No database."** — per-tenant accounts and token storage
  effectively need a real data store; multi-tenant on a bare Sheet is not safe. This rule would have
  to be revisited for the product (it was explicitly kept for the single-user MVP).
- **"Build for self first, sell later only after a proof bar."** — multi-tenant is the "sell later"
  phase; starting it now is ahead of the bar.
- **Console is read-only.** — onboarding needs write routes, following the flag-gated, tested,
  injected-store pattern already used for import and calls.
