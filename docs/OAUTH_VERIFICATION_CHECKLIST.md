# Google OAuth setup — for you + a friend (no verification needed)

**Corrected 2026-10-10: the full verification/CASA path below this line does NOT apply right
now.** It was written assuming an open, public sign-up product. The actual near-term need —
confirmed with the founder — is just two people: the founder's own account, and one external
friend. That's trivially inside Google's unverified-app **Testing mode cap of 100 users**, which
needs zero review, zero cost, and zero wait. Full verification is only a later concern, if this
ever opens up to the public.

## What to actually do (today, free, no waiting)

1. **Google Cloud Console → APIs & Services → OAuth consent screen**, for project
   `lakshyaa-outreach` (or a new project if you'd rather keep this separate from your existing
   tooling).
2. **User type: External.** (Internal only works if every connecting account is inside your own
   Workspace org — your friend's account isn't, so External is required here, but that's fine:
   External apps in Testing mode don't need verification either, up to 100 users.)
3. **Publishing status: Testing** (this is the default when you first create the consent screen —
   just don't click "Publish app," which is the step that would require verification).
4. **Add test users**: on the OAuth consent screen's "Test users" section, add your own email and
   your friend's email explicitly. Only addresses on this list can complete the OAuth flow while
   in Testing mode.
5. **Create an OAuth 2.0 Client ID** (APIs & Services → Credentials → Create Credentials → OAuth
   client ID → Web application). Set its authorized redirect URI to the real callback this app
   uses (`https://<your-domain>/api/tenant/google/callback` — matches what
   `outreach/google_connect.py` expects).
6. **Add the scopes actually used**: `gmail.readonly`, `gmail.compose`, and whichever Drive scope
   the connect flow ends up needing. Testing mode lets you add restricted scopes without
   Google reviewing anything, as long as only test users (step 4) use them.
7. Set the resulting `GOOGLE_OAUTH_CLIENT_ID`, `GOOGLE_OAUTH_CLIENT_SECRET`, and
   `GOOGLE_OAUTH_REDIRECT_URI` wherever the running service reads them from (environment
   variables / Secret Manager) — this is what `outreach/google_connect.from_environment()` on
   the `multi-tenant` branch looks for.

## What you'll see, using it this way

- When you or your friend sign in and grant access, Google shows an **"unverified app"** warning
  screen first ("Google hasn't verified this app") - click through it (as the developer/a test
  user, this is expected and normal, not an error).
- Everything else works exactly like a verified app: real Gmail/Drive access, real refresh
  tokens, no functional limitation versus a verified app - only the warning screen and the
  100-test-user cap.

## When the thing below actually becomes relevant

Only if/when this stops being "me and a friend" and becomes "anyone can sign up publicly." At
that point, revisit verification and (maybe) CASA - and even then, check Google's current
official documentation first; what's below was researched from third-party sources, not Google's
own page, and pricing/process details shift over time.

---

## Superseded: the original full-verification plan (kept for later reference only)

**This section does NOT apply to the current two-person use case above. Only relevant if this
product later opens up to public sign-up.**

In Google Cloud Console → APIs & Services → OAuth consent screen, for project
`lakshyaa-outreach` (or a new project, if you want this kept separate from your own tooling):

| Field | Value to use (confirm or change) |
| --- | --- |
| App name | Lakshyaa (or the public product name you want shown to users granting access) |
| User support email | admin@lakshyaa.ai |
| App logo | [Needs a real logo image — not yet made] |
| Application home page | https://lakshyaa.ai (confirm this is the page you want linked) |
| Application privacy policy link | https://lakshyaa.ai/privacy — see `docs/PRIVACY_POLICY_DRAFT.md` |
| Application terms of service link | [Not yet drafted] |
| Authorized domains | lakshyaa.ai |
| Developer contact email | admin@lakshyaa.ai |
| User type | External |

Publishing the app (not just leaving it in Testing) triggers:
- A review of the published privacy policy against the requested scopes.
- A demo video of the OAuth consent flow.
- For restricted scopes (Gmail/Drive), a security assessment — Google's own CASA process. Cost
  and tier vary and were unclear even from recent third-party research (estimates ranged from
  ~$540/year to $15k+ depending on tier and assessor) — get a current quote from Google's own
  documentation and an actual assessor before budgeting around any number found online.
- Review turnaround estimates found online ranged from 2–8 weeks.

Do not start this until there's an actual reason to support more than 100 known users.
