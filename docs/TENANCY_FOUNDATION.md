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

**Slice 2, done**: `migrations/tenant/0003_account_sheet.sql` adds a `sheet_id` column to
`tenant.accounts` - one connected Sheet per account (not per `tenant.projects` row; the founder's
actual use case is one Sheet per purpose, and each purpose is already its own account).
`outreach/tenancy.get_sheet_id`/`set_sheet_id` read/write it. `outreach/tenant_sheet.ensure_sheet
(api, conn, account_id, *, link_sheet_id=None, title=None)` is the actual provisioning: an account
that already has a Sheet keeps it (idempotent - never silently swaps a Sheet out from under data
already written to the old one); with no `link_sheet_id`, it creates a brand-new blank
spreadsheet via the Sheets API and stores its id; with one, it verifies the account's Google
credential can actually open that Sheet (a real read, not just trusting the string) before
storing it, and refuses (`tenant_sheet.LinkRefused`) if it can't. Both paths supported, since the
founder/friend's existing accounts want to link an existing Sheet with real data in it, while a
future new signup would want one auto-created. 10 new tests, offline against a fake Sheets client
and fake DB cursor. Full suite 1316 pass.

**Slice 3, done**: `outreach/tenant_google.sheets_api(connector, conn, account_id)` replaces
`founder_credentials()` for the per-account path - looks up the account's own `drive`-kind
connection (`tenancy.latest_connection_id`, added for this), asks the already-built `Connector`
for a fresh access token (it already refreshes and, on `invalid_grant`, revokes a dead
connection), wraps it in a bare `Credentials(token=...)` and builds a Sheets client authorized
as that account - never the founder.

Fixed a real gap found wiring this up: the `drive` connection kind in `google_connect.SCOPES`
only ever requested `spreadsheets.readonly`. The outreach engine *writes* to the Sheet (lead
status, research, drafts, tracking) - read-only would have silently blocked every one of those
writes the first time a real account tried to use it. Widened to full `spreadsheets`, matching
what the single-tenant founder OAuth (`outreach/signin.py`) already requests for exactly this
reason. 2 new tests (no connection yet refuses with `NotConnected`; the right account, connection
and scope are asked for, and the returned token reaches the Sheets client). Full suite 1318 pass.

**Slice 4, done**: `job_check.run`, `job_research.run` and `job_profile.run` now take optional
`api`/`sheet_id` keyword arguments, defaulting to the founder's own singleton/`SHEET_ID` exactly
as before - `main`'s scheduled jobs are unaffected. `job_auto.run` passes the same pair to all
three stages it chains. A caller that has both pieces from slices 2 and 3 (`tenant_google.
sheets_api`, `tenant_sheet.ensure_sheet`) can now run the whole check/research/profile pipeline
against one connected account's own Sheet - never the founder's - just by passing those two
values through. 4 new tests assert the values actually reach `append_run` and every chained
stage, not just that the parameters exist. Full suite 1322 pass.

**`job_draft.py` deliberately NOT touched in this slice**: unlike the three autorun jobs above,
it's the console-route-driven module behind drafting/approval (handbook lookups, quote gating,
Gmail draft creation) and references `SHEET_ID` directly in several smaller helpers
(`_records`, `_suppressed`, `_call_effect`, `_read`) rather than through `Store`/`Tab` alone -
a bigger, separate piece of surface than the three CLI-shaped jobs, worth its own slice.

**Slice 5, done**: `job_draft.py`'s own Sheet-reading helpers (`_records`, `_suppressed`,
`_call_effect`, `_read`) and `handbook_store.active`/`set_active` now take the same optional
`sheet_id`, defaulting to `SHEET_ID` - `main` unaffected. Threaded through every public entry
point (`previews`, `create`, `create_edited`, `reconcile`) and the internal handbook lookups
(`_handbook`, `project_handbook`, `_revalidated`). Together with slices 2-4, the entire
draft-and-approve path - not just the three autorun jobs - can now run against one connected
account's own Sheet and Google credential instead of the founder's. 5 new tests prove each
helper actually reads the given `sheet_id`. Full suite 1327 pass.

**Slice 6, done**: `outreach/tenant_google.gmail_api(connector, conn, account_id)` is the Gmail
twin of `sheets_api` - looks up the account's own `gmail`-kind connection (already granted
`gmail.compose`) and builds a Gmail client authorized as that account, never the founder. Both
credential functions now share one `_client()` helper parameterized by kind/scope/service/
version, so the two paths can't drift apart. `outreach/send.py` - the one sanctioned send path -
gets the same `sheet_id` threading as everything else (`_find`, `_set_status`,
`send_created_draft`), defaulting to `SHEET_ID` so `main` is unaffected.

With this, every piece needed to run the full engine for one connected account exists: its own
Sheet (`tenant_sheet.ensure_sheet`), its own Sheets credential (`tenant_google.sheets_api`), and
its own Gmail credential (`tenant_google.gmail_api`) - with check/research/profile/draft/send all
able to take them instead of the founder's singletons. 6 new tests (gmail_api needs a connection
first; asks for the right connection/scope/service; a gmail-kind connection correctly cannot
satisfy a Sheets request; `send_created_draft` actually works end-to-end against an explicit
`sheet_id`, not just that the parameter is accepted). Full suite 1331 pass.

**Slice 7, done**: `tenant_console.py` now has real routes wiring the engine to a signed-in
session, all gated by `@_signed_in` and resolving everything from the ACTIVE account - never the
founder:

- `POST /api/account/sheet` - link an existing Sheet (verified openable with this account's own
  credential before it's trusted, via `tenant_sheet.ensure_sheet`) or create a new one with no
  body; idempotent, matching `ensure_sheet`'s own guarantee.
- `GET /api/account/sheet` - the account's current `sheet_id`, or `null`.
- `POST /api/jobs/auto` - check/research/profile for this account's own leads (`job_auto.run`
  with this account's `api`/`sheet_id`).
- `POST /api/jobs/draft/preview` / `POST /api/jobs/draft/create` - preview and create Gmail
  DRAFTS for this account (`job_draft.previews`/`job_draft.create`), using this account's own
  Sheets AND Gmail credentials.

`tenant_google.NotConnected`, `tenant_sheet.LinkRefused` and `job_draft.DraftBlocked` all surface
as 400s through these routes rather than 500s.

**Deliberately no `/api/jobs/send` route.** `outreach/send.py` - the one sanctioned send path -
may only be imported by `outreach/console.py` (a human's "Approve and send" click) and
`outreach/auto_send.py` (the scheduled, cap-limited drip), both pinned by `tests/test_no_send.py`
per the founder's own explicit decision recorded in `CLAUDE.md`: "nothing else may send... ever,
without the same kind of explicit founder decision these two had." Wiring a third caller in here
quietly, just because the rest of the engine was being threaded through anyway, would have
broken that pinned invariant (confirmed: adding the import made `test_no_send.py` fail
immediately). Actually sending on behalf of a connected tenant account is held back as its own,
separate decision - not bundled into this slice. A local test
(`test_there_is_no_jobs_send_route`) pins the same thing inside `tenant_console.py` itself, so a
future change can't reintroduce it without that test failing too.

9 new tests (sheet create/link/refuse-unreadable; `jobs/auto` requires a sheet first and then
runs against this account's own `api`/`sheet_id`, not the founder's; the no-send-route pin).
Full suite 1339 pass.

## Where this leaves the whole multi-tenant engine effort

Every library-level piece of the single-tenant engine now has a tenant-scoped twin, and
`tenant_console.py` exposes the read/draft half of it over real HTTP routes to a signed-in
session:

| Single-tenant (main)                          | Multi-tenant (this branch)                          |
|------------------------------------------------|------------------------------------------------------|
| `outreach/sheet.py`'s hardcoded `SHEET_ID`     | `tenant_sheet.ensure_sheet` (create or link, per account) |
| `google_auth.founder_credentials()` (Sheets)   | `tenant_google.sheets_api(connector, conn, account_id)` |
| `gmail_drafts.client()` (Gmail)                | `tenant_google.gmail_api(connector, conn, account_id)` |
| `job_check/research/profile/draft.run(...)`    | same functions, now accept `api`/`sheet_id` (slices 4-5) |
| `console.py` (IAP, one hardcoded identity)     | `tenant_console.py` (real sign-in, multi-account, isolated by RLS) |
| `send.py` (console click or `auto_send.py`)    | **not wired for tenants - explicit founder decision needed** |

## Update, 2026-10-12: real Cloud KMS wiring, proven live

Provisioned a fresh KMS key for this work rather than reusing the abandoned codex branch's
(`outreach-staging/google-refresh`, left untouched): `outreach-tenant/google-refresh`
(`projects/lakshyaa-outreach/locations/us-central1/keyRings/outreach-tenant/cryptoKeys/
google-refresh`, `GOOGLE_SYMMETRIC_ENCRYPTION`, 90-day rotation). `google-cloud-kms` and
`grpcio`/`grpcio-status`/`grpc-google-iam-v1` installed into the shared venv (`google-crc32c`
was already there) - the plain `pip install -r requirements-tenant.txt` hit pip's
`resolution-too-deep` error in this environment; installing each package individually with
`--no-deps`, pinned, worked around it without touching `requirements-tenant.txt` itself (still
correct, just not what made this particular install succeed today).

Ran `KMSVault`'s real `encrypt`/`decrypt` directly against the new key (not a fake client this
time): encrypted a test refresh token, decrypted it back to the exact original, and confirmed
the AAD binding actually enforces account isolation - decrypting the same ciphertext under a
different `account_id` was refused (`Refused`) rather than silently succeeding. Test data was
never written to the real database, only exercised in-memory.

One environment wrinkle worth recording: this machine's ambient Application Default Credentials
have `quota_project_id` set to an unrelated project (`jobradar-pilot-20261009`, from other work
on this shared machine), so the KMS client had to be built with an explicit
`client_options={"quota_project_id": "lakshyaa-outreach"}` for this one-off test. Production
code never hits this: `KMSVault._get_client()` builds a plain `kms_v1.KeyManagementServiceClient()`
with no options, which is correct once deployed under a Cloud Run service account scoped to
`lakshyaa-outreach` - this wrinkle was purely an artifact of testing from a shared dev machine
with other unrelated GCP projects' ADC state, not something the application code needs to
handle.

## Update, 2026-10-12: the OAuth client exists, and a real frontend was built

Founder completed the Cloud Console side (new "Google Auth Platform" UI, successor to the old
"OAuth consent screen" page): Branding filled in, Audience set to External/Testing with 3 test
users (the founder, their own personal Gmail, and a friend's), and a Web OAuth client created
under "Clients" named `outreach-tenant-console`, redirect URI
`https://outreach-tenant-console-30387157876.us-central1.run.app/api/tenant/google/callback`
(Cloud Run URLs in this project are deterministic - `<service>-30387157876.us-central1.run.app`
- so the redirect URI could be fixed before anything was deployed). Client ID and secret stored
in Secret Manager as `tenant-oauth-client-id`/`tenant-oauth-client-secret` (never typed into
chat - founder created them directly in the Secret Manager web UI). Gmail API and Sheets API
were already enabled on the project from the single-tenant work.

Also built a real frontend: `tenant-console/`, a Vite + React + TypeScript app mirroring
`console/`'s own conventions and design tokens, giving `tenant_console.py`'s JSON API an actual
UI - sign in with Google (Identity Services), switch between several signed-in accounts, connect
Gmail/Sheets, create-or-link a Sheet, run check/research/profile, and preview a draft email. Two
small backend additions to serve it: `GET /api/config` (the OAuth client id only - public, safe
to expose, unlike the secret) and `GET /`/`GET /assets/<path>` serving the built app, the same
pattern `console.py` already uses.

**A real bug was found and fixed by actually running this**, not just by unit tests: a relative
`static_dir` (exactly the shape the real deploy passes, e.g. `"tenant-console/dist"`) made
`send_from_directory` raise `NotFound` internally even though the file existed and the route
matched - every page request 404'd. Fixed by resolving `static_dir` to an absolute path; a
pinned regression test now covers this exact shape. Verified end-to-end against the real Flask
app (not a fake): built the frontend, ran it with a throwaway local dev server (a fake DB cursor,
a dev-only credential verifier accepting any string - clearly marked, never shipped), confirmed
the sign-in page renders, `POST /api/session/google` round-trips into a real session, the
Dashboard renders every section, and an unconfigured connector's 503 correctly reaches the UI.

**What's still needed before an actual signed-in person (the founder's friend, or the founder's
own second account) could use this for real, in order**:
1. ~~An actual OAuth client in Testing mode~~ - **done above.**
2. **`tenant_console.py` deployed somewhere real**, given a real `conn_factory` pointed at
   `outreach-tenant` (host `35.253.52.165`, root password in Secret Manager) instead of the fakes
   every test uses, and `GOOGLE_OAUTH_CLIENT_ID`/`_SECRET`/`_REDIRECT_URI`/`TENANT_TOKEN_KMS_KEY`
   now real values (`tenant-oauth-client-id`/`tenant-oauth-client-secret` secrets, the redirect
   URI above, and the KMS key name above) so `google_connect.from_environment()` builds a real
   `Connector` instead of `None`. Needs a production entrypoint (`_deployed()`-equivalent, like
   `console.py`'s), a Dockerfile building both the frontend and the Python service, and a deploy
   script - not yet written.
3. **The founder's own explicit decision on sending for tenant accounts** - whether/how
   `send.py` gets a third sanctioned caller, and what guard(s) it needs beyond what `console.py`
   and `auto_send.py` already have (the daily cap, suppression, call-log checks already live
   inside `send_created_draft`/`job_draft.create` either way).
4. **Per-account settings/company identity** - **done, 2026-10-12**. `outreach/company_settings.
   py`'s `overrides()`/`set_field()` now take the same `sheet_id` as every other engine module
   (defaulting to `SHEET_ID`, `main` unaffected), so sender name/email/product name/daily cap can
   be stored and read per connected account's own Sheet instead of one shared global. 4 new tests
   prove the given `sheet_id` actually reaches the Sheets calls and that two accounts' stored
   identities never mix. Full suite 1342 pass. Not yet wired into a `tenant_console.py` route -
   no UI/API surface exists for a signed-in account to set its own identity yet (library-level
   piece only, same order as everything else in this doc).
5. **Follow-ups, sync/reply handling, tracking, calls, A/B tests - checked, 2026-10-12, no code
   needed.** `outreach/sync.py` and `tracking_job.py` already accept an injected `store=None ->
   Store()`; since `Store` already takes `sheet_id` (slice 1), a caller can already do
   `sync.run(store=Store(api, sheet_id=...), gmail=...)` or the same for `tracking_job.run` with
   no change to either module - every existing test for both already proves the injection point
   works (they substitute a `MemoryStore`, and a real per-account `Store` satisfies the identical
   interface). `outreach/calls.py` and `outreach/experiments.py` have no Sheet/API access
   whatsoever - pure functions over data their caller already read, so there is nothing in them
   to thread at all.
