"""What a message means: a reply, a request to stop, an automatic answer or a delivery failure."""

import pytest

from outreach import drafting, mailbox
from stage4_fakes import at, bounce_notice, message

WHEN = at("2026-09-24 10:00")


def reply(body="", **kwargs):
    return message("r1", thread="t1", when=WHEN, sender="Sam Rivers <sam@example-electric.test>",
                   to="admin@lakshyaa.ai", subject="Re: A question", body=body, **kwargs)


# --- the replier's own words, not the quoted email -----------------------------------------

def test_gmail_style_quote_is_left_out():
    text = ("Sounds good, call me Thursday.\n\nOn Tue, Sep 22, 2026 at 1:18 PM Admin Lakshyaa "
            "<admin@lakshyaa.ai> wrote:\n> Hi Sam,\n> reply \"no thanks\" and I'll stop.")
    assert mailbox.new_text(text) == "Sounds good, call me Thursday."


def test_a_wrapped_reply_header_is_still_found():
    text = ("Not now.\n\nOn Tue, Sep 22, 2026 at 1:18 PM Admin Lakshyaa <\n"
            "admin@lakshyaa.ai> wrote:\n\nHi Sam, the whole original email")
    assert mailbox.new_text(text) == "Not now."


def test_outlook_style_header_block_is_left_out():
    text = ("Let's talk.\n\nFrom: Admin Lakshyaa <admin@lakshyaa.ai>\nSent: Tuesday, September 22, "
            "2026 1:18 PM\nTo: Sam\nSubject: A question\n\nIf you don't want further outreach...")
    assert mailbox.new_text(text) == "Let's talk."


def test_quoted_lines_without_a_reply_header_are_left_out():
    text = '> If you don\'t want further outreach, reply "no thanks" and I\'ll stop.\nHappy to talk.'
    assert mailbox.new_text(text) == "Happy to talk."
    assert mailbox.stop_words(mailbox.new_text(text)) == ""


def test_our_own_opt_out_sentence_copied_back_unquoted_is_not_the_replier_speaking():
    text = "Thanks, let's talk next week.\n\n" + drafting.OPT_OUT.replace("'", "’")
    assert mailbox.stop_words(mailbox.new_text(text)) == ""


# --- a request to stop ---------------------------------------------------------------------

@pytest.mark.parametrize("text,words", [
    ("No thanks, we're all set.", "No thanks"),
    ("Please remove me from your list.", "remove me"),
    ("We are not interested.", "not interested"),
    ("Unsubscribe", "Unsubscribe"),
    ("Don't email me again", "Don't email"),
    ("No\n\nJohn Smith\nSmith Plumbing", "no"),
    ("Stop.", "stop"),
])
def test_a_request_to_stop_is_recognised(text, words):
    assert mailbox.stop_words(text) == words


@pytest.mark.parametrize("text", [
    "Not right now, maybe try us in spring.",
    "We're a one-stop shop for mechanical work.",
    "Sure, Thursday works.",
    "No problem, happy to talk.",
])
def test_an_ordinary_answer_is_not_a_request_to_stop(text):
    assert mailbox.stop_words(text) == ""


def test_a_stop_request_only_in_the_quoted_email_is_a_reply():
    body = ("Happy to chat.\n\nOn Tue, Sep 22, 2026 at 1:18 PM Admin Lakshyaa <admin@lakshyaa.ai>"
            " wrote:\n> " + drafting.OPT_OUT)
    assert mailbox.received_kind(reply(body))[0] == mailbox.REPLIED


def test_an_html_only_reply_is_read():
    kind, detail = mailbox.received_kind(reply(html="<div>No thanks.</div><div><br></div>"))
    assert kind == mailbox.OPT_OUT and detail == 'said "No thanks"'


# --- automatic answers ---------------------------------------------------------------------

def test_an_automatic_reply_by_header():
    kind, _ = mailbox.received_kind(reply("I'm out until Monday. No thanks needed.",
                                          headers=[("Auto-Submitted", "auto-replied")]))
    assert kind == mailbox.AUTO_REPLY


def test_an_automatic_reply_by_subject_that_says_they_left():
    found = message("r2", thread="t1", when=WHEN, sender="sam@example-electric.test",
                    to="admin@lakshyaa.ai", subject="Automatic reply: A question",
                    body="Sam is no longer with the company.")
    assert mailbox.received_kind(found) == (mailbox.AUTO_REPLY, "says they may have left")


# --- delivery notices ----------------------------------------------------------------------

def test_a_permanent_failure_is_a_bounce_with_its_address_and_status():
    notice = bounce_notice("b1", thread="t1", when=WHEN, failed="sam@example-electric.test")
    assert mailbox.is_bounce_notice(notice)
    kind, failed, in_text, detail = mailbox.bounce(notice)
    assert (kind, failed, detail) == (mailbox.BOUNCED, ["sam@example-electric.test"], "status 5.1.1")
    assert "sam@example-electric.test" in in_text


def test_a_temporary_failure_is_a_delay_not_a_bounce():
    notice = bounce_notice("b2", thread="t1", when=WHEN, failed="sam@example-electric.test",
                           status="4.4.7", subject="Delivery Status Notification (Delay)")
    assert mailbox.bounce(notice)[0] == mailbox.DELAYED


def test_a_delay_notice_without_a_status_code_is_still_a_delay():
    notice = message("b3", thread="t1", when=WHEN, sender="mailer-daemon@googlemail.com",
                     to="admin@lakshyaa.ai", subject="Delivery Status Notification (Delay)",
                     body="There was a temporary problem delivering your message.")
    assert mailbox.bounce(notice)[0] == mailbox.DELAYED


def test_an_ordinary_reply_is_not_a_delivery_notice():
    assert not mailbox.is_bounce_notice(reply("Sure."))
