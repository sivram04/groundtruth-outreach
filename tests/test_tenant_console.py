"""outreach/tenant_console.py through its real Flask routes: sign in with a fake Google
credential, read the session, start and complete a Gmail connection (fake connector), and log
out. No real Google, no real Postgres - a fake DB cursor and injected verifiers throughout."""

import sys
from pathlib import Path

import pytest

from outreach import google_connect as gc
from outreach import job_auto, job_draft, tenant_console, tenant_google


class FakeCursor:
    def __init__(self, store):
        self.store = store
        self._last = None
        self.rowcount = 0

    def execute(self, sql, params=()):
        sql = " ".join(sql.split())
        s = self.store
        if sql.startswith("SELECT set_config"):
            pass
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
        elif sql.startswith("SELECT sheet_id FROM tenant.accounts"):
            (account_id,) = params
            self._last = [(s.get("sheet_ids", {}).get(account_id),)] if account_id in s["accounts"] else []
        elif sql.startswith("UPDATE tenant.accounts SET sheet_id"):
            sheet_id, account_id = params
            if account_id in s["accounts"]:
                s.setdefault("sheet_ids", {})[account_id] = sheet_id
                self.rowcount = 1
        elif sql.startswith("INSERT INTO tenant.google_connections"):
            (account_id, connection_id, kind, google_subject, email, scopes,
             ciphertext, kms_key_name) = params
            s.setdefault("connections", {})[(account_id, kind)] = connection_id
        elif sql.startswith("SELECT connection_id FROM tenant.google_connections"):
            account_id, kind = params
            hit = s.get("connections", {}).get((account_id, kind))
            self._last = [(hit,)] if hit else []
        elif sql.startswith("DELETE FROM tenant.google_connections"):
            account_id, connection_id = params
            matches = [k for k, v in s.get("connections", {}).items() if v == connection_id]
            for key in matches:
                if key[0] == account_id:
                    del s["connections"][key]
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
        self.begin_calls, self.complete_calls, self.access_token_calls = [], [], []

    def begin(self, conn, account_id, provider_subject, kind):
        self.begin_calls.append((account_id, provider_subject, kind))
        return f"https://accounts.google.com/fake-auth?kind={kind}"

    def complete(self, conn, account_id, provider_subject, state, code):
        self.complete_calls.append((account_id, provider_subject, state, code))
        if code == "bad-code":
            raise gc.Refused("The Google connection request expired or was already used.")
        conn.store.setdefault("connections", {})[(account_id, "gmail")] = "conn-1"
        return {"id": "conn-1", "kind": "gmail", "email": "sam@example.test"}

    def access_token(self, conn, account_id, connection_id, kind, required_scope):
        self.access_token_calls.append((account_id, connection_id, kind, required_scope))
        return "fake-access-token"


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


def test_the_callback_completes_the_connection_and_sends_the_browser_back_to_the_app(client_and_fakes):
    """A page navigation (Google's own redirect), not a fetch() call - raw JSON here would leave
    the founder stranded with no way back to the Dashboard, so this must redirect, not render."""
    client, connector, store = client_and_fakes
    client.post("/api/session/google", json={"credential": "good-credential"})
    r = client.get("/api/tenant/google/callback?state=abc&code=good-code")
    assert r.status_code == 302
    assert r.location == "/?connected=gmail"


def test_the_callback_surfaces_a_refusal_as_a_redirect_not_a_500(client_and_fakes):
    client, connector, store = client_and_fakes
    client.post("/api/session/google", json={"credential": "good-credential"})
    r = client.get("/api/tenant/google/callback?state=abc&code=bad-code")
    assert r.status_code == 302
    assert r.location.startswith("/?connect_error=")
    assert "expired" in r.location


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


class FakeSpreadsheets:
    """Stands in for `sheets_api()`'s return value: just enough to drive ensure_sheet."""

    def __init__(self, openable=()):
        self.openable = set(openable)
        self.created = []

    def create(self, body=None):
        new_id = f"new-sheet-{len(self.created) + 1}"
        self.created.append(body["properties"]["title"])
        self.openable.add(new_id)
        return _Exec({"spreadsheetId": new_id})

    def get(self, spreadsheetId):
        if spreadsheetId not in self.openable:
            raise RuntimeError("404: not found or no access")
        return _Exec({"spreadsheetId": spreadsheetId})


class _Exec:
    def __init__(self, result):
        self._result = result

    def execute(self):
        return self._result


def _fake_build(monkeypatch, spreadsheets=None, gmail=None):
    def build(service, version, **kw):
        if service == "sheets":
            return _SheetsBuild(spreadsheets or FakeSpreadsheets())
        return gmail or "fake-gmail-client"
    monkeypatch.setattr(tenant_google, "build", build)


class _SheetsBuild:
    def __init__(self, spreadsheets):
        self._spreadsheets = spreadsheets

    def spreadsheets(self):
        return self._spreadsheets


def _connect_drive(store, account_id):
    store.setdefault("connections", {})[(account_id, "drive")] = "conn-drive-1"


def test_connections_reports_nothing_connected_for_a_fresh_account(client_and_fakes):
    client, connector, store = client_and_fakes
    client.post("/api/session/google", json={"credential": "good-credential"})
    r = client.get("/api/account/connections")
    assert r.status_code == 200
    assert r.get_json() == {"gmail": False, "drive": False}


def test_connections_reports_true_for_a_kind_the_account_actually_connected(client_and_fakes):
    client, connector, store = client_and_fakes
    account = client.post("/api/session/google", json={"credential": "good-credential"}).get_json()
    _connect_drive(store, account["account_id"])
    r = client.get("/api/account/connections")
    assert r.get_json() == {"gmail": False, "drive": True}


def test_connections_requires_signing_in_first(client_and_fakes):
    client, connector, store = client_and_fakes
    r = client.get("/api/account/connections")
    assert r.status_code == 401


def test_unlink_sheet_clears_it(client_and_fakes, monkeypatch):
    client, connector, store = client_and_fakes
    account = client.post("/api/session/google", json={"credential": "good-credential"}).get_json()
    _connect_drive(store, account["account_id"])
    _fake_build(monkeypatch, spreadsheets=FakeSpreadsheets())
    sheet_id = client.post("/api/account/sheet").get_json()["sheet_id"]
    assert sheet_id

    r = client.delete("/api/account/sheet")
    assert r.status_code == 200 and r.get_json() == {"ok": True}
    assert client.get("/api/account/sheet").get_json() == {"sheet_id": None}


def test_unlink_sheet_requires_signing_in_first(client_and_fakes):
    client, connector, store = client_and_fakes
    r = client.delete("/api/account/sheet")
    assert r.status_code == 401


def test_disconnect_revokes_an_existing_connection(client_and_fakes):
    client, connector, store = client_and_fakes
    account = client.post("/api/session/google", json={"credential": "good-credential"}).get_json()
    _connect_drive(store, account["account_id"])
    assert client.get("/api/account/connections").get_json()["drive"] is True

    r = client.delete("/api/connections/drive")
    assert r.status_code == 200 and r.get_json() == {"ok": True}
    assert client.get("/api/account/connections").get_json()["drive"] is False


def test_disconnect_a_never_connected_kind_is_a_no_op():
    verify_credential = lambda credential: {"sub": "g-subject-1", "email": "sam@example.test",
                                            "email_verified": True, "name": "Sam"}
    app = tenant_console.create_app(
        conn_factory=lambda: FakeConn(), verify_credential=verify_credential,
        connector=FakeConnector(), secret_key=b"test-secret",
    )
    client = app.test_client()
    client.post("/api/session/google", json={"credential": "good-credential"})
    r = client.delete("/api/connections/gmail")
    assert r.status_code == 200 and r.get_json() == {"ok": True}


def test_disconnect_refuses_an_unknown_kind(client_and_fakes):
    client, connector, store = client_and_fakes
    client.post("/api/session/google", json={"credential": "good-credential"})
    r = client.delete("/api/connections/calendar")
    assert r.status_code == 400


def test_disconnect_requires_signing_in_first(client_and_fakes):
    client, connector, store = client_and_fakes
    r = client.delete("/api/connections/gmail")
    assert r.status_code == 401


def test_link_sheet_requires_a_drive_connection_first(client_and_fakes):
    client, connector, store = client_and_fakes
    client.post("/api/session/google", json={"credential": "good-credential"})
    r = client.post("/api/account/sheet")
    assert r.status_code == 400
    assert "Connect Google Sheets" in r.get_json()["error"]


def test_link_sheet_creates_a_new_sheet_when_none_given(client_and_fakes, monkeypatch):
    client, connector, store = client_and_fakes
    account = client.post("/api/session/google", json={"credential": "good-credential"}).get_json()
    _connect_drive(store, account["account_id"])
    fake_sheets = FakeSpreadsheets()
    _fake_build(monkeypatch, spreadsheets=fake_sheets)
    r = client.post("/api/account/sheet")
    assert r.status_code == 200
    assert r.get_json()["sheet_id"] == "new-sheet-1"
    assert fake_sheets.created == ["Lakshyaa outreach leads"]


def test_link_sheet_links_an_existing_openable_sheet(client_and_fakes, monkeypatch):
    client, connector, store = client_and_fakes
    account = client.post("/api/session/google", json={"credential": "good-credential"}).get_json()
    _connect_drive(store, account["account_id"])
    _fake_build(monkeypatch, spreadsheets=FakeSpreadsheets(openable=["existing-sheet"]))
    r = client.post("/api/account/sheet", json={"sheet_id": "existing-sheet"})
    assert r.status_code == 200
    assert r.get_json()["sheet_id"] == "existing-sheet"


def test_link_sheet_refuses_a_sheet_this_account_cannot_open(client_and_fakes, monkeypatch):
    client, connector, store = client_and_fakes
    account = client.post("/api/session/google", json={"credential": "good-credential"}).get_json()
    _connect_drive(store, account["account_id"])
    _fake_build(monkeypatch, spreadsheets=FakeSpreadsheets(openable=[]))
    r = client.post("/api/account/sheet", json={"sheet_id": "not-mine"})
    assert r.status_code == 400


def test_get_sheet_is_none_before_linking(client_and_fakes):
    client, connector, store = client_and_fakes
    client.post("/api/session/google", json={"credential": "good-credential"})
    assert client.get("/api/account/sheet").get_json() == {"sheet_id": None}


def test_jobs_auto_requires_a_sheet_first(client_and_fakes):
    client, connector, store = client_and_fakes
    client.post("/api/session/google", json={"credential": "good-credential"})
    r = client.post("/api/jobs/auto")
    assert r.status_code == 400
    assert "no Sheet yet" in r.get_json()["error"]


def test_jobs_auto_runs_against_the_accounts_own_sheet(client_and_fakes, monkeypatch):
    client, connector, store = client_and_fakes
    account = client.post("/api/session/google", json={"credential": "good-credential"}).get_json()
    _connect_drive(store, account["account_id"])
    _fake_build(monkeypatch, spreadsheets=FakeSpreadsheets())
    sheet_id = client.post("/api/account/sheet").get_json()["sheet_id"]

    captured = {}
    monkeypatch.setattr(job_auto, "run",
                       lambda where, **kw: captured.update(kw) or {"checked": {}, "researched": {}, "profiled": {}})
    r = client.post("/api/jobs/auto")
    assert r.status_code == 200
    assert captured["sheet_id"] == sheet_id
    assert captured["api"] is not None


def test_there_is_no_jobs_send_route():
    """outreach/send.py - the one sanctioned send path - may only be imported by console.py and
    auto_send.py (tests/test_no_send.py pins this at the repo level). This test pins the same
    invariant locally: tenant_console.py must never grow a third caller, even behind a signed-in
    check, without the same kind of explicit founder decision those two had."""
    import re
    source = Path(tenant_console.__file__).read_text(encoding="utf-8")
    assert not re.search(r"^\s*from outreach import .*\bsend\b", source, re.MULTILINE)
    assert not re.search(r'@app\.(get|post)\("/api/jobs/send"\)', source)


def test_config_exposes_the_public_client_id_with_no_sign_in_required():
    app = tenant_console.create_app(
        conn_factory=lambda: FakeConn(), verify_credential=lambda c: {},
        connector=None, secret_key=b"test-secret", google_client_id="123-abc.apps.googleusercontent.com",
    )
    r = app.test_client().get("/api/config")
    assert r.status_code == 200
    assert r.get_json() == {"google_client_id": "123-abc.apps.googleusercontent.com"}


def test_the_page_route_refuses_cleanly_when_no_build_exists(tmp_path):
    app = tenant_console.create_app(
        conn_factory=lambda: FakeConn(), verify_credential=lambda c: {},
        connector=None, secret_key=b"test-secret", static_dir=str(tmp_path),
    )
    r = app.test_client().get("/")
    assert r.status_code == 503


def test_the_page_route_serves_the_built_index_html(tmp_path):
    """Regression: a relative static_dir (e.g. "tenant-console/dist", as the real deploy passes)
    must resolve the same way send_from_directory does internally - a bare relative Path once
    produced a 404 for every request regardless of cwd, even though the file genuinely existed."""
    (tmp_path / "index.html").write_text("<html>tenant console</html>", encoding="utf-8")
    assets = tmp_path / "assets"
    assets.mkdir()
    (assets / "app.js").write_text("console.log('ok')", encoding="utf-8")
    app = tenant_console.create_app(
        conn_factory=lambda: FakeConn(), verify_credential=lambda c: {},
        connector=None, secret_key=b"test-secret", static_dir=str(tmp_path),
    )
    client = app.test_client()
    r = client.get("/")
    assert r.status_code == 200 and b"tenant console" in r.data
    r2 = client.get("/assets/app.js")
    assert r2.status_code == 200


def test_deployed_builds_cleanly_with_no_environment_configured(monkeypatch):
    """Importing the module (app = _deployed()) must never require real env vars, real Postgres
    or real Google credentials - conn_factory/verify_credential/connector are only ever touched
    per-request, never at app-construction time. Every test in this file already proves this by
    merely importing tenant_console; this test pins it explicitly against a route that touches
    neither (GET /api/session only reads the Flask session cookie)."""
    for name in ("GOOGLE_OAUTH_CLIENT_ID", "GOOGLE_OAUTH_CLIENT_SECRET", "GOOGLE_OAUTH_REDIRECT_URI",
                 "TENANT_TOKEN_KMS_KEY", "TENANT_DB_HOST", "TENANT_DB_PASSWORD"):
        monkeypatch.delenv(name, raising=False)
    app = tenant_console._deployed()
    r = app.test_client().get("/api/session")
    assert r.status_code == 200
    assert r.get_json() == {"signed_in": False, "accounts": []}


def test_deployed_s_conn_factory_needs_real_db_env_vars_only_when_actually_called(monkeypatch):
    """A route that DOES need a connection (sign-in) fails rather than silently connecting
    nowhere, if the DB env vars were never set - proving conn_factory is still lazy (deferred to
    the first request that needs it), not memoized or validated at app-construction time."""
    for name in ("TENANT_DB_HOST", "TENANT_DB_PASSWORD"):
        monkeypatch.delenv(name, raising=False)
    app = tenant_console._deployed()
    r = app.test_client().post("/api/session/google", json={"credential": "x"})
    assert r.status_code == 500


def test_deployed_passes_each_env_var_to_the_right_create_app_argument(monkeypatch):
    monkeypatch.setenv("GOOGLE_OAUTH_CLIENT_ID", "client-123")
    monkeypatch.setenv("TENANT_CONSOLE_STATIC_DIR", "/srv/static")
    monkeypatch.setenv("TENANT_CONSOLE_SECRET_KEY", "a-real-persisted-secret")

    captured = {}

    def fake_create_app(**kwargs):
        captured.update(kwargs)
        return "the-app"

    monkeypatch.setattr(tenant_console, "create_app", fake_create_app)
    result = tenant_console._deployed()
    assert result == "the-app"
    assert captured["google_client_id"] == "client-123"
    assert captured["static_dir"] == "/srv/static"
    assert captured["secret_key"] == b"a-real-persisted-secret"
    assert callable(captured["conn_factory"])
    assert callable(captured["verify_credential"])


class _FakePsycopg:
    def __init__(self):
        self.calls = []

    def connect(self, **kwargs):
        self.calls.append(kwargs)
        return "a-connection"


def test_conn_factory_prefers_the_cloud_sql_socket_over_a_public_host(monkeypatch):
    fake = _FakePsycopg()
    monkeypatch.setitem(sys.modules, "psycopg", fake)
    monkeypatch.setenv("TENANT_DB_SOCKET", "/cloudsql/lakshyaa-outreach:us-central1:outreach-tenant")
    monkeypatch.setenv("TENANT_DB_HOST", "35.253.52.165")
    monkeypatch.setenv("TENANT_DB_PASSWORD", "secret")
    result = tenant_console._conn_factory()
    assert result == "a-connection"
    assert fake.calls[0]["host"] == "/cloudsql/lakshyaa-outreach:us-central1:outreach-tenant"
    assert "sslmode" not in fake.calls[0]  # the socket needs no TLS negotiation


def test_conn_factory_falls_back_to_a_public_host_with_tls(monkeypatch):
    fake = _FakePsycopg()
    monkeypatch.setitem(sys.modules, "psycopg", fake)
    monkeypatch.delenv("TENANT_DB_SOCKET", raising=False)
    monkeypatch.setenv("TENANT_DB_HOST", "35.253.52.165")
    monkeypatch.setenv("TENANT_DB_PASSWORD", "secret")
    tenant_console._conn_factory()
    assert fake.calls[0]["host"] == "35.253.52.165"
    assert fake.calls[0]["sslmode"] == "require"


class _TransactionalConn:
    """A real DB-API connection commits/rolls back explicitly - closing it uncommitted silently
    discards any write (this is psycopg's actual default behavior, autocommit=False). Tracks
    calls so a test can prove the route wrapper commits on success and rolls back on failure."""

    def __init__(self, store):
        self.store = store
        self.calls = []

    def cursor(self):
        return FakeCursor(self.store)

    def commit(self):
        self.calls.append("commit")

    def rollback(self):
        self.calls.append("rollback")

    def close(self):
        self.calls.append("close")


def test_with_conn_commits_a_successful_write_instead_of_silently_discarding_it():
    """Regression: _with_conn never called commit(), so a route's write (e.g. sign-in creating
    an account) looked successful - no exception, a normal response - but psycopg's connection
    defaults to autocommit=False, and closing it uncommitted rolls the transaction back. The
    account only ever existed inside that one request; the next request's session cookie
    referenced an account_id nothing in the database actually had, and every later route failed
    with a foreign-key violation. Caught live, not by this test first."""
    store = {"accounts": {}, "identities": {}}
    conn = _TransactionalConn(store)
    app = tenant_console.create_app(
        conn_factory=lambda: conn,
        verify_credential=lambda c: {"sub": "g-subject-1", "email": "sam@example.test",
                                     "email_verified": True, "name": "Sam"},
        connector=None, secret_key=b"test-secret",
    )
    r = app.test_client().post("/api/session/google", json={"credential": "good-credential"})
    assert r.status_code == 200
    assert conn.calls == ["commit", "close"]
    assert store["accounts"]  # actually persisted, not just returned in the response


def test_with_conn_rolls_back_a_failed_request_instead_of_leaving_it_dangling():
    """sign_in only catches a verify_credential failure itself; a DB-layer exception past that
    point (here, simulated inside resolve_identity's own cursor) is NOT caught by the route and
    must reach _with_conn, which should roll back rather than commit a partial write."""

    class _BrokenConn(_TransactionalConn):
        def cursor(self):
            raise RuntimeError("the database is unreachable")

    conn = _BrokenConn({"accounts": {}, "identities": {}})
    app = tenant_console.create_app(
        conn_factory=lambda: conn,
        verify_credential=lambda c: {"sub": "g-subject-1", "email": "sam@example.test",
                                     "email_verified": True, "name": "Sam"},
        connector=None, secret_key=b"test-secret",
    )
    r = app.test_client().post("/api/session/google", json={"credential": "good-credential"})
    assert r.status_code == 500
    assert conn.calls == ["rollback", "close"]
