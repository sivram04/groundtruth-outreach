"""Project-aware handbook loading: a lead drafts from its project's handbook, loaded by id override,
and a project with no handbook (and no settings fallback) is refused, never guessed."""

import pytest

from outreach import handbook_drive, job_draft, projects


class _Exec:
    def __init__(self, value):
        self.value = value

    def execute(self):
        return self.value


class RecordingDrive:
    """Records which file id was fetched, so a test can prove the project's handbook was loaded."""

    def __init__(self):
        self.requested = []

    def files(self):
        return self

    def get(self, fileId, fields=None):
        self.requested.append(fileId)
        return _Exec({"id": fileId, "name": "Handbook", "mimeType": "text/plain",
                      "modifiedTime": "2026-10-07T12:00:00Z", "version": "1"})

    def get_media(self, fileId):
        text = ("This is the project's outreach handbook. It explains the offer, the tone, the "
                "follow-up cadence and the question to ask, in enough detail to be the real document "
                "and not a stub. " * 6)
        return _Exec(text.encode())


def prow(pid, kind, doc):
    return {"Project ID": pid, "Name": pid, "Type": kind, "Handbook doc ID": doc,
            "Offer JSON": "", "Input schema": "", "Created at (UTC)": ""}


def test_document_id_uses_a_validated_override():
    assert handbook_drive.document_id({"handbook_doc_id": "settingsdoc1"}, override="projectdoc99") == "projectdoc99"
    with pytest.raises(handbook_drive.HandbookUnavailable):
        handbook_drive.document_id(None, override="bad id!")


def test_project_handbook_loads_the_leads_project_handbook():
    all_projects = projects.parse_all([prow("P-default", "lead", "defaultdoc1"),
                                       prow("P-ref", "referral", "referraldoc2")])
    drive = RecordingDrive()
    book, why = job_draft.project_handbook({"Project": "P-ref"}, {}, all_projects, drive=drive)
    assert why is None and book is not None
    assert drive.requested == ["referraldoc2"]  # the referral project's handbook, not the default


def test_a_blank_project_loads_the_default_projects_handbook():
    all_projects = projects.parse_all([prow("P-default", "lead", "defaultdoc1")])
    drive = RecordingDrive()
    job_draft.project_handbook({"Project": ""}, {}, all_projects, drive=drive)
    assert drive.requested == ["defaultdoc1"]


def test_a_project_with_no_handbook_and_no_settings_is_refused():
    all_projects = projects.parse_all([prow("P-none", "investor", "")])
    book, why = job_draft.project_handbook({"Project": "P-none"}, {}, all_projects, drive=RecordingDrive())
    assert book is None and "no handbook" in why


def test_a_project_with_no_handbook_falls_back_to_the_settings_handbook():
    all_projects = projects.parse_all([prow("P-none", "investor", "")])
    drive = RecordingDrive()
    job_draft.project_handbook({"Project": "P-none"}, {"handbook_doc_id": "settingsdoc1"}, all_projects, drive=drive)
    assert drive.requested == ["settingsdoc1"]
