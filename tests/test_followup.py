"""Follow-up drafts, offline: the founder's own wording, in the right thread, only when due.

Every path that could put an unapproved follow-up, or one to a person who answered, in front of
a recipient must fail closed.
"""

import pytest

from outreach import drafting, followup, gmail_drafts, sequence, sync
from stage4_fakes import FakeGmail, MemoryStore, at, lead, message, parsed, sent

SAM = "sam@example-electric.test"
NOW = at("2026-09-28 09:00")  # a Monday; follow-up 1 for a Tuesday 22 September send was due Friday

OFFER = [
    "Draft offer values for founder review",
    "[INTENDED_USE]: use bank balances, open invoices and bills, payroll dates, fixed costs, and "
    "upcoming job billings to compare scenarios and explain recommended next steps",
    "[NEXT_WEEK_ACTION]: have a twenty minute conversation about the early preview",
    "[CTA_QUESTION]: Would you be open to a twenty minute conversation next week about the early "
    "preview?",
]
SIGNATURE = ["Best,  ", "[SENDER_NAME]  ", "[FOUNDER_TITLE], [PRODUCT_NAME]  ", "[SENDER_WEBSITE]  ",
             "[POSTAL_ADDRESS]  ", drafting.OPT_OUT]
# The handbook as the repository draft writes it: Markdown headings, hard-wrapped paragraphs.
MARKDOWN = "\n".join([
    "# MVP outreach handbook — template draft", "", "Status: pre-launch template.", *OFFER, "",
    "## Fields to fill before using the templates", "",
    "| `[NEXT_WEEK_ACTION]` | A verb phrase for a truthful next-week activity. |", "",
    "## Initial email", "", "Hi [FIRST_NAME],", "", "[VERIFIED_COMPANY_OBSERVATION]", "",
    "[CTA_QUESTION]", "", *SIGNATURE, "",
    "## Follow-up 1", "",
    "Draft on the third business day after the founder sends the initial email, if",
    "there has been no reply. Keep it in the same thread.", "",
    "Hi [FIRST_NAME],", "",
    "Following up on my note about [PRODUCT_NAME]. If you choose to [NEXT_WEEK_ACTION],",
    "I'd value your honest reaction to the direction we're taking, including what we",
    "might be missing.", "", "[CTA_QUESTION]", "", *SIGNATURE, "",
    "## Follow-up 2", "",
    "Draft on the third business day after the founder sends follow-up 1, if there",
    "has been no reply. This is the last follow-up.", "",
    "Hi [FIRST_NAME],", "",
    "I'll close the loop on [PRODUCT_NAME]. If you'd like to [NEXT_WEEK_ACTION], reply and",
    "I'll arrange it. If the timing isn't right, no need to respond; this is my last note.", "",
    *SIGNATURE,
])
# The same handbook as a Google Doc exports it: one line a paragraph, no blank lines, CRLF.
EXPORTED = "\r\n".join([
    "MVP outreach handbook — template draft", "Status: pre-launch template.", *OFFER,
    "Initial email", "Hi [FIRST_NAME],", "[VERIFIED_COMPANY_OBSERVATION]", "[CTA_QUESTION]",
    *[s.strip() for s in SIGNATURE],
    "Follow-up 1",
    "Draft on the third business day after the founder sends the initial email, if there has "
    "been no reply.",
    "Hi [FIRST_NAME],",
    "Following up on my note about [PRODUCT_NAME]. If you choose to [NEXT_WEEK_ACTION], I'd value "
    "your honest reaction to the direction we're taking, including what we might be missing.",
    "[CTA_QUESTION]", *[s.strip() for s in SIGNATURE],
    "Follow-up 2",
    "Hi [FIRST_NAME],",
    "I'll close the loop on [PRODUCT_NAME]. If you'd like to [NEXT_WEEK_ACTION], reply and I'll "
    "arrange it. If the timing isn't right, no need to respond; this is my last note.",
    *[s.strip() for s in SIGNATURE],
])
BOOK = {"text": MARKDOWN, "content_hash": "hash-one", "document_id": "doc-one", "name": "Handbook",
        "version": "1", "modified": "2026-09-23T05:00:00Z", "source": "drive"}

FOLLOWUP_1 = """Hi Sam,

Following up on my note about Example Product. If you choose to have a twenty minute conversation about the early preview, I'd value your honest reaction to the direction we're taking, including what we might be missing.

Would you be open to a twenty minute conversation next week about the early preview?

Best,
A Founder
Founder, Example Product
https://example.test
614-555-0100
1 Example St, Columbus, OH 43215
""" + drafting.OPT_OUT


def settings(**changes):
    config = {"product_name": "Example Product", "sender_name": "A Founder",
              "founder_title": "Founder", "sender_website": "https://example.test",
              "postal_address": "1 Example St, Columbus, OH 43215", "sender_phone": "614-555-0100",
              "sender_email": "admin@lakshyaa.ai", "daily_cap": 4, "offer_approved": True,
              "version": "prelaunch-v1", followup.APPROVAL_KEY: "hash-one"}
    config.update(changes)
    return config


def event(kind, step, when, *, message_id="m1", match="DRAFT", thread="t-sys", lead_id="A-0001"):
    return sync._event(lead_id, kind, step, when, SAM, match, thread, message_id, "")


def initial_sent():
    return event(sequence.SENT, sequence.INITIAL, at("2026-09-22 13:18"))


def system_store(*events, row=None, suppression=()):
    return MemoryStore([row or lead()], events=events or [initial_sent()], suppression=list(suppression))


def gmail_with(*extra, drafts=None, address="admin@lakshyaa.ai"):
    return FakeGmail([sent("m1", thread="t-sys", when=at("2026-09-22 13:18"), to=SAM), *extra],
                     drafts=drafts, address=address)


@pytest.fixture
def enabled(monkeypatch):
    monkeypatch.setenv("ENABLE_GMAIL_DRAFTS", "true")


def run(store, gmail=None, *, dry_run=False, now=NOW, config=None, book=BOOK):
    return followup.run(dry_run=dry_run, store=store, gmail=gmail, settings=config or settings(),
                        handbook=book, now=now)


# --- the founder's wording, read from the handbook ------------------------------------------

@pytest.mark.parametrize("text", [MARKDOWN, EXPORTED])
def test_both_handbook_shapes_give_the_same_follow_ups(text):
    parts, problems = followup.templates(text)
    assert problems == []
    assert parts[1] == ["Following up on my note about [PRODUCT_NAME]. If you choose to "
                        "[NEXT_WEEK_ACTION], I'd value your honest reaction to the direction we're "
                        "taking, including what we might be missing.", "[CTA_QUESTION]"]
    assert parts[2] == ["I'll close the loop on [PRODUCT_NAME]. If you'd like to [NEXT_WEEK_ACTION], "
                        "reply and I'll arrange it. If the timing isn't right, no need to respond; "
                        "this is my last note."]
    assert followup.render(1, text, settings(), "Sam") == (FOLLOWUP_1, [])


def test_offer_values_given_twice_differently_block():
    text = MARKDOWN.replace(OFFER[2], OFFER[2] + "\n[NEXT_WEEK_ACTION]: book a demo")
    body, problems = followup.render(1, text, settings(), "Sam")
    assert body is None and "the handbook gives [NEXT_WEEK_ACTION] more than one value" in problems


def test_a_missing_offer_value_is_never_left_as_a_placeholder():
    body, problems = followup.render(1, MARKDOWN.replace(OFFER[3], ""), settings(), "Sam")
    assert body is None and any("[CTA_QUESTION]" in p for p in problems)


def test_a_handbook_without_the_follow_up_blocks_it():
    body, problems = followup.render(2, MARKDOWN.replace("## Follow-up 2", "## Later"), settings(), "Sam")
    assert body is None and any('"Follow-up 2" headings' in p for p in problems)


@pytest.mark.parametrize("change,why", [
    ({"postal_address": ""}, "settings field POSTAL_ADDRESS is missing"),
    ({"postal_address": "Box 1"}, "postal address is too short"),
    ({"sender_phone": "call me"}, "sender phone is invalid"),
    ({"sender_name": "[SENDER_NAME]"}, "settings field SENDER_NAME is missing"),
])
def test_an_incomplete_signature_blocks_every_follow_up(change, why):
    body, problems = followup.render(1, MARKDOWN, settings(**change), "Sam")
    assert body is None and why in problems


def test_the_preview_names_the_hash_to_approve_until_it_is_approved():
    out = followup.preview(settings=settings(**{followup.APPROVAL_KEY: ""}), handbook=BOOK)
    assert out["approved"] is False and "hash-one" in out["to_approve"]
    assert out["followups"]["1"]["body"].startswith("Hi <first name>,")
    assert followup.preview(settings=settings(), handbook=BOOK)["approved"] is True


# --- who is due -----------------------------------------------------------------------------

def test_only_sequences_this_system_started_are_due():
    hand = lead("A-0002", **{"BEST EMAIL": "pat@acme.test", "Their email": "pat@acme.test"})
    store = MemoryStore([lead(), hand], events=[
        initial_sent(), sync._event("A-0002", sequence.SENT, sequence.INITIAL, at("2026-09-22 13:30"),
                                    "pat@acme.test", "ADDRESS", "t2", "m2", "")], suppression=[])
    report = run(store, dry_run=True)
    assert report["due"] == [{"lead_id": "A-0001", "step": 1, "due": "2026-09-25", "to": SAM}]
    assert report["later"] == [] and report["created"] == []


def test_a_hand_sent_sequence_is_never_due_even_if_its_state_said_so(monkeypatch):
    """The founder's rule is enforced twice. `lead_state` never sets `due` for a thread started
    by hand; this checks the second guard on its own, in case the first ever changes."""
    real = sequence.lead_state

    def claims_due(row, events, **kwargs):
        state = real(row, events, **kwargs)
        state["sequence"]["origin"] = sequence.HAND
        return state
    monkeypatch.setattr(sequence, "lead_state", claims_due)
    assert run(system_store(), dry_run=True)["due"] == []


def test_a_follow_up_not_yet_due_waits():
    store = system_store(event(sequence.SENT, sequence.INITIAL, at("2026-09-25 10:00")))
    report = run(store, dry_run=True)
    assert report["due"] == [] and report["later"][0]["due"] == "2026-09-30"


@pytest.mark.parametrize("extra", [
    event(sequence.REPLIED, "", at("2026-09-23 10:00"), message_id="r1", match="THREAD"),
    event(sequence.OPT_OUT, "", at("2026-09-23 10:00"), message_id="r1", match="THREAD"),
    event(sequence.BOUNCED, "", at("2026-09-22 13:19"), message_id="b1", match="THREAD"),
])
def test_a_reply_a_request_to_stop_or_a_bounce_ends_the_sequence(extra):
    assert run(system_store(initial_sent(), extra), dry_run=True)["due"] == []


def test_hold_and_suppression_end_the_sequence():
    assert run(system_store(row=lead(HOLD="yes")), dry_run=True)["due"] == []
    domain = [{"Address or domain": "example-electric.test", "Reason": "asked", "Added at": "",
               "Source": "founder"}]
    assert run(system_store(suppression=domain), dry_run=True)["due"] == []


def test_a_missing_suppression_tab_is_unknown_and_drafts_nothing():
    """The gate now names the cause, because that is what the founder has to act on."""
    store = MemoryStore([lead()], events=[initial_sent()], suppression=None)
    assert run(store, dry_run=True)["gates"] == ["there is no Suppression tab in the Sheet"]


# --- creating the draft ---------------------------------------------------------------------

def test_the_follow_up_is_drafted_in_the_thread_to_the_address_actually_used(enabled):
    store, gmail = system_store(), gmail_with()
    report = run(store, gmail)
    assert [c["lead_id"] for c in report["created"]] == ["A-0001"] and report["blocked"] == []
    request = gmail.created[0]
    email = parsed(request)
    assert request["threadId"] == "t-sys"
    assert email["To"] == SAM and email["Subject"] == "A question"
    assert email["In-Reply-To"] == "<m1@mail.test>" and email["References"] == "<m1@mail.test>"
    assert email[gmail_drafts.ACTION_HEADER] == report["created"][0]["action_id"]
    assert email.get_content().rstrip("\n") == FOLLOWUP_1
    row = store.rows["A-0001"]
    assert (row["Follow-up step"], row["Follow-up status"], row["Follow-up draft ID"]) == \
        ("1", "CREATED", "draft-1")
    assert store.event_rows[-1]["Event"] == sequence.FOLLOWUP_DRAFTED
    assert store.event_rows[-1]["Step"] == "FOLLOWUP_1"
    assert store.runs[-1]["Result"] == "OK"


def test_with_tracking_on_the_follow_up_is_tracked_and_says_so(enabled, monkeypatch):
    from outreach import tracking
    monkeypatch.setattr(tracking, "key", lambda: bytes(range(32)))
    store, gmail = system_store(), gmail_with()
    run(store, gmail, config=settings(tracking_enabled=True))
    email = parsed(gmail.created[0])
    assert email.get_body(preferencelist=("plain",)).get_content().rstrip("\n") == FOLLOWUP_1
    assert tracking.BASE + "/o/" in email.get_body(preferencelist=("html",)).get_content()
    assert store.event_rows[-1]["Detail"].endswith(", tracked")


def test_tracking_on_without_its_key_drafts_no_follow_up(enabled, monkeypatch):
    from outreach import tracking

    def missing():
        raise tracking.TrackingUnavailable("the tracking signing key is not available")
    monkeypatch.setattr(tracking, "key", missing)
    store, gmail = system_store(), gmail_with()
    report = run(store, gmail, config=settings(tracking_enabled=True))
    assert "tracking is on" in report["blocked"][0]["why"][0]
    assert gmail.created == [] and store.lead_writes == []


def test_a_reconciled_follow_up_knows_whether_it_was_tracked(enabled):
    from outreach import tracking
    store = system_store(row=lead(**{"Follow-up step": "1", "Follow-up action": "act-f1",
                                     "Follow-up status": "RESERVED", "Sent to": SAM,
                                     "Follow-up action at": NOW.isoformat()}))
    gmail = gmail_with()
    gmail_drafts.create(gmail, to=SAM, from_address="admin@lakshyaa.ai", subject="A question",
                        body="x", action_id="act-f1", thread_id="t-sys",
                        html=tracking.tracked_html("x https://lakshyaa.ai", "a" * 32, bytes(range(32))))
    followup.reconcile("A-0001", store=store, gmail=gmail, now=NOW)
    assert store.event_rows[-1]["Detail"] == "draft draft-1, tracked"


def test_running_again_does_not_draft_the_same_follow_up_twice(enabled):
    store, gmail = system_store(), gmail_with()
    run(store, gmail)
    again = run(store, gmail)
    assert again["due"] == [] and len(gmail.created) == 1


@pytest.mark.parametrize("config,why", [
    (settings(**{followup.APPROVAL_KEY: "hash-zero"}),
     "the follow-up wording is not approved for the handbook as it stands now"),
    (settings(offer_approved=False), "founder has not approved the offer wording"),
])
def test_unapproved_wording_blocks(enabled, config, why):
    store, gmail = system_store(), gmail_with()
    report = run(store, gmail, config=config)
    assert report["created"] == [] and why in report["blocked"][0]["why"]
    assert gmail.created == [] and store.lead_writes == [] and store.runs[-1]["Result"] == "BLOCKED"


def test_drafting_stays_off_without_authorization(monkeypatch):
    monkeypatch.delenv("ENABLE_GMAIL_DRAFTS", raising=False)
    store, gmail = system_store(), gmail_with()
    report = run(store, gmail)
    assert "Gmail draft creation is disabled" in report["gates"] and gmail.created == []


def test_a_reply_not_yet_synced_stops_the_draft(enabled):
    store = system_store()
    gmail = gmail_with(message("r1", thread="t-sys", when=at("2026-09-26 10:00"), sender=SAM,
                               to="admin@lakshyaa.ai", body="Call me."))
    report = run(store, gmail)
    assert report["blocked"][0]["why"] == ["the thread changed since the last sync; run sync first"]
    assert gmail.created == [] and store.lead_writes == []


def test_a_draft_already_in_the_thread_stops_the_draft(enabled):
    store = system_store()
    gmail = gmail_with(drafts={"d-old": {"id": "d-old", "message": {"id": "x", "threadId": "t-sys"}}})
    report = run(store, gmail)
    assert report["blocked"][0]["why"] == ["a draft already sits in this thread"]
    assert gmail.created == [] and store.lead_writes == []


def test_a_message_from_someone_else_anywhere_in_the_thread_stops_the_draft(enabled):
    """Sync would normally have recorded it as a reply; this is the last check before Gmail."""
    events = [initial_sent(), event(sequence.SENT, "FOLLOWUP_1", at("2026-09-28 10:00"), message_id="m2")]
    store = system_store(*events)
    gmail = gmail_with(message("r1", thread="t-sys", when=at("2026-09-24 10:00"),
                               sender="owner@gmail.com", to="admin@lakshyaa.ai", body="Hm."),
                       sent("m2", thread="t-sys", when=at("2026-09-28 10:00"), to=SAM))
    report = run(store, gmail, now=at("2026-10-01 09:00"))
    assert report["blocked"][0]["why"] == ["the thread holds a message from someone else"]
    assert gmail.created == [] and store.lead_writes == []


def test_a_follow_up_only_goes_to_an_address_the_thread_was_sent_to(enabled):
    wrong = sync._event("A-0001", sequence.SENT, sequence.INITIAL, at("2026-09-22 13:18"),
                        "other@example-electric.test", "DRAFT", "t-sys", "m1", "")
    report = run(system_store(wrong), gmail_with())
    assert report["blocked"][0]["why"] == [
        "the address is not a recipient of the thread's first email"]


@pytest.mark.parametrize("cap", [0, 31, "four"])
def test_a_daily_cap_outside_one_to_thirty_blocks(enabled, cap):
    report = run(system_store(), gmail_with(), config=settings(daily_cap=cap))
    assert "daily cap must be between 1 and 30" in report["blocked"][0]["why"]


def test_a_mailbox_that_is_not_the_sender_is_refused(enabled):
    report = run(system_store(), gmail_with(address="someone@lakshyaa.ai"))
    assert report["blocked"][0]["why"] == ["the signed-in Gmail mailbox is not the sender"]


def test_an_uncertain_gmail_result_leaves_the_reservation_and_is_never_retried(enabled):
    store, gmail = system_store(), gmail_with()
    gmail.fail_create = TimeoutError("unknown if Gmail committed")
    with pytest.raises(TimeoutError):
        run(store, gmail)
    assert store.rows["A-0001"]["Follow-up status"] == "RESERVED"
    gmail.fail_create = None
    assert run(store, gmail)["due"] == [] and len(gmail.created) == 1


@pytest.mark.parametrize("status,stamp", [("Draft status", "Draft action at"),
                                          ("Follow-up status", "Follow-up action at")])
def test_one_daily_cap_covers_initial_and_follow_up_drafts(enabled, status, stamp):
    other = lead("A-0002", **{"BEST EMAIL": "pat@acme.test", status: "CREATED",
                              stamp: NOW.isoformat()})
    store = MemoryStore([lead(), other], events=[initial_sent()], suppression=[])
    report = run(store, gmail_with(), config=settings(daily_cap=1))
    assert report["blocked"][0]["why"] == ["the daily draft cap is reached"]


def test_a_follow_up_goes_where_the_first_email_went_with_a_neutral_greeting(enabled):
    """The founder changed the draft's recipient before sending: the follow-up follows it."""
    row = lead(**{"BEST EMAIL": "dennis@example-electric.test",
                  "Their email": "dennis@example-electric.test", "Decision maker": "Dennis Moore",
                  "Emails we already had": SAM})
    store = system_store(row=row)
    gmail = gmail_with()
    run(store, gmail)
    email = parsed(gmail.created[0])
    assert email["To"] == SAM and email.get_content().startswith("Hi there,")


def test_a_reservation_the_sheet_refuses_never_reaches_gmail(enabled):
    store, gmail = system_store(), gmail_with()
    store.refuse_writes = True
    report = run(store, gmail)
    assert report["blocked"][0]["why"] == [
        "the lead changed before the reservation; Gmail was not touched"]
    assert gmail.created == []


def test_follow_up_columns_changed_during_the_run_stop_the_draft(enabled):
    store, gmail = system_store(), gmail_with()
    real = store.fresh_lead
    store.fresh_lead = lambda lead_id: (real(lead_id)[0], 3,
                                        {**store.rows[lead_id], "Follow-up status": "RESERVED"})
    report = run(store, gmail)
    assert report["blocked"][0]["why"] == ["the lead's follow-up columns changed during the run"]
    assert gmail.created == []


def test_follow_up_two_answers_follow_up_one(enabled):
    events = [initial_sent(),
              event(sequence.SENT, "FOLLOWUP_1", at("2026-09-28 10:00"), message_id="m2")]
    store = system_store(*events, row=lead(**{"Follow-up step": "1", "Follow-up status": "CREATED",
                                              "Follow-up draft ID": "draft-0",
                                              "Follow-up action at": "2026-09-28T13:00:00+00:00"}))
    gmail = gmail_with(sent("m2", thread="t-sys", when=at("2026-09-28 10:00"), to=SAM,
                            subject="A question", headers=[("References", "<m1@mail.test>")]))
    assert run(store, gmail, now=at("2026-09-30 09:00"))["due"] == []  # due Thursday
    report = run(store, gmail, now=at("2026-10-01 09:00"))
    email = parsed(gmail.created[0])
    assert report["created"][0]["step"] == 2
    assert email["In-Reply-To"] == "<m2@mail.test>"
    assert email["References"] == "<m1@mail.test> <m2@mail.test>"
    assert "I'll close the loop on Example Product." in email.get_content()
    assert store.rows["A-0001"]["Follow-up step"] == "2"


def test_a_follow_up_event_recorded_twice_counts_once():
    once = event(sequence.SENT, "FOLLOWUP_1", at("2026-09-28 10:00"), message_id="m2")
    store = system_store(initial_sent(), once, dict(once))
    report = run(store, dry_run=True, now=at("2026-10-01 09:00"))
    assert [(d["step"], d["due"]) for d in report["due"]] == [(2, "2026-10-01")]


def test_nothing_after_the_second_follow_up(enabled):
    events = [initial_sent(), event(sequence.SENT, "FOLLOWUP_1", at("2026-09-28 10:00"), message_id="m2"),
              event(sequence.SENT, "FOLLOWUP_2", at("2026-10-01 10:00"), message_id="m3")]
    assert run(system_store(*events), now=at("2026-10-09 09:00"))["due"] == []


def test_a_reserved_follow_up_is_reconciled_from_its_draft_and_never_recreated(enabled):
    store = system_store(row=lead(**{"Follow-up step": "1", "Follow-up action": "act-f1",
                                     "Follow-up status": "RESERVED", "Sent to": SAM,
                                     "Follow-up action at": NOW.isoformat()}))
    gmail = gmail_with()
    gmail_drafts.create(gmail, to=SAM, from_address="admin@lakshyaa.ai", subject="A question",
                        body="x", action_id="act-f1", thread_id="t-sys")
    result = followup.reconcile("A-0001", store=store, gmail=gmail, now=NOW)
    assert result == {"lead_id": "A-0001", "status": "CREATED", "draft_id": "draft-1"}
    assert store.rows["A-0001"]["Follow-up status"] == "CREATED" and len(gmail.created) == 1
    assert store.event_rows[-1]["Event"] == sequence.FOLLOWUP_DRAFTED


def test_a_draft_in_a_thread_carries_the_headers_that_keep_it_there():
    gmail = FakeGmail()
    gmail_drafts.create(gmail, to=SAM, from_address="admin@lakshyaa.ai", subject="A question",
                        body="Hello", action_id="a1", thread_id="t-9", in_reply_to="<m@x>",
                        references="<m@x>")
    assert gmail.created[0]["threadId"] == "t-9"
    email = parsed(gmail.created[0])
    assert (email["In-Reply-To"], email["References"]) == ("<m@x>", "<m@x>")
    gmail_drafts.create(gmail, to=SAM, from_address="admin@lakshyaa.ai", subject="New",
                        body="Hello", action_id="a2")
    assert "threadId" not in gmail.created[1] and parsed(gmail.created[1])["In-Reply-To"] is None
