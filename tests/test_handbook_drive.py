"""The Drive handbook loader fails closed: no document, no drafting."""

import hashlib

import pytest
from googleapiclient.errors import HttpError

from outreach import handbook_drive

TEXT = ("Example Product is a cash-flow decision tool for construction subcontractors. " * 6).strip()
DOC_ID = "1AbCdEfGhIjKlMnOpQrStUvWxYz0123456789"


class FakeDrive:
    """Minimal Drive: files().get / export / get_media."""

    def __init__(self, meta=None, data=b"", error=None):
        self.meta, self.data, self.error = meta, data, error
        self.exported = []

    def files(self):
        return self

    def get(self, fileId, fields=None):
        if self.error and fields:
            raise self.error
        return _Exec(self.meta)

    def export(self, fileId, mimeType):
        self.exported.append(mimeType)
        if self.error:
            raise self.error
        return _Exec(self.data)

    def get_media(self, fileId):
        return _Exec(self.data)


class _Exec:
    def __init__(self, value):
        self.value = value

    def execute(self):
        return self.value


def doc(mime=handbook_drive.GOOGLE_DOC, **changes):
    meta = {"id": DOC_ID, "name": "Outreach handbook", "mimeType": mime,
            "modifiedTime": "2026-09-22T10:00:00Z", "version": "7"}
    meta.update(changes)
    return meta


def http_error(status):
    class Resp:
        pass
    resp = Resp()
    resp.status = status
    resp.reason = "denied"
    return HttpError(resp, b"{}")


def test_google_doc_is_exported_as_text_and_hashed():
    drive = FakeDrive(doc(), TEXT.encode())
    book = handbook_drive.load({"handbook_doc_id": DOC_ID}, drive=drive)
    assert drive.exported == ["text/plain"]
    assert book["text"] == TEXT and book["source"] == "drive"
    assert book["content_hash"] == hashlib.sha256(TEXT.encode()).hexdigest()
    assert book["document_id"] == DOC_ID and book["version"] == "7"


def test_editing_the_document_changes_the_hash():
    first = handbook_drive.load({"handbook_doc_id": DOC_ID}, drive=FakeDrive(doc(), TEXT.encode()))
    second = handbook_drive.load({"handbook_doc_id": DOC_ID},
                                 drive=FakeDrive(doc(), (TEXT + " One more line.").encode()))
    assert first["content_hash"] != second["content_hash"]


def test_plain_text_file_is_read_directly():
    drive = FakeDrive(doc(mime="text/plain"), TEXT.encode())
    assert handbook_drive.load({"handbook_doc_id": DOC_ID}, drive=drive)["text"] == TEXT
    assert drive.exported == []


@pytest.mark.parametrize("settings", [{}, {"handbook_doc_id": ""}, {"handbook_doc_id": "short"},
                                      {"handbook_doc_id": "has spaces in it here"}])
def test_missing_or_malformed_document_id_fails_closed(settings, monkeypatch):
    monkeypatch.delenv("HANDBOOK_DOC_ID", raising=False)
    with pytest.raises(handbook_drive.HandbookUnavailable):
        handbook_drive.load(settings, drive=FakeDrive(doc(), TEXT.encode()))


def test_environment_overrides_settings(monkeypatch):
    monkeypatch.setenv("HANDBOOK_DOC_ID", DOC_ID)
    assert handbook_drive.document_id({"handbook_doc_id": "zzz-other-document-id"}) == DOC_ID


@pytest.mark.parametrize("status,words", [(403, "scope"), (404, "not found"), (500, "HTTP 500")])
def test_drive_errors_fail_closed_with_a_reason(status, words):
    with pytest.raises(handbook_drive.HandbookUnavailable, match=words):
        handbook_drive.load({"handbook_doc_id": DOC_ID},
                            drive=FakeDrive(doc(), TEXT.encode(), error=http_error(status)))


@pytest.mark.parametrize("mime", ["application/pdf", "application/vnd.google-apps.spreadsheet",
                                  "image/png"])
def test_a_document_that_is_not_text_is_refused(mime):
    with pytest.raises(handbook_drive.HandbookUnavailable, match="Google Doc or text"):
        handbook_drive.load({"handbook_doc_id": DOC_ID}, drive=FakeDrive(doc(mime=mime), b"x"))


@pytest.mark.parametrize("data", [b"", b"too short to be a handbook"])
def test_empty_or_tiny_document_is_refused(data):
    with pytest.raises(handbook_drive.HandbookUnavailable, match="empty or too short"):
        handbook_drive.load({"handbook_doc_id": DOC_ID}, drive=FakeDrive(doc(), data))


def test_oversized_document_is_refused():
    with pytest.raises(handbook_drive.HandbookUnavailable, match="larger than"):
        handbook_drive.load({"handbook_doc_id": DOC_ID},
                            drive=FakeDrive(doc(), b"x" * (handbook_drive.MAX_CHARS + 1)))
