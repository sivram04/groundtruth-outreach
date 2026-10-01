"""The playbook routes through the real Flask app: upload -> review -> select-by-hash -> candidate preview.
Read-only and local; off unless switched on. No Gmail, no Drive, no send."""

import io

import pytest

from outreach import console, console_auth, playbook
from stage4_fakes import MemoryStore
from test_console_auth import ALLOWED, AUDIENCE, Keys, token
from test_playbook import GOOD

HEADER = console_auth.HEADER
OFFER = {"product_name": "Lakshyaa", "sender_name": "A Founder", "founder_title": "Founder",
         "sender_website": "https://example.test", "postal_address": "1 Example St, Columbus OH",
         "sender_phone": "614-555-0100"}


@pytest.fixture
def built(tmp_path):
    (tmp_path / "assets").mkdir()
    (tmp_path / "index.html").write_text("<!doctype html><div id=root></div>", encoding="utf-8")
    return tmp_path


def signed(**claims):
    return {HEADER: token(**claims)}


def make(built, **changes):
    options = dict(verifier=console_auth.Verifier(AUDIENCE, ALLOWED, fetch=Keys()),
                   store=lambda: MemoryStore([]), settings=lambda: dict(OFFER), clock=lambda: None,
                   static_dir=built, enable_playbook=True)
    options.update(changes)
    return console.create_app(**options).test_client()


def _docx(paragraphs):
    import docx
    document = docx.Document()
    for p in paragraphs:
        document.add_paragraph(p)
    buffer = io.BytesIO()
    document.save(buffer)
    buffer.seek(0)
    return buffer


def test_review_extracts_and_reviews_a_docx(built):
    client = make(built)
    data = _docx(GOOD.split("\n"))
    r = client.post("/api/playbook/review", headers=signed(),
                    data={"file": (data, "playbook.docx")}, content_type="multipart/form-data")
    assert r.status_code == 200
    body = r.get_json()
    assert body["kind"] == "docx"
    assert body["review"]["initial_email"]["present"] and body["review"]["follow_ups"]["1"]["present"]
    assert body["review"]["content_hash"] and body["text"].strip()


def test_review_rejects_an_unsupported_file(built):
    r = make(built).post("/api/playbook/review", headers=signed(),
                         data={"file": (io.BytesIO(b"just notes"), "notes.txt")},
                         content_type="multipart/form-data")
    assert r.status_code == 422 and r.get_json()["reason"] == "unsupported"


def test_review_needs_a_file(built):
    assert make(built).post("/api/playbook/review", headers=signed()).status_code == 400


def test_preview_renders_a_followup_from_the_selected_version(built):
    client = make(built)
    r = client.post("/api/playbook/preview", headers=signed(),
                    json={"text": GOOD, "content_hash": playbook.content_hash(GOOD), "first_name": "Dana"})
    assert r.status_code == 200
    body = r.get_json()
    assert body["problems"] == [] and body["body"] and "Following up" in body["body"]
    assert body["body"].startswith("Hi Dana,") and body["content_hash"] == playbook.content_hash(GOOD)


def test_preview_refuses_a_changed_file(built):
    # The selected hash is for GOOD, but the posted text changed: a changed file must be reviewed again.
    client = make(built)
    r = client.post("/api/playbook/preview", headers=signed(),
                    json={"text": GOOD + "\nAn extra sentence.", "content_hash": playbook.content_hash(GOOD)})
    assert r.status_code == 409


def test_preview_needs_a_selection(built):
    assert make(built).post("/api/playbook/preview", headers=signed(),
                            json={"text": "", "content_hash": ""}).status_code == 400


def test_playbook_is_off_unless_switched_on(built):
    client = console.create_app(
        verifier=console_auth.Verifier(AUDIENCE, ALLOWED, fetch=Keys()), store=lambda: MemoryStore([]),
        settings=lambda: dict(OFFER), clock=lambda: None, static_dir=built).test_client()
    assert client.post("/api/playbook/review", headers=signed()).status_code == 404
    assert client.post("/api/playbook/preview", headers=signed(), json={}).status_code == 404


def test_playbook_needs_a_signed_in_session(built):
    assert make(built).post("/api/playbook/review").status_code == 401
    assert make(built).post("/api/playbook/preview", json={}).status_code == 401
