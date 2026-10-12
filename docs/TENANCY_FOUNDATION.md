# Multi-tenant foundation: what this branch is and isn't

Status: engineering started 2026-10-10, merged into `main` 2026-10-10 (the `multi-tenant` branch
is fully merged; its worktree can be removed). As of 2026-10-11, **a real Postgres database exists
and tenant isolation is proven against it, live** - see the update below. Still not deployed
anywhere; `main`'s existing single-tenant console is completely unaffected and remains what's
actually live for real users.

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

## Update, same day: the connect flow itself

`outreach/google_connect.py` ports that same prior attempt's `Connector`/`KMSVault` classes -
also sound, reviewed design (PKCE, state stored only as a hash, redirect-URI pinned to the exact
HTTPS callback path, scope-grant verified against what was actually requested, the connected
identity read from Google's own signed ID token and checked against the nonce from `begin`, and
KMS ciphertext bound via AAD to the exact account+kind+subject it was encrypted for, so it can
never be replayed into a different row). Adapted to call `tenancy.py`'s functions (added this
same session: `create_auth_attempt`, `consume_auth_attempt`, `get_connection_record`,
`revoke_connection`) instead of a connection-pool-backed store object, and to this branch's
simpler schema - a connection that fails refresh (Google's `invalid_grant`) is deleted outright
rather than marked `RECONNECT_REQUIRED` (a soft-disabled audit row the reference schema has and
this one doesn't yet).

13 new tests, offline, against a fake DB cursor, a fake HTTP post, and a fake ID-token verifier -
proving the security-relevant branches directly: a state can never be reused, an expired attempt
is refused, a mismatched nonce is refused, an under-granted scope is refused, an unverified email
is refused, and a `invalid_grant` refresh revokes the connection rather than retrying it silently.
Full suite 1278 pass.

**Still not done**: `KMSVault` itself (the real Cloud KMS calls) has no direct test yet - every
test above injects a trivial fake vault, proving `Connector`'s logic but not KMS's actual
encrypt/decrypt request shape. Worth a focused test with a fake low-level KMS client before this
goes anywhere near a real key.

## Update, same day: a real, working sign-in - today, no verification wait

`outreach/tenant_console.py` is the account-aware entry point, deliberately separate from
`outreach/console.py` (IAP-gated, one hardcoded founder identity - wrong model for arbitrary
external users). It splits two OAuth concepts that are easy to conflate:

- **Sign-in** ("who is this person") uses Google Identity Services: the browser's "Sign in with
  Google" button hands the backend a signed credential JWT directly - no OAuth redirect, no
  restricted scope, approved for any app instantly. `POST /api/session/google` verifies it and
  resolves/creates the account (`tenancy.resolve_identity`), `GET /api/session` reads the signed
  cookie, `POST /api/session/logout` clears it. **This works today** - nothing here is blocked
  on Google's verification.
- **Connect** ("may this app read/draft in Gmail or Drive") is the restricted-scope flow from
  `google_connect.py` - `POST /api/connections/<kind>/start` and
  `GET /api/tenant/google/callback`, both signed-in-only. With no `connector` configured yet
  (true today - no OAuth client exists), they correctly refuse with 503 rather than crash, so
  there is nothing left to wire the day verification clears.

10 new tests (Flask test client, fake DB cursor, fake credential verifier, fake connector) -
sign-in creates an account, a repeat sign-in with the same identity resolves to the same one, an
invalid credential is refused with no session created, connect routes require sign-in, and the
no-connector-yet 503 path. Full suite 1299 pass.

## Fixed, same day: RLS was defined but never activated

Self-review (prompted by the founder asking "what about tenant isolation?") found that
`tenancy.py` never actually turned on the RLS policies the migrations define. The policies read
`current_setting('app.tenant_id', true)`; nothing in this module ever called
`set_config('app.tenant_id', account_id, true)` to set it. Depending on how the runtime database
role ends up configured, that meant either every RLS-protected query would return zero rows (a
restricted role - fails closed, but simply broken) or RLS would be silently skipped entirely (an
owner/bypass role), leaving this module's own `WHERE account_id = ...` filters as the *only*
thing preventing cross-tenant access - no defense in depth from the database at all.

Fixed: every function touching an RLS-protected table (`google_connections`,
`google_auth_attempts` - `tenant.accounts`/`tenant.identities` are deliberately exempt, see
`_scope_to_tenant`'s docstring for why) now calls a new `_scope_to_tenant(conn, account_id)`
helper first, in the same transaction, before its query. One new pinning test asserts the
`set_config` call happens immediately before each protected query, not just that the feature
exists.

**Still not enforced by this module**: the reference design calls for two separate runtime
database roles - a narrow "registry" role for `accounts`/`identities` only, and a "data" role,
RLS-scoped, for everything else. `tenancy.py` runs every call as whatever role `conn` happens to
be opened with; it does not itself provision or select between two roles. That split needs to
exist before this goes near a real, shared database - until then, RLS is correctly *activated*
by this code, but a compromised or misconfigured connection role could still see across tenants
if it was never restricted in the first place. Database role provisioning is infrastructure
work, not something `tenancy.py` can own.

## Fixed, same day: one browser, several of your own accounts, no re-login to switch

Founder's actual use case: one person, two of their OWN Google accounts for two purposes (a
leads mailbox and a referral mailbox), plus a friend's separate account on the same product.
Each purpose gets its own account/tenant (simpler than linking one account to multiple
connections - see the superseded plan in the change history), but switching between the
founder's own two accounts in one browser used to mean logging out and back in every time.

`tenant_console.py`'s session now holds a MAP of every account signed into THIS browser
(`{account_id: {email, name, provider_subject}}`) plus which one is active, instead of a single
value:
- Signing into a new account adds it to the map and makes it active - any other account already
  signed in in this browser stays signed in too.
- `POST /api/session/switch` makes a different already-signed-in account active with no
  re-authentication - and can only switch to an account this browser already has a credential
  for, so it can never activate an account nobody in this browser ever actually signed into.
- `POST /api/session/logout` takes an optional `account_id` (sign just that one out, falling back
  to another still-signed-in account if any remain) or `{"all": true}` (clear everything).
- The connect routes (`start`/`callback`) always act on whichever account is currently active.

This is a client-side convenience only - **it does not relax tenant isolation at all**. Every
request still resolves to exactly one active `account_id`, and that's still the only id
`_scope_to_tenant` ever sets for that request's RLS scope. Holding several accounts in one
session cookie just avoids re-authenticating to switch which one is active.

6 new tests (sign into two accounts, switch without re-auth, refuse switching to an account never
signed into in this browser, logout-one vs. logout-all, connect routes follow the active
account). Full suite 1306 pass.

## Update, 2026-10-11: a real Postgres database exists and isolation is proven live

Reusing `outreach-staging` (the old codex work's instance) turned out not to be worth it: it
carries leftover automation (a cost-control job auto-stopping the instance based on a label whose
target timestamp was a week in the past) that fought every attempt to start it for long enough to
even apply a schema - four separate attempts, via both `gcloud` and the Cloud Console UI, all lost
the race before a change could be saved. Rather than keep fighting someone else's stale automation,
provisioned a **new, clean instance instead**: `outreach-tenant` (Postgres 17, `db-f1-micro`,
`us-central1`, `--edition=ENTERPRISE` - the org's default edition for new instances requires a
larger minimum tier, so edition had to be set explicitly to get the cheap tier). No leftover
automation, no race.

Applied both migrations to it directly (`migrations/tenant/0001_registry_and_projects.sql`,
`0002_google_connections.sql`) - confirmed via `information_schema`: schema `tenant` with tables
`accounts`, `identities`, `projects`, `google_auth_attempts`, `google_connections`, exactly as
expected. Then ran `tenancy.py`'s own real functions against this real database (not a fake
cursor): created an account, confirmed a repeat sign-in resolves to the same one, confirmed a
second identity gets a separate account, round-tripped an encrypted connection through a real
write and read, and - the one that actually answers "how does tenant isolation work" - confirmed
the second account **cannot read the first account's connection**, enforced by the RLS policy
actually running against real Postgres, not a test double. Test data cleaned up afterward.

The instance is currently **left running** (founder's choice, small ongoing cost at this tier) -
root password is in Secret Manager as `outreach-tenant-root-password`, never written to this repo
or shown in plaintext in chat. `outreach-staging` (the old instance) was left alone, untouched,
still carrying its own stale automation - not part of this going forward.

**Still needed before this is usable by an actual signed-in person:**
1. **Real Cloud KMS wiring** for the refresh-token ciphertext (currently every test and this
   real-DB check used an injected fake encrypt/decrypt pair - `KMSVault`'s real Cloud KMS calls
   have never been exercised against an actual key).
2. **An actual OAuth client.** Corrected understanding (see `docs/OAUTH_VERIFICATION_CHECKLIST.md`
   on `main`): the founder's real near-term need is 2 known people (the founder + one external
   friend), which fits inside Google's unverified-app Testing-mode cap of 100 users - **no
   verification clock, no CASA, no cost, no wait**. Just needs the OAuth consent screen set up in
   Testing mode and a client ID/secret created (steps 1-7 in that doc).
3. **`tenant_console.py` needs to actually be deployed somewhere** and given a real `conn_factory`
   pointed at `outreach-tenant` (connection details: host `35.253.52.165`, the root password
   above) instead of the fakes every test uses - it is still not reachable by anyone right now.

## Update, 2026-10-11: porting the single-tenant outreach engine itself, started

Everything above is the account/tenant layer only - sign-in, connect, isolation. Until now it
had **zero connection** to the actual outreach engine (leads, research, drafting, sending,
tracking), which still only existed in its single-tenant form on `main`, reading and writing one
hardcoded Google Sheet (`outreach/sheet.py`'s module-level `SHEET_ID`) through one hardcoded
Gmail/Sheets credential (`outreach/google_auth.py`'s `founder_credentials()`). Founder's
instruction: port that engine so each connected account gets its own Sheet and its own Gmail,
with the same capabilities as today. Isolated on branch `multi-tenant-engine`, worktree
`D:\lakshyaa-outreach-engine`.

Checked first whether this is a small or a large port: `Store`/`Tab` (the only code that reads or
writes the Sheet) already take `api` as a constructor parameter rather than building one
internally, and the job modules (`writer.py`, `drafting.py`, `research.py`, `calls.py`, etc.) are
already storage-agnostic pure functions operating on whatever `Store`/`api` they're handed - the
single-tenant behavior comes entirely from always constructing those with the one hardcoded
`SHEET_ID`/`founder_credentials()`. So the real work is narrower than a rewrite: thread an
explicit Sheet ID and an explicit per-account Google credential through, instead of changing the
job logic itself.

**Slice 1, done**: `Store.__init__`, `Tab.__init__`, the module-level `ensure_tab()` and
`append_run()` in `outreach/sheet.py` now all accept an explicit `sheet_id`, defaulting to the
existing `SHEET_ID` constant - every internal reference to the bare constant was replaced with
`self.sheet_id` (or a threaded parameter, for the two free functions that aren't methods). `main`
is unaffected: no caller on `main` passes the new parameter, so its behavior is identical.
Full suite 1306 pass (one test helper in `test_suppression.py` constructs a `Store` via
`Store.__new__` and needed `sheet_id` added to it by hand, since that bypasses `__init__`).

**Still to do, in order**:
1. Provision/link a Sheet per connected account - store its id somewhere (`tenant.projects`
   already has a slot structurally similar to the single-tenant `handbook_doc_id` concept; needs
   a migration or a reused column).
2. Build a credentials object from a tenant connection instead of `founder_credentials()`. The
   pieces already exist: `google_connect.Connector.access_token(conn, account_id, connection_id,
   kind, required_scope)` already returns a live access token (refreshing and, on `invalid_grant`,
   revoking the connection) - a thin adapter can wrap that into something `googleapiclient.build()`
   accepts (`google.oauth2.credentials.Credentials(token=<that access token>)`), replacing
   `founder_credentials()`'s call site in `outreach/sheet.py`'s `_api()` for the per-account path.
3. Thread an explicit `(sheet_id, api)` pair through each job (`job_check`, `job_research`,
   `job_profile`, `job_draft`, sync/send) instead of each one grabbing the global singleton -
   mechanical once 1 and 2 exist, since the job functions already take `Store`/`api` as parameters.
4. Gmail drafting/sending (`outreach/gmail_drafts.py`, `outreach/send.py`) have their own
   singleton client the same way `outreach/sheet.py` does - same pattern of work, not yet touched.
