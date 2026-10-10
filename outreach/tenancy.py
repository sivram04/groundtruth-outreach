"""Account/tenant resolution and Google connections, over the schema in
``migrations/tenant/0001_registry_and_projects.sql`` and ``0002_google_connections.sql``
(ported from a prior multi-tenant attempt - see ``docs/TENANCY_FOUNDATION.md``).

Every function here takes a ``conn`` (a DB-API connection/cursor-providing object) rather than
opening one itself, matching this repo's existing convention everywhere else (``outreach/sheet.py``
takes an ``api``, never builds one internally except at the one real entry point) - so this is
fully testable offline against a fake cursor, with no real Postgres needed for the logic tests.

Token encryption is NOT implemented yet. ``save_connection``/``read_connection`` take injectable
``encrypt``/``decrypt`` callables; omitting them raises ``NotImplementedError`` rather than ever
storing a refresh token in plain text by accident.
"""

import uuid
from dataclasses import dataclass

KINDS = ("gmail", "drive")


class TenancyError(Exception):
    """A tenancy operation could not complete; nothing was written unless stated otherwise."""


def _scope_to_tenant(conn, account_id):
    """Activate the RLS policy on every tenant-scoped table (``tenant.projects``,
    ``tenant.google_connections``, ``tenant.google_auth_attempts``) for the REST of this
    transaction, by setting the session-local ``app.tenant_id`` their ``USING``/``WITH CHECK``
    clauses read.

    This is the one line every function below was missing before this was pointed out: without
    it, the policies in the migrations do nothing at all - either every query against those
    tables returns zero rows (a restricted runtime role, fails closed but is simply broken), or
    RLS is silently skipped by role privilege (a bypass/owner role), leaving this module's own
    ``WHERE account_id = ...`` filters as the *only* thing preventing cross-tenant access - no
    defense in depth from the database at all. Call this first, in the same transaction as the
    query it protects (``SET LOCAL``-style: ``set_config``'s third argument ``true`` scopes it to
    the current transaction, so it can never leak into a pooled connection's next, unrelated
    request).

    ``tenant.accounts``/``tenant.identities`` are deliberately NOT behind this (and have no RLS
    policy in the migration): resolving an identity to an account happens before the caller knows
    which tenant it is, so it cannot be tenant-scoped yet. The reference design calls this the
    registry role vs. the data role - two different runtime DB roles, the first with access to
    accounts/identities only, the second RLS-scoped to everything else. This module does not yet
    enforce that role split itself (it runs as whatever role ``conn`` was opened with); provisioning
    two separate runtime roles, and connecting as the right one for each call, is still open.
    """
    conn.cursor().execute("SELECT set_config('app.tenant_id', %s, true)", (str(account_id),))


@dataclass(frozen=True)
class Account:
    id: str
    name: str


def resolve_identity(conn, provider_subject, email, *, display_name=None):
    """The account for this signed-in Google identity, creating both on first sign-in.

    ``provider_subject`` is the STABLE identity (Google's subject claim) - never the email,
    which can change. A second sign-in by the same subject always resolves to the same account,
    regardless of any later email change.
    """
    if not provider_subject or not str(provider_subject).strip():
        raise TenancyError("a provider subject is required to resolve an identity")
    cur = conn.cursor()
    cur.execute("SELECT account_id FROM tenant.identities WHERE provider_subject = %s",
               (provider_subject,))
    row = cur.fetchone()
    if row is not None:
        return Account(id=str(row[0]), name=_account_name(cur, row[0]))

    account_id = str(uuid.uuid4())
    name = (display_name or email or provider_subject).strip()[:120] or "New account"
    cur.execute("INSERT INTO tenant.accounts (id, name) VALUES (%s, %s)", (account_id, name))
    cur.execute(
        "INSERT INTO tenant.identities (provider_subject, account_id, email) VALUES (%s, %s, %s)",
        (provider_subject, account_id, email or ""))
    return Account(id=account_id, name=name)


def _account_name(cur, account_id):
    cur.execute("SELECT name FROM tenant.accounts WHERE id = %s", (account_id,))
    row = cur.fetchone()
    return row[0] if row else ""


def save_connection(conn, account_id, *, kind, google_subject, email, scopes, refresh_token,
                    encrypt, kms_key_name):
    """Store one Google connection's refresh token, ciphertext only.

    ``encrypt`` is a required callable (plaintext bytes/str -> ciphertext bytes) - there is no
    default, so a caller that forgets to pass a real encryptor gets a loud `TypeError` at the
    call site, never a silent plaintext write. One connection per (account, kind, google_subject);
    a repeat connect for the same identity replaces the stored token (a new consent re-grants the
    same scopes, it does not create a second row to go stale).
    """
    if kind not in KINDS:
        raise TenancyError(f"unknown connection kind: {kind}")
    if not refresh_token:
        raise TenancyError("a connection needs a refresh token")
    ciphertext = encrypt(refresh_token)
    connection_id = str(uuid.uuid4())
    _scope_to_tenant(conn, account_id)
    cur = conn.cursor()
    cur.execute(
        """INSERT INTO tenant.google_connections
             (account_id, connection_id, kind, google_subject, email, scopes,
              refresh_ciphertext, kms_key_name)
           VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
           ON CONFLICT (account_id, kind, google_subject) DO UPDATE SET
             connection_id = EXCLUDED.connection_id, email = EXCLUDED.email,
             scopes = EXCLUDED.scopes, refresh_ciphertext = EXCLUDED.refresh_ciphertext,
             kms_key_name = EXCLUDED.kms_key_name""",
        (account_id, connection_id, kind, google_subject, email, scopes, ciphertext, kms_key_name))
    return connection_id


def read_connection(conn, account_id, *, kind, decrypt):
    """The decrypted refresh token for this account's connection of this kind, or None.

    ``decrypt`` is required for the same reason ``encrypt`` is in `save_connection` - no default,
    so a caller cannot accidentally treat ciphertext as a usable token.
    """
    _scope_to_tenant(conn, account_id)
    cur = conn.cursor()
    cur.execute(
        """SELECT refresh_ciphertext, google_subject, email, scopes FROM tenant.google_connections
           WHERE account_id = %s AND kind = %s ORDER BY connected_at DESC LIMIT 1""",
        (account_id, kind))
    row = cur.fetchone()
    if row is None:
        return None
    ciphertext, google_subject, email, scopes = row
    return {"refresh_token": decrypt(ciphertext), "google_subject": google_subject,
           "email": email, "scopes": list(scopes)}


# --- the OAuth connect flow's own storage (outreach/google_connect.py calls these) ----------

def create_auth_attempt(conn, account_id, provider_subject, kind, state_hash, nonce, verifier,
                        *, now, ttl_minutes=10):
    """Record one in-flight connect attempt, state/verifier never exposed again except to the
    one caller that completes it with the matching state. Also sweeps expired attempts, so the
    table never grows unbounded on abandoned flows."""
    if kind not in KINDS:
        raise TenancyError(f"unknown connection kind: {kind}")
    _scope_to_tenant(conn, account_id)
    cur = conn.cursor()
    cur.execute("DELETE FROM tenant.google_auth_attempts WHERE expires_at <= %s", (now,))
    expires_at = now + _minutes(ttl_minutes)
    cur.execute(
        """INSERT INTO tenant.google_auth_attempts
             (account_id, state_hash, provider_subject, kind, nonce, code_verifier, expires_at)
           VALUES (%s, %s, %s, %s, %s, %s, %s)""",
        (account_id, state_hash, provider_subject, kind, nonce, verifier, expires_at))


def consume_auth_attempt(conn, account_id, provider_subject, state_hash, *, now):
    """Atomically read-and-delete the matching, unexpired attempt - a state can be used at most
    once, and only by the same (account, subject) that started it. None if there is no match."""
    _scope_to_tenant(conn, account_id)
    cur = conn.cursor()
    cur.execute(
        """DELETE FROM tenant.google_auth_attempts
           WHERE account_id = %s AND state_hash = %s AND provider_subject = %s AND expires_at > %s
           RETURNING kind, nonce, code_verifier""",
        (account_id, state_hash, provider_subject, now))
    row = cur.fetchone()
    return {"kind": row[0], "nonce": row[1], "verifier": row[2]} if row else None


def _minutes(n):
    from datetime import timedelta
    return timedelta(minutes=n)


def get_connection_record(conn, account_id, connection_id, kind):
    """The raw (still-encrypted) connection record, for refreshing an access token - never
    decrypted here. None if it doesn't exist or belongs to a different account/kind."""
    if kind not in KINDS:
        raise TenancyError(f"unknown connection kind: {kind}")
    _scope_to_tenant(conn, account_id)
    cur = conn.cursor()
    cur.execute(
        """SELECT google_subject, scopes, refresh_ciphertext, kms_key_name, email
           FROM tenant.google_connections
           WHERE account_id = %s AND connection_id = %s AND kind = %s""",
        (account_id, connection_id, kind))
    row = cur.fetchone()
    if row is None:
        return None
    google_subject, scopes, ciphertext, kms_key_name, email = row
    return {"google_subject": google_subject, "scopes": list(scopes), "ciphertext": bytes(ciphertext),
           "kms_key_name": kms_key_name, "email": email}


def revoke_connection(conn, account_id, connection_id):
    """Remove a connection entirely (e.g. its refresh token was rejected - invalid_grant).

    Simpler than the reference design's RECONNECT_REQUIRED state (a soft-disabled row kept for
    audit): deleting means a disconnected/expired connection is indistinguishable from one never
    made. Revisit if an audit trail of past connections turns out to matter."""
    _scope_to_tenant(conn, account_id)
    cur = conn.cursor()
    cur.execute(
        "DELETE FROM tenant.google_connections WHERE account_id = %s AND connection_id = %s",
        (account_id, connection_id))
