"""Importing a small list: parsing (CSV/TSV/XLSX), mapping to the destination's own columns,
classifying, de-duplicating, reporting unstorable fields, and committing only new rows.

Nothing here touches Google. The fake Store (`stage4_fakes.MemoryStore`) stands in for the Sheet, and
`console_model.build` is the real model, so the journey - import a small list, then show the correct
next action for every lead, including phone-only and company-only - is exercised end to end. The real
Store.append_leads adapter is tested separately in `test_sheet_append.py`.
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
    assert list(accepted) == ["A-0002", "A-0003", "A-0004"]  # numbering continues past A-0001
    assert accepted["A-0002"]["channel"] == channels.EMAIL
    assert accepted["A-0003"]["channel"] == channels.CALL   # phone-only kept
    assert accepted["A-0003"]["row"]["Phone"] == "(614) 555-0142"
    assert accepted["A-0004"]["channel"] == channels.COMPANY_ONLY  # company-only kept
    assert accepted["A-0004"]["row"]["Company"] == "Cedar Roofing"
    assert accepted["A-0002"]["row"]["Location"] == "Columbus OH"  # a supplied field preserved
    assert [d["matched"] for d in result["duplicates"]] == ["A-0001"]
    assert result["skipped"] and "no company, email or phone" in result["skipped"][0]["reason"]
    assert result["summary"] == {"accepted": 3, "duplicates": 1, "skipped": 1, "unstorable": 0,
                                 "by_channel": {"EMAIL": 1, "CALL": 1, "COMPANY_ONLY": 1}}


def test_a_field_with_no_destination_column_is_shown_not_silently_dropped():
    # The destination has neither a Phone nor a Location column.
    dest = ["Lead ID", "Company", "Decision maker", "BEST EMAIL", "Website"]
    result = importer.import_leads(importer.records_from_csv(CSV), {}, prefix="A",
                                   destination_columns=dest)
    call_lead = next(i for i in result["accepted"] if i["channel"] == channels.CALL)
    # the phone has nowhere to go: it is reported, and the row does not carry it
    assert {"field": "phone", "value": "(614) 555-0142"} in call_lead["unstorable"]
    assert "Phone" not in call_lead["row"]
    email_lead = next(i for i in result["accepted"] if i["channel"] == channels.EMAIL)
    assert {"field": "Location", "value": "Columbus OH"} in email_lead["unstorable"]
    assert set(result["unstorable_fields"]) == {"phone", "Location"}
    assert result["summary"]["unstorable"] == 2


def test_a_lead_with_both_an_email_and_a_phone_keeps_both():
    records = [{"Company": "Acme", "Email": "pat@acme.test", "Phone": "614-555-0100"}]
    result = importer.import_leads(records, {}, prefix="A", destination_columns=FULL)
    row = result["accepted"][0]["row"]
    assert row["BEST EMAIL"] == "pat@acme.test" and row["Phone"] == "614-555-0100"
    assert result["accepted"][0]["channel"] == channels.EMAIL  # primary action only; still callable


def test_the_fingerprint_binds_the_accepted_rows_but_not_the_provisional_id():
    a = importer.import_leads(importer.records_from_csv(CSV), existing(), prefix="A",
                             destination_columns=FULL)
    # same input again -> same accepted rows -> same fingerprint
    b = importer.import_leads(importer.records_from_csv(CSV), existing(), prefix="A",
                             destination_columns=FULL)
    assert a["fingerprint"] == b["fingerprint"]
    rows = [item["row"] for item in a["accepted"]]
    assert importer.fingerprint(rows, "A") == a["fingerprint"]
    rows[0]["Company"] = "Changed"
    assert importer.fingerprint(rows, "A") != a["fingerprint"]  # any edit is caught


def test_prepare_commit_assigns_ids_and_skips_rows_now_present():
    result = importer.import_leads(importer.records_from_csv(CSV), existing(), prefix="A",
                                   destination_columns=FULL)
    rows = [item["row"] for item in result["accepted"]]
    to_append, already = importer.prepare_commit(rows, existing(), prefix="A")
    assert [r["Lead ID"] for r in to_append] == ["A-0002", "A-0003", "A-0004"] and already == []
    # if one is now already present (a second commit, or added meanwhile), it is skipped, not doubled
    now = {**existing(), "A-0002": {"Company": "Bluebird Electric",
                                    "BEST EMAIL": "dana@bluebird-electric.test"}}
    to_append2, already2 = importer.prepare_commit(rows, now, prefix="A")
    assert [r["Lead ID"] for r in to_append2] == ["A-0003", "A-0004"]  # renumbered from the current max
    assert [a["matched"] for a in already2] == ["A-0002"]


def test_the_imported_leads_flow_through_the_store_and_show_the_correct_next_action():
    store = MemoryStore([lead("A-0001")], lead_columns=FULL)
    preview = importer.import_leads(importer.records_from_csv(CSV), store.leads(), prefix="A",
                                    destination_columns=store.lead_columns("A"))
    rows = [item["row"] for item in preview["accepted"]]
    to_append, _ = importer.prepare_commit(rows, store.leads(), prefix="A")
    store.append_leads("A", to_append)

    data = console_model.snapshot(store, settings={}, now=at("2026-09-28 09:00"))
    views = {v["id"]: v for v in data["leads"]}
    assert views["A-0003"]["channel"] == "CALL" and views["A-0003"]["phone"] == "(614) 555-0142"
    assert views["A-0003"]["action"].startswith("Call Redwood Plumbing")
    assert views["A-0004"]["channel"] == "COMPANY_ONLY"
    assert views["A-0004"]["action"].startswith("Find a contact for Cedar Roofing")
    assert views["A-0001"]["channel"] == "EMAIL"  # existing email lead untouched
    assert store.lead_writes == [] and [p for p, _ in store.lead_appends] == ["A"]
