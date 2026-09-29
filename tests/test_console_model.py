"""The console's data: where each lead stands, what needs the founder, and the counts.

Worked out from made-up leads (`console_fixture`) that cover every kind of lead the pages show.
"""

import json
from collections import defaultdict
from datetime import date

import pytest

import console_fixture as fx
from outreach import console_model, sequence, sheet, sync
from stage4_fakes import MemoryStore, at


@pytest.fixture(scope="module")
def data():
    return fx.snapshot()


def leads(data):
    return {v["id"]: v for v in data["leads"]}


def test_each_lead_gets_the_status_the_sync_writes(data):
    assert {v["id"]: v["status"] for v in data["leads"]} == {
        "A-0001": "SENT", "A-0002": "REPLIED", "A-0003": "SENT", "A-0004": "REVIEW_NEEDED",
        "A-0005": "BOUNCED", "A-0006": "OPTED_OUT", "A-0007": "", "A-0008": "", "A-0009": "",
        "A-0010": "", "A-0011": "", "A-0012": "", "A-0013": "", "A-0014": "", "B-0001": "SENT",
        "B-0002": "DRAFTED",
        "B-0003": ""}


def test_the_console_and_the_lead_tabs_say_the_same_thing(data):
    """The sync writes these columns every ten minutes; the console works them out again for the
    same day with the same function, so the two can never tell different stories."""
    rows = {row["Lead ID"]: row for row in fx.rows()}
    by_lead = defaultdict(list)
    for event in sync.unique(fx.events()):
        by_lead[event["Lead ID"]].append(event)
    written = sync.summaries(rows, by_lead, fx.suppression(), date(2026, 9, 28))
    for lead_id, view in leads(data).items():
        for column in sheet.SYNC_COLUMNS + sheet.TRACKING_COLUMNS:
            assert view["cells"][column] == written.get(lead_id, {}).get(column, ""), (lead_id, column)


def test_what_needs_the_founder_comes_in_order_with_the_sheets_own_words(data):
    needs = [(item["lead_id"], item["label"]) for item in data["needs_you"]]
    assert needs == [("A-0002", "Reply to answer"), ("A-0001", "Follow-up due"),
                     ("B-0002", "Draft waiting"), ("A-0005", "To check"), ("A-0004", "To check")]
    by = {item["lead_id"]: item for item in data["needs_you"]}
    assert by["A-0001"]["text"] == leads(data)["A-0001"]["action"] == (
        "Follow-up 1 was due Fri 2026-09-25. You started this thread by hand, so write it "
        "yourself in the same thread.")
    assert by["A-0004"]["address"] == "jeff@riverbend-drywall.test"  # the address emailed
    assert "A-0006" not in by  # asked to stop: nothing more to do, ever


def test_follow_ups_coming_up_are_listed_by_day(data):
    assert [(i["lead_id"], i["step"], i["day"]) for i in data["coming_up"]] == [
        ("B-0001", 1, "Tue 2026-09-29"), ("A-0003", 1, "Wed 2026-09-30")]
    assert data["coming_up_days"] == console_model.COMING_UP_BUSINESS_DAYS


def test_ready_for_a_first_draft_uses_the_drafting_steps_own_checks(data):
    assert data["ready"] == ["A-0007", "A-0008", "A-0013", "A-0014"]
    blockers = {lead_id: view["blockers"] for lead_id, view in leads(data).items()}
    assert blockers["A-0009"] == ["email check is RISKY"]
    assert blockers["A-0010"] == ["fit is DISQUALIFIED"]
    assert blockers["A-0011"] == ["on hold"]
    assert blockers["A-0012"] == ["company profile is not READY"]
    assert blockers["B-0003"][0] == "email check is not done"
    assert "already emailed" in blockers["B-0001"]


def test_the_counts_follow_the_sheet_dashboards_definitions(data):
    a, b, both = data["tiers"]
    assert (a["leads"], a["emailed"], a["emails_sent"], a["replied"], a["reply_rate"]) == (14, 6, 6, 2, "33%")
    assert (a["opted_out"], a["bounced"], a["review_needed"], a["ready"]) == (1, 1, 1, 4)
    assert (a["checked_ok"], a["qualified"], a["profiled"], a["drafted"]) == (13, 13, 13, 3)
    assert (b["emailed"], b["tracked"], b["opened"], b["open_rate"], b["clicked"]) == (1, 1, 1, "100%", 1)
    assert a["open_rate"] == "-"  # no tracked email in A: no rate, never 0%
    assert both["label"] == "A and B" and both["emails_sent"] == 7  # the tracking test is no lead


def test_gmail_drafts_waiting_are_the_ones_the_sheet_knows_and_were_not_sent(data):
    assert [(d["lead_id"], d["kind"], d["status"]) for d in data["gmail_drafts"]] == [
        ("B-0002", "First email", "CREATED")]


def test_a_website_link_is_given_only_for_an_http_address(data):
    view = leads(data)
    assert view["A-0001"]["website_href"] == "https://example-electric.test/"
    assert view["A-0012"]["website_href"] == ""  # javascript:alert(1)
    assert view["A-0004"]["website_href"] == ""  # no scheme: shown as text, not linked
    assert view["A-0012"]["company"] == "Oak Tile & Stone <b>Ltd</b>"  # data, escaped by the page


def test_the_settings_show_approvals_and_never_the_founders_address_or_phone(data):
    assert data["approvals"] == {"offer": False, "followups": False, "tracking": False,
                                 "daily_cap": 4, "sender": "admin@lakshyaa.ai"}
    # A draft's signature carries the address by design; nothing else may.
    text = json.dumps({key: value for key, value in data.items() if key != "drafts"})
    assert fx.SETTINGS["postal_address"] not in text and fx.SETTINGS["sender_phone"] not in text
    assert console_model.approvals({}) is None


def test_the_links_the_pages_use(data):
    assert data["links"] == {
        "sheet": console_model.SHEET_URL,
        "handbook": "https://docs.google.com/document/d/demo-handbook-document/edit",
        "gmail_account": "admin@lakshyaa.ai"}


def test_it_is_plain_json_in_a_versioned_shape(data):
    assert json.loads(json.dumps(data)) == data
    assert data["version"] == console_model.VERSION == 2
    assert data["today"] == "2026-09-28" and data["read_at"] == "2026-09-28 09:00 ET"
    assert data["sync"] == {"at": "2026-09-28 08:50 ET", "result": "OK",
                            "detail": "read 3 messages; new events: none; cursor 2026-09-28T12:50:00Z"}


def test_an_unreadable_suppression_tab_means_nobody_is_called_ready():
    data = console_model.build({r["Lead ID"]: r for r in fx.rows()}, fx.events(), None, [],
                               settings={}, now=fx.NOW)
    assert data["ready"] is None and data["suppression_count"] is None
    assert data["approvals"] is None
    assert any("Suppression tab cannot be read" in w for w in data["warnings"])
    assert all(not v["ready"] for v in data["leads"])


def test_a_lead_whose_events_cannot_be_read_is_flagged_and_the_rest_still_show():
    broken = [dict(e) for e in fx.events()]
    for event in broken:
        if event["Lead ID"] == "A-0003":
            event[sequence.OCCURRED] = "last Friday"
    data = console_model.build({r["Lead ID"]: r for r in fx.rows()}, broken, fx.suppression(), [],
                               settings={}, now=fx.NOW)
    view = {v["id"]: v for v in data["leads"]}
    assert view["A-0003"]["error"] and view["A-0003"]["status_label"] == "Could not be worked out"
    assert view["A-0002"]["status"] == "REPLIED"
    assert any("A-0003" in w for w in data["warnings"])
    assert ("A-0003", "To check") in [(i["lead_id"], i["label"]) for i in data["needs_you"]]


def test_reading_the_console_writes_nothing():
    store = MemoryStore(fx.rows(), events=fx.events(), suppression=fx.suppression(), runs=fx.runs())
    before = (store.leads(), store.events(), store.suppression(), list(store.runs))
    console_model.snapshot(store, settings=fx.SETTINGS, now=fx.NOW)
    assert (store.leads(), store.events(), store.suppression(), list(store.runs)) == before
    assert store.lead_writes == [] and store.columns_added == []


def test_the_react_apps_demo_data_is_this_fixture_through_the_real_model():
    """If this fails, run `python tests/console_fixture.py --write` and look at the change."""
    assert fx.FIXTURE.read_text(encoding="utf-8") == fx.text()


def test_moment_reads_both_ways_this_system_writes_a_time():
    assert console_model.moment("2026-09-28 16:06:01") == "2026-09-28 12:06 ET"
    assert console_model.moment("2026-09-24T13:00:00+00:00") == "2026-09-24 09:00 ET"
    assert console_model.moment("") == "" and console_model.moment("soon") == "soon"


def test_percent_is_whole_and_says_so_when_there_is_nothing_to_divide_by():
    assert console_model.percent(1, 3) == "33%" and console_model.percent(2, 3) == "67%"
    assert console_model.percent(0, 0) == "-"
    assert at("2026-09-28 09:00") == fx.NOW


def test_a_follow_up_due_today_needs_the_founder_and_is_not_also_coming_up():
    """Emailed by hand on Wednesday: follow-up 1 is due on the third business day, Monday, today."""
    row = fx.person("A-0001", "Example Electric", "Sam Rivers", "sam@example-electric.test",
                    "https://example-electric.test/", **{"Sent by hand": "2026-09-23"})
    sent = fx._event("A-0001", sequence.SENT, "INITIAL", at("2026-09-23 10:00"),
                     "sam@example-electric.test", "ADDRESS", "t1", "m1", "")
    data = console_model.build({"A-0001": row}, [sent], [], [], settings={}, now=fx.NOW)
    assert [(i["lead_id"], i["label"]) for i in data["needs_you"]] == [("A-0001", "Follow-up due")]
    assert data["needs_you"][0]["text"].startswith("Follow-up 1 is due today.")
    assert data["coming_up"] == []
    assert data["leads"][0]["next_followup"] == {"step": 1, "date": "2026-09-28", "day": "Mon 2026-09-28"}


def test_an_event_recorded_twice_counts_once():
    """Two runs at the same moment could both append the same event: it is still one email."""
    doubled = fx.events() + [e for e in fx.events() if e["Event"] == sequence.SENT]
    data = console_model.build({r["Lead ID"]: r for r in fx.rows()}, doubled, fx.suppression(), [],
                               settings={}, now=fx.NOW)
    assert data["tiers"][-1]["emails_sent"] == 7
    assert data["event_count"] == len(fx.events())
    history = {v["id"]: v["events"] for v in data["leads"]}["A-0001"]
    assert [e["event"] for e in history] == ["Sent"]


# --- the Drafts tab ------------------------------------------------------------------------------

def test_drafts_come_in_order_of_what_can_be_done_with_them(data):
    assert [(d["lead_id"], d["status"], d["status_label"]) for d in data["drafts"]] == [
        ("A-0007", "WAITING", "Waiting for you"), ("A-0008", "WAITING", "Waiting for you"),
        ("A-0013", "HELD", "Held")]
    assert data["drafts_summary"] == {"ready": 0, "waiting": 2, "held": 1, "waiting_for_offer": 2}


def test_a_draft_says_why_it_waits_and_where_its_quote_is_from(data):
    first, second, held = data["drafts"]
    assert first["why"] == ["You have not approved the offer wording yet"]
    assert first["quote_href"] == "https://lakeside-concrete.test/services"
    assert first["contact"] == "Jo Bennett" and first["to"] == "jo@lakeside-concrete.test"
    assert len(second["why"]) == 2 and "not found on its own site" in second["why"][1]
    assert second["quote_href"] == "" and second["quote_page"] == "javascript:alert(2)"
    assert held["body"] == "" and held["why"]


def test_a_draft_never_carries_its_approval_hash_or_the_writers_output(data):
    for draft in data["drafts"]:
        assert "Approval hash" not in draft and "Written" not in draft
        assert set(draft) == {"lead_id", "kind", "to", "company", "contact", "tier", "subject",
                              "body", "quote", "quote_page", "quote_href", "status",
                              "status_label", "why", "prepared_at"}


def test_each_lead_knows_its_drafts_status(data):
    view = leads(data)
    assert (view["A-0007"]["draft"], view["A-0013"]["draft"], view["A-0001"]["draft"]) == (
        "WAITING", "HELD", None)


def test_a_drafts_tab_that_cannot_be_read_is_said_and_the_rest_still_shows():
    class Unreadable(MemoryStore):
        def drafts(self):
            raise RuntimeError("the Drafts tab's columns were changed; it is neither read nor written")

    store = Unreadable(fx.rows(), events=fx.events(), suppression=fx.suppression(), runs=fx.runs())
    data = console_model.snapshot(store, settings=fx.SETTINGS, now=fx.NOW)
    assert data["drafts"] == [] and data["drafts_summary"]["waiting"] == 0
    assert any("The Drafts tab cannot be read" in w and "columns were changed" in w
               for w in data["warnings"])
    assert len(data["leads"]) == len(fx.rows())


def test_drafts_that_can_be_approved_come_first_then_waiting_then_held():
    rows = [dict(fx.draft_rows()[2]), dict(fx.draft_rows()[0], **{"Status": "READY", "Why": ""}),
            dict(fx.draft_rows()[1], **{"Why": 'the company name "Pioneer Paving" was not found on '
                                                 "its own site; check it"})]
    data = console_model.build({r["Lead ID"]: r for r in fx.rows()}, fx.events(), fx.suppression(), [],
                               settings={}, now=fx.NOW, draft_rows=rows)
    assert [(d["lead_id"], d["status"]) for d in data["drafts"]] == [
        ("A-0007", "READY"), ("A-0008", "WAITING"), ("A-0013", "HELD")]
    # Waiting only for a name to be checked is not waiting for the offer approval.
    assert data["drafts_summary"] == {"ready": 1, "waiting": 1, "held": 1, "waiting_for_offer": 0}
