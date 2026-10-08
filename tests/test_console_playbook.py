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


def _store_with_api():
    store = MemoryStore([])
    store.api = object()  # the set route passes store().api to handbook_store (stubbed in tests)
    return store


def test_set_persists_the_playbook_as_the_live_source(built, monkeypatch):
    seen = {}

    def fake_set(text, *, set_by, name, source, api, now=None):
        seen.update(text=text, set_by=set_by, name=name, source=source)
        return "hash123"

    monkeypatch.setattr(console.handbook_store, "set_active", fake_set)
    client = make(built, store=lambda: _store_with_api())
    r = client.post("/api/playbook/set", headers=signed(), json={"text": "x" * 300, "name": "Pitch"})
    assert r.status_code == 200 and r.get_json()["content_hash"] == "hash123"
    assert seen["name"] == "Pitch" and seen["source"] == "console"
    assert seen["set_by"] and "@" in seen["set_by"]  # the IAP identity, never a client value


def test_set_refuses_a_playbook_that_is_too_short(built):
    # Real handbook_store.set_active raises ValueError on length BEFORE touching the Sheet.
    client = make(built, store=lambda: _store_with_api())
    r = client.post("/api/playbook/set", headers=signed(), json={"text": "tiny"})
    assert r.status_code == 422


def test_set_needs_a_signed_in_caller(built):
    client = make(built, store=lambda: _store_with_api())
    assert client.post("/api/playbook/set", json={"text": "x" * 300}).status_code in (401, 403, 503)


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


def _review_good(client):
    """Review a real DOCX of GOOD and return its JSON (text + a review_token: proof of review only)."""
    r = client.post("/api/playbook/review", headers=signed(),
                    data={"file": (_docx(GOOD.split("\n")), "playbook.docx")},
                    content_type="multipart/form-data")
    assert r.status_code == 200
    return r.get_json()


def _select(client, reviewed, headers=None):
    """Exchange a review token for a selection token at the explicit Select boundary."""
    return client.post("/api/playbook/select", headers=headers or signed(),
                       json={"text": reviewed["text"], "review_token": reviewed["review_token"]})


def test_review_returns_a_review_token_not_a_selection(built):
    # The review step proves review; it must not itself carry a selection token.
    reviewed = _review_good(make(built))
    assert reviewed["review_token"] and "selection_token" not in reviewed


def test_select_exchanges_a_review_token_then_preview_renders(built):
    client = make(built)
    reviewed = _review_good(client)
    sel = _select(client, reviewed)
    assert sel.status_code == 200
    selection = sel.get_json()
    assert selection["content_hash"] == reviewed["review"]["content_hash"]
    r = client.post("/api/playbook/preview", headers=signed(),
                    json={"text": reviewed["text"], "selection_token": selection["selection_token"],
                          "first_name": "Dana"})
    assert r.status_code == 200
    body = r.get_json()
    assert body["problems"] == [] and body["body"] and "Following up" in body["body"]
    assert body["body"].startswith("Hi Dana,")


def test_a_reviewed_but_never_selected_version_is_refused_at_preview(built):
    # A review token must NOT open a preview: only an explicit selection does.
    client = make(built)
    reviewed = _review_good(client)
    r = client.post("/api/playbook/preview", headers=signed(),
                    json={"text": reviewed["text"], "selection_token": reviewed["review_token"]})
    assert r.status_code == 403


def test_select_refuses_a_forged_or_changed_review_token(built):
    client = make(built)
    reviewed = _review_good(client)
    # A forged review token cannot be exchanged for a selection.
    forged = client.post("/api/playbook/select", headers=signed(),
                         json={"text": reviewed["text"], "review_token": "9999999999.deadbeef"})
    assert forged.status_code == 403
    # A valid review token does not cover changed text.
    changed = client.post("/api/playbook/select", headers=signed(),
                          json={"text": reviewed["text"] + "\nAn extra sentence.",
                                "review_token": reviewed["review_token"]})
    assert changed.status_code == 403


def test_select_needs_text_and_a_review_token(built):
    client = make(built)
    assert client.post("/api/playbook/select", headers=signed(),
                       json={"text": "", "review_token": ""}).status_code == 400


def test_direct_preview_without_a_valid_token_is_refused(built):
    # Posting arbitrary text with no token, or a forged token, must not yield a "selected" preview.
    client = make(built)
    assert client.post("/api/playbook/preview", headers=signed(), json={"text": GOOD}).status_code == 400
    forged = client.post("/api/playbook/preview", headers=signed(),
                         json={"text": GOOD, "selection_token": "9999999999.deadbeef"})
    assert forged.status_code == 403


def test_preview_refuses_a_changed_file_even_with_a_valid_selection(built):
    # The selection was minted for GOOD; previewing different text with it must be refused (re-select).
    client = make(built)
    reviewed = _review_good(client)
    selection = _select(client, reviewed).get_json()
    r = client.post("/api/playbook/preview", headers=signed(),
                    json={"text": reviewed["text"] + "\nAn extra sentence.",
                          "selection_token": selection["selection_token"]})
    assert r.status_code == 403


def test_a_selection_from_one_founder_does_not_work_for_another(built):
    client = make(built)
    reviewed = _review_good(client)  # minted for the default signed-in founder
    selection = _select(client, reviewed).get_json()
    other = client.post("/api/playbook/preview", headers={HEADER: token(email="intruder@lakshyaa.ai")},
                        json={"text": reviewed["text"], "selection_token": selection["selection_token"]})
    assert other.status_code in (401, 403)  # 401 if not allow-listed, else 403 on the token check


def test_preview_needs_a_selection(built):
    assert make(built).post("/api/playbook/preview", headers=signed(),
                            json={"text": "", "selection_token": ""}).status_code == 400


def test_an_oversized_upload_is_rejected_before_parsing(built):
    # The request-size bound is enforced before multipart parsing, so an oversized body is a 413.
    from outreach import playbook_extract
    big = io.BytesIO(b"x" * (playbook_extract.MAX_BYTES + 1000))
    r = make(built).post("/api/playbook/review", headers=signed(),
                         data={"file": (big, "big.docx")}, content_type="multipart/form-data")
    assert r.status_code == 413 and r.get_json()["reason"] == "too_large"


def test_an_oversized_upload_without_content_length_is_rejected(built):
    # The per-request limit is enforced even when Content-Length is not usable (chunked/streamed).
    from outreach import playbook_extract
    body = (b'--b\r\nContent-Disposition: form-data; name="file"; filename="big.docx"\r\n'
            b"Content-Type: application/octet-stream\r\n\r\n"
            + b"x" * (playbook_extract.MAX_BYTES + 1000) + b"\r\n--b--\r\n")
    r = make(built).post("/api/playbook/review", headers=signed(),
                         data=body, content_type="multipart/form-data; boundary=b")
    assert r.status_code == 413 and r.get_json()["reason"] == "too_large"


def test_oversized_preview_json_is_rejected_before_parsing(built):
    from outreach import playbook_extract
    huge = "x" * (playbook_extract.MAX_BYTES + 1000)
    r = make(built).post("/api/playbook/preview", headers=signed(),
                         json={"text": huge, "selection_token": "9999999999.deadbeef"})
    assert r.status_code == 413


def test_oversized_select_json_is_rejected_before_parsing(built):
    from outreach import playbook_extract
    huge = "x" * (playbook_extract.MAX_BYTES + 1000)
    r = make(built).post("/api/playbook/select", headers=signed(),
                         json={"text": huge, "review_token": "9999999999.deadbeef"})
    assert r.status_code == 413


def test_playbook_is_off_unless_switched_on(built):
    client = console.create_app(
        verifier=console_auth.Verifier(AUDIENCE, ALLOWED, fetch=Keys()), store=lambda: MemoryStore([]),
        settings=lambda: dict(OFFER), clock=lambda: None, static_dir=built).test_client()
    assert client.post("/api/playbook/review", headers=signed()).status_code == 404
    assert client.post("/api/playbook/preview", headers=signed(), json={}).status_code == 404


def test_playbook_needs_a_signed_in_session(built):
    assert make(built).post("/api/playbook/review").status_code == 401
    assert make(built).post("/api/playbook/preview", json={}).status_code == 401
