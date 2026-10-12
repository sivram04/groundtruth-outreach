"""Roadmap #5, first slice: a newly added lead gets assessed without anyone calling a job by
hand. Runs the three read-only assessment stages in the order each depends on the last writing
first - email check, then fit research (needs an OK/RISKY email), then company profile (needs
OK email and QUALIFIED fit) - in one scheduled pass over the same Sheet.

Nothing here drafts, creates a Gmail draft, or sends; it only fills in the columns a human would
otherwise have triggered by hand (`POST /jobs/check`, `/jobs/research`, `/jobs/profile`), so a
lead arrives at the approve screen already checked, researched and profiled. Each stage still
writes its own Runs row (unchanged), so this adds no new audit surface - it is exactly the same
three calls, just made for you.
"""

from outreach import job_check, job_profile, job_research
from outreach.sheet import SHEET_ID

RESEARCH_LIMIT = job_research.DEFAULT_LIMIT
PROFILE_LIMIT = job_profile.MAX_LIMIT


def run(where="local", *, research_limit=RESEARCH_LIMIT, profile_limit=PROFILE_LIMIT,
        api=None, sheet_id=SHEET_ID):
    checked = job_check.run(where, api=api, sheet_id=sheet_id)
    researched = job_research.run(where, limit=research_limit, api=api, sheet_id=sheet_id)
    profiled = job_profile.run(where, limit=profile_limit, api=api, sheet_id=sheet_id)
    return {"checked": checked, "researched": researched, "profiled": profiled}


if __name__ == "__main__":
    print(run("local"))
