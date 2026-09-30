"""The import routes: upload/paste -> preview -> confirm -> persist, through the real Flask app with a
synthetic Store. Import is OFF unless switched on, writes only new rows, revalidates against the
destination schema, assigns stable immutable ids before writing, is idempotent on retry, prevents
cross-instance duplicates via a claim ledger, and reconciles an uncertain append by id.
"""

import io
import threading

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


def commit(client, body, key="key-1"):
    return client.post("/api/import/commit", headers=signed(),
                       json={"prefix": body["prefix"], "rows": [i["row"] for i in body["accepted"]],
                             "fingerprint": body["fingerprint"], "idempotency_key": key})


def test_import_is_off_unless_switched_on(built):
    client = console.create_app(
        verifier=console_auth.Verifier(AUDIENCE, ALLOWED, fetch=Keys()), store=a_store,
        settings=lambda: {}, clock=lambda: fx.NOW, static_dir=built).test_client()
    assert client.post("/api/import/preview", json={"text": CSV}, headers=signed()).status_code == 404
    assert client.post("/api/import/commit", json={}, headers=signed()).status_code == 404


def test_preview_keeps_company_only_phone_only_and_email_and_writes_nothing(built):
    store = a_store()
    body = preview(make(built, store), CSV).get_json()
    channels = {i["row"]["Company"]: i["channel"] for i in body["accepted"]}
    assert channels == {"Bluebird Electric": "EMAIL", "Redwood Plumbing": "CALL",
                        "Cedar Roofing": "COMPANY_ONLY"}
    assert body["summary"] == {"accepted": 3, "duplicates": 0, "skipped": 1, "unstorable": 0,
                               "invalid": 0, "by_channel": {"EMAIL": 1, "CALL": 1, "COMPANY_ONLY": 1}}
    assert store.lead_appends == []  # preview writes nothing


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
    done = commit(client, body)
    assert done.status_code == 200
    result = done.get_json()
    assert result["written"] == 3 and len(result["lead_ids"]) == 3
    assert all(not lid.split("-", 1)[1].isdigit() for lid in result["lead_ids"])  # stable hex ids

    snap = client.get("/api/snapshot", headers=signed()).get_json()
    views = {v["company"]: v for v in snap["leads"]}
    assert views["Redwood Plumbing"]["channel"] == "CALL"
    assert views["Redwood Plumbing"]["action"].startswith("Call Redwood")
    assert views["Cedar Roofing"]["channel"] == "COMPANY_ONLY"
    assert len(store.lead_appends) == 1


def test_a_new_id_never_collides_with_an_existing_numeric_id(built):
    # Regression: an existing numeric id in the "gap" used to be re-derived and duplicated.
    store = a_store()
    store.rows["A-0002"] = {"Company": "Placeholder", "Lead ID": "A-0002"}  # a sparse existing id
    client = make(built, store)
    body = preview(client, "Company,Email\nBrand New,new@brand.test").get_json()
    result = commit(client, body).get_json()
    assert result["written"] == 1
    assert result["lead_ids"][0] != "A-0002" and not result["lead_ids"][0].split("-", 1)[1].isdigit()
    assert "A-0002" in store.rows and store.rows["A-0002"]["Company"] == "Placeholder"  # untouched


def test_retrying_the_same_confirmed_import_adds_nothing(built):
    store = a_store()
    client = make(built, store)
    body = preview(client, CSV).get_json()
    first = commit(client, body, key="same-key").get_json()
    second = commit(client, body, key="same-key").get_json()
    assert first["written"] == 3
    assert second["written"] == 0 and second["already_present"] == 3  # idempotent, one physical copy
    assert len(store.lead_appends) == 1


def test_a_stale_destination_is_refused_before_writing(built):
    store = a_store()
    client = make(built, store)
    body = preview(client, "Company,Phone\nRedwood Plumbing,614-555-0142").get_json()
    assert body["accepted"][0]["row"].get("Phone") == "614-555-0142"
    store.lead_header = [c for c in store.lead_header if c != "Phone"]  # column removed after preview
    assert commit(client, body).status_code == 409
    assert store.lead_appends == []


def test_invalid_contact_values_show_in_the_preview(built):
    store = a_store()
    body = preview(make(built, store), "Company,Email,Phone\nSynthetic,wrong-address,123").get_json()
    item = body["accepted"][0]
    assert item["channel"] == "COMPANY_ONLY" and item["row"]["Company"] == "Synthetic"
    assert {i["field"] for i in item["invalid"]} == {"email", "phone"} and body["summary"]["invalid"] == 2


class _WriteThenFail(MemoryStore):
    """The append writes, then the response is lost (an exception after the write landed)."""

    def append_leads(self, prefix, rows):
        super().append_leads(prefix, rows)
        raise RuntimeError("the response was lost after the write landed")


def test_an_append_whose_response_is_lost_is_reconciled_not_double_written(built):
    store = _WriteThenFail([{"Lead ID": "A-0001", "Company": "Example Electric",
                             "BEST EMAIL": "sam@example-electric.test"}], lead_columns=COLUMNS)
    client = make(built, store)
    body = preview(client, "Company,Email\nBluebird,dana@bluebird.test").get_json()
    result = commit(client, body, key="k").get_json()
    # reconciled by id: the write had landed, so it is reported written, not failed
    assert result["written"] == 1 and result.get("reconciled") is True
    lead_id = result["lead_ids"][0]
    # the row already landed, so a retry (same key) finds it present and adds nothing - one copy only
    retry = commit(client, body, key="k").get_json()
    assert retry["written"] == 0 and retry["already_present"] == 1
    assert sum(1 for r in store.rows.values() if r.get("Lead ID") == lead_id) == 1


class _FailBeforeWrite(MemoryStore):
    def append_leads(self, prefix, rows):
        raise RuntimeError("failed before writing")


def test_a_failed_append_that_wrote_nothing_says_so_and_is_safe_to_retry(built):
    store = _FailBeforeWrite([{"Lead ID": "A-0001", "Company": "Example Electric",
                               "BEST EMAIL": "sam@example-electric.test"}], lead_columns=COLUMNS)
    client = make(built, store)
    body = preview(client, "Company,Email\nBluebird,dana@bluebird.test").get_json()
    response = commit(client, body, key="k")
    assert response.status_code == 502 and "Nothing was written" in response.get_json()["error"]


def test_two_independent_applications_importing_the_same_list_write_each_lead_once(built):
    from outreach.sheet import Store
    from test_sheet_append import A_HEADER, FakeSheets

    api = FakeSheets()  # one shared, thread-safe simulated Sheet; existing A-0001 at row 3
    barrier = threading.Barrier(2, timeout=10)

    class BarrierStore(Store):
        def leads(self):
            snapshot = super().leads()
            barrier.wait()  # both commits read the same existing leads, then race
            return snapshot

    def make_app():
        return console.create_app(
            verifier=console_auth.Verifier(AUDIENCE, ALLOWED, fetch=Keys()),
            store=lambda: BarrierStore(api=api), settings=lambda: {}, clock=lambda: fx.NOW,
            static_dir=built, enable_import=True).test_client()

    records = importer.records_from_csv("Company,Email\nAlpha,a@alpha.test\nBeta,b@beta.test")
    body = importer.import_leads(records, Store(api=api).leads(), prefix="A",
                                 destination_columns=A_HEADER)
    payload = {"prefix": "A", "rows": [i["row"] for i in body["accepted"]],
               "fingerprint": body["fingerprint"]}
    ids = [i["row"]["Lead ID"] for i in body["accepted"]]
    results = {}

    def submit(key):
        results[key] = make_app().post("/api/import/commit",
                                       json={**payload, "idempotency_key": key},
                                       headers=signed()).get_json()

    threads = [threading.Thread(target=submit, args=("app-one",)),
               threading.Thread(target=submit, args=("app-two",))]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    # Two independent submissions (distinct keys) of the same list: each lead is written exactly once.
    for lead_id in ids:
        assert api.count("A_Contact_Now", lead_id) == 1
    assert results["app-one"]["written"] + results["app-two"]["written"] == 2  # 2 leads, once total


def test_import_still_needs_a_signed_in_session(built):
    assert make(built, a_store()).post("/api/import/preview", json={"text": CSV}).status_code == 401


def test_a_commit_without_an_idempotency_key_is_refused(built):
    store = a_store()
    client = make(built, store)
    body = preview(client, CSV).get_json()
    response = client.post("/api/import/commit", headers=signed(),
                           json={"prefix": "A", "rows": [i["row"] for i in body["accepted"]],
                                 "fingerprint": body["fingerprint"]})
    assert response.status_code == 400 and store.lead_appends == []


def test_an_oversized_upload_is_refused(built):
    huge = "Company\n" + ("x\n" * 1_100_000)
    assert make(built, a_store()).post("/api/import/preview", json={"text": huge, "prefix": "A"},
                                       headers=signed()).status_code == 413


def test_an_unreadable_file_is_refused_clearly(built):
    response = make(built, a_store()).post(
        "/api/import/preview", headers=signed(),
        data={"file": (io.BytesIO(b"%PDF-1.4 not a spreadsheet"), "leads.pdf")},
        content_type="multipart/form-data")
    assert response.status_code == 400 and "unsupported file type" in response.get_json()["error"]
