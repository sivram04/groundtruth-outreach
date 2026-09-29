"""The console's server: every request proves who sent it, the data is read-only, and the
page files are served only behind the same check."""

import pytest

import console_fixture as fx
from outreach import assistant, console, console_auth
from stage4_fakes import MemoryStore
from test_console_auth import AUDIENCE, ALLOWED, Keys, token

HEADER = console_auth.HEADER


@pytest.fixture
def built(tmp_path):
    (tmp_path / "assets").mkdir()
    (tmp_path / "index.html").write_text("<!doctype html><div id=root></div>", encoding="utf-8")
    (tmp_path / "assets" / "app-abc123.js").write_text("console.log(1)", encoding="utf-8")
    return tmp_path


def store():
    return MemoryStore(fx.rows(), events=fx.events(), suppression=fx.suppression(), runs=fx.runs(),
                       drafts=fx.draft_rows())


def app(static, **changes):
    options = dict(verifier=console_auth.Verifier(AUDIENCE, ALLOWED, fetch=Keys()),
                   store=store, settings=lambda: dict(fx.SETTINGS), clock=lambda: fx.NOW,
                   static_dir=static, handbook_doc_id=fx.HANDBOOK)
    options.update(changes)
    return console.create_app(**options).test_client()


def signed(**claims):
    return {HEADER: token(**claims)}


def test_the_data_is_the_console_worked_out_from_the_sheet(built):
    response = app(built).get("/api/snapshot", headers=signed())
    assert response.status_code == 200
    assert response.get_json() == fx.snapshot()
    assert response.headers["Cache-Control"] == "no-store"


def test_nothing_is_served_without_a_token(built):
    client = app(built)
    for path in ("/api/snapshot", "/", "/assets/app-abc123.js"):
        response = client.get(path)
        assert response.status_code == 401, path
    assert client.get("/api/snapshot").get_json() == {
        "error": "no sign-in token: open the console through its Google sign-in"}
    assert client.get("/").mimetype == "text/plain"


def test_googles_plain_email_header_alone_lets_nobody_in(built):
    response = app(built).get("/api/snapshot", headers={
        "X-Goog-Authenticated-User-Email": "accounts.google.com:admin@lakshyaa.ai"})
    assert response.status_code == 401


def test_a_signed_in_person_not_on_the_list_is_forbidden(built):
    response = app(built).get("/api/snapshot", headers=signed(email="guest@lakshyaa.ai"))
    assert response.status_code == 403


def test_a_console_that_is_not_configured_opens_for_nobody(built):
    client = app(built, verifier=None)
    for path in ("/api/snapshot", "/"):
        assert client.get(path, headers=signed()).status_code == 503


def test_the_page_and_its_files_are_served_to_the_signed_in_founder(built):
    client = app(built)
    page = client.get("/", headers=signed())
    assert page.status_code == 200 and b'<div id=root>' in page.data
    asset = client.get("/assets/app-abc123.js", headers=signed())
    assert asset.status_code == 200
    assert asset.headers["Cache-Control"] == "private, max-age=31536000, immutable"
    assert client.get("/assets/missing.js", headers=signed()).status_code == 404


def test_a_file_outside_the_built_folder_cannot_be_reached(built, tmp_path):
    client = app(built / "assets")  # the built folder's parent holds index.html
    for path in ("/assets/..%2Findex.html", "/assets/%2e%2e/index.html", "/assets/../../etc/passwd"):
        assert client.get(path, headers=signed()).status_code == 404, path


def test_pages_not_built_say_so(tmp_path):
    response = app(tmp_path).get("/", headers=signed())
    assert response.status_code == 503


def test_every_response_carries_the_security_headers(built):
    client = app(built)
    for path in ("/api/snapshot", "/", "/assets/app-abc123.js", "/nowhere"):
        headers = client.get(path, headers=signed()).headers
        assert "script-src 'self'" in headers["Content-Security-Policy"], path
        assert "frame-ancestors 'none'" in headers["Content-Security-Policy"]
        assert headers["X-Content-Type-Options"] == "nosniff"
        assert headers["X-Frame-Options"] == "DENY"
        assert headers["Referrer-Policy"] == "no-referrer"


def test_the_console_only_reads(built):
    client = app(built)
    for method in ("post", "put", "patch", "delete"):
        response = getattr(client, method)("/api/snapshot", headers=signed())
        assert response.status_code == 405, method
    unsigned = client.post("/api/snapshot")
    assert unsigned.status_code == 401  # the sign-in check comes first, whatever the method
    routes = {rule.rule: rule.methods for rule in console.create_app(verifier=None).url_map.iter_rules()}
    # The assistant's is the one route that is not a GET, and it only reads.
    assert routes.pop("/api/ask") <= {"POST", "OPTIONS"}
    assert all(methods <= {"GET", "HEAD", "OPTIONS"} for methods in routes.values())


def test_serving_the_data_writes_nothing_to_the_sheet(built):
    shared = store()
    before = (shared.leads(), shared.events(), shared.suppression(), list(shared.runs))
    client = app(built, store=lambda: shared)
    for _ in range(3):
        assert client.get("/api/snapshot", headers=signed()).status_code == 200
    assert (shared.leads(), shared.events(), shared.suppression(), list(shared.runs)) == before
    assert shared.lead_writes == [] and shared.columns_added == []


# --- the assistant --------------------------------------------------------------------------

def answering(said):
    def model(prompt, schema):
        model.prompt = prompt
        return said, {"totalTokenCount": 120}
    model.prompt = ""
    return model


def asked(client, question="What needs me today?", **body):
    return client.post("/api/ask", headers=signed(), json={"question": question, **body})


def test_the_assistant_answers_one_question_about_the_sheet(built, monkeypatch):
    model = answering({"answer": "Acme Plumbing replied. Answer it by hand.",
                       "lead_ids": ["A-0002"],
                       "link": {"page": "lead", "lead_id": "A-0002", "label": "Open it"}})
    monkeypatch.setattr(assistant.gemini, "generate_json", model)
    response = asked(app(built))
    assert response.status_code == 200
    assert response.get_json() == {"answer": "Acme Plumbing replied. Answer it by hand.",
                                   "lead_ids": ["A-0002"], "tokens": 120, "refused": False,
                                   "link": {"page": "lead", "lead_id": "A-0002",
                                            "label": "Open it", "show": ""}}
    assert "Acme Plumbing" in model.prompt and "What needs me today?" in model.prompt


def test_a_refused_answer_is_said_in_words_and_never_shown(built, monkeypatch):
    monkeypatch.setattr(assistant.gemini, "generate_json",
                        answering({"answer": "You have 4,318 leads waiting."}))
    body = asked(app(built)).get_json()
    assert body["refused"] is True and "4,318" not in body["answer"]
    assert "have not answered" in body["answer"]


def test_nobody_may_ask_without_signing_in(built, monkeypatch):
    def forbidden(prompt, schema):
        raise AssertionError("the model was called")

    monkeypatch.setattr(assistant.gemini, "generate_json", forbidden)
    assert app(built).post("/api/ask", json={"question": "anything"}).status_code == 401


def test_asking_writes_nothing_to_the_sheet(built, monkeypatch):
    monkeypatch.setattr(assistant.gemini, "generate_json", answering({"answer": "Nothing needs you."}))
    shared = store()
    before = (shared.leads(), shared.events(), shared.suppression(), list(shared.runs))
    client = app(built, store=lambda: shared)
    assert asked(client).status_code == 200
    assert (shared.leads(), shared.events(), shared.suppression(), list(shared.runs)) == before
    assert shared.lead_writes == [] and shared.draft_writes == []


def test_a_sheet_that_cannot_be_read_is_never_answered_from(built, monkeypatch):
    def forbidden(prompt, schema):
        raise AssertionError("the model was called")

    monkeypatch.setattr(assistant.gemini, "generate_json", forbidden)

    def broken():
        raise RuntimeError("no Sheet")

    response = asked(app(built, store=broken))
    assert response.status_code == 502


def test_a_sheet_that_cannot_be_read_is_a_clear_error_without_details(built):
    def broken():
        raise RuntimeError("secret internal detail")

    response = app(built, store=broken).get("/api/snapshot", headers=signed())
    assert response.status_code == 502
    assert "secret internal detail" not in response.get_data(as_text=True)
    assert "could not be read" in response.get_json()["error"]


def test_unreadable_settings_leave_the_rest_of_the_console_working(built):
    def broken():
        raise ValueError("bad json")

    response = app(built, settings=broken).get("/api/snapshot", headers=signed())
    assert response.status_code == 200
    assert response.get_json()["approvals"] is None
