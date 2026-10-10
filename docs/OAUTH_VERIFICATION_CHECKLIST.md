# Google OAuth verification — what to actually do, in order

**This starts a ~6-week clock that runs regardless of code progress** (per
`docs/MULTI_TENANT_PLAN.md`). None of these steps can be done by an agent — they need your own
Google Cloud Console access, business decisions, and (for CASA) a payment. This checklist exists
so each step is unambiguous and nothing stalls waiting on a decision that could have been made
in advance.

## 1. Decide the OAuth consent screen's public-facing details

In Google Cloud Console → APIs & Services → OAuth consent screen, for project `lakshyaa-outreach`
(or a new project, if you want this kept separate from the founder's own tooling — recommended,
so a verification problem never touches your own working console):

| Field | Value to use (confirm or change) |
| --- | --- |
| App name | Lakshyaa (or the public product name you want shown to users granting access) |
| User support email | admin@lakshyaa.ai |
| App logo | [Needs a real logo image — not yet made] |
| Application home page | https://lakshyaa.ai (confirm this is the page you want linked) |
| Application privacy policy link | https://lakshyaa.ai/privacy — **must be live before submitting**; see `docs/PRIVACY_POLICY_DRAFT.md` |
| Application terms of service link | [Not yet drafted — optional but recommended] |
| Authorized domains | lakshyaa.ai |
| Developer contact email | admin@lakshyaa.ai |
| User type | **External** (so any Google account can connect, not only your own Workspace org) |

## 2. Publish the privacy policy at a real URL

Take `docs/PRIVACY_POLICY_DRAFT.md`, resolve its placeholders, and publish it at
`https://lakshyaa.ai/privacy` (or wherever the Application privacy policy link above points).
Google's reviewers will actually read it and check it matches the scopes requested — vague or
contradictory language is the most common reason for a verification rejection or delay.

## 3. Add the exact scopes being requested

Only request what's actually used:
- `https://www.googleapis.com/auth/gmail.readonly`
- `https://www.googleapis.com/auth/gmail.compose`
- `https://www.googleapis.com/auth/drive` (or a narrower Drive scope if the per-tenant design
  ends up only needing file-level access — narrower scopes get reviewed faster and need less
  justification; revisit this once the connect flow's actual Drive usage is designed)

Each restricted/sensitive scope needs a short justification in the console form, plus **a demo
video** (step 4) showing exactly how and why the app uses it.

## 4. Record the OAuth consent demo video

Google requires a short unlisted YouTube video showing: signing in, granting the requested
scopes, and the app actually using each one (e.g., a draft appearing in Gmail, a lead list being
read from Sheets). This has to show the REAL built flow — recommend recording it once the
account/connect flow (the parallel engineering track) has something real to show, not a mockup.

## 5. Submit for verification

From the OAuth consent screen page, "Submit for verification." Google's team will respond with
either approval, a request for more information, or a request to engage CASA (step 6) if the
scopes are classified as requiring it (Gmail/Drive scopes typically do).

## 6. CASA (Cloud Application Security Assessment)

For apps using restricted scopes, Google requires an annual third-party security assessment.
**This has a real cost** (typically starts around $1,500–2,000+ depending on scope and assessor,
current as of general industry pricing — get an actual quote, this is not a guaranteed number).
Google provides a list of authorized assessors. Budget for this before submitting if you want to
avoid a mid-process surprise. This repeats annually for as long as the app keeps these scopes.

## What NOT to wait on before starting

Steps 1–3 can start **today**, independent of the engineering work — the sooner this clock
starts, the sooner it's done. Step 4 (the demo video) is the one step that benefits from waiting
until the connect flow is real, so the video shows the actual product rather than a mockup that
would need re-recording later.
