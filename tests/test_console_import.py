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


def commit(client, body, key="key-1", resume=False):
    return client.post("/api/import/commit", headers=signed(),
                       json={"prefix": body["prefix"], "rows": [i["row"] for i in body["accepted"]],
                             "fingerprint": body["fingerprint"], "idempotency_key": key,
                             "resume": resume})


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
    assert result["outcome"] == "done" and result["written"] == 3 and len(result["lead_ids"]) == 3
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
    # reconciled by id: the write had landed, so it is reported done, not failed
    assert result["outcome"] == "done" and result["written"] == 1 and result.get("reconciled") is True
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


def _two_apps(built, keys):
    """Run two independent Flask apps over one shared simulated Sheet, each committing the same list
    with the given idempotency `keys`, synchronised at a barrier after reading existing leads. Returns
    (api, lead ids, list of the two JSON results)."""
    from outreach.sheet import Store
    from test_sheet_append import A_HEADER, FakeSheets

    api = FakeSheets()
    barrier = threading.Barrier(len(keys), timeout=10)

    class BarrierStore(Store):
        def leads(self):
            snapshot = super().leads()
            barrier.wait()  # both read the same existing leads, then race to claim/append
            return snapshot

    def app():
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
    results, lock = [], threading.Lock()

    def submit(key):
        got = app().post("/api/import/commit", json={**payload, "idempotency_key": key},
                         headers=signed()).get_json()
        with lock:
            results.append(got)

    threads = [threading.Thread(target=submit, args=(key,)) for key in keys]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    return api, ids, results


def test_two_independent_applications_distinct_keys_write_each_lead_once(built):
    api, ids, results = _two_apps(built, ["op-one", "op-two"])
    for lead_id in ids:
        assert api.count("A_Contact_Now", lead_id) == 1  # exactly one physical copy
    assert sum(r["written"] for r in results) == 2  # two leads, written once in total


def test_same_key_concurrent_attempts_write_each_lead_once(built):
    # The reviewer's failure 1: a shared operation key must NOT authorize two simultaneous writers.
    api, ids, results = _two_apps(built, ["shared-key", "shared-key"])
    for lead_id in ids:
        assert api.count("A_Contact_Now", lead_id) == 1  # not two physical copies
    assert sum(r["written"] for r in results) == 2
    # the attempt that did not win reports pending (its own operation's other attempt owns the leads)
    assert any(r.get("outcome") == "pending" for r in results)


class _WriteThenUnreadable(MemoryStore):
    """The append writes, its response is lost, and the reconciliation read then fails too."""

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self._appended = False

    def leads(self):
        if self._appended:
            raise RuntimeError("the store could not be read")
        return super().leads()

    def append_leads(self, prefix, rows):
        super().append_leads(prefix, rows)  # the write lands
        self._appended = True
        raise RuntimeError("the response was lost")


def test_a_lost_response_with_an_unreadable_reconciliation_is_uncertain_not_nothing(built):
    # The reviewer's failure 2: an unreadable reconciliation must not be reported as "Nothing written".
    store = _WriteThenUnreadable([{"Lead ID": "A-0001", "Company": "Example Electric",
                                   "BEST EMAIL": "sam@example-electric.test"}], lead_columns=COLUMNS)
    client = make(built, store)
    body = preview(client, "Company,Email\nBluebird,dana@bluebird.test").get_json()
    response = commit(client, body, key="k")
    assert response.status_code == 200
    result = response.get_json()
    assert result["outcome"] == "uncertain"  # explicit unknown, never a false "nothing written"
    assert "Nothing was written" not in (result.get("message") or "")
    # the write actually landed: exactly one physical copy exists (not lost, not doubled)
    assert sum(1 for r in store.rows.values() if r["Company"] == "Bluebird") == 1


class _FailFirstAppend(MemoryStore):
    """Fails the first append (an owner that claims then dies before writing); later appends succeed."""

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self._failed_once = False

    def append_leads(self, prefix, rows):
        if not self._failed_once:
            self._failed_once = True
            raise RuntimeError("the owner failed before writing")
        return super().append_leads(prefix, rows)


def test_an_abandoned_pre_write_claim_stays_pending_and_is_not_auto_recovered(built):
    # An owner wins the claim then dies before appending. Resume is READ-ONLY: it never takes over and
    # writes the lead (a takeover could double-write it against a still-active owner). It reports
    # pending. Recovering such a lead is a documented, unmet requirement.
    store = _FailFirstAppend([{"Lead ID": "A-0001", "Company": "Example Electric",
                               "BEST EMAIL": "sam@example-electric.test"}], lead_columns=COLUMNS)
    client = make(built, store)
    body = preview(client, "Company,Email\nBluebird,dana@bluebird.test").get_json()

    first = commit(client, body, key="op-1")  # claims, then the append fails before writing
    assert first.status_code == 502 and "Nothing was written" in first.get_json()["error"]

    # a fresh-key re-import (a different operation) is told the lead is claimed elsewhere - not "done"
    other = commit(client, body, key="op-2").get_json()
    assert other["written"] == 0 and other["claimed_elsewhere"] == 1 and other["outcome"] == "blocked"

    # resuming the SAME operation reconciles read-only: the lead is still owned and unwritten -> pending,
    # nothing written, no physical row (the honest, documented limitation - not a false completion)
    resumed = commit(client, body, key="op-1", resume=True).get_json()
    assert resumed["outcome"] == "pending" and resumed["written"] == 0
    assert not any(r["Company"] == "Bluebird" for r in store.rows.values())


def test_overlapping_original_and_resume_write_the_lead_once(built):
    # The reviewer's overlap: pause the original's lead append AFTER its presence recheck, run a resume
    # of the same operation through an independent app to its append, then release the original. Only the
    # earliest claim (the original) may write, so exactly ONE physical row exists.
    from outreach.sheet import Store
    from test_sheet_append import A_HEADER, FakeSheets

    api = FakeSheets()
    api.pause_leads = True  # pause the first lead append, past its recheck, before it commits

    def app():
        return console.create_app(
            verifier=console_auth.Verifier(AUDIENCE, ALLOWED, fetch=Keys()),
            store=lambda: Store(api=api), settings=lambda: {}, clock=lambda: fx.NOW,
            static_dir=built, enable_import=True).test_client()

    body = importer.import_leads(importer.records_from_csv("Company,Email\nSynthetic slow,slow@example.test"),
                                 Store(api=api).leads(), prefix="A", destination_columns=A_HEADER)
    lead_id = body["accepted"][0]["row"]["Lead ID"]
    payload = {"prefix": "A", "rows": [i["row"] for i in body["accepted"]],
               "fingerprint": body["fingerprint"], "idempotency_key": "op-1"}
    results = {}

    def original():
        results["A"] = app().post("/api/import/commit", json=payload, headers=signed()).get_json()

    thread = threading.Thread(target=original)
    thread.start()
    assert api.reached.wait(5)  # the original is paused inside its lead append, past its recheck
    results["B"] = app().post("/api/import/commit", json={**payload, "resume": True},
                              headers=signed()).get_json()  # resume, same op, while the original is in flight
    api.release.set()
    thread.join()

    assert api.count("A_Contact_Now", lead_id) == 1  # exactly one physical row, not two
    assert results["A"]["written"] == 1 and results["A"]["outcome"] == "done"
    assert results["B"]["written"] == 0 and results["B"]["outcome"] == "pending"  # resume wrote nothing


def test_simultaneous_resumes_of_an_abandoned_claim_write_nothing(built):
    from outreach.sheet import Store
    from test_sheet_append import A_HEADER, FakeSheets

    api = FakeSheets()
    body = importer.import_leads(importer.records_from_csv("Company,Email\nGamma,g@gamma.test"),
                                 Store(api=api).leads(), prefix="A", destination_columns=A_HEADER)
    lead_id = body["accepted"][0]["row"]["Lead ID"]
    Store(api=api).claim_leads([lead_id], "op-1", "attempt-original")  # the original claimed, then died
    payload = {"prefix": "A", "rows": [i["row"] for i in body["accepted"]],
               "fingerprint": body["fingerprint"], "idempotency_key": "op-1", "resume": True}
    results, lock = [], threading.Lock()

    def app():
        return console.create_app(
            verifier=console_auth.Verifier(AUDIENCE, ALLOWED, fetch=Keys()),
            store=lambda: Store(api=api), settings=lambda: {}, clock=lambda: fx.NOW,
            static_dir=built, enable_import=True).test_client()

    def submit():
        got = app().post("/api/import/commit", json=payload, headers=signed()).get_json()
        with lock:
            results.append(got)

    threads = [threading.Thread(target=submit) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    # two resumes, both reconciling read-only: neither writes, so no duplicate (and the lead is not
    # recovered - the documented limitation)
    assert api.count("A_Contact_Now", lead_id) == 0
    assert all(r["written"] == 0 and r["outcome"] == "pending" for r in results)


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
