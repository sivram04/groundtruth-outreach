"""outreach/tenant_console.py through its real Flask routes: sign in with a fake Google
credential, read the session, start and complete a Gmail connection (fake connector), and log
out. No real Google, no real Postgres - a fake DB cursor and injected verifiers throughout."""

import pytest

from outreach import google_connect as gc
from outreach import tenant_console


class FakeCursor:
    def __init__(self, store):
        self.store = store
        self._last = None

    def execute(self, sql, params=()):
        sql = " ".join(sql.split())
        s = self.store
        if sql.startswith("SELECT account_id FROM tenant.identities"):
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
        else:
            raise AssertionError(f"fake cursor does not know: {sql}")

    def fetchone(self):
        return self._last[0] if self._last else None


class FakeConn:
    def __init__(self, store=None):
        self.store = store if store is not None else {"accounts": {}, "identities": {}}
        self.closed = False

    def cursor(self):
        return FakeCursor(self.store)

    def close(self):
        self.closed = True


class FakeConnector:
    """Stands in for google_connect.Connector so these tests exercise tenant_console's own
    routing/session logic, not the connect flow's internals (covered by test_google_connect.py)."""

    def __init__(self):
        self.begin_calls, self.complete_calls = [], []

    def begin(self, conn, account_id, provider_subject, kind):
        self.begin_calls.append((account_id, provider_subject, kind))
        return f"https://accounts.google.com/fake-auth?kind={kind}"

    def complete(self, conn, account_id, provider_subject, state, code):
        self.complete_calls.append((account_id, provider_subject, state, code))
        if code == "bad-code":
            raise gc.Refused("The Google connection request expired or was already used.")
        return {"id": "conn-1", "kind": "gmail", "email": "sam@example.test"}


IDENTITIES = {
    "good-credential": {"sub": "g-subject-1", "email": "sam@example.test",
                        "email_verified": True, "name": "Sam"},
    "good-credential-2": {"sub": "g-subject-2", "email": "sam.referrals@example.test",
                          "email_verified": True, "name": "Sam (referrals)"},
}


@pytest.fixture
def client_and_fakes():
    shared_store = {"accounts": {}, "identities": {}}
    verify_credential = lambda credential: IDENTITIES[credential] if credential in IDENTITIES \
        else (_ for _ in ()).throw(ValueError("bad credential"))
    connector = FakeConnector()
    app = tenant_console.create_app(
        conn_factory=lambda: FakeConn(shared_store), verify_credential=verify_credential,
        connector=connector, secret_key=b"test-secret",
    )
    return app.test_client(), connector, shared_store


def test_signing_in_with_a_valid_credential_creates_an_account(client_and_fakes):
    client, connector, store = client_and_fakes
    r = client.post("/api/session/google", json={"credential": "good-credential"})
    assert r.status_code == 200
    body = r.get_json()
    assert body["email"] == "sam@example.test" and body["name"] == "Sam"
    assert body["account_id"] in store["accounts"]


def test_a_second_sign_in_with_the_same_identity_resolves_to_the_same_account(client_and_fakes):
    client, connector, store = client_and_fakes
    first = client.post("/api/session/google", json={"credential": "good-credential"}).get_json()
    client.post("/api/session/logout")
    second = client.post("/api/session/google", json={"credential": "good-credential"}).get_json()
    assert first["account_id"] == second["account_id"]
    assert len(store["accounts"]) == 1


def test_an_invalid_credential_is_refused_and_creates_no_session(client_and_fakes):
    client, connector, store = client_and_fakes
    r = client.post("/api/session/google", json={"credential": "forged"})
    assert r.status_code == 401
    assert client.get("/api/session").get_json() == {"signed_in": False, "accounts": []}


def test_session_reflects_signed_in_state_and_logout_clears_it(client_and_fakes):
    client, connector, store = client_and_fakes
    assert client.get("/api/session").get_json() == {"signed_in": False, "accounts": []}
    client.post("/api/session/google", json={"credential": "good-credential"})
    assert client.get("/api/session").get_json()["signed_in"] is True
    client.post("/api/session/logout")
    assert client.get("/api/session").get_json() == {"signed_in": False, "accounts": []}


def test_signing_into_a_second_account_keeps_the_first_and_makes_the_second_active(client_and_fakes):
    client, connector, store = client_and_fakes
    first = client.post("/api/session/google", json={"credential": "good-credential"}).get_json()
    second = client.post("/api/session/google", json={"credential": "good-credential-2"}).get_json()
    assert first["account_id"] != second["account_id"]
    current = client.get("/api/session").get_json()
    assert current["account_id"] == second["account_id"]  # the one most recently signed into
    ids = {a["account_id"] for a in current["accounts"]}
    assert ids == {first["account_id"], second["account_id"]}  # both still signed in
    active_flags = {a["account_id"]: a["active"] for a in current["accounts"]}
    assert active_flags[second["account_id"]] is True and active_flags[first["account_id"]] is False


def test_switching_to_an_already_signed_in_account_needs_no_credential(client_and_fakes):
    client, connector, store = client_and_fakes
    first = client.post("/api/session/google", json={"credential": "good-credential"}).get_json()
    client.post("/api/session/google", json={"credential": "good-credential-2"})
    r = client.post("/api/session/switch", json={"account_id": first["account_id"]})
    assert r.status_code == 200 and r.get_json()["account_id"] == first["account_id"]
    assert client.get("/api/session").get_json()["account_id"] == first["account_id"]


def test_switching_to_an_account_never_signed_into_in_this_browser_is_refused(client_and_fakes):
    client, connector, store = client_and_fakes
    client.post("/api/session/google", json={"credential": "good-credential"})
    r = client.post("/api/session/switch", json={"account_id": "some-other-account-never-seen"})
    assert r.status_code == 400


def test_logging_out_one_account_falls_back_to_another_still_signed_in(client_and_fakes):
    client, connector, store = client_and_fakes
    first = client.post("/api/session/google", json={"credential": "good-credential"}).get_json()
    second = client.post("/api/session/google", json={"credential": "good-credential-2"}).get_json()
    r = client.post("/api/session/logout", json={"account_id": second["account_id"]})
    assert r.status_code == 200
    current = client.get("/api/session").get_json()
    assert current["signed_in"] is True
    assert current["account_id"] == first["account_id"]  # the only one left
    assert {a["account_id"] for a in current["accounts"]} == {first["account_id"]}


def test_logging_out_with_all_true_clears_every_signed_in_account(client_and_fakes):
    client, connector, store = client_and_fakes
    client.post("/api/session/google", json={"credential": "good-credential"})
    client.post("/api/session/google", json={"credential": "good-credential-2"})
    client.post("/api/session/logout", json={"all": True})
    assert client.get("/api/session").get_json() == {"signed_in": False, "accounts": []}


def test_connect_routes_act_on_the_currently_active_account(client_and_fakes):
    client, connector, store = client_and_fakes
    first = client.post("/api/session/google", json={"credential": "good-credential"}).get_json()
    second = client.post("/api/session/google", json={"credential": "good-credential-2"}).get_json()
    client.post("/api/connections/gmail/start")
    assert connector.begin_calls[-1][0] == second["account_id"]  # acts on the active (second) one
    client.post("/api/session/switch", json={"account_id": first["account_id"]})
    client.post("/api/connections/gmail/start")
    assert connector.begin_calls[-1][0] == first["account_id"]  # now acts on the first


def test_starting_a_connection_requires_signing_in_first(client_and_fakes):
    client, connector, store = client_and_fakes
    r = client.post("/api/connections/gmail/start")
    assert r.status_code == 401
    assert connector.begin_calls == []


def test_starting_a_connection_returns_the_authorization_url(client_and_fakes):
    client, connector, store = client_and_fakes
    client.post("/api/session/google", json={"credential": "good-credential"})
    r = client.post("/api/connections/gmail/start")
    assert r.status_code == 200
    assert r.get_json()["authorization_url"].startswith("https://accounts.google.com/fake-auth")
    assert connector.begin_calls[0][2] == "gmail"


def test_starting_a_connection_refuses_an_unknown_kind(client_and_fakes):
    client, connector, store = client_and_fakes
    client.post("/api/session/google", json={"credential": "good-credential"})
    r = client.post("/api/connections/calendar/start")
    assert r.status_code == 400


def test_the_callback_completes_the_connection(client_and_fakes):
    client, connector, store = client_and_fakes
    client.post("/api/session/google", json={"credential": "good-credential"})
    r = client.get("/api/tenant/google/callback?state=abc&code=good-code")
    assert r.status_code == 200
    body = r.get_json()
    assert body["ok"] is True and body["email"] == "sam@example.test"


def test_the_callback_surfaces_a_refusal_without_a_500(client_and_fakes):
    client, connector, store = client_and_fakes
    client.post("/api/session/google", json={"credential": "good-credential"})
    r = client.get("/api/tenant/google/callback?state=abc&code=bad-code")
    assert r.status_code == 400
    assert "expired" in r.get_json()["error"]


def test_connections_are_inert_with_no_connector_configured():
    # Before the OAuth client exists (still waiting on Google's verification), the connect
    # routes correctly refuse rather than crash - nothing left to build once it clears.
    verify_credential = lambda credential: {"sub": "g-subject-1", "email": "sam@example.test",
                                            "email_verified": True, "name": "Sam"}
    app = tenant_console.create_app(
        conn_factory=lambda: FakeConn(), verify_credential=verify_credential,
        connector=None, secret_key=b"test-secret",
    )
    client = app.test_client()
    client.post("/api/session/google", json={"credential": "good-credential"})
    r = client.post("/api/connections/gmail/start")
    assert r.status_code == 503
