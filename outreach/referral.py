"""Compose a referral email from a project's referral template and a target's inputs.

A referral project's handbook holds the message the founder asks a referral with, written with
``{placeholders}`` - for example ``Hi {name}, I'm applying for {role} at {company} ({job_url})``. This
module fills those placeholders from the target's own inputs and refuses when a required one is missing.
It is DETERMINISTIC: no model, no invented role, company or link. Like every draft in this system it is
for the founder to review and approve; nothing is sent here.
"""

import re

PLACEHOLDER = re.compile(r"\{([a-z_][a-z0-9_]*)\}")


class NotEligible(Exception):
    """A referral cannot be composed as asked (a required input is missing); the reason is reported,
    never filled with a guess."""

    def __init__(self, reason):
        self.reason = reason
        super().__init__(reason)


def placeholders(template):
    """The distinct ``{placeholder}`` names in a template, in first-seen order."""
    return list(dict.fromkeys(PLACEHOLDER.findall(template or "")))


def compose(subject_template, body_template, inputs):
    """Fill the subject and body templates' placeholders from ``inputs`` (a ``{name: value}`` map).

    Every placeholder must have a non-blank value in ``inputs``; a missing one raises ``NotEligible``
    rather than leaving a blank or inventing a value. Values are inserted verbatim (stripped). Returns
    ``{"subject": ..., "body": ...}``.
    """
    inputs = {k: str(v).strip() for k, v in (inputs or {}).items()}

    def fill(text):
        missing = sorted({p for p in placeholders(text) if not inputs.get(p)})
        if missing:
            raise NotEligible(f"missing referral input(s): {', '.join(missing)}")
        return PLACEHOLDER.sub(lambda m: inputs[m.group(1)], text or "")

    return {"subject": fill(subject_template), "body": fill(body_template)}


def required_inputs(subject_template, body_template):
    """Every input a referral draft needs for these templates - what a target row (and the account's
    resume) must supply before a draft can be composed. Lets the caller ask for them up front."""
    return sorted(set(placeholders(subject_template)) | set(placeholders(body_template)))
