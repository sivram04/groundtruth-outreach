# Reviewer identity: recording decisions the worker can verify but not forge

Status: the **signing/verification and ordering mechanism is implemented locally and tested**
(`outreach/review_identity.py`), and it is now **wired through the real application entry points**
(the draft gate, `job_draft.create`, the follow-up boundary, and the console review GET/POST) — these
deployable paths resolve one trusted identity configuration and **block when it is missing**, with no
silent fall-back to unsigned mode (see "What is implemented now"). The **permission model below is
still a recommendation** — no spreadsheet, credential, key or permission is created or changed here,
and no key or verifier/signer config is provisioned. Review-gate activation stays disabled until the
permission model is in place and approved; with no configuration present, every gated path fails
closed.

## The problem

The Sheet is reached through **one shared OAuth credential** — the founder's Google account, refresh
token in Secret Manager `google-signin-token` (`outreach/google_auth.py`) — used by the **worker**,
the **console** and any local **script**. So any holder of that credential can append, edit, delete
and reorder rows in the review store, and the `Reviewer` column is just a string the writer chose.
The gate must be able to trust the **current** decision; nothing today stops another party from
manufacturing or manipulating one, and — corrected below — per-row signatures alone do not fix it.

## Correction 1 — ownership: a service account cannot own Drive files; use a shared drive

An earlier draft said the review spreadsheet would be "owned by the console service account." That is
not possible. Per Google's documentation
(https://developers.google.com/workspace/drive/api/guides/about-shareddrives, read 2026-09-30):

- "Files in a shared drive belong to the organization, not an individual user." and "Service
  accounts ... can't own files. Instead, they must upload files and folders into shared drives."
- Shared-drive roles are `organizer`, `fileOrganizer`, `writer`, `commenter`, `reader` (the `owner`
  role is not permitted). `writer` and above can add/edit files; `commenter`/`reader` cannot.
- **Permissions are strictly expansive**: a file-level permission cannot reduce access below a
  member's shared-drive role. So write access is controlled by the **drive-level role**, not by a
  file-level override.

**Corrected design.** Put the review spreadsheet in an **organization-owned shared drive** dedicated
to reviews. Because access is strictly expansive, every credential the worker can present must be at
most `reader`/`commenter` at the **shared-drive** level:

- the **console identity**: `writer` (it uploads/appends review rows) — the only writer;
- the **worker identity**: `reader`;
- the **founder's account** (whose token the worker holds as `google-signin-token`): `reader`, **not**
  `organizer`/`writer`. This is the crux the review raised: a read-only *worker* identity is not
  enough while another credential the worker holds (the founder OAuth) can still write. The founder
  account must therefore not have a writing role on this shared drive.

With this, no credential the worker holds can write, delete or reorder the review rows; only the
console can append.

**Unverified, to confirm with the Workspace admin (I did not and cannot change or fully inspect org
config here):** (a) whether a **service account may be a member of a shared drive** with a `writer`
role in this org (the doc does not state it explicitly; the alternative is domain-wide delegation so
the console acts as a `writer` human), and (b) that the founder account can be limited to `reader` on
that shared drive given the org's sharing policies. These are read-only checks/decisions for the
admin; nothing was applied.

## Correction 2 — ordering: `max(seq)+1` is unsafe; use a signed hash chain (no counter)

`max(seq)+1` reads then writes, so two concurrent requests can both compute the same next number and
assign **duplicate** sequence numbers — an ambiguous "latest." A process-local lock does not help
across instances. There is no safe auto-increment on a bare Sheet, so **no sequence counter is
used.** Instead each decision names the **signature of the decision it supersedes** (`prev`), forming
a per-review **hash chain**:

- The current decision is the single **tip** of a single unbroken chain.
- Two decisions off the same predecessor (concurrent writes from any thread/process/instance), a
  replayed row (a duplicate signature), a cycle, or a detached branch all make the tip non-unique or
  the chain ill-formed. The worker reports **CONFLICT/TAMPERED and BLOCKS** — it never picks an
  arbitrary confirmation. (`outreach/review_identity.resolve_current`.)
- **Harmless row reordering does NOT break an intact chain.** `resolve_current` reconstructs the order
  from the `prev` links, not from where rows physically sit, so shuffling the rows of an otherwise
  intact history resolves to the same tip. Physical order is irrelevant; only a genuine fork,
  duplicate, cycle or detached branch conflicts.

Ordering is thus the chain itself, allocated safely (each decision only references what it observed),
and conflicts fail closed.

## Authenticity: sign with a private key the worker lacks

Symmetric HMAC is unusable (verify would equal forge). Each decision is signed with an **Ed25519
private key only the console holds** (`Signer`); the worker verifies with the **public key**
(`Verifier`), supplied as **trusted configuration** and **never read from the writable store**, so a
writer cannot substitute a key. The signature covers `review_id | prev | fingerprint | reviewer |
decision | reviewed_at`, so it **binds the authenticated reviewer identity and the candidate
fingerprint** to each decision, and altering any field invalidates it. The worker holds only the
public key, so it can verify but cannot forge.

## How this handles each attack

- **Forgery of a new decision:** needs the console private key → impossible for the worker/scripts.
- **Deletion of the latest (a rejection) to expose an older confirmation:** prevented by
  Correction 1 (only the console can write/delete; worker and shared OAuth are `reader`). Signatures
  alone do NOT stop this (a shorter chain still verifies) — write-exclusivity is what stops it.
- **Replay of an old signed confirmation:** the duplicate signature is detected → TAMPERED; and with
  write-exclusivity an outsider cannot append at all.
- **Concurrent conflict:** resolved by the chain (the single tip), genuine forks → CONFLICT → block.
- **Harmless reordering:** the resolver reads the `prev` chain, not physical row position, so shuffled
  but intact rows resolve to the same tip — reordering alone is not a conflict.
- **Public-key substitution:** the key is trusted config, not read from the store.

**Acknowledged residuals:** the console is trusted (it is the authenticated writer and the signer); a
compromised console private key allows forgery until rotated (standard secret hygiene). Denial is
possible only by the console (the sole writer). Fail-closed throughout: any doubt blocks approval.

## What is implemented now (local; wired through the real paths, no config provisioned)

`outreach/review_identity.py`: `Signer`, `Verifier`, `resolve_current` (chain + conflict/tamper
blocking), and `tip_signature`. The contract carries it: `record_confirmation` / `record_rejection`
accept a `signer` (the console signs and chains onto the tip); `enforce` / `is_reviewed` accept a
`verifier` (the worker resolves the signed chain); `_current_record`, `resolved_status` and the
console read-back all resolve the **same** signed chain, so a conflicted or tampered history can never
surface as current approval. The stores keep a per-review `history` for chain resolution and preserve
the existing uncertain-write handling.

**The deployable paths are now wired to one trusted identity configuration and block when it is
missing:**

- One config, two halves. The **public key** (verifier) is `settings['review_public_key']`
  (`configured_verifier`), read by both the worker gate and the console. The **private key** (signer)
  is the console-only env `REVIEW_PRIVATE_KEY` (`configured_signer_from_env`), kept out of worker
  settings — so the worker can verify but cannot sign.
- `job_draft._gate_hash`, `job_draft.create` and `followup._create` resolve the verifier and **refuse
  to issue an approval hash / create a draft / create a follow-up when it is absent** (they no longer
  call the review checks with `verifier=None`). Missing verification configuration blocks; it does not
  fall back to accepting unsigned records.
- The console GET resolves status through `resolved_status` (the signed-chain resolver), and the POST
  refuses the write with **503** when no signer is configured, then reads the result back through
  `resolved_status` — preserving the distinction between a successfully saved decision and an
  unavailable/conflicted current status ("recorded, but its current status could not be loaded").
- The unsigned `verifier=None` path remains **only** for explicitly isolated unit fixtures
  (legacy `tests/test_review_identity.py`); no deployable caller passes `None`.

Activation is still disabled and nothing is provisioned: no `review_public_key` or `REVIEW_PRIVATE_KEY`
is set in any deployable config, no key exists, the review store is the fail-closed default, and
`ENABLE_GMAIL_DRAFTS` is unset. With no configuration present, every gated path fails closed.

## Required credential / permission changes (identify only — not applied, no key generated)

1. Create an organization-owned **shared drive** for reviews and a spreadsheet in it (uploaded by the
   console identity; the SA cannot own it).
2. Shared-drive roles: console identity `writer`; worker identity `reader`; **founder account
   `reader`, not writer/organizer** (so its OAuth cannot write). Confirm no other worker credential
   has a writing role.
3. Confirm with the admin whether a service account may be a shared-drive `writer` member, or use
   domain-wide delegation for the console's writes (unverified above).
4. Generate an Ed25519 keypair (a provisioning step, not done here). Store the **private** key in a
   secret readable only by the console identity; deliver the **public** key to the worker as trusted
   config (env/secret), never via the review store.
5. Point `SheetReviewStore` at the review spreadsheet; the schema carries `Prev` and `Signature`
   columns (already in `REVIEWS_HEADER`); the migration dry-run reports the manual header change.
6. Activation (separate, after the above): configure the console with the `Signer` and the worker
   gate with the `Verifier`; keep `ENABLE_GMAIL_DRAFTS` unset.

## What the tests establish, and what they do not

`tests/test_review_identity.py` proves the **cryptographic and chain logic**: valid decisions verify
and gate; forged/altered records and wrong-key signatures are rejected; replay after rejection
blocks; concurrent/forked decisions block as conflicts; missing/invalid verification material blocks;
and a signed write still surfaces the store's uncertain-write outcome.

The **application-level** tests now exercise the same behaviour **through the real entry points**, not
just the crypto helpers (`tests/test_draft_pipeline.py`, `tests/test_followup.py`,
`tests/test_console_api.py`, using ephemeral in-memory keys from `tests/review_fixtures.py`):

- missing verifier configuration issues **no approval hash** and **blocks `create`**;
- an unsigned record and a record signed by the **wrong key** block as TAMPERED;
- a **conflicting history** blocks as CONFLICT and never shows as current approval;
- a valid **signed confirmation** gates and mints the hash; a later **signed rejection** blocks;
- the console POST refuses with **503** when no signer is configured, and reports
  recorded-but-status-unavailable when the read-back cannot be verified.

All of these are **mocked-store** tests: they establish that the application code requires and honours
one trusted identity configuration and fails closed without it. They do **not** establish the deployed
access guarantees — the shared-drive write-exclusivity (Correction 1) is a Google Workspace
configuration to verify with the admin, not something this suite can assert.

Container result (`deploy/test.Dockerfile`, `docker run --network none`): **831 Python tests passed**.
Frontend unchanged this pass; `deploy/console-test.Dockerfile` re-run for the record: **54 tests
passed**, typecheck and build clean.
