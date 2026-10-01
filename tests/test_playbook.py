"""Reviewing an uploaded playbook's text: the identified sections, the timing rule, missing and ambiguous
parts, and the immutable content hash. Pure; nothing is written and no text is run as instructions."""

from outreach import playbook

GOOD = """## What Example Product is
Example Product is a cash-flow tool for subcontractors.

## Initial email
Hi [FIRST_NAME],

[VERIFIED_COMPANY_OBSERVATION]

[CTA_QUESTION]

Best,
[SENDER_NAME]

## Follow-up 1
Draft on the third business day after the initial email, if there has been no reply.

Hi [FIRST_NAME],

Following up on my note about [PRODUCT_NAME]. If you choose to [NEXT_WEEK_ACTION], I'd value your reaction.

[CTA_QUESTION]

Best,
[SENDER_NAME]

## Follow-up 2
Draft on the seventh business day.

Hi [FIRST_NAME],

One last note about [PRODUCT_NAME].

[CTA_QUESTION]

Best,
[SENDER_NAME]

## Fields to fill
[INTENDED_USE]: an early preview
[NEXT_WEEK_ACTION]: a short call
[CTA_QUESTION]: Would next week work?
"""


def test_a_complete_playbook_reviews_clean():
    r = playbook.review(GOOD)
    assert r["initial_email"]["present"] and len(r["initial_email"]["paragraphs"]) == 2
    assert r["follow_ups"]["1"]["present"] and r["follow_ups"]["2"]["present"]
    assert r["timing"]["stated"] and r["timing"]["business_days"] == [3, 7]
    assert r["offer_values"]["CTA_QUESTION"] == "Would next week work?"
    assert r["missing"] == [] and r["ambiguous"] == [] and r["usable_for_followups"] is True


def test_the_content_hash_is_the_immutable_version_and_ignores_line_endings():
    assert playbook.content_hash(GOOD) == playbook.review(GOOD)["content_hash"]
    assert playbook.content_hash(GOOD) == playbook.content_hash(GOOD.replace("\n", "\r\n"))
    assert playbook.content_hash(GOOD) == playbook.content_hash(GOOD + "\n\n  ")  # trailing space ignored
    assert playbook.content_hash(GOOD) != playbook.content_hash(GOOD + " and one more line of real text.")


def test_a_missing_initial_email_is_reported():
    without = GOOD.replace("## Initial email", "## Opening (todo)")
    r = playbook.review(without)
    assert r["initial_email"]["present"] is False
    assert any("Initial email" in m for m in r["missing"])


def test_a_missing_follow_up_is_reported():
    without = GOOD.split("## Follow-up 2")[0] + "## Fields to fill\n[CTA_QUESTION]: Would next week work?\n"
    r = playbook.review(without)
    assert r["follow_ups"]["1"]["present"] and r["follow_ups"]["2"]["present"] is False
    assert any("Follow-up 2" in m for m in r["missing"])


def test_a_contradicted_offer_value_is_ambiguous():
    clash = GOOD + "\n[CTA_QUESTION]: Something different?\n"
    r = playbook.review(clash)
    assert any("CTA_QUESTION" in a for a in r["ambiguous"])


def test_missing_timing_is_reported():
    no_timing = GOOD.replace("third business day", "soon").replace("seventh business day", "later")
    r = playbook.review(no_timing)
    assert r["timing"]["stated"] is False
    assert any("timing" in m for m in r["missing"])
