"""outreach/google_connect.py: PKCE + state-bound connect flow, against a fake DB cursor, a
fake HTTP post, a fake ID-token verifier, and a fake vault - no real network, no real Google
keys, no real KMS. Proves the security-relevant branches: state reuse, expiry, scope
under-grant, nonce mismatch, and invalid_grant revocation."""

from datetime import datetime, timedelta, timezone

import pytest

from outreach import google_connect as gc
from outreach import tenancy

NOW = datetime(2026, 10, 10, 12, 0, tzinfo=timezone.utc)
REDIRECT = "https://outreach.example.test/api/tenant/google/callback"


class FakeDBCursor:
    def __init__(self, store):
        self.store = store
        self._last = None

    def execute(self, sql, params=()):
        sql = " ".join(sql.split())
        s = self.store
        if sql.startswith("SELECT set_config"):
            pass  # activates the RLS tenant scope - see test_tenancy.py for the pinning test
        elif sql.startswith("SELECT account_id FROM tenant.identities"):
            (subject,) = params
            self._last = [(s["identities"][subject],)] if subject in s["identities"] else []
        elif sql.startswith("INSERT INTO tenant.accounts"):
            account_id, name = params
            s["accounts"][account_id] = name
        elif sql.startswith("INSERT INTO tenant.identities"):
            subject, account_id, email = params
            s["identities"][subject] = account_id
        elif sql.startswith("SELECT name FROM tenant.accounts"):
            (account_id,) = params
            self._last = [(s["accounts"][account_id],)] if account_id in s["accounts"] else []
        elif sql.startswith("DELETE FROM tenant.google_auth_attempts WHERE expires_at"):
            (now,) = params
            s["attempts"] = {k: v for k, v in s["attempts"].items() if v["expires_at"] > now}
        elif sql.startswith("INSERT INTO tenant.google_auth_attempts"):
            account_id, state_hash, subject, kind, nonce, verifier, expires_at = params
            s["attempts"][(account_id, state_hash)] = {
                "provider_subject": subject, "kind": kind, "nonce": nonce,
                "code_verifier": verifier, "expires_at": expires_at,
            }
        elif sql.startswith("DELETE FROM tenant.google_auth_attempts"):
            account_id, state_hash, subject, now = params
            key = (account_id, state_hash)
            row = s["attempts"].get(key)
            if row and row["provider_subject"] == subject and row["expires_at"] > now:
                del s["attempts"][key]
                self._last = [(row["kind"], row["nonce"], row["code_verifier"])]
            else:
                self._last = []
        elif sql.startswith("INSERT INTO tenant.google_connections"):
            (account_id, connection_id, kind, google_subject, email, scopes,
             ciphertext, kms_key_name) = params
            s["connections"][(account_id, kind, google_subject)] = {
                "connection_id": connection_id, "email": email, "scopes": scopes,
                "refresh_ciphertext": ciphertext, "kms_key_name": kms_key_name,
            }
        elif sql.startswith("SELECT google_subject, scopes, refresh_ciphertext"):
            account_id, connection_id, kind = params
            hit = next(((gs, v) for (a, k, gs), v in s["connections"].items()
                       if a == account_id and k == kind and v["connection_id"] == connection_id), None)
            self._last = [(hit[0], hit[1]["scopes"], hit[1]["refresh_ciphertext"], hit[1]["kms_key_name"],
                          hit[1]["email"])] if hit else []
        elif sql.startswith("DELETE FROM tenant.google_connections"):
            account_id, connection_id = params
            key = next((k for k, v in s["connections"].items()
                       if k[0] == account_id and v["connection_id"] == connection_id), None)
            if key:
                del s["connections"][key]
        else:
            raise AssertionError(f"fake cursor does not know: {sql}")

    def fetchone(self):
        return self._last[0] if self._last else None


class FakeConn:
    def __init__(self):
        self.store = {"accounts": {}, "identities": {}, "attempts": {}, "connections": {}}

    def cursor(self):
        return FakeDBCursor(self.store)


class FakeVault:
    key_name = "projects/x/locations/y/keyRings/z/cryptoKeys/w"

    def encrypt(self, plaintext, account_id, kind, google_subject):
        return f"ENC|{account_id}|{kind}|{google_subject}|{plaintext}".encode()

    def decrypt(self, ciphertext, account_id, kind, google_subject, *, key_name=None):
        prefix = f"ENC|{account_id}|{kind}|{google_subject}|".encode()
        if not ciphertext.startswith(prefix):
            raise gc.Refused("wrong account/kind/subject for this ciphertext")
        return ciphertext[len(prefix):].decode()


class FakeResponse:
    def __init__(self, status_code, payload):
        self.status_code = status_code
        self._payload = payload

    def json(self):
        return self._payload


def connector(post=None, verify=None):
    return gc.Connector("client-id", "client-secret", REDIRECT, FakeVault(), post=post, verify=verify)


def test_the_redirect_uri_must_be_https_and_the_exact_callback_path():
    with pytest.raises(ValueError):
        gc.Connector("id", "secret", "http://x.test/api/tenant/google/callback", FakeVault())
    with pytest.raises(ValueError):
        gc.Connector("id", "secret", "https://x.test/wrong/path", FakeVault())


def test_begin_returns_an_authorization_url_with_pkce_and_state():
    conn = FakeConn()
    url = connector().begin(conn, "acct-1", "subj-1", "gmail", now=NOW)
    assert url.startswith(gc.AUTH_URL)
    assert "code_challenge=" in url and "code_challenge_method=S256" in url
    assert "state=" in url and "scope=" in url
    assert len(conn.store["attempts"]) == 1


def _begin_and_capture_state(conn, kind="gmail", account_id="acct-1", subject="subj-1"):
    # Recover the plaintext state the way the browser would carry it back - by state_hash lookup
    # here, since begin() only ever returns it embedded in the URL in real use.
    from urllib.parse import parse_qs, urlsplit
    url = connector().begin(conn, account_id, subject, kind, now=NOW)
    query = parse_qs(urlsplit(url).query)
    return query["state"][0], query["nonce"][0]


def _token_response(id_token_sub="g-subject-1", email="sam@example.test", scope_kind="gmail"):
    return FakeResponse(200, {"refresh_token": "real-refresh-token", "id_token": "opaque-id-token",
                             "scope": " ".join(sorted(gc.SCOPES[scope_kind]))})


def test_complete_stores_a_connection_on_a_valid_callback():
    conn = FakeConn()
    state, nonce = _begin_and_capture_state(conn)
    post = lambda *a, **k: _token_response()
    verify = lambda token: {"sub": "g-subject-1", "email": "sam@example.test",
                            "email_verified": True, "nonce": nonce}
    result = connector(post=post, verify=verify).complete(conn, "acct-1", "subj-1", state, "auth-code", now=NOW)
    assert result == {"id": conn.store["connections"][("acct-1", "gmail", "g-subject-1")]["connection_id"],
                      "kind": "gmail", "email": "sam@example.test"}
    assert len(conn.store["attempts"]) == 0  # consumed, cannot be replayed


def test_a_real_google_scope_response_is_accepted_not_just_the_requested_alias():
    """Regression, found live 2026-10-12: a real consent grant's token response echoes back the
    scope "https://www.googleapis.com/auth/userinfo.email", never the literal "email" alias the
    authorization request used - confirmed against a real Google OAuth flow, where a user who
    visibly granted every requested permission (screenshot: both Gmail checkboxes checked) still
    got "requested Google permissions were not granted" because SCOPES compared against the
    literal alias. This test hardcodes that real response shape directly, not via gc.SCOPES, so
    it cannot pass merely because SCOPES and the comparison happen to be defined from the same
    (possibly still-wrong) set."""
    conn = FakeConn()
    state, nonce = _begin_and_capture_state(conn)
    real_granted_scope = ("openid https://www.googleapis.com/auth/userinfo.email "
                          "https://www.googleapis.com/auth/gmail.readonly "
                          "https://www.googleapis.com/auth/gmail.compose")
    post = lambda *a, **k: FakeResponse(200, {"refresh_token": "real-refresh-token",
                                              "id_token": "opaque-id-token", "scope": real_granted_scope})
    verify = lambda token: {"sub": "g-subject-1", "email": "sam@example.test",
                            "email_verified": True, "nonce": nonce}
    result = connector(post=post, verify=verify).complete(conn, "acct-1", "subj-1", state, "auth-code", now=NOW)
    assert result["kind"] == "gmail"


def test_a_state_can_never_be_reused():
    conn = FakeConn()
    state, nonce = _begin_and_capture_state(conn)
    post = lambda *a, **k: _token_response()
    verify = lambda token: {"sub": "g-subject-1", "email": "sam@example.test",
                            "email_verified": True, "nonce": nonce}
    c = connector(post=post, verify=verify)
    c.complete(conn, "acct-1", "subj-1", state, "auth-code", now=NOW)
    with pytest.raises(gc.Refused, match="expired or was already used"):
        c.complete(conn, "acct-1", "subj-1", state, "auth-code", now=NOW)


def test_an_expired_attempt_is_refused():
    conn = FakeConn()
    state, nonce = _begin_and_capture_state(conn)
    later = NOW + timedelta(minutes=11)  # past the 10-minute attempt window
    with pytest.raises(gc.Refused, match="expired"):
        connector().complete(conn, "acct-1", "subj-1", state, "auth-code", now=later)


def test_a_mismatched_nonce_is_refused():
    conn = FakeConn()
    state, nonce = _begin_and_capture_state(conn)
    post = lambda *a, **k: _token_response()
    verify = lambda token: {"sub": "g-subject-1", "email": "sam@example.test",
                            "email_verified": True, "nonce": "not-the-real-nonce"}
    with pytest.raises(gc.Refused, match="could not be verified"):
        connector(post=post, verify=verify).complete(conn, "acct-1", "subj-1", state, "auth-code", now=NOW)


def test_an_under_granted_scope_is_refused():
    conn = FakeConn()
    state, nonce = _begin_and_capture_state(conn)
    post = lambda *a, **k: FakeResponse(200, {"refresh_token": "t", "id_token": "x",
                                              "scope": "openid email"})  # missing gmail scopes
    with pytest.raises(gc.Refused, match="permissions were not granted"):
        connector(post=post).complete(conn, "acct-1", "subj-1", state, "auth-code", now=NOW)


def test_an_unverified_email_is_refused():
    conn = FakeConn()
    state, nonce = _begin_and_capture_state(conn)
    post = lambda *a, **k: _token_response()
    verify = lambda token: {"sub": "g-subject-1", "email": "sam@example.test",
                            "email_verified": False, "nonce": nonce}
    with pytest.raises(gc.Refused, match="could not be verified"):
        connector(post=post, verify=verify).complete(conn, "acct-1", "subj-1", state, "auth-code", now=NOW)


def test_googles_own_rejection_is_refused_without_a_token_leak():
    conn = FakeConn()
    state, nonce = _begin_and_capture_state(conn)
    post = lambda *a, **k: FakeResponse(400, {"error": "invalid_grant"})
    with pytest.raises(gc.Refused, match="did not authorize"):
        connector(post=post).complete(conn, "acct-1", "subj-1", state, "auth-code", now=NOW)


def test_access_token_refreshes_a_stored_connection():
    conn = FakeConn()
    state, nonce = _begin_and_capture_state(conn)
    post = lambda *a, **k: _token_response()
    verify = lambda token: {"sub": "g-subject-1", "email": "sam@example.test",
                            "email_verified": True, "nonce": nonce}
    c = connector(post=post, verify=verify)
    result = c.complete(conn, "acct-1", "subj-1", state, "auth-code", now=NOW)

    refresh_post = lambda *a, **k: FakeResponse(200, {"access_token": "fresh-access-token"})
    c2 = connector(post=refresh_post)
    token = c2.access_token(conn, "acct-1", result["id"], "gmail",
                            "https://www.googleapis.com/auth/gmail.readonly")
    assert token == "fresh-access-token"


def test_access_token_revokes_the_connection_on_invalid_grant():
    conn = FakeConn()
    state, nonce = _begin_and_capture_state(conn)
    post = lambda *a, **k: _token_response()
    verify = lambda token: {"sub": "g-subject-1", "email": "sam@example.test",
                            "email_verified": True, "nonce": nonce}
    result = connector(post=post, verify=verify).complete(conn, "acct-1", "subj-1", state, "auth-code", now=NOW)
    assert len(conn.store["connections"]) == 1

    refresh_post = lambda *a, **k: FakeResponse(400, {"error": "invalid_grant"})
    with pytest.raises(gc.Refused, match="expired"):
        connector(post=refresh_post).access_token(conn, "acct-1", result["id"], "gmail",
                                                  "https://www.googleapis.com/auth/gmail.readonly")
    assert len(conn.store["connections"]) == 0  # revoked, not left stale


def test_access_token_refuses_a_scope_the_connection_never_granted():
    conn = FakeConn()
    state, nonce = _begin_and_capture_state(conn)
    post = lambda *a, **k: _token_response()
    verify = lambda token: {"sub": "g-subject-1", "email": "sam@example.test",
                            "email_verified": True, "nonce": nonce}
    result = connector(post=post, verify=verify).complete(conn, "acct-1", "subj-1", state, "auth-code", now=NOW)
    with pytest.raises(gc.Refused, match="Reconnect"):
        connector().access_token(conn, "acct-1", result["id"], "gmail", "https://not-a-granted-scope")


def test_from_environment_is_none_without_every_required_variable(monkeypatch):
    for var in ("GOOGLE_OAUTH_CLIENT_ID", "GOOGLE_OAUTH_CLIENT_SECRET",
               "GOOGLE_OAUTH_REDIRECT_URI", "TENANT_TOKEN_KMS_KEY"):
        monkeypatch.delenv(var, raising=False)
    assert gc.from_environment() is None
