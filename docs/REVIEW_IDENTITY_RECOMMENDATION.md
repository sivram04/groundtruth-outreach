# Recommendation: recording authenticated review decisions the worker can verify but not forge

Status: **recommendation only.** Nothing here is implemented, and no credential or permission is
changed. This closes the open question left by the review-persistence milestone: a reviewer email
stored in a writable Sheet is not proof of an authenticated human decision, and — corrected below —
a per-row signature alone does not protect the *latest* decision. Enabling the review gate stays
blocked until a design like this is in place and approved.

## The problem, precisely

The Sheet is reached through **one shared OAuth credential** — the founder's Google account, refresh
token in Secret Manager `google-signin-token` (`outreach/google_auth.py`) — used by the **worker**,
the **console** and any local **script**. So any holder of that credential can append, edit, delete
and reorder rows in the review store, and the `Reviewer` column is just a string the writer chose.
The gate must be able to trust the **current** decision for a candidate; today nothing stops another
party from manufacturing or manipulating one.

## Correction: signatures alone do NOT protect the latest decision

An earlier version of this document proposed per-row Ed25519 signatures and claimed that deletion
"can only block approval." **That is wrong.** A signature proves a given row was produced by the
console, but the current decision is *whichever row wins*, and an attacker who can write the store
can change which row wins **without forging anything**:

- **Deletion to expose an older decision.** Reviewer confirms (signed), later rejects (signed).
  Delete the rejection row and the newest remaining row is the *genuinely signed* older
  confirmation — approval is now shown as current. No forgery needed.
- **Replay.** Copy the old, genuinely signed confirmation and append it again after the rejection.
  Its signature verifies; if "latest" is by row position, the replayed confirmation wins.
- **Reordering.** If "latest" is by row order, moving rows changes the winner.

So per-row signatures must be combined with (a) control over **who can write the store at all** and
(b) an ordering the signature itself commits to. The primary control is write-exclusivity.

## Design that protects the latest decision

**1. A separate review spreadsheet the worker cannot write with ANY credential it holds.**
Put the `Reviews` tab in its own spreadsheet, **owned by the console's service account**
(`outreach-console@…`). Grant:

- **console SA:** editor (the only writer);
- **worker:** viewer (read-only);
- **the founder's Google account:** viewer at most — **not editor.**

The last point is the crux the founder raised: the worker holds the shared founder OAuth
(`google-signin-token`), so a read-only worker service account is **not** sufficient by itself — if
the founder's account can edit the review spreadsheet, the worker can too, through that token.
Therefore the review spreadsheet must be one the founder's account cannot edit (owned by the console
SA, founder shared as viewer). Every credential the worker can present — its own SA and the shared
founder OAuth — is then read-only to the review store. Only the console SA can append, and it never
deletes or rewrites (append-only), so no other party can delete a rejection, replay a confirmation,
or reorder rows.

**2. A monotonic sequence per review id, inside the signed payload.** Each decision the console
writes carries a per-`review_id` sequence number `seq` (1, 2, 3 …), and the console signs
`review_id | seq | fingerprint | reviewer | decision | reviewed_at` with an Ed25519 **private key
only the console can read**. The worker selects, for a review id, the row with the **highest signed
`seq`** whose signature verifies — not the last row by position. This makes ordering an attested
property, not a positional accident.

**3. The worker verifies with a public key whose integrity is protected.** The public key need not
be secret, but it must not be swappable by a writer: deliver it to the worker as **trusted
configuration** (an env var or a secret the worker reads), **never from the review store**. If the
public key came from the writable store, a writer could substitute their own key and forge.

## How this handles each attack

- **Forgery of a new decision:** impossible without the console's private key (worker holds only the
  public key). ✓
- **Deletion of the latest (rejection):** the worker and the shared OAuth are read-only on the
  review spreadsheet; only the console SA can delete, and it does not. An outsider cannot remove the
  rejection to expose an older confirmation. ✓
- **Replay of an old signed confirmation:** an outsider cannot append at all (read-only); and even
  an accepted append would carry a *lower* `seq` than the rejection, so highest-signed-`seq` still
  selects the rejection. ✓
- **Reordering:** the winner is chosen by signed `seq`, not row position, so moving rows changes
  nothing. ✓
- **Public-key substitution:** the key is trusted config, not read from the store. ✓

**Remaining, acknowledged:** the console SA is trusted — it is the authenticated-review writer, so
this design assumes the console service is not compromised. Denial is still possible only by the
console SA (the sole writer); the worker/shared-OAuth cannot even deny by deletion. A compromised
console private key would allow forgery until rotated; standard secret hygiene (rotation, restricted
access) applies. None of this weakens the fail-closed default: any unverifiable or missing current
decision blocks approval.

## Required credential / permission changes (identify only — do not apply here)

1. Create a **new, separate spreadsheet** for reviews, **owned by the console service account**.
2. Share it: console SA = editor; worker identity = viewer; **founder account = viewer, not
   editor** (so the shared `google-signin-token` cannot write it). Confirm no other credential the
   worker holds has edit access.
3. `SheetReviewStore` gains a `spreadsheet_id` for the review spreadsheet (already a constructor
   parameter) pointed at the new file; the schema gains **`Seq`** and **`Signature`** columns (exact
   header; the migration dry-run already reports header mismatches and would describe the manual
   change).
4. Generate an Ed25519 keypair offline. Store the **private** key as a secret readable only by the
   console SA (`roles/secretmanager.secretAccessor` to the console SA only). Deliver the **public**
   key to the worker as trusted configuration (env var or a secret), not via the review store.
5. Console write path signs `review_id | seq | fingerprint | reviewer | decision | reviewed_at` and
   sets `seq = 1 + max(seq for this review_id)`; worker verify path (`is_reviewed` / `enforce`)
   selects the highest signed `seq` and verifies its signature, treating any missing/invalid
   signature or unknown key as no valid review (fail-closed).

## Smallest viable step

Write-exclusivity on a separate spreadsheet (items 1–2) is the single most important change: it
alone stops deletion, replay and reordering by anyone other than the console. The signed monotonic
`seq` (items 3–5) hardens ordering and binds the authenticated reviewer, and is what lets the worker
*verify* rather than merely *trust* the store. Neither is built or applied here; enabling the review
gate remains blocked until they are approved and in place.
