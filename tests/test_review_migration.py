"""The Reviews-tab migration dry run: it reports the plan and never writes or creates anything."""

from outreach import review, review_migration
from test_review import HDR, Sheets, srow


def dry(tabs):
    return review_migration.dry_run(api=Sheets(tabs), spreadsheet_id="sid")


def test_it_reports_the_tab_would_be_created_when_absent():
    api = Sheets({"Reviews": None})
    report = review_migration.dry_run(api=api, spreadsheet_id="sid")
    assert report["status"] == "ABSENT" and report["would_write"] is False
    assert report["expected_header"] == list(review.REVIEWS_HEADER)
    assert "Attempt ID" in report["expected_header"]  # the unique-id column is part of the schema
    assert any("create" in step for step in report["plan"])
    assert api.appends == 0 and api.tabs["Reviews"] is None  # nothing created or written


def test_it_reports_ready_when_the_tab_and_header_match():
    report = dry({"Reviews": [HDR, srow("A-0001", "b" * 64, "confirmed", "t1")]})
    assert report["status"] == "READY" and report["existing_rows"] == 1
    assert "append-only" in report["existing_data"]


def test_it_reports_a_header_mismatch_without_changing_anything():
    api = Sheets({"Reviews": [["Lead ID", "Wrong"], ["A-0001", "x"]]})
    report = review_migration.dry_run(api=api, spreadsheet_id="sid")
    assert report["status"] == "HEADER_MISMATCH" and report["would_write"] is False
    assert api.appends == 0


def test_an_older_five_column_header_is_a_mismatch_and_the_manual_migration_is_described():
    old = ["Review ID", "Fingerprint", "Reviewer", "Decision", "Reviewed at (UTC)"]
    report = review_migration.dry_run(api=Sheets({"Reviews": [old]}), spreadsheet_id="sid")
    assert report["status"] == "HEADER_MISMATCH" and report["would_write"] is False
    assert any("Attempt ID" in step for step in report["plan"])  # names the required manual change


def test_the_dry_run_names_rollback_and_older_revision_behavior():
    for tabs in ({"Reviews": None}, {"Reviews": [HDR]}):
        report = dry(tabs)
        assert report["rollback"] and report["older_revisions"]
