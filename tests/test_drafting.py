"""Stage 3 preview and one-way Gmail draft reservation, entirely offline."""

import base64
from email import policy
from email.parser import BytesParser

import pytest

from outreach import drafting, gmail_drafts, job_draft, worker

QUOTE = "We install electrical distribution systems for commercial buildings."
URL = "https://example.test/services"


def lead(**changes):
    row = {
        "Lead ID": "A-0001", "Company": "Example Electric", "BEST EMAIL": "owner@example.test",
        "Website": "https://example.test/", "Email check": "OK", "Fit": "QUALIFIED",
        "Profile status": "READY", "Profiled at": "2026-09-22 12:00:00",
        "Offerings evidence": f'"{QUOTE}" ({URL})',
    }
    row.update(changes)
    return row


def facts(**changes):
    fact = {"Lead ID": "A-0001", "Researched at": "2026-09-22 12:00:00",
            "Category": "OFFERING", "Quote": QUOTE, "Page URL": URL}
    fact.update(changes)
    return [fact]


def settings(**changes):
    config = {"product_name": "Lakshyaa", "intended_use": "help trade contractors review cash timing",
              "next_week_action": "have a short conversation about an early preview",
              "cta_question": "Would a short conversation next week be useful?",
              "sender_name": "Founder", "founder_title": "Founder",
              "sender_website": "https://lakshyaa.ai", "postal_address": "123 Example St, Cleveland, OH 44101",
              "sender_email": "admin@lakshyaa.ai", "daily_cap": 4, "offer_approved": True,
              "version": "prelaunch-v1"}
    config.update(changes)
    return config


def test_preview_uses_only_current_matching_company_quote():
    out = drafting.preview(lead(), facts(), settings(), suppressed=False,
                           subject_template="Question for [COMPANY]?")
    assert out["preview_hash"] and out["blockers"] == []
    assert QUOTE in out["body"] and out["evidence"] == {"category": "OFFERING", "quote": QUOTE, "url": URL}
    assert out["subject"] == "Question for Example Electric?"
    assert "MVP is still being finished" in out["body"]
    assert "no thanks" in out["body"] and "123 Example St" in out["body"]


@pytest.mark.parametrize("change", [
    {"Researched at": "old"}, {"Quote": "We have no verifiable statement."},
    {"Page URL": "https://other.test/services"},
])
def test_mismatched_evidence_cannot_become_send_ready(change):
    out = drafting.preview(lead(), facts(**change), settings(), suppressed=False)
    assert out["preview_hash"] is None and "no current, verified company quote" in out["blockers"]


@pytest.mark.parametrize("row_change,suppressed,config_change", [
    ({"Email check": "RISKY"}, False, {}),
    ({"Fit": "REVIEW_NEEDED"}, False, {}),
    ({"Sent by hand": "Sent email on 9/22/2026"}, False, {}),
    ({"HOLD": "yes"}, False, {}),
    ({"Draft status": "RESERVED"}, False, {}),
    ({}, True, {}),
    ({}, None, {}),
    ({}, False, {"postal_address": "[POSTAL_ADDRESS]"}),
    ({}, False, {"offer_approved": "true"}),
    ({}, False, {"cta_question": "Please book a call"}),
    ({}, False, {"sender_email": ""}),
])
def test_unsafe_previews_never_have_an_approvable_hash(row_change, suppressed, config_change):
    out = drafting.preview(lead(**row_change), facts(), settings(**config_change),
                           suppressed=suppressed)
    assert out["preview_hash"] is None and out["blockers"]


def test_missing_handbook_fields_are_visible_but_not_send_ready():
    out = drafting.preview(lead(), facts(), {}, suppressed=False)
    assert out["preview_hash"] is None
    assert "handbook field INTENDED_USE is missing" in out["blockers"]
    assert "[INTENDED_USE]" in out["body"]


def test_phone_appears_between_website_and_address_when_set():
    out = drafting.preview(lead(), facts(), settings(sender_phone="614-599-3989"), suppressed=False)
    assert out["preview_hash"] and out["blockers"] == []
    assert "https://lakshyaa.ai\n614-599-3989\n123 Example St" in out["body"]


def test_no_phone_leaves_no_blank_line():
    out = drafting.preview(lead(), facts(), settings(), suppressed=False)
    assert out["preview_hash"] and "https://lakshyaa.ai\n123 Example St" in out["body"]
    assert "[SENDER_PHONE]" not in out["body"]


@pytest.mark.parametrize("phone", ["12345", "call me", "614-599-398"])
def test_malformed_phone_blocks_approval(phone):
    out = drafting.preview(lead(), facts(), settings(sender_phone=phone), suppressed=False)
    assert out["preview_hash"] is None and "sender phone is invalid" in out["blockers"]


def test_phone_is_part_of_approved_hash():
    assert (drafting.preview(lead(), facts(), settings(), suppressed=False)["preview_hash"]
            != drafting.preview(lead(), facts(), settings(sender_phone="614-599-3989"),
                                suppressed=False)["preview_hash"])


def test_sender_identity_is_part_of_approved_hash():
    first = drafting.preview(lead(), facts(), settings(), suppressed=False)
    second = drafting.preview(lead(), facts(), settings(sender_email="other@lakshyaa.ai"),
                              suppressed=False)
    assert first["preview_hash"] != second["preview_hash"]


def test_default_opening_skips_residential_and_run_in_headings_for_verified_market_quote():
    residential = "New Construction Plumbing Plumbing layout and rough-in for homes."
    heading = "Commercial HVAC Comfort cooling, chillers, DX systems, and boilers."
    market = "Our portfolio includes schools, hospitals, and industrial facilities across Ohio."
    rows = [
        {"Lead ID": "A-0001", "Researched at": "2026-09-22 12:00:00", "Category": "OFFERING",
         "Quote": residential, "Page URL": "https://example.test/residential"},
        {"Lead ID": "A-0001", "Researched at": "2026-09-22 12:00:00", "Category": "OFFERING",
         "Quote": heading, "Page URL": "https://example.test/commercial"},
        {"Lead ID": "A-0001", "Researched at": "2026-09-22 12:00:00", "Category": "MARKET",
         "Quote": market, "Page URL": "https://example.test/projects"},
    ]
    row = lead(**{
        "Offerings evidence": (f'"{residential}" (https://example.test/residential)\n'
                               f'"{heading}" (https://example.test/commercial)'),
        "Markets evidence": f'"{market}" (https://example.test/projects)',
    })
    out = drafting.preview(row, rows, settings(), suppressed=False)
    assert out["evidence"]["quote"] == market
    assert len(out["evidence_options"]) == 3
    assert out["preview_hash"]


def test_decision_maker_first_name_only_when_their_email_matches_recipient():
    named = lead(**{"BEST EMAIL": "brian@example.test", "Decision maker": "Brian Monroe, Owner",
                    "Their email": "brian@example.test"})
    matching = drafting.preview(named, facts(), settings(), suppressed=False)
    assert matching["body"].startswith("Hi Brian,")

    named["Their email"] = "other@example.test"
    mismatched = drafting.preview(named, facts(), settings(), suppressed=False)
    assert mismatched["body"].startswith("Hi there,")

    named["Their email"] = "brian@example.test"
    named["BEST EMAIL"] = "owner@example.test"
    role_inbox = drafting.preview(named, facts(), settings(), suppressed=False)
    assert role_inbox["body"].startswith("Hi there,")


def test_selected_verified_market_quote_changes_copy_and_hash():
    market = "Our portfolio includes schools, hospitals, and industrial facilities across Ohio."
    market_url = "https://example.test/projects"
    row = lead(**{"Markets evidence": f'"{market}" ({market_url})'})
    rows = facts() + [{"Lead ID": "A-0001", "Researched at": "2026-09-22 12:00:00",
                      "Category": "MARKET", "Quote": market, "Page URL": market_url}]
    default = drafting.preview(row, rows, settings(), suppressed=False)
    choice = next(o["quote_id"] for o in default["evidence_options"] if o["category"] == "MARKET")
    selected = drafting.preview(row, rows, settings(), suppressed=False, selected_quote_id=choice)
    assert selected["evidence"]["quote"] == market
    assert selected["preview_hash"] != default["preview_hash"]
    assert selected["selected_quote_id"] == choice


def test_unverified_or_residential_selected_quote_cannot_be_approved():
    residential = "We provide residential plumbing repairs and service for local homes."
    url = "https://example.test/residential"
    row = lead(**{"Offerings evidence": f'"{residential}" ({url})'})
    rows = facts(Quote=residential, **{"Page URL": url})
    option = drafting.preview(row, rows, settings(), suppressed=False)["evidence_options"][0]
    assert not option["usable"]
    blocked = drafting.preview(row, rows, settings(), suppressed=False,
                               selected_quote_id=option["quote_id"])
    assert blocked["preview_hash"] is None
    missing = drafting.preview(row, rows, settings(), suppressed=False,
                               selected_quote_id="not-a-current-quote")
    assert missing["preview_hash"] is None

    generic_page = "https://example.test/about"
    row["Offerings evidence"] = f'"{residential}" ({generic_page})'
    rows[0]["Page URL"] = generic_page
    residential_words = drafting.preview(row, rows, settings(), suppressed=False)
    assert not residential_words["evidence_options"][0]["usable"]


def test_quote_choice_flows_through_preview_job():
    market = "Our portfolio includes schools, hospitals, and industrial facilities across Ohio."
    market_url = "https://example.test/projects"
    row = lead(**{"Markets evidence": f'"{market}" ({market_url})'})
    rows = facts() + [{"Lead ID": "A-0001", "Researched at": "2026-09-22 12:00:00",
                      "Category": "MARKET", "Quote": market, "Page URL": market_url}]
    option = drafting.preview(row, rows, settings(), suppressed=False)["evidence_options"][1]
    result = job_draft.previews(["A-0001"], settings=settings(),
                                fixture={"leads": [row], "research": rows,
                                         "suppressed": {"A-0001": False}},
                                quote_choices={"A-0001": option["quote_id"]})[0]
    assert result["evidence"]["quote"] == market


def test_default_quality_screen_accepts_company_sentence_and_rejects_fragments():
    facts_for_opening = [
        {"category": "OFFERING", "quote": (
            "Monroe Plumbing installs and modifies commercial gas lines for equipment upgrades "
            "and renovations with safety in mind."), "url": "https://example.test/commercial"},
        {"category": "MARKET", "quote": "for commercial, industrial, and institutional projects.",
         "url": "https://example.test/projects"},
        {"category": "MARKET", "quote": (
            "Healthcare, workplace, retail, hospitality, industrial, automotive, "
            "and specialty medical environments."), "url": "https://example.test/markets"},
    ]
    options = drafting.opening_options(facts_for_opening, "Monroe Plumbing LLC")
    assert options[0]["default_eligible"]
    assert not options[1]["default_eligible"] and "starts mid-sentence" in options[1]["warnings"]
    assert not options[2]["default_eligible"] and "not a complete sentence" in options[2]["warnings"]


class FakeTab:
    name = "A_Contact_Now"

    def __init__(self, row):
        self.lead = row
        self.rows = [(3, row)]
        self.writes = []

    def ensure_columns(self, names):
        assert "Draft action" in names

    def write(self, changes):
        assert list(changes) == [3]
        self.lead.update(changes[3])
        self.writes.append(changes[3])
        return {"written": 1, "skipped": []}


class Mailbox:
    def users(self):
        return self

    def getProfile(self, **kwargs):
        return self

    def execute(self):
        return {"emailAddress": "admin@lakshyaa.ai"}


def test_reconcile_only_finalizes_one_matching_draft(monkeypatch):
    monkeypatch.setenv("ENABLE_GMAIL_DRAFTS", "true")
    row = lead(**{"Draft action": "action-1", "Draft status": "RESERVED",
                  "Draft hash": "hash", "Draft action at": "2026-09-22T12:00:00+00:00"})
    tab = FakeTab(row)
    monkeypatch.setattr(job_draft, "_read", lambda api, ids, sheet_id=None: ([tab], [(tab, 3, row)], []))
    monkeypatch.setattr(gmail_drafts, "drafts_for_action", lambda gmail, action: [])
    assert job_draft.reconcile("A-0001", api=object(), gmail=Mailbox())["status"] == "UNRESOLVED"
    assert tab.writes == []
    monkeypatch.setattr(gmail_drafts, "drafts_for_action", lambda gmail, action: [{"id": "draft-1"}])
    assert job_draft.reconcile("A-0001", api=object(), gmail=Mailbox())["status"] == "CREATED"
    assert row["Draft ID"] == "draft-1"


def test_gmail_write_is_disabled_by_default(monkeypatch):
    monkeypatch.delenv("ENABLE_GMAIL_DRAFTS", raising=False)
    with pytest.raises(job_draft.DraftBlocked, match="disabled"):
        job_draft.create("A-0001", "hash", settings=settings(), api=object(), gmail=Mailbox())


def test_worker_draft_create_endpoint_is_disabled_by_default(monkeypatch):
    monkeypatch.delenv("ENABLE_GMAIL_DRAFTS", raising=False)
    result = worker.app.test_client().post(
        "/jobs/draft/create", json={"lead_id": "A-0001", "approved_hash": "hash"})
    assert result.status_code == 403


def test_gmail_boundary_creates_only_a_draft():
    class Call:
        def __init__(self, result):
            self.result = result

        def execute(self):
            return self.result

    class Gmail:
        body = None

        def users(self):
            return self

        def drafts(self):
            return self

        def create(self, **kwargs):
            self.body = kwargs["body"]
            return Call({"id": "draft-1"})

    gmail = Gmail()
    assert gmail_drafts.create(gmail, to="owner@example.test", from_address="admin@lakshyaa.ai",
                               subject="Question", body="Hello", action_id="action-1")["id"] == "draft-1"
    raw = gmail.body["message"]["raw"]
    message = BytesParser(policy=policy.default).parsebytes(
        base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4)))
    assert message["To"] == "owner@example.test"
    assert message[gmail_drafts.ACTION_HEADER] == "action-1"
    assert message.get_content().strip() == "Hello"
