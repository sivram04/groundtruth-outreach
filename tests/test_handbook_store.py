"""The durable Playbook store: a stored playbook becomes the live handbook only when the founder has
switched it on, latest row wins, and it carries the Drive handbook's shape so hashes stay consistent."""

import pytest

from outreach import handbook_store, job_draft, playbook

TEXT = ("Initial email\n\n" + "We help specialty-trade subcontractors stay ahead of cash. " * 12)


class _Exec:
    def __init__(self, fn):
        self.fn = fn

    def execute(self):
        return self.fn()


class _Values:
    def __init__(self, api):
        self.api = api

    @staticmethod
    def _name(rng):
        return rng.strip("'").split("!")[0].strip("'")

    def get(self, spreadsheetId, range):
        name = self._name(range)
        return _Exec(lambda: {"values": [list(r) for r in self.api.tabs.get(name, [])]})

    def append(self, spreadsheetId, range, valueInputOption, body):
        name = self._name(range)

        def run():
            self.api.tabs.setdefault(name, []).extend([list(r) for r in body["values"]])
            return {}

        return _Exec(run)

    def update(self, spreadsheetId, range, valueInputOption, body):
        name = self._name(range)

        def run():
            self.api.tabs[name] = [list(r) for r in body["values"]]
            return {}

        return _Exec(run)


class FakeApi:
    """The slice of the Sheets client handbook_store and ensure_tab use."""

    def __init__(self, tabs=None):
        self.tabs = {k: [list(r) for r in v] for k, v in (tabs or {}).items()}

    def values(self):
        return _Values(self)

    def get(self, spreadsheetId):
        return _Exec(lambda: {"sheets": [{"properties": {"title": t}} for t in self.tabs]})

    def batchUpdate(self, spreadsheetId, body):
        title = body["requests"][0]["addSheet"]["properties"]["title"]

        def run():
            self.api_add(title)
            return {}

        return _Exec(run)

    def api_add(self, title):
        self.tabs.setdefault(title, [])


def test_active_is_none_when_no_playbook_is_stored():
    assert handbook_store.active(api=FakeApi()) is None  # no tab/rows -> Drive stays the source


def test_set_then_active_returns_the_stored_playbook():
    api = FakeApi()
    h = handbook_store.set_active(TEXT, set_by="admin@lakshyaa.ai", name="Pitch", api=api)
    book = handbook_store.active(api=api)
    assert book["source"] == "stored" and book["text"] == playbook.normalize(TEXT)
    assert book["content_hash"] == h == playbook.content_hash(TEXT)
    assert book["name"] == "Pitch" and book["document_id"].startswith("playbook:")


def test_the_latest_row_wins():
    api = FakeApi()
    handbook_store.set_active(TEXT, set_by="a@x", api=api)
    newer = TEXT + "\n\nWe also read bank balances and open invoices to see weeks ahead."
    handbook_store.set_active(newer, set_by="a@x", api=api)
    assert handbook_store.active(api=api)["text"] == playbook.normalize(newer)


def test_active_is_none_for_text_too_short_to_be_a_playbook():
    api = FakeApi(tabs={handbook_store.TAB: [handbook_store.HEADER,
                                             ["2026-10-08", "a@x", "upload", "", "h", "too short"]]})
    assert handbook_store.active(api=api) is None


def test_set_active_rejects_text_that_is_too_short():
    with pytest.raises(ValueError):
        handbook_store.set_active("tiny", set_by="a@x", api=FakeApi())


def test_set_active_needs_a_setter():
    with pytest.raises(ValueError):
        handbook_store.set_active(TEXT, set_by="", api=FakeApi())


def test_job_draft_handbook_uses_a_stored_playbook_when_a_client_is_passed():
    api = FakeApi()
    handbook_store.set_active(TEXT, set_by="admin@lakshyaa.ai", api=api)
    book, why = job_draft._handbook({}, api=api)
    assert why is None and book["source"] == "stored" and book["text"] == playbook.normalize(TEXT)


def test_job_draft_handbook_skips_the_store_when_no_client_is_passed(monkeypatch):
    # Without an api, the store is never consulted; the Drive loader is (and fails closed here).
    monkeypatch.setattr(job_draft.handbook_drive, "load",
                        lambda settings, drive=None: (_ for _ in ()).throw(
                            job_draft.handbook_drive.HandbookUnavailable("no drive")))
    book, why = job_draft._handbook({})
    assert book is None and "handbook unavailable" in why
