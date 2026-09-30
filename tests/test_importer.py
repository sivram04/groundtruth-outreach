"""Importing a small list: parsing (CSV/TSV/XLSX), mapping to the destination's own columns,
classifying, de-duplicating, reporting unstorable AND invalid contact values, and committing only new
rows. Lead IDs are allocated by the store's append, not here.

Nothing here touches Google. The fake Store (`stage4_fakes.MemoryStore`) stands in for the Sheet, and
`console_model.build` is the real model, so the journey - import a small list, then show the correct
next action for every lead, including phone-only and company-only - is exercised end to end. The real
Store.append_leads adapter is tested in `test_sheet_append.py`.
"""

import io

import openpyxl

from outreach import channels, console_model, importer
from stage4_fakes import MemoryStore, at, lead

CSV = (
    "Company,Contact,Email,Phone,Website,Location\n"
    "Bluebird Electric,Dana Cole,dana@bluebird-electric.test,,https://bluebird-electric.test/,Columbus OH\n"
    "Redwood Plumbing,Sam Ford,,(614) 555-0142,https://redwood-plumbing.test/,Dublin OH\n"  # phone-only
    "Cedar Roofing,,,,cedar-roofing.test,\n"                                                 # company-only
    "Example Electric,Sam Rivers,sam@example-electric.test,,,\n"                             # duplicate of A-0001
    ",,,,,\n"                                                                                 # nothing to import
)
FULL = ["Lead ID", "Company", "Decision maker", "BEST EMAIL", "Website", "Phone", "Location"]


def existing():
    return {"A-0001": lead("A-0001")}  # Example Electric, sam@example-electric.test


def test_a_csv_is_read_into_records_whatever_the_delimiter():
    rows = importer.records_from_csv(CSV)
    assert rows[0]["Company"] == "Bluebird Electric" and rows[0]["Email"] == "dana@bluebird-electric.test"
    tsv = "Company\tPhone\nAcme\t614-555-0100\n"
    assert importer.records_from_csv(tsv) == [{"Company": "Acme", "Phone": "614-555-0100"}]
    assert importer.records_from_csv("") == [] and importer.records_from_csv("   ") == []


def test_records_from_file_reads_csv_tsv_and_xlsx_and_refuses_other_types():
    assert importer.records_from_file("leads.csv", b"Company,Phone\nAcme,614-555-0100\n") == [
        {"Company": "Acme", "Phone": "614-555-0100"}]
    assert importer.records_from_file("leads.tsv", b"Company\tPhone\nAcme\t614-555-0100\n") == [
        {"Company": "Acme", "Phone": "614-555-0100"}]
    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.append(["Company", "Phone"])
    sheet.append(["Acme", 6145550100])  # a phone stored as a number must not be lost
    buffer = io.BytesIO()
    workbook.save(buffer)
    assert importer.records_from_file("leads.xlsx", buffer.getvalue()) == [
        {"Company": "Acme", "Phone": "6145550100"}]
    try:
        importer.records_from_file("leads.pdf", b"%PDF-1.4")
        assert False, "a .pdf should be refused"
    except ValueError as exc:
        assert "unsupported file type" in str(exc)


def test_import_keeps_all_four_kinds_and_dedupes_and_numbers():
    result = importer.import_leads(importer.records_from_csv(CSV), existing(), prefix="A",
                                   destination_columns=FULL)
    accepted = {item["lead_id"]: item for item in result["accepted"]}
    assert list(accepted) == ["A-0002", "A-0003", "A-0004"]  # provisional numbering, for display
    assert accepted["A-0002"]["channel"] == channels.EMAIL
    assert accepted["A-0003"]["channel"] == channels.CALL   # phone-only kept
    assert accepted["A-0003"]["row"]["Phone"] == "(614) 555-0142"
    assert accepted["A-0004"]["channel"] == channels.COMPANY_ONLY  # company-only kept
    assert accepted["A-0002"]["row"]["Location"] == "Columbus OH"  # a supplied field preserved
    assert [d["matched"] for d in result["duplicates"]] == ["A-0001"]
    assert result["skipped"] and "no company, email or phone" in result["skipped"][0]["reason"]
    assert result["summary"] == {"accepted": 3, "duplicates": 1, "skipped": 1, "unstorable": 0,
                                 "invalid": 0, "by_channel": {"EMAIL": 1, "CALL": 1, "COMPANY_ONLY": 1}}


def test_invalid_contact_values_are_preserved_in_the_feedback_not_discarded():
    # The reviewer's counterexample: a malformed email and a too-short phone must be shown, with why,
    # and the company-only lead is still accepted.
    result = importer.import_leads([{"Company": "Synthetic", "Email": "wrong-address", "Phone": "123"}],
                                   {}, destination_columns=importer.CANONICAL)
    item = result["accepted"][0]
    assert item["channel"] == channels.COMPANY_ONLY
    assert item["row"] == {"Company": "Synthetic"}  # nothing invalid was stored
    assert {"field": "email", "value": "wrong-address", "reason": "not a valid email address"} in item["invalid"]
    assert any(i["field"] == "phone" and i["value"] == "123" for i in item["invalid"])
    assert result["summary"]["invalid"] == 2


def test_invalid_values_on_a_row_with_nothing_to_key_on_are_still_reported():
    result = importer.import_leads([{"Email": "nope", "Phone": "12"}], {},
                                   destination_columns=importer.CANONICAL)
    assert result["accepted"] == []
    skipped = result["skipped"][0]
    assert skipped["reason"].startswith("no company")
    assert {"field": "email", "value": "nope", "reason": "not a valid email address"} in skipped["invalid"]


def test_a_field_with_no_destination_column_is_shown_not_silently_dropped():
    dest = ["Lead ID", "Company", "Decision maker", "BEST EMAIL", "Website"]  # no Phone, no Location
    result = importer.import_leads(importer.records_from_csv(CSV), {}, prefix="A",
                                   destination_columns=dest)
    call_lead = next(i for i in result["accepted"] if i["channel"] == channels.CALL)
    assert {"field": "phone", "value": "(614) 555-0142"} in call_lead["unstorable"]
    assert "Phone" not in call_lead["row"]
    email_lead = next(i for i in result["accepted"] if i["channel"] == channels.EMAIL)
    assert {"field": "Location", "value": "Columbus OH"} in email_lead["unstorable"]
    assert set(result["unstorable_fields"]) == {"phone", "Location"}


def test_a_lead_with_both_an_email_and_a_phone_keeps_both():
    records = [{"Company": "Acme", "Email": "pat@acme.test", "Phone": "614-555-0100"}]
    result = importer.import_leads(records, {}, prefix="A", destination_columns=FULL)
    row = result["accepted"][0]["row"]
    assert row["BEST EMAIL"] == "pat@acme.test" and row["Phone"] == "614-555-0100"
    assert result["accepted"][0]["channel"] == channels.EMAIL  # primary action only; still callable


def test_the_fingerprint_binds_the_rows_and_the_destination_schema():
    a = importer.import_leads(importer.records_from_csv(CSV), existing(), prefix="A",
                             destination_columns=FULL)
    rows = [item["row"] for item in a["accepted"]]
    assert importer.fingerprint(rows, "A", FULL) == a["fingerprint"]
    # an edit to a row changes it
    changed = [dict(r) for r in rows]
    changed[0]["Company"] = "Changed"
    assert importer.fingerprint(changed, "A", FULL) != a["fingerprint"]
    # and, crucially, a change to the destination columns changes it too (the reviewer's failure #1)
    without_phone = [c for c in FULL if c != "Phone"]
    assert importer.fingerprint(rows, "A", without_phone) != a["fingerprint"]


def test_prepare_commit_skips_rows_now_present_and_assigns_no_ids():
    result = importer.import_leads(importer.records_from_csv(CSV), existing(), prefix="A",
                                   destination_columns=FULL)
    rows = [item["row"] for item in result["accepted"]]
    to_append, already = importer.prepare_commit(rows, existing(), prefix="A")
    assert len(to_append) == 3 and all("Lead ID" not in r for r in to_append)  # ids assigned at append
    assert already == []
    # if a row is now already present (a second commit, or added meanwhile), it is skipped
    now = {**existing(), "A-0002": {"Company": "Bluebird Electric",
                                    "BEST EMAIL": "dana@bluebird-electric.test"}}
    to_append2, already2 = importer.prepare_commit(rows, now, prefix="A")
    assert len(to_append2) == 2 and [a["matched"] for a in already2] == ["A-0002"]


def test_the_imported_leads_flow_through_the_store_and_show_the_correct_next_action():
    store = MemoryStore([lead("A-0001")], lead_columns=FULL)
    preview = importer.import_leads(importer.records_from_csv(CSV), store.leads(), prefix="A",
                                    destination_columns=store.lead_columns("A"))
    rows = [item["row"] for item in preview["accepted"]]
    to_append, _ = importer.prepare_commit(rows, store.leads(), prefix="A")
    ids = store.append_leads("A", to_append)  # the store allocates the ids
    assert ids == ["A-0002", "A-0003", "A-0004"]

    data = console_model.snapshot(store, settings={}, now=at("2026-09-28 09:00"))
    views = {v["id"]: v for v in data["leads"]}
    assert views["A-0003"]["channel"] == "CALL" and views["A-0003"]["phone"] == "(614) 555-0142"
    assert views["A-0003"]["action"].startswith("Call Redwood Plumbing")
    assert views["A-0004"]["channel"] == "COMPANY_ONLY"
    assert views["A-0004"]["action"].startswith("Find a contact for Cedar Roofing")
    assert views["A-0001"]["channel"] == "EMAIL"  # existing email lead untouched
    assert store.lead_writes == [] and [p for p, _ in store.lead_appends] == ["A"]
