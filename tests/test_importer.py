"""Importing a small list: parsing, normalizing, classifying, de-duplicating and reporting, and the
whole way through the real persistence boundary and console model with synthetic data.

Nothing here touches Google. The fake Store (`stage4_fakes.MemoryStore`) stands in for the Sheet, and
`console_model.build` is the real model, so the journey - import a small list, then show the correct
next action for every lead, including phone-only and company-only - is exercised end to end.
"""

from outreach import channels, console_model, importer
from stage4_fakes import MemoryStore, at, lead

CSV = (
    "Company,Contact,Email,Phone,Website\n"
    "Bluebird Electric,Dana Cole,dana@bluebird-electric.test,,https://bluebird-electric.test/\n"
    "Redwood Plumbing,Sam Ford,,(614) 555-0142,https://redwood-plumbing.test/\n"  # phone-only
    "Cedar Roofing,,,,cedar-roofing.test\n"                                        # company-only
    "Example Electric,Sam Rivers,sam@example-electric.test,,\n"                    # duplicate of A-0001
    ",,,,\n"                                                                        # nothing to import
)


def existing():
    return {"A-0001": lead("A-0001")}  # Example Electric, sam@example-electric.test


def test_a_csv_is_read_into_records_whatever_the_delimiter():
    rows = importer.records_from_csv(CSV)
    assert rows[0]["Company"] == "Bluebird Electric" and rows[0]["Email"] == "dana@bluebird-electric.test"
    tsv = "Company\tPhone\nAcme\t614-555-0100\n"
    assert importer.records_from_csv(tsv) == [{"Company": "Acme", "Phone": "614-555-0100"}]
    assert importer.records_from_csv("") == [] and importer.records_from_csv("   ") == []


def test_import_keeps_email_phone_only_and_company_only_and_reports_the_rest():
    result = importer.import_leads(importer.records_from_csv(CSV), existing(), prefix="A")
    ids = [row["Lead ID"] for row in result["accepted"]]
    assert ids == ["A-0002", "A-0003", "A-0004"]  # numbering continues past A-0001
    by_id = {row["Lead ID"]: row for row in result["accepted"]}
    assert result["channels"] == {
        "A-0002": channels.EMAIL, "A-0003": channels.CALL, "A-0004": channels.COMPANY_ONLY}
    assert by_id["A-0003"]["Phone"] == "(614) 555-0142" and by_id["A-0003"]["BEST EMAIL"] == ""
    assert by_id["A-0004"]["Company"] == "Cedar Roofing"
    # the duplicate of an existing lead and the empty row are not imported, each with a reason
    assert [d["matched"] for d in result["duplicates"]] == ["A-0001"]
    assert result["skipped"] and "no company, email or phone" in result["skipped"][0]["reason"]
    assert result["summary"] == {"accepted": 3, "duplicates": 1, "skipped": 1,
                                 "by_channel": {"EMAIL": 1, "CALL": 1, "COMPANY_ONLY": 1}}


def test_a_duplicate_within_the_same_batch_is_only_imported_once():
    records = [{"Company": "Acme", "Phone": "614-555-0100"},
               {"Company": "Acme (again)", "Phone": "(614) 555 0100"}]  # same digits
    result = importer.import_leads(records, {}, prefix="B")
    assert [r["Lead ID"] for r in result["accepted"]] == ["B-0001"]
    assert result["duplicates"][0]["matched"] == "B-0001"


def test_no_founder_column_is_invented_or_overwritten():
    result = importer.import_leads([{"Company": "Acme", "Email": "a@acme.test"}], {}, prefix="A")
    row = result["accepted"][0]
    # only canonical columns, and a founder field left blank stays blank - never guessed
    assert set(row) == {"Lead ID", "Company", "Decision maker", "BEST EMAIL", "Website", "Phone"}
    assert row["Decision maker"] == "" and row["Phone"] == "" and row["Website"] == ""


def test_the_imported_leads_flow_through_the_store_and_show_the_correct_next_action():
    store = MemoryStore([lead("A-0001")])
    result = importer.import_leads(importer.records_from_csv(CSV), store.leads(), prefix="A")
    store.append_leads("A", result["accepted"])

    data = console_model.snapshot(store, settings={}, now=at("2026-09-28 09:00"))
    views = {v["id"]: v for v in data["leads"]}
    assert views["A-0002"]["channel"] == "EMAIL"
    assert views["A-0003"]["channel"] == "CALL"
    assert views["A-0003"]["phone"] == "(614) 555-0142"
    assert views["A-0003"]["action"].startswith("Call Redwood Plumbing")
    assert views["A-0004"]["channel"] == "COMPANY_ONLY"
    assert views["A-0004"]["action"].startswith("Find a contact for Cedar Roofing")
    # an existing email lead is untouched by any of this
    assert views["A-0001"]["channel"] == "EMAIL"
    # the import appended new rows and rewrote nothing
    assert store.lead_writes == [] and [p for p, _ in store.lead_appends] == ["A"]


def test_a_phone_only_lead_on_hold_shows_no_call_action():
    store = MemoryStore([lead("A-0001")])
    store.append_leads("A", [{"Lead ID": "A-0002", "Company": "Redwood Plumbing",
                              "BEST EMAIL": "", "Phone": "614-555-0142", "HOLD": "waiting"}])
    data = console_model.snapshot(store, settings={}, now=at("2026-09-28 09:00"))
    view = {v["id"]: v for v in data["leads"]}["A-0002"]
    assert view["channel"] == "CALL" and view["action"] == ""  # a hold is respected
