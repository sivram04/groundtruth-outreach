"""The pure projects model: parse/validate project rows and select a target's project."""

import json

import pytest

from outreach import projects


def row(**over):
    base = {"Project ID": "P-leads", "Name": "Construction leads", "Type": "lead",
            "Handbook doc ID": "doc-123", "Offer JSON": "", "Input schema": "",
            "Created at (UTC)": "2026-10-07T12:00:00Z"}
    base.update(over)
    return base


def test_parse_a_valid_project():
    p = projects.parse(row(**{"Offer JSON": json.dumps({"cta": "a call"}),
                              "Input schema": json.dumps(["company", "offer"])}))
    assert p["id"] == "P-leads" and p["type"] == "lead" and p["handbook_doc_id"] == "doc-123"
    assert p["offer"] == {"cta": "a call"} and p["input_schema"] == ["company", "offer"]


def test_blank_offer_and_schema_default():
    p = projects.parse(row())
    assert p["offer"] == {} and p["input_schema"] == []


def test_each_type_is_accepted():
    for kind in ("lead", "referral", "investor", "custom"):
        assert projects.parse(row(Type=kind))["type"] == kind


def test_an_unknown_type_is_rejected():
    with pytest.raises(projects.ProjectError):
        projects.parse(row(Type="partnership"))


def test_missing_id_or_name_is_rejected():
    with pytest.raises(projects.ProjectError):
        projects.parse(row(**{"Project ID": ""}))
    with pytest.raises(projects.ProjectError):
        projects.parse(row(Name=""))


def test_malformed_json_is_rejected_not_guessed():
    with pytest.raises(projects.ProjectError):
        projects.parse(row(**{"Offer JSON": "{not json"}))
    with pytest.raises(projects.ProjectError):
        projects.parse(row(**{"Input schema": json.dumps({"not": "a list"})}))


def test_parse_all_keys_by_id_and_rejects_duplicates():
    got = projects.parse_all([row(**{"Project ID": "P-a"}), row(**{"Project ID": "P-b"})])
    assert set(got) == {"P-a", "P-b"}
    with pytest.raises(projects.ProjectError):
        projects.parse_all([row(**{"Project ID": "P-a"}), row(**{"Project ID": "P-a"})])


def test_a_target_resolves_to_its_project_or_the_default():
    all_projects = projects.parse_all([row(**{"Project ID": "P-default"}),
                                       row(**{"Project ID": "P-ref", "Type": "referral"})])
    assert projects.project_of(all_projects, {"Project": "P-ref"})["type"] == "referral"
    assert projects.project_of(all_projects, {"Project": ""})["id"] == "P-default"  # blank -> default
    assert projects.project_of(all_projects, {"Project": "P-missing"}) is None  # named but absent


def test_handbook_doc_is_picked_by_the_targets_project():
    all_projects = projects.parse_all([
        row(**{"Project ID": "P-default", "Handbook doc ID": "doc-default"}),
        row(**{"Project ID": "P-ref", "Type": "referral", "Handbook doc ID": "doc-ref"}),
        row(**{"Project ID": "P-none", "Type": "investor", "Handbook doc ID": ""}),
    ])
    # a lead's own project's handbook wins
    assert projects.handbook_doc_for({"Project": "P-ref"}, all_projects) == "doc-ref"
    # a blank Project resolves to the default project's handbook
    assert projects.handbook_doc_for({"Project": ""}, all_projects) == "doc-default"
    # a project with no handbook falls back to the settings handbook
    assert projects.handbook_doc_for({"Project": "P-none"}, all_projects, {"handbook_doc_id": "doc-s"}) == "doc-s"
    # nothing configured -> "" so the caller refuses rather than guesses
    assert projects.handbook_doc_for({"Project": "P-none"}, all_projects) == ""
