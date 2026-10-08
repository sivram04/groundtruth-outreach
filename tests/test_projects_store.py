"""Store.projects(): read the Projects tab, or an implicit default project so a single-project
account is unchanged. The default is always present, so a lead with a blank Project resolves."""

import pytest

from outreach import projects, sheet
from test_sheet_append import FakeSheets


def store_with(projects_grid=None):
    fake = FakeSheets()
    if projects_grid is not None:
        fake.tabs["Projects"] = projects_grid  # header in row 1 (no title row), like the other tabs table() reads
    return sheet.Store(api=fake)


def test_default_project_uses_the_settings_handbook():
    p = projects.default_project({"handbook_doc_id": "doc-xyz"})
    assert p["id"] == "P-default" and p["type"] == "lead" and p["handbook_doc_id"] == "doc-xyz"


def test_no_projects_tab_gives_one_implicit_default_project():
    got = store_with(None).projects({"handbook_doc_id": "doc-1"})
    assert set(got) == {"P-default"} and got["P-default"]["handbook_doc_id"] == "doc-1"


def test_the_projects_tab_is_read_and_the_default_is_kept():
    grid = [list(projects.HEADER),
            ["P-ref", "Referrals", "referral", "doc-ref", "", "", "2026-10-07"]]
    got = store_with(grid).projects({})
    assert got["P-ref"]["type"] == "referral" and got["P-ref"]["handbook_doc_id"] == "doc-ref"
    assert "P-default" in got  # always present so a blank-Project lead resolves


def test_a_projects_tab_with_changed_columns_is_refused():
    grid = [["Project ID", "Wrong"], ["P-x", "y"]]
    with pytest.raises(RuntimeError):
        store_with(grid).projects({})
