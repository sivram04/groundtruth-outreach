"""outreach/tenant_sheet.py against a fake Sheets client and a fake DB cursor."""

import pytest

from outreach import tenancy, tenant_sheet


class FakeCursor:
    def __init__(self, store):
        self.store = store
        self.rowcount = 0

    def execute(self, sql, params=()):
        sql = " ".join(sql.split())
        if sql.startswith("INSERT INTO tenant.accounts"):
            account_id, name = params
            self.store["accounts"][account_id] = name
        elif sql.startswith("SELECT sheet_id FROM tenant.accounts"):
            (account_id,) = params
            self._last = [(self.store["sheet_ids"].get(account_id),)] if account_id in self.store["accounts"] else []
        elif sql.startswith("UPDATE tenant.accounts SET sheet_id"):
            sheet_id, account_id = params
            if account_id in self.store["accounts"]:
                self.store["sheet_ids"][account_id] = sheet_id
                self.rowcount = 1
        else:
            raise AssertionError(f"FakeCursor does not know this query: {sql}")

    def fetchone(self):
        return self._last[0] if getattr(self, "_last", None) else None


class FakeConn:
    def __init__(self):
        self.store = {"accounts": {}, "sheet_ids": {}}

    def cursor(self):
        return FakeCursor(self.store)


class FakeApi:
    """Enough of the Sheets `spreadsheets()` client for ensure_sheet: `create` and `get`."""

    def __init__(self, openable=()):
        self.openable = set(openable)
        self.created = []

    def create(self, body=None):
        title = body["properties"]["title"]
        new_id = f"new-{len(self.created) + 1}"
        self.created.append(title)
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


def _account(conn):
    conn.store["accounts"]["acc-1"] = "Sam"
    return "acc-1"


def test_a_new_account_gets_a_freshly_created_sheet():
    conn, api = FakeConn(), FakeApi()
    account_id = _account(conn)
    sheet_id = tenant_sheet.ensure_sheet(api, conn, account_id)
    assert sheet_id == "new-1"
    assert tenancy.get_sheet_id(conn, account_id) == "new-1"
    assert api.created == ["Lakshyaa outreach leads"]


def test_an_account_that_already_has_a_sheet_keeps_it():
    conn, api = FakeConn(), FakeApi()
    account_id = _account(conn)
    first = tenant_sheet.ensure_sheet(api, conn, account_id)
    second = tenant_sheet.ensure_sheet(api, conn, account_id, title="Different title")
    assert first == second
    assert len(api.created) == 1


def test_linking_an_existing_openable_sheet_stores_it_instead_of_creating_one():
    conn, api = FakeConn(), FakeApi(openable=["existing-sheet"])
    account_id = _account(conn)
    sheet_id = tenant_sheet.ensure_sheet(api, conn, account_id, link_sheet_id="existing-sheet")
    assert sheet_id == "existing-sheet"
    assert tenancy.get_sheet_id(conn, account_id) == "existing-sheet"
    assert api.created == []


def test_linking_a_sheet_this_account_cannot_open_is_refused():
    conn, api = FakeConn(), FakeApi(openable=[])
    account_id = _account(conn)
    with pytest.raises(tenant_sheet.LinkRefused):
        tenant_sheet.ensure_sheet(api, conn, account_id, link_sheet_id="not-mine")
    assert tenancy.get_sheet_id(conn, account_id) is None


def test_two_accounts_each_get_their_own_sheet():
    conn, api = FakeConn(), FakeApi()
    conn.store["accounts"]["acc-1"] = "Sam"
    conn.store["accounts"]["acc-2"] = "Pat"
    a = tenant_sheet.ensure_sheet(api, conn, "acc-1")
    b = tenant_sheet.ensure_sheet(api, conn, "acc-2")
    assert a != b
    assert tenancy.get_sheet_id(conn, "acc-1") == a
    assert tenancy.get_sheet_id(conn, "acc-2") == b
