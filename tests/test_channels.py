"""How a lead's channel is worked out, and the next action for a lead with no email to draft."""

from outreach import channels


def test_a_lead_with_an_email_is_an_email_lead():
    row = {"Company": "Acme", "BEST EMAIL": "pat@acme.test", "Phone": "555-0100"}
    assert channels.channel_of(row) == channels.EMAIL
    assert channels.email_of(row) == "pat@acme.test"


def test_a_lead_with_only_a_phone_is_a_call_lead():
    row = {"Company": "Acme", "BEST EMAIL": "", "Phone": "(614) 555-0142"}
    assert channels.channel_of(row) == channels.CALL
    assert channels.phone_of(row) == "(614) 555-0142"


def test_a_lead_with_neither_an_email_nor_a_phone_is_company_only():
    assert channels.channel_of({"Company": "Acme"}) == channels.COMPANY_ONLY
    assert channels.channel_of({"Company": "Acme", "Website": "acme.test"}) == channels.COMPANY_ONLY


def test_a_value_that_is_not_an_email_does_not_count_as_one():
    row = {"Company": "Acme", "BEST EMAIL": "not-an-email", "Phone": "555 010 0199"}
    assert channels.email_of(row) == ""
    assert channels.channel_of(row) == channels.CALL  # falls back to the phone


def test_a_scrap_of_digits_is_not_a_phone():
    assert channels.phone_of({"Phone": "x12"}) == ""
    assert channels.channel_of({"Company": "Acme", "Phone": "ext 12"}) == channels.COMPANY_ONLY


def test_phone_and_email_headers_are_matched_by_name_not_position():
    assert channels.email_of({"Email": "a@b.test"}) == "a@b.test"
    assert channels.phone_of({"Mobile": "202-555-0111"}) == "202-555-0111"
    assert channels.phone_of({"Telephone": "202 555 0111"}) == "202 555 0111"


def test_the_next_action_tells_the_founder_what_to_do_by_channel():
    assert "Call Acme" in channels.next_action(channels.CALL, "Acme")
    assert "no email" in channels.next_action(channels.CALL, "Acme")
    assert "Find a contact for Acme" in channels.next_action(channels.COMPANY_ONLY, "Acme")
    # an email lead flows through the draft path, so no call/enrich action here
    assert channels.next_action(channels.EMAIL, "Acme") == ""
    # a missing company name never leaves a blank in the sentence
    assert "this company" in channels.next_action(channels.CALL, "")
