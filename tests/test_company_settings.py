"""outreach/company_settings.py (the durable store) and outreach/company_chat.py (the
deterministic interpreter) - setting the founder's sender/company identity from chat instead of
only by hand-editing the outreach-settings secret."""

import pytest

from outreach import company_chat, company_settings
from test_handbook_store import FakeApi


def test_overrides_is_empty_when_nothing_is_stored():
    assert company_settings.overrides(api=FakeApi()) == {}


def test_set_field_then_overrides_returns_it():
    api = FakeApi()
    clean = company_settings.set_field("sender_name", "  John   Doe  ", set_by="admin@lakshyaa.ai", api=api)
    assert clean == "John Doe"
    assert company_settings.overrides(api=api) == {"sender_name": "John Doe"}


def test_the_latest_value_for_a_field_wins():
    api = FakeApi()
    company_settings.set_field("sender_name", "John Doe", set_by="a@x", api=api)
    company_settings.set_field("sender_name", "Jane Doe", set_by="a@x", api=api)
    assert company_settings.overrides(api=api)["sender_name"] == "Jane Doe"


def test_different_fields_both_persist():
    api = FakeApi()
    company_settings.set_field("sender_name", "John Doe", set_by="a@x", api=api)
    company_settings.set_field("daily_cap", "10", set_by="a@x", api=api)
    assert company_settings.overrides(api=api) == {"sender_name": "John Doe", "daily_cap": "10"}


def test_set_field_rejects_an_unknown_field():
    with pytest.raises(company_settings.InvalidField):
        company_settings.set_field("favourite_colour", "blue", set_by="a@x", api=FakeApi())


def test_set_field_needs_a_setter():
    with pytest.raises(ValueError):
        company_settings.set_field("sender_name", "John Doe", set_by="", api=FakeApi())


@pytest.mark.parametrize("field", list(company_settings.OPTIONAL_LINKS))
def test_optional_links_accept_a_real_url(field):
    assert company_settings.validate(field, "https://cal.com/founder") == "https://cal.com/founder"


@pytest.mark.parametrize("field", list(company_settings.OPTIONAL_LINKS))
def test_optional_links_reject_a_non_url(field):
    with pytest.raises(company_settings.InvalidField, match="real link"):
        company_settings.validate(field, "cal.com/founder")  # no scheme


@pytest.mark.parametrize("field", list(company_settings.OPTIONAL_LINKS))
def test_optional_links_reject_an_obvious_placeholder(field):
    with pytest.raises(company_settings.InvalidField, match="real link"):
        company_settings.validate(field, "https://your-link-here.example.com")


def test_optional_links_are_never_auto_asked():
    # Unset entirely, next_missing still only tracks the required fields.
    assert company_settings.next_missing({})[0] == "sender_name"


def test_booking_link_set_via_chat_is_the_one_reply_py_reads():
    from outreach import reply
    api = FakeApi()
    company_settings.set_field("booking_link", "https://cal.com/founder", set_by="a@x", api=api)
    merged = company_settings.overrides(api=api)
    assert reply.booking_link(merged) == "https://cal.com/founder"


@pytest.mark.parametrize("field,raw,why", [
    ("sender_email", "not an email", "email"),
    ("sender_phone", "not a phone", "phone"),
    ("sender_website", "not a website !!", "website"),
    ("postal_address", "123 Main", "short"),
    ("daily_cap", "forty", "whole number"),
    ("daily_cap", "0", "between 1 and 30"),
    ("daily_cap", "31", "between 1 and 30"),
])
def test_validate_rejects_bad_values(field, raw, why):
    with pytest.raises(company_settings.InvalidField, match=why):
        company_settings.validate(field, raw)


def test_validate_normalises_a_website_without_a_scheme():
    assert company_settings.validate("sender_website", "lakshyaa.ai") == "https://lakshyaa.ai"


def test_validate_treats_skip_as_clearing_the_optional_phone():
    assert company_settings.validate("sender_phone", "skip") == ""


def test_missing_treats_empty_and_bracket_placeholder_as_missing():
    assert company_settings.missing("") is True
    assert company_settings.missing("[SENDER_NAME]") is True
    assert company_settings.missing("John Doe") is False


def test_next_missing_is_the_first_unset_required_field_in_order():
    assert company_settings.next_missing({}) == ("sender_name", company_settings.LABELS["sender_name"])
    assert company_settings.next_missing({"sender_name": "John Doe"})[0] == "founder_title"


def test_next_missing_is_none_once_every_required_field_is_set():
    full = {
        "sender_name": "John Doe", "founder_title": "Owner", "sender_email": "a@x.test",
        "sender_website": "https://x.test", "postal_address": "123 Main St, Columbus, OH",
        "product_name": "Lakshyaa", "daily_cap": "4",
    }
    assert company_settings.next_missing(full) is None


class TestInterpret:
    def test_an_explicit_key_value_message_sets_that_field(self):
        p = company_chat.interpret("email: admin@lakshyaa.ai", {})
        assert p == {"status": "ready", "field": "sender_email",
                    "label": company_settings.LABELS["sender_email"], "value": "admin@lakshyaa.ai"}

    def test_a_bare_value_answers_whatever_is_next_missing(self):
        p = company_chat.interpret("John Doe", {})
        assert p["status"] == "ready" and p["field"] == "sender_name" and p["value"] == "John Doe"

    def test_a_bare_value_with_nothing_missing_is_unclear(self):
        full = {
            "sender_name": "John Doe", "founder_title": "Owner", "sender_email": "a@x.test",
            "sender_website": "https://x.test", "postal_address": "123 Main St, Columbus, OH",
            "product_name": "Lakshyaa", "daily_cap": "4",
        }
        assert company_chat.interpret("what's the weather", full) == {"status": "unclear"}

    def test_an_invalid_value_is_reported_without_writing(self):
        p = company_chat.interpret("not an email", {"sender_name": "John Doe", "founder_title": "Owner",
                                                      "sender_email": ""})
        # sender_email is the next missing field, and "not an email" fails its own validation
        assert p["status"] == "invalid" and p["field"] == "sender_email"

    def test_an_empty_message_is_unclear(self):
        assert company_chat.interpret("   ", {}) == {"status": "unclear"}

    def test_recognises_the_canonical_field_name_too(self):
        p = company_chat.interpret("daily_cap: 7", {})
        assert p["status"] == "ready" and p["field"] == "daily_cap" and p["value"] == "7"

    def test_a_named_optional_link_is_set_even_though_everything_required_is_still_missing(self):
        p = company_chat.interpret("booking link: https://cal.com/founder", {})
        assert p["status"] == "ready" and p["field"] == "booking_link"
        assert p["value"] == "https://cal.com/founder"

    def test_survey_and_doc_link_aliases(self):
        assert company_chat.interpret("survey: https://forms.example.com/s", {})["field"] == "survey_link"
        assert company_chat.interpret("case study: https://x.test/case", {})["field"] == "doc_link"
