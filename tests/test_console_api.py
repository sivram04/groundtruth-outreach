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

import review_fixtures as rf  # noqa: E402
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


def review_settings():
    return {**fx.SETTINGS, "review_public_key": rf.PUBLIC_KEY_B64}  # the trusted verifier key


def review_app(static, reviews=None, **changes):
    shared = MemoryStore(fx.rows(), events=fx.events(), suppression=fx.suppression(),
                         runs=fx.runs(), drafts=review_rows())
    options = dict(store=lambda: shared, enable_review=True, settings=review_settings,
                   review_signer=rf.SIGNER,  # the console's signing authority (ephemeral test key)
                   review_store=reviews if reviews is not None else review.MemoryReviewStore())
    options.update(changes)
    return app(static, **options)


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


# --- the approve-sends wiring: prepare the candidate, create the Gmail draft ------------------------

def _store_with_drafts(draft_rows):
    shared = MemoryStore(fx.rows(), events=fx.events(), suppression=fx.suppression(), runs=fx.runs(),
                         drafts=draft_rows)
    shared.api = object()  # the create route passes st.api to job_draft.create
    return shared


def _send_app(built, shared):
    return app(built, store=lambda: shared, enable_review=True, settings=review_settings,
               review_signer=rf.SIGNER, review_store=review.MemoryReviewStore(),
               gmail_client=lambda: object())


def test_preparing_a_draft_regates_the_stored_candidate(built, monkeypatch):
    # A stored candidate is re-gated (picking up a review), never re-composed.
    monkeypatch.setattr(console.drafts, "regate_one",
                        lambda store, lead_id, **kw: {"status": "WAITING", "why": "awaiting review"})
    r = review_app(built).post("/api/drafts/prepare/A-0014", headers=signed())
    assert r.status_code == 200 and r.get_json()["ok"] is True and r.get_json()["status"] == "WAITING"


def test_preparing_composes_when_no_candidate_is_stored_yet(built, monkeypatch):
    # No stored candidate -> compose once (the only path that calls the model).
    monkeypatch.setattr(console.drafts, "regate_one", lambda store, lead_id, **kw: None)
    monkeypatch.setattr(console.drafts, "prepare",
                        lambda store, **kw: {"written": {"A-0014": {"status": "WAITING", "why": "awaiting review"}}})
    r = review_app(built).post("/api/drafts/prepare/A-0014", headers=signed())
    assert r.status_code == 200 and r.get_json()["status"] == "WAITING"


def test_create_gmail_draft_uses_the_reviewed_ready_candidate(built, monkeypatch):
    seen = {}
    # Re-gate (no model) picks up the confirmation; it must NOT re-compose the candidate.
    monkeypatch.setattr(console.drafts, "regate_one",
                        lambda store, lead_id, **kw: {"status": "READY", "why": ""})

    def fake_create(lead_id, approved_hash, *, written=None, **kw):
        seen.update(lead_id=lead_id, approved_hash=approved_hash)
        return {"lead_id": lead_id, "draft_id": "d1", "status": "CREATED"}

    monkeypatch.setattr(console.job_draft, "create", fake_create)
    ready = {**review_rows()[0], "Status": "READY", "Approval hash": "approved-hash-xyz"}
    r = _send_app(built, _store_with_drafts([ready])).post("/api/draft/create/A-0014", headers=signed())
    assert r.status_code == 200 and r.get_json()["draft_id"] == "d1"
    assert seen["lead_id"] == "A-0014" and seen["approved_hash"] == "approved-hash-xyz"


def test_create_refuses_a_candidate_that_is_not_ready(built, monkeypatch):
    monkeypatch.setattr(console.drafts, "regate_one", lambda store, lead_id, **kw: None)
    # review_rows() has an empty Approval hash -> not reviewed/approved -> cannot create
    r = _send_app(built, _store_with_drafts(review_rows())).post("/api/draft/create/A-0014", headers=signed())
    assert r.status_code == 409


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
                 review_store=reviews, review_signer=rf.SIGNER)

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

class _ReadFails:
    """History cannot be read: the resolver reports 'unreadable' and never shows approval."""

    def get(self, lead_id):
        raise RuntimeError("the review store is unreachable")

    def history(self, lead_id):
        raise RuntimeError("the review store is unreachable")

    def put(self, record):
        raise AssertionError("no write expected")


class _PutFails:
    def get(self, lead_id):
        return None

    def history(self, lead_id):
        return []

    def put(self, record):
        raise RuntimeError("the review store is unwritable")


def test_a_review_store_read_error_fails_closed(built):
    # A read error never shows approval: the resolver reports 'unreadable' and the status is not
    # a confirmation.
    view = review_app(built, reviews=_ReadFails()).get("/api/review/A-0014",
                                                       headers=signed()).get_json()
    assert view["review"]["decision"] is None and view["review"]["current"] is False
    assert view["review"]["state"] == "unreadable"


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
    rf.confirm(reviews, "A-0014", "admin@lakshyaa.ai", "a" * 64)  # a signed review of an old candidate
    view = review_app(built, reviews=reviews).get("/api/review/A-0014", headers=signed()).get_json()
    assert view["review"]["decision"] == "confirmed" and view["review"]["current"] is False


def test_no_signer_configured_blocks_the_write(built):
    reviews = review.MemoryReviewStore()
    client = review_app(built, reviews=reviews, review_signer=None)  # no signing authority
    fingerprint = client.get("/api/review/A-0014", headers=signed()).get_json()["fingerprint"]
    resp = client.post("/api/review/A-0014", headers=signed(),
                       json={"decision": "confirm", "fingerprint": fingerprint})
    assert resp.status_code == 503 and reviews.get("A-0014") is None


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


def test_every_feature_flag_is_read_from_its_own_environment_variable(monkeypatch):
    """Each ENABLE_* flag is independent: unset means off, and setting one does not turn on
    another. Catches a flag that create_app defaults to False but main() never reads from the
    environment, so no deploy configuration could ever turn it on."""
    names = {"enable_send": "ENABLE_SEND", "enable_lead_chat": "ENABLE_LEAD_CHAT",
             "enable_playbook": "ENABLE_PLAYBOOK", "enable_import": "ENABLE_IMPORT",
             "enable_calls": "ENABLE_CALLS", "enable_experiments": "ENABLE_EXPERIMENTS",
             "enable_reply": "ENABLE_REPLY"}
    for env_name in names.values():
        monkeypatch.delenv(env_name, raising=False)

    captured = {}

    def fake_create_app(**kwargs):
        captured.update(kwargs)
        return None

    monkeypatch.setattr(console, "create_app", fake_create_app)
    console._deployed()
    assert all(captured[kwarg] is False for kwarg in names)

    for kwarg, env_name in names.items():
        monkeypatch.setenv(env_name, "true")
        captured.clear()
        console._deployed()
        assert captured[kwarg] is True
        assert all(captured[other] is False for other in names if other != kwarg)
        monkeypatch.delenv(env_name, raising=False)


# --- an uncertain write must not be reported as "nothing was changed" ------------------------

class _Uncertain:
    def get(self, lead_id):
        return None

    def history(self, lead_id):
        return []

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


# --- item 1: saving is separate from reading the status back --------------------------------

class _ReadFailsAfterSave:
    """put() records; get() works until something is saved, then fails - so the SAVE succeeds but
    the follow-up status read does not."""

    def __init__(self):
        self._m = review.MemoryReviewStore()
        self.saved = False

    def get(self, lead_id):
        if self.saved:
            raise RuntimeError("the review store read failed after the save")
        return self._m.get(lead_id)

    def history(self, lead_id):
        if self.saved:
            raise RuntimeError("the review store read failed after the save")
        return self._m.history(lead_id)

    def put(self, record):
        self.saved = True
        self._m.put(record)


def test_a_save_that_succeeds_but_cannot_be_read_back_says_so(built):
    client = review_app(built, reviews=_ReadFailsAfterSave())
    fingerprint = client.get("/api/review/A-0014", headers=signed()).get_json()["fingerprint"]
    resp = client.post("/api/review/A-0014", headers=signed(),
                       json={"decision": "confirm", "fingerprint": fingerprint})
    assert resp.status_code == 200
    body = resp.get_json()
    assert body.get("recorded") is True and body.get("status_unavailable") is True
    assert body["message"] == ("Your review was recorded, but its current status could not be "
                               "loaded. Reload before continuing.")
    # it does not claim nothing changed, and shows no current approval
    assert "review" not in body and "nothing was changed" not in body["message"].lower()


# --- item 3: a rejection between the confirm write and the status read is not shown as approval ---

class _RejectAfterConfirm:
    """A concurrent rejection lands AFTER the confirmation is appended but BEFORE the console reads
    the current decision back."""

    def __init__(self):
        self._m = review.MemoryReviewStore()

    def get(self, lead_id):
        return self._m.get(lead_id)

    def history(self, lead_id):
        return self._m.history(lead_id)

    def put(self, record):
        self._m.put(record)
        if record["decision"] == "confirmed":
            # a concurrent, genuinely-signed rejection chained onto the confirmation lands first
            rej = {**record, "decision": "rejected", "prev": record["signature"]}
            rej["signature"] = rf.SIGNER.sign(
                review_id=rej["lead_id"], prev=rej["prev"], fingerprint=rej["fingerprint"],
                reviewer=rej["reviewer"], decision="rejected", reviewed_at=rej["reviewed_at"])
            self._m.put(rej)


def test_a_rejection_between_the_confirm_write_and_the_read_is_not_shown_as_approval(built):
    client = review_app(built, reviews=_RejectAfterConfirm())
    fingerprint = client.get("/api/review/A-0014", headers=signed()).get_json()["fingerprint"]
    resp = client.post("/api/review/A-0014", headers=signed(),
                       json={"decision": "confirm", "fingerprint": fingerprint})
    assert resp.status_code == 200
    view = resp.get_json()
    # the confirm was written, but the later rejection is what the read returns: not approval
    assert view["review"]["decision"] == "rejected"


class _ConflictAfterConfirm:
    """A concurrent, genuinely-signed SECOND ROOT (a fork) lands after the confirmation is appended,
    so the read-back resolves to a CONFLICT rather than a single trusted tip."""

    def __init__(self):
        self._m = review.MemoryReviewStore()

    def get(self, lead_id):
        return self._m.get(lead_id)

    def history(self, lead_id):
        return self._m.history(lead_id)

    def put(self, record):
        self._m.put(record)
        if record["decision"] == "confirmed":
            fork = {**record, "reviewed_at": "2026-01-01T00:00:00Z", "prev": ""}
            fork["signature"] = rf.SIGNER.sign(
                review_id=fork["lead_id"], prev="", fingerprint=fork["fingerprint"],
                reviewer=fork["reviewer"], decision="confirmed", reviewed_at=fork["reviewed_at"])
            self._m.put(fork)


def test_a_conflict_after_the_save_is_acknowledged_as_recorded_but_unavailable(built):
    # The save SUCCEEDS, but the current status resolves to a conflict: never shown as approval, and
    # the save is acknowledged rather than the failed history rendered as a decision.
    client = review_app(built, reviews=_ConflictAfterConfirm())
    fingerprint = client.get("/api/review/A-0014", headers=signed()).get_json()["fingerprint"]
    resp = client.post("/api/review/A-0014", headers=signed(),
                       json={"decision": "confirm", "fingerprint": fingerprint})
    assert resp.status_code == 200
    body = resp.get_json()
    assert body.get("recorded") is True and body.get("status_unavailable") is True
    assert "review" not in body and "nothing was changed" not in body["message"].lower()
