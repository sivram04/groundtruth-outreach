"""outreach/tenant_google.py against a fake Connector and a fake DB cursor - no real Google
OAuth or Postgres needed."""

import pytest

from outreach import tenancy, tenant_google


class FakeCursor:
    def __init__(self, store):
        self.store = store
        self._last = None

    def execute(self, sql, params=()):
        sql = " ".join(sql.split())
        if sql.startswith("SELECT set_config"):
            pass
        elif sql.startswith("INSERT INTO tenant.accounts"):
            account_id, name = params
            self.store["accounts"][account_id] = name
        elif sql.startswith("INSERT INTO tenant.identities"):
            subject, account_id, email = params
            self.store["identities"][subject] = account_id
        elif sql.startswith("SELECT account_id FROM tenant.identities"):
            (subject,) = params
            self._last = [(self.store["identities"][subject],)] if subject in self.store["identities"] else []
        elif sql.startswith("SELECT name FROM tenant.accounts"):
            (account_id,) = params
            self._last = [(self.store["accounts"][account_id],)] if account_id in self.store["accounts"] else []
        elif sql.startswith("INSERT INTO tenant.google_connections"):
            (account_id, connection_id, kind, google_subject, email, scopes,
             ciphertext, kms_key_name) = params
            self.store["connections"][(account_id, kind)] = connection_id
        elif sql.startswith("SELECT connection_id FROM tenant.google_connections"):
            account_id, kind = params
            hit = self.store["connections"].get((account_id, kind))
            self._last = [(hit,)] if hit else []
        else:
            raise AssertionError(f"FakeCursor does not know this query: {sql}")

    def fetchone(self):
        return self._last[0] if self._last else None


class FakeConn:
    def __init__(self):
        self.store = {"accounts": {}, "identities": {}, "connections": {}}

    def cursor(self):
        return FakeCursor(self.store)


class FakeConnector:
    def __init__(self, token="fresh-access-token"):
        self.token = token
        self.calls = []

    def access_token(self, conn, account_id, connection_id, kind, required_scope):
        self.calls.append((account_id, connection_id, kind, required_scope))
        return self.token


def _connected_account(conn):
    account = tenancy.resolve_identity(conn, "subj-1", "sam@example.test")
    tenancy.save_connection(conn, account.id, kind="drive", google_subject="subj-1",
                            email="sam@example.test", scopes=["https://www.googleapis.com/auth/spreadsheets"],
                            refresh_token="refresh-token", encrypt=lambda p: p, kms_key_name="k")
    return account.id


def test_sheets_api_needs_a_connection_first():
    conn = FakeConn()
    account = tenancy.resolve_identity(conn, "subj-1", "sam@example.test")
    with pytest.raises(tenant_google.NotConnected):
        tenant_google.sheets_api(FakeConnector(), conn, account.id)


def test_sheets_api_asks_the_connector_for_the_right_connection_and_scope(monkeypatch):
    conn = FakeConn()
    account_id = _connected_account(conn)
    connector = FakeConnector()
    captured = {}

    def fake_build(*a, **k):
        captured["creds"] = k.get("credentials")
        return _FakeBuild()

    monkeypatch.setattr(tenant_google, "build", fake_build)
    result = tenant_google.sheets_api(connector, conn, account_id)
    assert result == "sheets-client"
    [(called_account, connection_id, kind, scope)] = connector.calls
    assert called_account == account_id
    assert kind == "drive"
    assert scope == "https://www.googleapis.com/auth/spreadsheets"
    assert captured["creds"].token == "fresh-access-token"


class _FakeBuild:
    def spreadsheets(self):
        return "sheets-client"
