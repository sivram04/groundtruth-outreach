"""outreach/tenancy.py against a fake DB-API cursor - no real Postgres needed. Proves the SQL
shape and the logic (identity resolution, connection storage) the same way outreach/sheet.py's
tests prove Sheets logic against a fake Sheets client."""

import pytest

from outreach import tenancy


class FakeCursor:
    """Enough of a DB-API cursor to drive tenancy.py: accounts, identities, and connections,
    held in memory. Real enough to catch a wrong column order or a missing WHERE, not a
    substitute for testing against real Postgres before this goes live."""

    def __init__(self, store):
        self.store = store
        self._last = None
        self.rowcount = 0

    def execute(self, sql, params=()):
        sql = " ".join(sql.split())
        self.store.setdefault("query_log", []).append(sql.split("(")[0].strip())
        if sql.startswith("SELECT set_config"):
            self.store["tenant_scope_set_to"] = params[0]
        elif sql.startswith("SELECT account_id FROM tenant.identities"):
            (subject,) = params
            self._last = [(self.store["identities"][subject],)] if subject in self.store["identities"] else []
        elif sql.startswith("INSERT INTO tenant.accounts"):
            account_id, name = params
            self.store["accounts"][account_id] = name
        elif sql.startswith("INSERT INTO tenant.identities"):
            subject, account_id, email = params
            self.store["identities"][subject] = account_id
        elif sql.startswith("SELECT name FROM tenant.accounts"):
            (account_id,) = params
            self._last = [(self.store["accounts"][account_id],)] if account_id in self.store["accounts"] else []
        elif sql.startswith("INSERT INTO tenant.google_connections"):
            (account_id, connection_id, kind, google_subject, email, scopes,
             ciphertext, kms_key_name) = params
            self.store["connections"][(account_id, kind, google_subject)] = {
                "connection_id": connection_id, "email": email, "scopes": scopes,
                "refresh_ciphertext": ciphertext, "kms_key_name": kms_key_name,
            }
        elif sql.startswith("SELECT refresh_ciphertext, google_subject, email, scopes"):
            account_id, kind = params
            hit = next((v for (a, k, _), v in self.store["connections"].items()
                       if a == account_id and k == kind), None)
            self._last = [(hit["refresh_ciphertext"], next(gs for (a, k, gs) in self.store["connections"]
                                                            if a == account_id and k == kind),
                          hit["email"], hit["scopes"])] if hit else []
        elif sql.startswith("SELECT sheet_id FROM tenant.accounts"):
            (account_id,) = params
            self._last = ([(self.store.get("sheet_ids", {}).get(account_id),)]
                          if account_id in self.store["accounts"] else [])
        elif sql.startswith("UPDATE tenant.accounts SET sheet_id"):
            sheet_id, account_id = params
            if account_id in self.store["accounts"]:
                self.store.setdefault("sheet_ids", {})[account_id] = sheet_id
                self.rowcount = 1
            else:
                self.rowcount = 0
        elif sql.startswith("SELECT lead_tabs FROM tenant.accounts"):
            (account_id,) = params
            self._last = ([(self.store.get("lead_tabs", {}).get(account_id),)]
                          if account_id in self.store["accounts"] else [])
        elif sql.startswith("UPDATE tenant.accounts SET lead_tabs"):
            lead_tabs, account_id = params
            if account_id in self.store["accounts"]:
                self.store.setdefault("lead_tabs", {})[account_id] = lead_tabs
                self.rowcount = 1
            else:
                self.rowcount = 0
        else:
            raise AssertionError(f"FakeCursor does not know this query: {sql}")

    def fetchone(self):
        return self._last[0] if self._last else None


class FakeConn:
    def __init__(self):
        self.store = {"accounts": {}, "identities": {}, "connections": {}}

    def cursor(self):
        return FakeCursor(self.store)


def test_a_new_identity_creates_an_account():
    conn = FakeConn()
    account = tenancy.resolve_identity(conn, "subj-1", "sam@example.test", display_name="Sam")
    assert account.name == "Sam"
    assert conn.store["accounts"][account.id] == "Sam"
    assert conn.store["identities"]["subj-1"] == account.id


def test_a_repeat_sign_in_resolves_to_the_same_account():
    conn = FakeConn()
    first = tenancy.resolve_identity(conn, "subj-1", "sam@example.test")
    second = tenancy.resolve_identity(conn, "subj-1", "sam-new-email@example.test")
    assert first.id == second.id  # the stable subject wins, not the (changed) email
    assert len(conn.store["accounts"]) == 1


def test_two_different_identities_get_two_different_accounts():
    conn = FakeConn()
    a = tenancy.resolve_identity(conn, "subj-1", "sam@example.test")
    b = tenancy.resolve_identity(conn, "subj-2", "pat@example.test")
    assert a.id != b.id


def test_resolve_identity_needs_a_subject():
    conn = FakeConn()
    with pytest.raises(tenancy.TenancyError):
        tenancy.resolve_identity(conn, "", "sam@example.test")


def test_falls_back_to_email_then_subject_for_the_account_name():
    conn = FakeConn()
    account = tenancy.resolve_identity(conn, "subj-1", "sam@example.test")
    assert account.name == "sam@example.test"
    conn2 = FakeConn()
    account2 = tenancy.resolve_identity(conn2, "subj-2", "")
    assert account2.name == "subj-2"


def test_save_and_read_connection_round_trips_through_the_encryptor():
    conn = FakeConn()
    account = tenancy.resolve_identity(conn, "subj-1", "sam@example.test")
    tenancy.save_connection(
        conn, account.id, kind="gmail", google_subject="subj-1", email="sam@example.test",
        scopes=["gmail.readonly", "gmail.compose"], refresh_token="real-refresh-token",
        encrypt=lambda plain: f"ENC({plain})".encode(), kms_key_name="projects/x/keyRings/y/cryptoKeys/z")
    result = tenancy.read_connection(conn, account.id, kind="gmail",
                                     decrypt=lambda cipher: cipher.decode().removeprefix("ENC(").removesuffix(")"))
    assert result["refresh_token"] == "real-refresh-token"
    assert result["email"] == "sam@example.test"
    assert result["scopes"] == ["gmail.readonly", "gmail.compose"]


def test_save_and_read_connection_activate_the_rls_tenant_scope_first():
    # Pins the fix: without this, the RLS policies in the migrations do nothing at all (see
    # tenancy._scope_to_tenant's docstring) - either every query fails closed, or isolation is
    # only ever enforced by this module remembering its own WHERE clauses, never the database.
    conn = FakeConn()
    account = tenancy.resolve_identity(conn, "subj-1", "sam@example.test")
    tenancy.save_connection(
        conn, account.id, kind="gmail", google_subject="subj-1", email="sam@example.test",
        scopes=["gmail.readonly"], refresh_token="t", encrypt=lambda p: p.encode(), kms_key_name="k")
    assert conn.store["tenant_scope_set_to"] == account.id
    assert conn.store["query_log"][-2] == "SELECT set_config"  # set immediately before the write
    tenancy.read_connection(conn, account.id, kind="gmail", decrypt=lambda c: c.decode())
    assert conn.store["query_log"][-2] == "SELECT set_config"  # and immediately before the read


def test_a_second_connect_for_the_same_identity_replaces_the_stored_token():
    conn = FakeConn()
    account = tenancy.resolve_identity(conn, "subj-1", "sam@example.test")
    kwargs = dict(account_id=account.id, kind="gmail", google_subject="subj-1", email="sam@example.test",
                 scopes=["gmail.readonly"], encrypt=lambda p: p.encode(), kms_key_name="k")
    tenancy.save_connection(conn, refresh_token="old-token", **kwargs)
    tenancy.save_connection(conn, refresh_token="new-token", **kwargs)
    result = tenancy.read_connection(conn, account.id, kind="gmail", decrypt=lambda c: c.decode())
    assert result["refresh_token"] == "new-token"
    assert len(conn.store["connections"]) == 1  # replaced, not a second row


def test_read_connection_is_none_when_nothing_is_connected():
    conn = FakeConn()
    account = tenancy.resolve_identity(conn, "subj-1", "sam@example.test")
    assert tenancy.read_connection(conn, account.id, kind="gmail", decrypt=lambda c: c) is None


def test_save_connection_refuses_an_unknown_kind():
    conn = FakeConn()
    account = tenancy.resolve_identity(conn, "subj-1", "sam@example.test")
    with pytest.raises(tenancy.TenancyError):
        tenancy.save_connection(conn, account.id, kind="calendar", google_subject="subj-1",
                                email="sam@example.test", scopes=[], refresh_token="t",
                                encrypt=lambda p: p, kms_key_name="k")


def test_save_connection_refuses_an_empty_token():
    conn = FakeConn()
    account = tenancy.resolve_identity(conn, "subj-1", "sam@example.test")
    with pytest.raises(tenancy.TenancyError):
        tenancy.save_connection(conn, account.id, kind="gmail", google_subject="subj-1",
                                email="sam@example.test", scopes=[], refresh_token="",
                                encrypt=lambda p: p, kms_key_name="k")


def test_save_connection_needs_an_explicit_encryptor():
    conn = FakeConn()
    account = tenancy.resolve_identity(conn, "subj-1", "sam@example.test")
    with pytest.raises(TypeError):
        tenancy.save_connection(conn, account.id, kind="gmail", google_subject="subj-1",
                                email="sam@example.test", scopes=[], refresh_token="t",
                                kms_key_name="k")


def test_read_connection_needs_an_explicit_decryptor():
    conn = FakeConn()
    account = tenancy.resolve_identity(conn, "subj-1", "sam@example.test")
    with pytest.raises(TypeError):
        tenancy.read_connection(conn, account.id, kind="gmail")


def test_a_new_account_has_no_sheet_yet():
    conn = FakeConn()
    account = tenancy.resolve_identity(conn, "subj-1", "sam@example.test")
    assert tenancy.get_sheet_id(conn, account.id) is None


def test_set_sheet_id_is_then_read_back():
    conn = FakeConn()
    account = tenancy.resolve_identity(conn, "subj-1", "sam@example.test")
    tenancy.set_sheet_id(conn, account.id, "sheet-123")
    assert tenancy.get_sheet_id(conn, account.id) == "sheet-123"


def test_set_sheet_id_refuses_a_blank_id():
    conn = FakeConn()
    account = tenancy.resolve_identity(conn, "subj-1", "sam@example.test")
    with pytest.raises(tenancy.TenancyError):
        tenancy.set_sheet_id(conn, account.id, "")


def test_set_sheet_id_refuses_an_unknown_account():
    conn = FakeConn()
    with pytest.raises(tenancy.TenancyError):
        tenancy.set_sheet_id(conn, "no-such-account", "sheet-123")


def test_two_accounts_have_independent_sheets():
    conn = FakeConn()
    a = tenancy.resolve_identity(conn, "subj-1", "sam@example.test")
    b = tenancy.resolve_identity(conn, "subj-2", "pat@example.test")
    tenancy.set_sheet_id(conn, a.id, "sheet-a")
    tenancy.set_sheet_id(conn, b.id, "sheet-b")
    assert tenancy.get_sheet_id(conn, a.id) == "sheet-a"
    assert tenancy.get_sheet_id(conn, b.id) == "sheet-b"


def test_a_new_account_has_no_lead_tabs_layout_yet():
    conn = FakeConn()
    account = tenancy.resolve_identity(conn, "subj-1", "sam@example.test")
    assert tenancy.get_lead_tabs(conn, account.id) is None


def test_set_lead_tabs_is_then_read_back():
    conn = FakeConn()
    account = tenancy.resolve_identity(conn, "subj-1", "sam@example.test")
    tenancy.set_lead_tabs(conn, account.id, {"Leads": "L"})
    assert tenancy.get_lead_tabs(conn, account.id) == {"Leads": "L"}


def test_set_lead_tabs_refuses_an_empty_mapping():
    conn = FakeConn()
    account = tenancy.resolve_identity(conn, "subj-1", "sam@example.test")
    with pytest.raises(tenancy.TenancyError):
        tenancy.set_lead_tabs(conn, account.id, {})


def test_set_lead_tabs_refuses_a_blank_name_or_prefix():
    conn = FakeConn()
    account = tenancy.resolve_identity(conn, "subj-1", "sam@example.test")
    with pytest.raises(tenancy.TenancyError):
        tenancy.set_lead_tabs(conn, account.id, {"": "L"})
    with pytest.raises(tenancy.TenancyError):
        tenancy.set_lead_tabs(conn, account.id, {"Leads": ""})


def test_clear_lead_tabs_resets_to_the_system_default():
    conn = FakeConn()
    account = tenancy.resolve_identity(conn, "subj-1", "sam@example.test")
    tenancy.set_lead_tabs(conn, account.id, {"Leads": "L"})
    tenancy.clear_lead_tabs(conn, account.id)
    assert tenancy.get_lead_tabs(conn, account.id) is None


def test_two_accounts_have_independent_lead_tab_layouts():
    conn = FakeConn()
    a = tenancy.resolve_identity(conn, "subj-1", "sam@example.test")
    b = tenancy.resolve_identity(conn, "subj-2", "pat@example.test")
    tenancy.set_lead_tabs(conn, a.id, {"Leads A": "A"})
    tenancy.set_lead_tabs(conn, b.id, {"Leads B": "B", "Referrals B": "R"})
    assert tenancy.get_lead_tabs(conn, a.id) == {"Leads A": "A"}
    assert tenancy.get_lead_tabs(conn, b.id) == {"Leads B": "B", "Referrals B": "R"}


def test_clear_sheet_id_unlinks_it():
    conn = FakeConn()
    account = tenancy.resolve_identity(conn, "subj-1", "sam@example.test")
    tenancy.set_sheet_id(conn, account.id, "sheet-123")
    tenancy.clear_sheet_id(conn, account.id)
    assert tenancy.get_sheet_id(conn, account.id) is None


def test_clear_sheet_id_refuses_an_unknown_account():
    conn = FakeConn()
    with pytest.raises(tenancy.TenancyError):
        tenancy.clear_sheet_id(conn, "no-such-account")
