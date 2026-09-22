# Lakshyaa outreach

The founder's own cold-email funnel. `docs/ARCHITECTURE.md` is authoritative;
`docs/PIPELINE_2026-09-14.md` is the earlier plan, kept as history.

## Rules that do not bend

- **The system never sends email.** It only creates Gmail drafts. The founder reviews each one
  and presses Send in Gmail. No send call, SMTP client or auto-send path, ever.
- **Google Sheets is the only record** of leads, results, events and metrics. No database.
- **No third-party tools.** Only Google: Workspace (Gmail, Sheets), GCP, Gemini on Vertex AI.
  Apollo only supplied the email addresses.
- **Never overwrite the founder's columns** in the Sheet; identify rows by the system's Lead ID.
- **Never invent** a company fact; every company-specific statement traces to a stored quote.
- **Secrets live in `.secrets/` (git-ignored) or Secret Manager**, never in a commit.
- Commit locally. Push only when the founder asks.

## Where things are

- GCP project: `lakshyaa-outreach` (org `lakshyaa.ai`), signed in as `admin@lakshyaa.ai`.
- Leads Sheet: https://docs.google.com/spreadsheets/d/1eEVkxc0gJMFptYSr_u9prQ5O850TOX28AEq17CKaFiA/edit
- Build order: `docs/ARCHITECTURE.md` §11. Stage 0 passed 2026-09-22: the Cloud Run worker read 318 A + 174 B leads and wrote a Runs row. Next: stage 1 (email checks).
