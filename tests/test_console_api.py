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
    # Beside the console itself, the data names the build of the pages the server has.
    assert response.get_json() == {**fx.snapshot(), "build": ""}
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


def test_the_page_is_never_kept_by_a_browser_but_its_files_are(built):
    """A kept page would go on running an older console after a deploy."""
    client = app(built)
    page = client.get("/", headers=signed())
    assert page.headers["Cache-Control"] == "no-store"
    assert "ETag" not in page.headers and "Last-Modified" not in page.headers
    asset = client.get("/assets/app-abc123.js", headers=signed())
    assert asset.headers["Cache-Control"] == "private, max-age=31536000, immutable"


def test_the_data_names_the_build_the_server_has(built):
    """The pages compare it with their own script's name and say when they are older."""
    (built / "index.html").write_text(
        '<!doctype html><script type="module" crossorigin src="/assets/index-NEW123.js"></script>',
        encoding="utf-8")
    assert app(built).get("/api/snapshot", headers=signed()).get_json()["build"] == "index-NEW123.js"
    (built / "index.html").write_text("<!doctype html><div id=root></div>", encoding="utf-8")
    assert app(built).get("/api/snapshot", headers=signed()).get_json()["build"] == ""


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


# --- the human evidence-review flow (only when explicitly enabled) ---------------------------
# The console is read-only by default. When the review flow is switched on, a person can read a
# candidate beside its cited evidence and confirm or reject it; the decision is attributed to the
# IAP-verified signed-in reviewer and written to the injected store, never to the live Sheet.

import json  # noqa: E402

from outreach import review  # noqa: E402

WRITTEN = {
    "subject": "A conversation about a preview next week",
    "sentences": [{"text": "Cobalt Glass installs glass facades for commercial buildings.",
                   "kind": "COMPANY", "quote_id": "q1"},
                  {"text": "I'm building a cash-flow tool for subcontractors.", "kind": "PRODUCT",
                   "quote_id": ""}],
    "evidence": {"quote_id": "q1", "category": "OFFERING",
                 "quote": "We install glass facades for commercial buildings.",
                 "url": "https://cobalt-glass.test/services"},
}


def review_rows():
    row = {"Lead ID": "A-0014", "Email": "First email", "To": "rene@cobalt-glass.test",
           "Company": "Cobalt Glass", "Subject": WRITTEN["subject"],
           "Body": "Hi Rene,\n\n" + WRITTEN["sentences"][0]["text"] + "\n\nBest,",
           "Opening quote": WRITTEN["evidence"]["quote"], "Quote page": WRITTEN["evidence"]["url"],
           "Status": "READY", "Why": "", "Approval hash": "", "Handbook hash": "hash-one",
           "Written": json.dumps(WRITTEN), "Prepared at (UTC)": "2026-09-28 12:40:00"}
    return [row]


def review_app(static, reviews=None, **changes):
    shared = MemoryStore(fx.rows(), events=fx.events(), suppression=fx.suppression(),
                         runs=fx.runs(), drafts=review_rows())
    return app(static, store=lambda: shared, enable_review=True,
               review_store=reviews if reviews is not None else review.MemoryReviewStore(),
               **changes)


def test_the_review_routes_are_absent_unless_the_flow_is_enabled(built):
    client = app(built)  # default: review off
    assert client.get("/api/review/A-0014", headers=signed()).status_code == 404
    assert client.post("/api/review/A-0014", headers=signed(),
                       json={"decision": "confirm"}).status_code == 404


def test_the_candidate_is_shown_beside_its_evidence(built):
    response = review_app(built).get("/api/review/A-0014", headers=signed())
    assert response.status_code == 200
    view = response.get_json()
    assert view["subject"] == WRITTEN["subject"]
    assert view["evidence"]["quote"] == WRITTEN["evidence"]["quote"]
    assert view["claims"][0]["kind"] == "COMPANY"
    assert "not automated proof" in view["note"]
    assert view["review"]["decision"] is None and len(view["fingerprint"]) == 64


def test_a_lead_with_no_candidate_has_nothing_to_review(built):
    assert review_app(built).get("/api/review/A-9999", headers=signed()).status_code == 404


def test_confirming_records_the_signed_in_reviewer(built):
    reviews = review.MemoryReviewStore()
    client = review_app(built, reviews=reviews)
    fingerprint = client.get("/api/review/A-0014", headers=signed()).get_json()["fingerprint"]
    done = client.post("/api/review/A-0014", headers=signed(),
                       json={"decision": "confirm", "fingerprint": fingerprint})
    assert done.status_code == 200 and done.get_json()["review"]["current"] is True
    record = reviews.get("A-0014")
    # The reviewer is the IAP-verified signed-in identity, not anything the client sent.
    assert record["reviewer"] == "admin@lakshyaa.ai" and record["decision"] == "confirmed"
    assert record["fingerprint"] == fingerprint


def test_a_review_of_a_changed_candidate_is_refused(built):
    client = review_app(built)
    stale = client.post("/api/review/A-0014", headers=signed(),
                        json={"decision": "confirm", "fingerprint": "a" * 64})
    assert stale.status_code == 409


def test_rejecting_is_recorded(built):
    reviews = review.MemoryReviewStore()
    client = review_app(built, reviews=reviews)
    fingerprint = client.get("/api/review/A-0014", headers=signed()).get_json()["fingerprint"]
    client.post("/api/review/A-0014", headers=signed(),
                json={"decision": "reject", "fingerprint": fingerprint})
    assert reviews.get("A-0014")["decision"] == "rejected"


def test_a_review_action_needs_a_valid_decision(built):
    client = review_app(built)
    fingerprint = client.get("/api/review/A-0014", headers=signed()).get_json()["fingerprint"]
    bad = client.post("/api/review/A-0014", headers=signed(),
                      json={"decision": "maybe", "fingerprint": fingerprint})
    assert bad.status_code == 400


def test_the_review_routes_still_require_signing_in(built):
    client = review_app(built)
    assert client.get("/api/review/A-0014").status_code == 401
    assert client.post("/api/review/A-0014", json={"decision": "confirm"}).status_code == 401


# --- item 4: the reviewer is the verified identity, never a client-supplied field ------------

def test_a_client_supplied_reviewer_field_is_ignored(built):
    reviews = review.MemoryReviewStore()
    client = review_app(built, reviews=reviews)
    fingerprint = client.get("/api/review/A-0014", headers=signed()).get_json()["fingerprint"]
    client.post("/api/review/A-0014", headers=signed(),
                json={"decision": "confirm", "fingerprint": fingerprint,
                      "reviewer": "ceo@evil.test", "email": "ceo@evil.test"})
    # The recorded reviewer is the IAP-verified signed-in identity, not the forged body field.
    assert reviews.get("A-0014")["reviewer"] == "admin@lakshyaa.ai"


def test_an_unauthenticated_review_write_is_refused(built):
    # No IAP token: nothing is written.
    reviews = review.MemoryReviewStore()
    client = review_app(built, reviews=reviews)
    assert client.post("/api/review/A-0014", json={"decision": "confirm",
                                                   "fingerprint": "a" * 64}).status_code == 401
    assert reviews.get("A-0014") is None


def test_a_signed_in_but_not_allow_listed_person_cannot_write_a_review(built):
    reviews = review.MemoryReviewStore()
    client = review_app(built, reviews=reviews)
    forbidden = client.post("/api/review/A-0014", headers=signed(email="guest@lakshyaa.ai"),
                            json={"decision": "confirm", "fingerprint": "a" * 64})
    assert forbidden.status_code == 403 and reviews.get("A-0014") is None


# --- item 2: React↔Flask integration (real Flask API + real review module + real store) ------
# The offline demo proves presentation and the mocked React tests prove the component; this proves
# the real Flask review API works with the real review store and the hash gate, end to end. It is
# an API integration test (Flask test client). The browser leg (built React against this same
# Flask app) is recorded separately in AS_BUILT.

import json as _json  # noqa: E402

from outreach import job_draft, review  # noqa: E402
from test_draft_pipeline import (  # noqa: E402
    BOOK as DP_BOOK, SITE as DP_SITE, facts as dp_facts, lead as dp_lead, model_for as dp_model,
    settings as dp_settings)


def _compose_candidate(reviews):
    """Compose the standard written candidate with a given review store (unreviewed -> no hash)."""
    return job_draft.previews(["A-0001"], settings=dp_settings(), write=True, handbook=DP_BOOK,
                              model=dp_model(), review_store=reviews,
                              fixture={"leads": [dp_lead()], "research": dp_facts(), "pages": DP_SITE,
                                       "suppressed": {"A-0001": False}})[0]


def _drafts_row(candidate):
    return {"Lead ID": "A-0001", "Email": "First email", "To": candidate["to"],
            "Company": candidate["company"], "Subject": candidate["subject"], "Body": candidate["body"],
            "Opening quote": "", "Quote page": "", "Status": "WAITING", "Why": "", "Approval hash": "",
            "Handbook hash": candidate["handbook_hash"], "Written": _json.dumps(candidate["written"]),
            "Prepared at (UTC)": "2026-09-28 12:40:00"}


def test_the_console_review_flow_lets_an_approval_hash_mint_end_to_end(built):
    reviews = review.MemoryReviewStore()
    bare = _compose_candidate(review.MemoryReviewStore())
    assert bare["preview_hash"] is None  # no approval hash before a review
    shared = MemoryStore(fx.rows(), events=fx.events(), suppression=fx.suppression(), runs=fx.runs(),
                         drafts=[_drafts_row(bare)])
    client = app(built, store=lambda: shared, settings=lambda: dp_settings(), enable_review=True,
                 review_store=reviews)

    view = client.get("/api/review/A-0001", headers=signed()).get_json()
    assert view["review"]["decision"] is None and view["subject"] == bare["subject"]
    done = client.post("/api/review/A-0001", headers=signed(),
                       json={"decision": "confirm", "fingerprint": view["fingerprint"]})
    assert done.status_code == 200 and done.get_json()["review"]["current"] is True

    # The recomposed candidate now mints an approval hash, because the console recorded a review of
    # exactly this candidate (the fingerprint the gate computes equals the one the console showed).
    approved = _compose_candidate(reviews)
    assert approved["preview_hash"] and review.AWAITING_BLOCKER not in approved["blockers"]


# --- item 4: fail-closed on storage errors, and rejected/stale states survive a reload --------

class _GetFails:
    def get(self, lead_id):
        raise RuntimeError("the review store is unreachable")

    def put(self, record):
        raise AssertionError("no write expected")


class _PutFails:
    def get(self, lead_id):
        return None

    def put(self, record):
        raise RuntimeError("the review store is unwritable")


def test_a_review_store_read_error_fails_closed(built):
    assert review_app(built, reviews=_GetFails()).get("/api/review/A-0014",
                                                      headers=signed()).status_code == 502


def test_a_review_store_write_error_shows_no_success(built):
    client = review_app(built, reviews=_PutFails())
    fingerprint = client.get("/api/review/A-0014", headers=signed()).get_json()["fingerprint"]
    resp = client.post("/api/review/A-0014", headers=signed(),
                       json={"decision": "confirm", "fingerprint": fingerprint})
    assert resp.status_code == 502


def test_a_rejected_state_survives_a_reload(built):
    reviews = review.MemoryReviewStore()
    client = review_app(built, reviews=reviews)
    fingerprint = client.get("/api/review/A-0014", headers=signed()).get_json()["fingerprint"]
    client.post("/api/review/A-0014", headers=signed(),
                json={"decision": "reject", "fingerprint": fingerprint})
    again = client.get("/api/review/A-0014", headers=signed()).get_json()
    assert again["review"]["decision"] == "rejected" and again["review"]["current"] is True


def test_a_stale_state_survives_a_reload(built):
    reviews = review.MemoryReviewStore()
    review.record_confirmation(reviews, "A-0014", "admin@lakshyaa.ai", "a" * 64)  # an old candidate
    view = review_app(built, reviews=reviews).get("/api/review/A-0014", headers=signed()).get_json()
    assert view["review"]["decision"] == "confirmed" and view["review"]["current"] is False


# --- item 3: test authentication cannot be turned on through production configuration ---------

def test_no_environment_configuration_installs_a_stub_verifier(monkeypatch):
    """The deployed console derives its verifier from real IAP config only. No env var swaps in a
    permissive/test verifier (that override is a create_app argument tests pass); an unsigned
    request is always refused."""
    monkeypatch.setenv("CONSOLE_IAP_AUDIENCE", "/projects/1/locations/global/services/console")
    monkeypatch.setenv("CONSOLE_ALLOWED_EMAILS", "admin@lakshyaa.ai")
    monkeypatch.setenv("ENABLE_REVIEW", "true")
    monkeypatch.setenv("REVIEW_STORE", "sheet")
    client = console._deployed().test_client()
    assert client.get("/api/snapshot").status_code == 401  # real IAP verifier: no token, refused
    assert client.post("/api/review/A-0014", json={"decision": "confirm"}).status_code == 401


def test_an_unconfigured_console_opens_for_nobody_even_with_review_enabled(monkeypatch):
    monkeypatch.delenv("CONSOLE_IAP_AUDIENCE", raising=False)
    monkeypatch.delenv("CONSOLE_ALLOWED_EMAILS", raising=False)
    monkeypatch.setenv("ENABLE_REVIEW", "true")
    assert console._deployed().test_client().get("/api/snapshot").status_code == 503


# --- an uncertain write must not be reported as "nothing was changed" ------------------------

class _Uncertain:
    def get(self, lead_id):
        return None

    def put(self, record):
        raise review.ReviewsUncertain("the outcome is uncertain")


def test_an_uncertain_write_is_not_reported_as_nothing_changed(built):
    client = review_app(built, reviews=_Uncertain())
    fingerprint = client.get("/api/review/A-0014", headers=signed()).get_json()["fingerprint"]
    resp = client.post("/api/review/A-0014", headers=signed(),
                       json={"decision": "confirm", "fingerprint": fingerprint})
    assert resp.status_code == 502
    said = resp.get_json()["error"].lower()
    assert "uncertain" in said and "nothing was changed" not in said
