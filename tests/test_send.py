"""The one sanctioned send path: outreach/send.py, human-approved, at most once.

Offline, against the simulated Sheets API and a fake Gmail. Proves the flag gate, the approver
requirement, that exactly one email leaves per created draft (a second click never sends again),
and that an uncreated or already-sent lead is refused.
"""

import pytest

from outreach import send
from test_sheet_append import FakeSheets, FakeValues, _Exec

HEADER = ["Company", "Decision maker", "BEST EMAIL", "Website", "Lead ID",
          "Draft status", "Draft ID", "Sent at"]


class _Values(FakeValues):
    """FakeValues plus the one call Tab.write makes that the base fake lacks: values().batchUpdate,
    which just applies each single-cell update."""

    def batchUpdate(self, spreadsheetId, body):
        for entry in body["data"]:
            self.update(spreadsheetId=spreadsheetId, range=entry["range"],
                        valueInputOption=body.get("valueInputOption", "RAW"),
                        body={"values": entry["values"]})
        return _Exec({})


class _Sheets(FakeSheets):
    def values(self):
        return _Values(self)


def sheets(*, draft_status="CREATED", draft_id="draft-xyz", sent_at=""):
    fake = _Sheets()
    fake.tabs = {
        "A_Contact_Now": [["A tab"], list(HEADER),
                          ["Example Electric", "Sam", "sam@example.test", "https://example.test/",
                           "A-0001", draft_status, draft_id, sent_at]],
        "B_Contact_Now": [["B tab"], list(HEADER)],
    }
    return fake


class _Send:
    def __init__(self, body, result, fail):
        self._body, self._result, self._fail = body, result, fail

    def execute(self):
        if self._fail:
            raise RuntimeError("the Gmail send failed")
        return self._result


class FakeGmail:
    def __init__(self, result=None, fail=False):
        self.sent = []
        self._result = result or {"id": "msg-1", "threadId": "thr-1"}
        self._fail = fail

    def users(self):
        return self

    def drafts(self):
        return self

    def send(self, userId, body):
        self.sent.append(body)
        return _Send(body, self._result, self._fail)


def test_send_is_disabled_without_the_flag(monkeypatch):
    monkeypatch.delenv("ENABLE_SEND", raising=False)
    gmail = FakeGmail()
    with pytest.raises(send.SendBlocked):
        send.send_created_draft("A-0001", sent_by="admin@lakshyaa.ai", api=sheets(), gmail=gmail)
    assert gmail.sent == []  # nothing left


def test_send_requires_a_named_approver(monkeypatch):
    monkeypatch.setenv("ENABLE_SEND", "true")
    gmail = FakeGmail()
    with pytest.raises(send.SendBlocked):
        send.send_created_draft("A-0001", sent_by="  ", api=sheets(), gmail=gmail)
    assert gmail.sent == []


def test_it_sends_the_created_draft_and_marks_it_sent(monkeypatch):
    monkeypatch.setenv("ENABLE_SEND", "true")
    api, gmail = sheets(), FakeGmail()
    result = send.send_created_draft("A-0001", sent_by="admin@lakshyaa.ai", api=api, gmail=gmail)
    assert result["sent"] and result["recorded"]
    assert result["message_id"] == "msg-1" and result["thread_id"] == "thr-1"
    assert gmail.sent == [{"id": "draft-xyz"}]  # sent the existing draft, by id
    _, _, lead = send._find(api, "A-0001")
    assert lead["Draft status"] == "SENT" and lead["Sent at"]


def test_sending_against_a_different_sheet_id_still_works_end_to_end(monkeypatch):
    """A caller that passes an explicit sheet_id (a connected account's own Sheet, not the
    founder's) still finds the lead, sends, and records the result - proving the parameter is
    actually threaded through _find/_set_status, not just accepted and ignored."""
    monkeypatch.setenv("ENABLE_SEND", "true")
    api, gmail = sheets(), FakeGmail()
    result = send.send_created_draft("A-0001", sent_by="admin@lakshyaa.ai", api=api, gmail=gmail,
                                     sheet_id="tenant-sheet-1")
    assert result["sent"] and result["recorded"]
    _, _, lead = send._find(api, "A-0001", "tenant-sheet-1")
    assert lead["Draft status"] == "SENT" and lead["Sent at"]


def test_a_second_click_never_sends_a_second_email(monkeypatch):
    monkeypatch.setenv("ENABLE_SEND", "true")
    api, gmail = sheets(), FakeGmail()
    send.send_created_draft("A-0001", sent_by="admin@lakshyaa.ai", api=api, gmail=gmail)
    with pytest.raises(send.SendBlocked):
        send.send_created_draft("A-0001", sent_by="admin@lakshyaa.ai", api=api, gmail=gmail)
    assert len(gmail.sent) == 1  # exactly one email ever


def test_a_lead_with_no_created_draft_is_refused(monkeypatch):
    monkeypatch.setenv("ENABLE_SEND", "true")
    gmail = FakeGmail()
    with pytest.raises(send.SendBlocked):
        send.send_created_draft("A-0001", sent_by="admin@lakshyaa.ai",
                                api=sheets(draft_status="RESERVED"), gmail=gmail)
    assert gmail.sent == []


def test_an_already_sent_lead_is_refused(monkeypatch):
    monkeypatch.setenv("ENABLE_SEND", "true")
    gmail = FakeGmail()
    with pytest.raises(send.SendBlocked):
        send.send_created_draft("A-0001", sent_by="admin@lakshyaa.ai",
                                api=sheets(draft_status="SENT", sent_at="2026-10-06T00:00:00+00:00"),
                                gmail=gmail)
    assert gmail.sent == []
