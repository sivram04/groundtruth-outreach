"""The per-tenant Google OAuth connect flow: PKCE + state binds one browser round trip to one
account, Cloud KMS encrypts the offline refresh token before it reaches storage, and the
connected identity is verified from Google's own signed ID token - never trusted from the
client.

Ported and adapted from a prior, far-more-divergent multi-tenant rewrite attempt
(``codex/full-outreach-product`` - see ``docs/TENANCY_FOUNDATION.md``): that implementation's
security design (PKCE, state-hash-not-state storage, redirect-URI pinning, scope-grant
verification, nonce-bound ID token check, KMS ciphertext bound to account+kind+subject via AAD)
was already sound and reviewed; this module keeps it, adapted to call ``outreach/tenancy.py``'s
functions instead of a connection-pool-backed store object, and to this branch's simpler schema
(no connection ``state`` column yet - a rejected/revoked connection is deleted outright, see
``tenancy.revoke_connection``).

The IAP-identified product user and a connected Google identity are deliberately different
concepts: IAP (or whatever replaces it) says who is using the product; this module records which
Google account they gave the product permission to read/draft through, which may or may not be
the same Google account.
"""

import base64
import hashlib
import hmac
import os
import re
import secrets
from datetime import datetime, timezone
from urllib.parse import urlencode, urlsplit

from outreach import tenancy

AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
SCOPES = {
    "gmail": frozenset({"openid", "email", "https://www.googleapis.com/auth/gmail.readonly",
                        "https://www.googleapis.com/auth/gmail.compose"}),
    # Full "spreadsheets", not "spreadsheets.readonly": the outreach engine writes lead status,
    # research, drafts and tracking back to the account's own Sheet - read-only would silently
    # block every write once this connection is actually used, matching what the single-tenant
    # founder OAuth (outreach/signin.py) already requests for the same reason.
    "drive": frozenset({"openid", "email", "https://www.googleapis.com/auth/drive.readonly",
                        "https://www.googleapis.com/auth/spreadsheets"}),
}
STATE = re.compile(r"^[A-Za-z0-9_-]{30,100}$")
KMS_KEY = re.compile(r"^projects/[^/]+/locations/[^/]+/keyRings/[^/]+/cryptoKeys/[^/]+$")


class Refused(RuntimeError):
    """A connection cannot be trusted; the message is always safe to show - never token data."""


def _digest(value):
    return hashlib.sha256(value.encode("ascii")).hexdigest()


def _aad(account_id, kind, google_subject):
    """Binds a ciphertext to exactly the row it was encrypted for - swapping it into a different
    account, kind or subject's row fails decryption rather than silently succeeding."""
    return f"outreach-google-refresh-v1|{account_id}|{kind}|{google_subject}".encode()


class KMSVault:
    """Cloud KMS envelope encryption for one refresh token at a time. A real client is built
    lazily (only when actually encrypting/decrypting), so constructing a KMSVault - and every
    offline test - never needs real GCP credentials; pass `client=` to inject a fake one."""

    def __init__(self, key_name, client=None):
        if not KMS_KEY.fullmatch(key_name or ""):
            raise ValueError("A valid Cloud KMS key is required.")
        self.key_name = key_name
        self._client = client

    def _get_client(self):
        if self._client is None:
            from google.cloud import kms_v1
            self._client = kms_v1.KeyManagementServiceClient()
        return self._client

    def encrypt(self, plaintext, account_id, kind, google_subject):
        import google_crc32c
        try:
            client = self._get_client()
            clear = plaintext.encode()
            aad = _aad(account_id, kind, google_subject)
            reply = client.encrypt(request={"name": self.key_name,
                "plaintext": clear, "plaintext_crc32c": google_crc32c.value(clear),
                "additional_authenticated_data": aad,
                "additional_authenticated_data_crc32c": google_crc32c.value(aad)},
                timeout=10)
            if (not reply.ciphertext or not reply.verified_plaintext_crc32c or
                    not reply.verified_additional_authenticated_data_crc32c or
                    reply.ciphertext_crc32c != google_crc32c.value(bytes(reply.ciphertext)) or
                    not reply.name.startswith(self.key_name + "/cryptoKeyVersions/")):
                raise Refused("Credential encryption failed.")
            return bytes(reply.ciphertext)
        except Refused:
            raise
        except Exception as exc:
            raise Refused("Credential encryption is unavailable.") from exc

    def decrypt(self, ciphertext, account_id, kind, google_subject, *, key_name=None):
        import google_crc32c
        selected_key = key_name or self.key_name
        if not KMS_KEY.fullmatch(selected_key):
            raise Refused("Stored credential key is invalid.")
        try:
            client = self._get_client()
            aad = _aad(account_id, kind, google_subject)
            reply = client.decrypt(request={"name": selected_key,
                "ciphertext": ciphertext, "ciphertext_crc32c": google_crc32c.value(ciphertext),
                "additional_authenticated_data": aad,
                "additional_authenticated_data_crc32c": google_crc32c.value(aad)},
                timeout=10)
            if not reply.plaintext or reply.plaintext_crc32c != google_crc32c.value(bytes(reply.plaintext)):
                raise Refused("Credential decryption failed.")
            return reply.plaintext.decode()
        except Refused:
            raise
        except Exception as exc:
            raise Refused("Credential decryption is unavailable.") from exc


class Connector:
    """One Google OAuth client configuration, used across every tenant's connect flow.

    `post` (an HTTP POST callable) and `verify` (an ID-token verifier) are injectable so every
    branch here is testable without a real network call or real Google keys."""

    def __init__(self, client_id, client_secret, redirect_uri, vault, *, post=None, verify=None):
        parsed = urlsplit(redirect_uri)
        if (parsed.scheme != "https" or not parsed.netloc or parsed.username or parsed.password
                or parsed.query or parsed.fragment or parsed.path != "/api/tenant/google/callback"):
            raise ValueError("Google redirect URI must be the HTTPS callback for this app.")
        if not client_id or not client_secret:
            raise ValueError("Google OAuth client credentials are required.")
        self.client_id, self.client_secret, self.redirect_uri = client_id, client_secret, redirect_uri
        self.vault = vault
        if post is None:
            import requests
            post = requests.post
        self.post = post
        if verify is None:
            def verify(token):
                from google.auth.transport.requests import Request as GoogleRequest
                from google.oauth2 import id_token
                return id_token.verify_oauth2_token(token, GoogleRequest(), self.client_id)
        self.verify = verify

    def begin(self, conn, account_id, provider_subject, kind, *, now=None):
        """Starts one connect attempt; returns the URL to send the browser to."""
        if kind not in SCOPES:
            raise ValueError("Choose Gmail or Drive.")
        now = now or datetime.now(timezone.utc)
        state = secrets.token_urlsafe(32)
        nonce = secrets.token_urlsafe(32)
        verifier = secrets.token_urlsafe(64)
        challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
        try:
            tenancy.create_auth_attempt(conn, account_id, provider_subject, kind, _digest(state),
                                        nonce, verifier, now=now)
        except Exception as exc:
            raise Refused("Google connection could not be started safely.") from exc
        query = urlencode({"client_id": self.client_id, "redirect_uri": self.redirect_uri,
            "response_type": "code", "scope": " ".join(sorted(SCOPES[kind])),
            "access_type": "offline", "include_granted_scopes": "true",
            "prompt": "consent select_account", "state": state, "nonce": nonce,
            "code_challenge": challenge, "code_challenge_method": "S256"})
        return AUTH_URL + "?" + query

    def complete(self, conn, account_id, provider_subject, state, code, *, now=None):
        """Exchanges the callback's code for tokens and stores the connection. Raises `Refused`
        (a safe message) for anything that doesn't check out - an expired/reused state, a token
        exchange failure, an ungranted scope, or an identity that fails nonce/verification."""
        if not STATE.fullmatch(state or "") or not isinstance(code, str) or not 1 <= len(code) <= 4096:
            raise Refused("The Google connection response is invalid. Start again.")
        now = now or datetime.now(timezone.utc)
        try:
            attempt = tenancy.consume_auth_attempt(conn, account_id, provider_subject, _digest(state),
                                                   now=now)
        except Exception as exc:
            raise Refused("Google connection could not be verified safely.") from exc
        if not attempt:
            raise Refused("The Google connection request expired or was already used.")
        try:
            response = self.post(TOKEN_URL, data={"code": code,
                "client_id": self.client_id, "client_secret": self.client_secret,
                "redirect_uri": self.redirect_uri, "grant_type": "authorization_code",
                "code_verifier": attempt["verifier"]}, timeout=10, allow_redirects=False)
            if response.status_code != 200:
                raise Refused("Google did not authorize the connection. Start again.")
            tokens = response.json()
            if not isinstance(tokens, dict):
                raise Refused("Google returned an invalid connection response.")
            refresh = tokens.get("refresh_token")
            encoded_identity = tokens.get("id_token")
            granted = set(str(tokens.get("scope", "")).split())
            if not isinstance(refresh, str) or not refresh or len(refresh) > 16000:
                raise Refused("Offline access was not granted. Start the connection again.")
            if not isinstance(encoded_identity, str) or not SCOPES[attempt["kind"]] <= granted:
                raise Refused("The requested Google permissions were not granted.")
            identity = self.verify(encoded_identity)
            google_subject = str(identity.get("sub", ""))
            email = str(identity.get("email", "")).strip().lower()
            if (not google_subject or len(google_subject) > 255 or
                    not email or len(email) > 320 or "@" not in email or
                    identity.get("email_verified") is not True or
                    not hmac.compare_digest(str(identity.get("nonce", "")), attempt["nonce"])):
                raise Refused("The connected Google identity could not be verified.")
            kind = attempt["kind"]
            connection_id = tenancy.save_connection(
                conn, account_id, kind=kind, google_subject=google_subject, email=email,
                scopes=sorted(granted), refresh_token=refresh,
                encrypt=lambda plain: self.vault.encrypt(plain, account_id, kind, google_subject),
                kms_key_name=self.vault.key_name)
            return {"id": connection_id, "kind": kind, "email": email}
        except Refused:
            raise
        except Exception as exc:
            raise Refused("Google connection could not be completed safely. Start again.") from exc

    def access_token(self, conn, account_id, connection_id, kind, required_scope):
        """A fresh access token for one tenant-owned connection, for one server-side Google read.
        An expired/revoked refresh token (Google's `invalid_grant`) deletes the connection, so a
        stale credential is never retried silently - the tenant must reconnect."""
        connection = tenancy.get_connection_record(conn, account_id, connection_id, kind)
        if connection is None or required_scope not in connection["scopes"]:
            raise Refused("Reconnect this Google account with the required permission.")
        refresh = self.vault.decrypt(connection["ciphertext"], account_id, kind,
                                     connection["google_subject"],
                                     key_name=connection["kms_key_name"])
        try:
            response = self.post(TOKEN_URL, data={"client_id": self.client_id,
                "client_secret": self.client_secret, "refresh_token": refresh,
                "grant_type": "refresh_token"}, timeout=10, allow_redirects=False)
            if response.status_code != 200:
                try:
                    failure = response.json()
                except Exception:
                    failure = None
                if (response.status_code == 400 and isinstance(failure, dict) and
                        failure.get("error") == "invalid_grant"):
                    tenancy.revoke_connection(conn, account_id, connection_id)
                raise Refused("The Google connection expired. Reconnect it.")
            payload = response.json()
            access = payload.get("access_token") if isinstance(payload, dict) else None
            if not isinstance(access, str) or not access or len(access) > 16000:
                raise Refused("Google did not return a usable access token.")
            return access
        except Refused:
            raise
        except Exception as exc:
            raise Refused("Google access is unavailable. Reconnect and try again.") from exc


def from_environment(environ=None):
    environ = os.environ if environ is None else environ
    keys = (environ.get("GOOGLE_OAUTH_CLIENT_ID"), environ.get("GOOGLE_OAUTH_CLIENT_SECRET"),
           environ.get("GOOGLE_OAUTH_REDIRECT_URI"), environ.get("TENANT_TOKEN_KMS_KEY"))
    if not all(keys):
        return None
    return Connector(keys[0], keys[1], keys[2], KMSVault(keys[3]))
