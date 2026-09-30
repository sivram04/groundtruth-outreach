"""The import routes: upload/paste -> preview -> confirm -> persist, through the real Flask app with a
synthetic in-memory Store. Import is OFF unless switched on, writes only new rows, revalidates before
committing, and is safe to retry.
"""

import io

import pytest

import console_fixture as fx
from outreach import console, console_auth, importer
from stage4_fakes import MemoryStore
from test_console_auth import ALLOWED, AUDIENCE, Keys, token

HEADER = console_auth.HEADER
COLUMNS = ["Lead ID", "Company", "Decision maker", "BEST EMAIL", "Website", "Phone"]

CSV = (
    "Company,Contact,Email,Phone,Website\n"
    "Bluebird Electric,Dana Cole,dana@bluebird-electric.test,,https://bluebird-electric.test/\n"
    "Redwood Plumbing,Sam Ford,,(614) 555-0142,https://redwood-plumbing.test/\n"
    "Cedar Roofing,,,,cedar-roofing.test\n"
    ",,,,\n"
)


@pytest.fixture
def built(tmp_path):
    (tmp_path / "assets").mkdir()
    (tmp_path / "index.html").write_text("<!doctype html><div id=root></div>", encoding="utf-8")
    return tmp_path


def signed(**claims):
    return {HEADER: token(**claims)}


def make(built, store, **changes):
    options = dict(verifier=console_auth.Verifier(AUDIENCE, ALLOWED, fetch=Keys()),
                   store=lambda: store, settings=lambda: dict(fx.SETTINGS), clock=lambda: fx.NOW,
                   static_dir=built, enable_import=True)
    options.update(changes)
    return console.create_app(**options).test_client()


def a_store(**kw):
    kw.setdefault("lead_columns", COLUMNS)
    return MemoryStore([{"Lead ID": "A-0001", "Company": "Example Electric",
                         "BEST EMAIL": "sam@example-electric.test"}], **kw)


def preview(client, text):
    return client.post("/api/import/preview", json={"text": text, "prefix": "A"}, headers=signed())


def test_import_is_off_unless_switched_on(built):
    client = console.create_app(
        verifier=console_auth.Verifier(AUDIENCE, ALLOWED, fetch=Keys()), store=a_store,
        settings=lambda: {}, clock=lambda: fx.NOW, static_dir=built).test_client()
    assert client.post("/api/import/preview", json={"text": CSV}, headers=signed()).status_code == 404
    assert client.post("/api/import/commit", json={}, headers=signed()).status_code == 404


def test_preview_shows_what_would_be_stored_without_writing(built):
    store = a_store()
    body = preview(make(built, store), CSV).get_json()
    assert body["summary"] == {"accepted": 3, "duplicates": 0, "skipped": 1, "unstorable": 0,
                               "by_channel": {"EMAIL": 1, "CALL": 1, "COMPANY_ONLY": 1}}
    assert store.lead_appends == []  # preview writes nothing


def test_preview_keeps_company_only_phone_only_and_email(built):
    store = a_store()
    body = preview(make(built, store), CSV).get_json()
    channels = {i["lead_id"]: i["channel"] for i in body["accepted"]}
    assert channels == {"A-0002": "EMAIL", "A-0003": "CALL", "A-0004": "COMPANY_ONLY"}
    assert body["summary"]["accepted"] == 3


def test_a_pasted_field_with_no_column_is_reported_before_confirmation(built):
    store = a_store(lead_columns=["Lead ID", "Company", "Decision maker", "BEST EMAIL", "Website"])
    body = preview(make(built, store), CSV).get_json()
    assert "phone" in body["unstorable_fields"]  # no Phone column at the destination
    call = next(i for i in body["accepted"] if i["channel"] == "CALL")
    assert {"field": "phone", "value": "(614) 555-0142"} in call["unstorable"]


def test_upload_a_csv_file_previews_the_same_way(built):
    store = a_store()
    response = make(built, store).post(
        "/api/import/preview", headers=signed(),
        data={"file": (io.BytesIO(CSV.encode("utf-8")), "leads.csv"), "prefix": "A"},
        content_type="multipart/form-data")
    assert response.status_code == 200 and response.get_json()["summary"]["accepted"] == 3


def test_confirm_persists_only_new_rows_and_a_reload_shows_them(built):
    store = a_store()
    client = make(built, store)
    body = preview(client, CSV).get_json()
    rows = [i["row"] for i in body["accepted"]]
    done = client.post("/api/import/commit",
                       json={"prefix": "A", "rows": rows, "fingerprint": body["fingerprint"]},
                       headers=signed())
    assert done.status_code == 200
    result = done.get_json()
    assert result["written"] == 3 and result["lead_ids"] == ["A-0002", "A-0003", "A-0004"]
    assert result["already_present"] == 0

    # a reload (snapshot) shows the imported leads with the right next actions
    snap = client.get("/api/snapshot", headers=signed()).get_json()
    views = {v["id"]: v for v in snap["leads"]}
    assert views["A-0003"]["channel"] == "CALL" and views["A-0003"]["action"].startswith("Call Redwood")
    assert views["A-0004"]["channel"] == "COMPANY_ONLY"
    assert len(store.lead_appends) == 1  # written once


def test_a_second_confirm_adds_nothing_and_does_not_claim_failure(built):
    store = a_store()
    client = make(built, store)
    body = preview(client, CSV).get_json()
    payload = {"prefix": "A", "rows": [i["row"] for i in body["accepted"]], "fingerprint": body["fingerprint"]}
    first = client.post("/api/import/commit", json=payload, headers=signed()).get_json()
    second = client.post("/api/import/commit", json=payload, headers=signed()).get_json()
    assert first["written"] == 3
    assert second["written"] == 0 and second["already_present"] == 3  # idempotent, not an error
    assert len(store.lead_appends) == 1  # nothing written the second time


def test_a_stale_preview_is_refused_before_writing(built):
    store = a_store()
    client = make(built, store)
    body = preview(client, CSV).get_json()
    rows = [i["row"] for i in body["accepted"]]
    rows[0]["Company"] = "Edited after preview"
    response = client.post("/api/import/commit",
                           json={"prefix": "A", "rows": rows, "fingerprint": body["fingerprint"]},
                           headers=signed())
    assert response.status_code == 409 and store.lead_appends == []


class _UncertainStore(MemoryStore):
    def append_leads(self, prefix, rows):
        raise RuntimeError("the append call failed")


def test_an_uncertain_append_is_reported_honestly(built):
    store = _UncertainStore([{"Lead ID": "A-0001", "Company": "Example Electric",
                              "BEST EMAIL": "sam@example-electric.test"}], lead_columns=COLUMNS)
    client = make(built, store)
    body = preview(client, CSV).get_json()
    response = client.post("/api/import/commit",
                           json={"prefix": "A", "rows": [i["row"] for i in body["accepted"]],
                                 "fingerprint": body["fingerprint"]}, headers=signed())
    assert response.status_code == 502 and "uncertain" in response.get_json()["error"]


def test_an_unreadable_file_is_refused_clearly(built):
    store = a_store()
    response = make(built, store).post(
        "/api/import/preview", headers=signed(),
        data={"file": (io.BytesIO(b"%PDF-1.4 not a spreadsheet"), "leads.pdf")},
        content_type="multipart/form-data")
    assert response.status_code == 400 and "unsupported file type" in response.get_json()["error"]


def test_an_oversized_upload_is_refused(built):
    store = a_store()
    huge = "Company\n" + ("x\n" * 1_100_000)  # over 2 MB
    response = make(built, store).post("/api/import/preview", json={"text": huge, "prefix": "A"},
                                       headers=signed())
    assert response.status_code == 413


def test_too_many_rows_are_refused(built):
    store = a_store()
    many = "Company\n" + "".join(f"Acme {n}\n" for n in range(importer.MAX_ROWS + 5))
    response = make(built, store).post("/api/import/preview", json={"text": many, "prefix": "A"},
                                       headers=signed())
    assert response.status_code == 413


def test_import_still_needs_a_signed_in_session(built):
    assert make(built, a_store()).post("/api/import/preview", json={"text": CSV}).status_code == 401
