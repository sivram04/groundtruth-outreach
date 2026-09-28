"""Sync, offline: sends, replies, bounces and opt-outs land on the right lead, or on none.

Every case here fails safe: an uncertain match starts no follow-up, a request to stop reaches
Suppression, and a second run changes nothing.
"""

import pytest

from outreach import sheet, sync
from stage4_fakes import (FakeGmail, MemoryStore, at, bounce_notice, lead, message, sent)

NOW = at("2026-09-28 09:00")  # a Monday
SETTINGS = {"sender_email": "admin@lakshyaa.ai", "sync_start_date": "2026-09-21"}
SAM = "sam@example-electric.test"
PAT = "pat@acme-plumbing.test"


def pat_lead(**changes):
    return lead("A-0002", Company="Acme Plumbing", **{"BEST EMAIL": PAT, "Their email": PAT,
                                                       "Decision maker": "Pat Lee",
                                                       "Website": "https://acme-plumbing.test/",
                                                       **changes})


def run(store, gmail, **kwargs):
    return sync.run(store=store, gmail=gmail, settings=SETTINGS, now=kwargs.pop("now", NOW), **kwargs)


def by_kind(report, kind):
    return [e for e in report["events"] if e["Event"] == kind]


# --- emails the founder wrote by hand -------------------------------------------------------

def test_hand_sent_emails_are_recorded_with_a_reminder_and_never_for_drafting():
    store = MemoryStore([lead(), pat_lead()], suppression=[])
    gmail = FakeGmail([sent("m1", thread="t1", when=at("2026-09-22 13:18"), to=SAM),
                       sent("m2", thread="t2", when=at("2026-09-22 13:30"), to=PAT)])
    report = run(store, gmail)
    sends = by_kind(report, "SENT")
    assert [(e["Lead ID"], e["Match"], e["Step"]) for e in sends] == [
        ("A-0001", "ADDRESS", "INITIAL"), ("A-0002", "ADDRESS", "INITIAL")]
    row = store.rows["A-0001"]
    assert row["Outreach status"] == "SENT" and row["Sent to"] == SAM
    assert row["Sent at"] == "2026-09-22 13:18 ET" and row["Follow-ups sent"] == "0"
    assert row["Next action"] == ("Follow-up 1 was due Fri 2026-09-25. You started this thread "
                                  "by hand, so write it yourself in the same thread.")
    assert store.runs[-1]["Job"] == "sync" and "cursor 2026-09-28T13:00:00Z" in store.runs[-1]["Detail"]


def test_an_address_only_on_the_company_domain_is_recorded_but_needs_checking():
    """The A-0005 case: the founder emailed jeff@, the row lists dennis@."""
    row = lead("A-0005", Company="Approved Plumbing", **{"BEST EMAIL": "dennis@approved.test",
                                                          "Their email": "dennis@approved.test",
                                                          "Website": "approved.test"})
    store = MemoryStore([row], suppression=[])
    run(store, FakeGmail([sent("m1", thread="t1", when=at("2026-09-22 13:40"),
                               to="jeff@approved.test")]))
    result = store.rows["A-0005"]
    assert result["Outreach status"] == "REVIEW_NEEDED"
    assert result["Next action"] == (
        "Check the match: you emailed jeff@approved.test on Tue 2026-09-22, which is not an "
        "address on this row. If it is this company, follow-up 1 was due Fri 2026-09-25.")
    assert store.event_rows[0]["Match"] == "DOMAIN" and store.event_rows[0]["Step"] == "UNCONFIRMED"


def test_an_address_listed_elsewhere_on_the_row_is_a_certain_match():
    row = lead("A-0005", **{"BEST EMAIL": "dennis@approved.test",
                            "Emails we already had": "office@approved.test; jeff@approved.test"})
    store = MemoryStore([row], suppression=[])
    run(store, FakeGmail([sent("m1", thread="t1", when=at("2026-09-22 13:40"),
                               to="Jeff <jeff@approved.test>")]))
    assert store.rows["A-0005"]["Outreach status"] == "SENT"


def test_a_personal_mailbox_is_never_matched_by_its_domain():
    store = MemoryStore([lead(**{"BEST EMAIL": "bob@gmail.com", "Their email": "bob@gmail.com",
                                 "Website": ""})], suppression=[])
    report = run(store, FakeGmail([sent("m1", thread="t1", when=at("2026-09-22 13:40"),
                                        to="someone.else@gmail.com")]))
    assert report["events"] == [] and "Outreach status" not in store.rows["A-0001"]


def test_two_leads_on_one_domain_are_both_left_for_review():
    store = MemoryStore([lead(), lead("A-0009", **{"BEST EMAIL": "kim@example-electric.test",
                                                   "Their email": "kim@example-electric.test"})],
                        suppression=[])
    run(store, FakeGmail([sent("m1", thread="t1", when=at("2026-09-22 13:40"),
                               to="info@example-electric.test")]))
    assert {e["Match"] for e in store.event_rows} == {"SEVERAL"}
    assert store.rows["A-0001"]["Outreach status"] == store.rows["A-0009"]["Outreach status"] \
        == "REVIEW_NEEDED"


# --- what comes back ------------------------------------------------------------------------

def first_send():
    return sent("m1", thread="t1", when=at("2026-09-22 13:18"), to=SAM)


def test_a_reply_stops_the_reminders():
    store = MemoryStore([lead()], suppression=[])
    run(store, FakeGmail([first_send(), message("r1", thread="t1", when=at("2026-09-24 10:02"),
                                                sender=f"Sam <{SAM}>", to="admin@lakshyaa.ai",
                                                body="Sure, call me Thursday.")]))
    row = store.rows["A-0001"]
    assert row["Outreach status"] == "REPLIED" and row["Replied at"] == "2026-09-24 10:02 ET"
    assert row["Next action"] == "Replied on Thu 2026-09-24. Answer by hand."


def test_the_founder_answering_a_reply_is_conversation_not_a_follow_up():
    store = MemoryStore([lead()], suppression=[])
    run(store, FakeGmail([first_send(),
                          message("r1", thread="t1", when=at("2026-09-24 10:02"), sender=SAM,
                                  to="admin@lakshyaa.ai", body="What does it cost?"),
                          sent("m2", thread="t1", when=at("2026-09-24 11:00"), to=SAM)]))
    assert [e["Step"] for e in store.event_rows if e["Event"] == "SENT"] == ["INITIAL", "CONVERSATION"]
    assert store.rows["A-0001"]["Follow-ups sent"] == "0"
    assert store.rows["A-0001"]["Outreach status"] == "REPLIED"


def test_a_colleague_answering_in_the_thread_is_a_reply_from_that_lead():
    store = MemoryStore([lead()], suppression=[])
    report = run(store, FakeGmail([first_send(), message(
        "r1", thread="t1", when=at("2026-09-24 10:02"), sender="office@example-electric.test",
        to="admin@lakshyaa.ai", body="Sam asked me to set up a call.")]))
    assert [(e["Event"], e["Match"]) for e in by_kind(report, "REPLIED")] == [("REPLIED", "THREAD")]


def test_mail_from_a_lead_before_anyone_wrote_to_them_is_not_outreach():
    store = MemoryStore([lead()], suppression=[])
    report = run(store, FakeGmail([message("x1", thread="t9", when=at("2026-09-21 09:00"),
                                           sender=SAM, to="admin@lakshyaa.ai", body="Newsletter")]))
    assert report["events"] == []


def test_a_bounce_suppresses_the_address_and_not_the_domain():
    store = MemoryStore([lead()], suppression=[])
    run(store, FakeGmail([first_send(),
                          bounce_notice("b1", thread="t1", when=at("2026-09-22 13:19"), failed=SAM)]))
    row = store.rows["A-0001"]
    assert row["Outreach status"] == "BOUNCED"
    assert row["Next action"] == f"{SAM} bounced on Tue 2026-09-22. Find another address."
    assert [e["Address or domain"] for e in store.entries] == [SAM]
    assert store.entries[0]["Reason"] == "bounced: status 5.1.1"


def test_a_delay_notice_stops_nothing():
    store = MemoryStore([lead()], suppression=[])
    report = run(store, FakeGmail([first_send(), bounce_notice(
        "b1", thread="t1", when=at("2026-09-22 14:00"), failed=SAM, status="4.4.7",
        subject="Delivery Status Notification (Delay)")]))
    assert [e["Event"] for e in report["events"]] == ["SENT", "DELAYED"]
    assert store.rows["A-0001"]["Outreach status"] == "SENT" and store.entries == []


def test_a_request_to_stop_reaches_suppression_for_both_addresses():
    store = MemoryStore([lead()], suppression=[])
    run(store, FakeGmail([first_send(), message(
        "r1", thread="t1", when=at("2026-09-23 08:00"), sender="office@example-electric.test",
        to="admin@lakshyaa.ai", body="Please remove us, not interested.")]))
    row = store.rows["A-0001"]
    assert row["Outreach status"] == "OPTED_OUT"
    assert row["Next action"] == 'Asked to stop on Wed 2026-09-23 (said "remove us"). Never contact again.'
    assert sorted(e["Address or domain"] for e in store.entries) == ["office@example-electric.test", SAM]


def test_an_automatic_reply_keeps_the_sequence_and_says_so():
    store = MemoryStore([lead()], suppression=[])
    run(store, FakeGmail([first_send(), message(
        "r1", thread="t1", when=at("2026-09-22 13:19"), sender=SAM, to="admin@lakshyaa.ai",
        subject="Out of Office: A question", body="Back Monday.")]))
    row = store.rows["A-0001"]
    assert row["Outreach status"] == "SENT"
    assert row["Next action"].startswith("Auto-reply on Tue 2026-09-22. Follow-up 1 was due")


def test_a_follow_up_written_by_hand_moves_the_reminder_to_the_second():
    store = MemoryStore([lead()], suppression=[])
    run(store, FakeGmail([first_send(), sent("m2", thread="t1", when=at("2026-09-25 09:00"),
                                             to=SAM, subject="Re: A question")]))
    row = store.rows["A-0001"]
    assert row["Follow-ups sent"] == "1"
    assert row["Next action"].startswith("Follow-up 2 is due Wed 2026-09-30.")
    assert [e["Step"] for e in store.event_rows] == ["INITIAL", "FOLLOWUP_1"]


def test_after_a_bounce_a_new_address_starts_a_new_sequence():
    store = MemoryStore([lead(**{"Emails we already had": "samuel@example-electric.test"})],
                        suppression=[])
    run(store, FakeGmail([first_send(),
                          bounce_notice("b1", thread="t1", when=at("2026-09-22 13:19"), failed=SAM),
                          sent("m2", thread="t2", when=at("2026-09-23 09:00"),
                               to="samuel@example-electric.test")]))
    row = store.rows["A-0001"]
    assert row["Outreach status"] == "SENT" and row["Sent to"] == "samuel@example-electric.test"
    assert [e["Step"] for e in store.event_rows if e["Event"] == "SENT"] == ["INITIAL", "INITIAL"]


# --- this system's own drafts ---------------------------------------------------------------

def drafted_lead():
    return lead(**{"Draft action": "act-1", "Draft status": "CREATED", "Draft ID": "draft-9",
                   "Draft thread ID": "t-sys", "Drafted at": "2026-09-22T12:00:00+00:00",
                   "Draft action at": "2026-09-22T11:59:00+00:00"})


def test_a_sent_system_draft_is_tied_to_its_action_and_waits_for_follow_up_one():
    store = MemoryStore([drafted_lead()], suppression=[])
    report = run(store, FakeGmail([sent("m1", thread="t-sys", when=at("2026-09-22 13:18"), to=SAM)]))
    assert [(e["Event"], e["Match"], e["Step"]) for e in report["events"]] == [
        ("DRAFTED", "DRAFT", "INITIAL"), ("SENT", "DRAFT", "INITIAL")]
    assert store.rows["A-0001"]["Next action"] == "Follow-up 1 was due Fri 2026-09-25; waiting to be drafted."


def test_an_unsent_system_draft_that_was_deleted_is_reported():
    store = MemoryStore([drafted_lead()], suppression=[])
    run(store, FakeGmail([]))
    assert store.rows["A-0001"]["Outreach status"] == "DRAFTED"
    assert store.rows["A-0001"]["Next action"] == "The initial draft is no longer in Gmail and was not sent."


def test_an_unsent_system_draft_still_in_gmail_asks_for_review():
    store = MemoryStore([drafted_lead()], suppression=[])
    run(store, FakeGmail([], drafts={"draft-9": {"id": "draft-9", "message": {"id": "d", "threadId": "t-sys"}}}))
    assert store.rows["A-0001"]["Next action"] == "The initial draft is in Gmail: review it and press Send."


# --- running again, dry runs and refusals ---------------------------------------------------

def test_a_second_run_changes_nothing_and_does_not_reread_known_messages():
    store = MemoryStore([lead()], suppression=[])
    messages = [first_send(), message("r1", thread="t1", when=at("2026-09-23 08:00"), sender=SAM,
                                      to="admin@lakshyaa.ai", body="No thanks.")]
    run(store, FakeGmail(messages), now=at("2026-09-23 09:00"))
    assert [e["Address or domain"] for e in store.entries] == [SAM]
    events, entries, rows = len(store.event_rows), list(store.entries), dict(store.rows["A-0001"])
    again = FakeGmail(messages)
    report = run(store, again, now=at("2026-09-23 09:10"))  # both messages are inside the window
    assert report["events"] == [] and report["suppression"] == [] and report["lead_updates"] == {}
    assert len(store.event_rows) == events and store.entries == entries and store.rows["A-0001"] == rows
    assert again.full_reads == []


def test_spam_and_trash_are_read_too():
    """A reply Gmail filed as spam, or one the founder deleted, is still a reply."""
    gmail = FakeGmail([first_send()])
    run(MemoryStore([lead()], suppression=[]), gmail)
    assert gmail.spam_and_trash == [True] and "-in:drafts" in gmail.queries[0]


def test_the_next_run_reads_from_two_days_before_the_last_cursor():
    store = MemoryStore([lead()], suppression=[])
    gmail = FakeGmail([first_send()])
    run(store, gmail)
    later = FakeGmail([first_send()])
    run(store, later, now=at("2026-09-29 09:00"))
    assert later.queries[0].startswith(f"after:{int(at('2026-09-26 09:00').timestamp())} ")


def test_a_run_that_finds_nothing_leaves_the_runs_tab_alone_for_six_hours():
    store = MemoryStore([lead()], suppression=[])
    run(store, FakeGmail([first_send()]))
    assert len(store.runs) == 1
    quiet = run(store, FakeGmail([first_send()]), now=at("2026-09-28 14:59"))
    assert quiet["runs_row"] is False and len(store.runs) == 1
    beat = run(store, FakeGmail([first_send()]), now=at("2026-09-28 15:01"))
    assert beat["runs_row"] is True and len(store.runs) == 2
    assert "cursor 2026-09-28T19:01:00Z" in store.runs[-1]["Detail"]


def test_a_run_that_records_something_always_writes_its_runs_row():
    store = MemoryStore([lead()], suppression=[])
    run(store, FakeGmail([first_send()]))
    reply = message("r1", thread="t1", when=at("2026-09-28 09:05"), sender=SAM,
                    to="admin@lakshyaa.ai", body="Call me.")
    report = run(store, FakeGmail([first_send(), reply]), now=at("2026-09-28 09:10"))
    assert report["runs_row"] is True and len(store.runs) == 2


def test_a_suppression_row_deleted_by_hand_is_put_back_on_the_next_run():
    """An opt-out is permanent here: the event stays, so the address goes back on the list."""
    store = MemoryStore([lead()], suppression=[])
    mail = [first_send(), message("r1", thread="t1", when=at("2026-09-23 08:00"), sender=SAM,
                                  to="admin@lakshyaa.ai", body="No thanks.")]
    run(store, FakeGmail(mail))
    store.entries = []
    report = run(store, FakeGmail(mail), now=at("2026-09-28 09:10"))
    assert report["runs_row"] is True and [e["Address or domain"] for e in store.entries] == [SAM]


def test_a_change_on_the_lead_row_alone_is_written_straight_away():
    """The founder marks HOLD between two runs: no new mail, but the row must say so now."""
    store = MemoryStore([lead()], suppression=[])
    run(store, FakeGmail([first_send()]))
    store.rows["A-0001"]["HOLD"] = "yes"
    report = run(store, FakeGmail([first_send()]), now=at("2026-09-28 09:10"))
    assert report["runs_row"] is True and store.rows["A-0001"]["Next action"] == "On hold: no follow-ups."


def test_an_event_appended_twice_is_read_once():
    """Read twice, one follow-up would count as two and end the sequence early."""
    store = MemoryStore([lead()], suppression=[])
    mail = [first_send(), sent("m2", thread="t1", when=at("2026-09-25 09:00"), to=SAM)]
    run(store, FakeGmail(mail))
    assert store.rows["A-0001"]["Follow-ups sent"] == "1"
    store.event_rows.append(dict(store.event_rows[-1]))  # two runs at the same moment
    report = run(store, FakeGmail(mail), now=at("2026-09-28 09:10"))
    assert report["lead_updates"] == {} and store.rows["A-0001"]["Follow-ups sent"] == "1"
    assert sync.unique(store.event_rows) == store.event_rows[:2]


def test_a_dry_run_writes_nothing():
    store = MemoryStore([lead()], suppression=[])
    report = run(store, FakeGmail([first_send()]), dry_run=True)
    assert report["dry_run"] and len(report["events"]) == 1 and "A-0001" in report["lead_updates"]
    assert store.event_rows == [] and store.lead_writes == [] and store.runs == []


def test_a_mailbox_that_is_not_the_sender_is_refused():
    with pytest.raises(sync.SyncBlocked):
        run(MemoryStore([lead()], suppression=[]), FakeGmail([], address="someone@lakshyaa.ai"))


def test_a_founder_column_of_the_same_name_is_never_written():
    class Tab:
        header = ["Company", "Next action", "BEST EMAIL", "Lead ID", "Email check"]
    assert sheet.founder_column_clash(Tab(), sheet.SYNC_COLUMNS) == ["Next action"]
    Tab.header = ["Company", "BEST EMAIL"]
    assert sheet.founder_column_clash(Tab(), ["Sent at"]) == ["Sent at"]
