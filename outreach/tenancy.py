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


class TenancyError(Exception):
    """A tenancy operation could not complete; nothing was written unless stated otherwise."""


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
    if kind not in ("gmail", "drive"):
        raise TenancyError(f"unknown connection kind: {kind}")
    if not refresh_token:
        raise TenancyError("a connection needs a refresh token")
    ciphertext = encrypt(refresh_token)
    connection_id = str(uuid.uuid4())
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
