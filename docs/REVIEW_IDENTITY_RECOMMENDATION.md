# Recommendation: recording authenticated review decisions the worker can verify but not forge

Status: **recommendation only.** Nothing here is implemented, and no credential or permission is
changed. This closes the open question left by the review-persistence milestone: a reviewer email
stored in a writable Sheet is not proof of an authenticated human decision. Enabling the review gate
stays blocked until this (or an equivalent) is in place.

## The problem, precisely

The Sheet is reached through **one shared OAuth credential** — the founder's Google account, refresh
token in Secret Manager `google-signin-token` (`outreach/google_auth.py`) — used by the **worker**,
the **console** and any local **script**. Consequences:

- Any holder of that credential can append (and edit) rows in the `Reviews` tab.
- The `Reviewer` column is a string the writer chose. It is not evidence that an authenticated human
  made the decision. Only the console derives the reviewer from IAP, but once the row is written it
  is indistinguishable from one the worker or a script wrote.

So today the worker (the enforcer, `job_draft.create` / `is_reviewed`) both **reads** reviews and
**could fabricate** them, and so could any script. We want: **the console records an authenticated
decision; the worker can verify it; the worker cannot forge one.**

## Why HMAC is not enough, and what to use

HMAC (a shared secret) is symmetric — whoever can verify can also sign, so if the worker could
verify it could forge. The property we need (verify without forge) requires an **asymmetric
signature**: the console signs with a **private** key only it holds; the worker verifies with the
**public** key, which is safe to distribute. Recommend **Ed25519** (small keys and signatures, in
`cryptography`, already a transitive dependency of the Google libraries; confirm before relying on
it).

## Design

**Recording (console, after IAP authentication).** The console already knows the authenticated
reviewer (`g.email`, IAP-verified). On confirm/reject it:

1. builds the canonical payload over the fields the review is already bound to —
   `review_id | fingerprint | reviewer | decision | reviewed_at` (the same fields the gate checks);
2. signs that payload with the **private** signing key (read from a secret only the console can
   access);
3. writes the row with a new **`Signature`** column (base64 Ed25519 signature).

**Verifying (worker, at the approval gate).** `is_reviewed` / `enforce`, after selecting the latest
row for the review id, additionally:

1. recomputes the canonical payload from the row's own fields;
2. verifies the `Signature` against it with the **public** key;
3. treats a row with a missing or invalid signature as **not a valid review** (fail-closed →
   blocks approval). The worker holds only the public key, so it cannot produce a valid signature
   and therefore cannot forge an approval. A script using the shared OAuth can still write a row,
   but cannot sign it, so its row fails verification and is ignored.

This slots into the existing seam: the store already isolates read/write, `enforce`/`is_reviewed`
already recompute the fingerprint, and the Reviews schema is already exact — the change is one more
column and one signature check on each side. The console's write path signs; the worker's verify
path checks; the `MemoryReviewStore`/`JsonFileReviewStore` used in tests can carry the same column.

## What it does and does not protect

- **Prevents forgery of an approval** by the worker or any shared-OAuth script: without the private
  key, no valid confirmation can be manufactured. This is the property that was missing.
- **Binds the decision to the authenticated reviewer**: the reviewer email is inside the signed
  payload, so a valid signature attests "the console, acting for this IAP-verified reviewer, made
  this decision."
- **Does NOT prevent denial**: a party with write access could still delete or overwrite rows in the
  tab, which can only *block* approval (a deleted/garbled row fails verification → fail-closed), never
  grant it. If denial matters, add the optional hardening below.
- **Does NOT change** the non-atomic revocation window, drafting/sending being disabled, or the
  follow-up block.

## Required credential / permission changes (identify only — do not apply here)

1. Generate an Ed25519 keypair offline.
2. Store the **private** key as a new Secret Manager secret (e.g. `review-signing-key`) and grant
   `roles/secretmanager.secretAccessor` to the **console's service account only** (`outreach-console@…`)
   — explicitly NOT the worker's service account and NOT the shared founder OAuth.
3. Give the **worker** the **public** key (an env var or a non-sensitive secret; it need not be
   protected).
4. Add the `Signature` column to the `Reviews` schema (exact header; the migration dry-run already
   reports a header mismatch and describes the manual column addition — this is one more column).
5. **Optional hardening against denial/tamper:** put the `Reviews` tab in its own spreadsheet (or use
   Sheet-level permissions) so only the console's identity can write it and the worker is read-only.
   This complements the signature (which already prevents forgery) by also preventing deletion by
   other credential-holders.

## Smallest viable step

Items 1–4 (asymmetric signature with a console-only private key) are the smallest change that
achieves "verify without forge," and they do not require moving reads off the shared OAuth. Item 5 is
a further, independent hardening. None of this should be built or applied until the founder approves
the key management and the schema change, and enabling the review gate remains blocked until it is.
