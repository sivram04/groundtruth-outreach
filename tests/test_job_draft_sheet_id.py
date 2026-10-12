"""job_draft.py's Sheet-reading helpers accept an explicit sheet_id instead of always reading the
founder's hardcoded SHEET_ID - the piece that lets drafting run against one connected account's
own Sheet. Each helper is checked directly: given a different sheet_id, it asks for THAT id."""

from outreach import handbook_store, job_draft


class RecordingApi:
    """Captures every spreadsheetId a call was made with; returns empty results."""

    def __init__(self):
        self.spreadsheet_ids = []

    def values(self):
        return self

    def get(self, spreadsheetId=None, **kw):
        self.spreadsheet_ids.append(spreadsheetId)
        return self

    def batchUpdate(self, spreadsheetId=None, **kw):
        self.spreadsheet_ids.append(spreadsheetId)
        return self

    def append(self, spreadsheetId=None, **kw):
        self.spreadsheet_ids.append(spreadsheetId)
        return self

    def execute(self):
        return {"values": [], "sheets": []}


def test_records_reads_the_given_sheet_id():
    api = RecordingApi()
    job_draft._records(api, "Research", sheet_id="tenant-sheet-9")
    assert api.spreadsheet_ids == ["tenant-sheet-9"]


def test_suppressed_reads_the_given_sheet_id():
    api = RecordingApi()
    job_draft._suppressed(api, "owner@example.test", sheet_id="tenant-sheet-9")
    assert api.spreadsheet_ids == ["tenant-sheet-9"]


def test_call_effect_reads_the_given_sheet_id():
    api = RecordingApi()
    job_draft._call_effect(api, "A-0001", sheet_id="tenant-sheet-9")
    assert api.spreadsheet_ids == ["tenant-sheet-9"]


def test_handbook_store_active_reads_the_given_sheet_id():
    api = RecordingApi()
    handbook_store.active(api=api, sheet_id="tenant-sheet-9")
    assert api.spreadsheet_ids == ["tenant-sheet-9"]


def test_read_passes_the_sheet_id_to_tab_and_records(monkeypatch):
    captured = {}

    class FakeTab:
        def __init__(self, api, name, system, sheet_id=None):
            captured.setdefault("tab_sheet_ids", []).append(sheet_id)
            self.rows = [(3, {"Lead ID": "A-0001"})] if name == "A_Contact_Now" else []

    monkeypatch.setattr(job_draft, "Tab", FakeTab)
    monkeypatch.setattr(job_draft, "_records",
                       lambda api, name, header_row=1, sheet_id=None: captured.setdefault("records_sheet_id", sheet_id) and [])
    job_draft._read(RecordingApi(), ["A-0001"], sheet_id="tenant-sheet-9")
    assert captured["tab_sheet_ids"] == ["tenant-sheet-9", "tenant-sheet-9"]
    assert captured["records_sheet_id"] == "tenant-sheet-9"
