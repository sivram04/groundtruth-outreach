"""load_settings must tolerate a UTF-8 BOM in the settings secret: a value written by PowerShell
5.1 (Set-Content -Encoding utf8) or some editors starts with \\ufeff, which plain json.loads rejects."""

import json

from outreach import job_draft


def test_settings_from_env_parse_with_a_leading_bom(monkeypatch):
    monkeypatch.setenv("OUTREACH_HANDBOOK_JSON", "﻿" + json.dumps({"review_public_key": "k", "offer_approved": True}))
    settings = job_draft.load_settings()
    assert settings["review_public_key"] == "k" and settings["offer_approved"] is True


def test_settings_from_env_parse_without_a_bom(monkeypatch):
    monkeypatch.setenv("OUTREACH_HANDBOOK_JSON", json.dumps({"review_public_key": "k"}))
    assert job_draft.load_settings()["review_public_key"] == "k"


def test_a_bom_encoded_settings_file_is_tolerated(tmp_path, monkeypatch):
    monkeypatch.delenv("OUTREACH_HANDBOOK_JSON", raising=False)
    p = tmp_path / "settings.json"
    p.write_text(json.dumps({"review_public_key": "k"}), encoding="utf-8-sig")  # writes a BOM
    assert job_draft.load_settings(path=p)["review_public_key"] == "k"
