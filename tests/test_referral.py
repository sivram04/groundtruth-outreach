"""The referral composer: deterministic template fill, refusing on a missing input, never guessing."""

import pytest

from outreach import referral

SUBJECT = "Referral for the {role} role at {company}"
BODY = ("Hi {name},\n\nI'm applying for the {role} role at {company} ({job_url}). "
        "Would you be open to referring me? Here is a short summary: {resume}.\n\nThanks!")


def test_compose_fills_every_placeholder_from_inputs():
    out = referral.compose(SUBJECT, BODY, {
        "name": "Dana", "role": "Data Engineer", "company": "Acme",
        "job_url": "https://acme.test/jobs/42", "resume": "MS Business Analytics, 3 yrs data.",
    })
    assert out["subject"] == "Referral for the Data Engineer role at Acme"
    assert out["body"].startswith("Hi Dana,")
    assert "https://acme.test/jobs/42" in out["body"] and "MS Business Analytics" in out["body"]


def test_a_missing_input_is_refused_not_blanked_or_guessed():
    with pytest.raises(referral.NotEligible) as exc:
        referral.compose(SUBJECT, BODY, {"name": "Dana", "role": "Data Engineer", "company": "Acme"})
    assert "job_url" in exc.value.reason and "resume" in exc.value.reason


def test_a_blank_input_counts_as_missing():
    with pytest.raises(referral.NotEligible):
        referral.compose("Hi {name}", "", {"name": "   "})


def test_values_are_inserted_verbatim_and_stripped():
    out = referral.compose("{role}", "to {name}", {"role": "  SWE  ", "name": "Sam"})
    assert out["subject"] == "SWE" and out["body"] == "to Sam"


def test_required_inputs_lists_every_placeholder_across_subject_and_body():
    assert referral.required_inputs(SUBJECT, BODY) == ["company", "job_url", "name", "resume", "role"]


def test_a_template_with_no_placeholders_composes_unchanged():
    out = referral.compose("A quick ask", "Would you refer me?", {})
    assert out == {"subject": "A quick ask", "body": "Would you refer me?"}
