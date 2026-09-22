"""Who may get a draft (stage 3 will call this; nothing drafts yet).

Email risk and company fit are separate columns and both must pass: a qualified company with
a RISKY address gets no draft, and a clean address at an unqualified company gets none either.
"""

from outreach import checks, research


def draft_eligible(row):
    """row: {header: value} from a lead tab. Returns (eligible, why_not)."""
    if row.get("Sent by hand"):
        return False, "already emailed by hand"
    if row.get("HOLD"):
        return False, "on hold"
    if row.get("Email check") != checks.OK:
        return False, f"email check is {row.get('Email check') or 'not done'}"
    if row.get("Fit") != research.QUALIFIED:
        return False, f"fit is {row.get('Fit') or 'not researched'}"
    return True, ""
