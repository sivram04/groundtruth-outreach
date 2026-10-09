# Lakshyaa outreach

The founder's own cold-email funnel. `docs/ARCHITECTURE.md` is authoritative;
`docs/PIPELINE_2026-09-14.md` is the earlier plan, kept as history.

## Rules that do not bend

- **A send happens only through `outreach/send.py`, and only from one of its two sanctioned
  callers.** Originally the system never sent at all; the founder's own decisions since then
  (2026-09-28, then the 5-feature roadmap item 3 on 2026-10-08) opened exactly two paths, both
  built and both pinned by `tests/test_no_send.py`:
  1. the console's human-clicked **Approve and send** (one click, one email — has sent one real
     email as of 2026-10-08);
  2. the scheduled, cap-limited drip in **`outreach/auto_send.py`** (`POST /jobs/send`), with no
     per-email click — **built and tested but not yet live**: `ENABLE_AUTO_SEND` is unset and no
     Cloud Scheduler job calls it yet (see `docs/AS_BUILT.md`).
  Nothing else may send — no SMTP client, no third path, ever, without the same kind of explicit
  founder decision these two had.
- **Web pages are React built with Vite** (`console/`), with Python serving data only. Not
  server-made HTML (founder, 2026-09-28).
- **Google Sheets is the only record** of leads, results, events and metrics. No database.
- **No third-party tools.** Only Google: Workspace (Gmail, Sheets), GCP, Gemini on Vertex AI.
  Apollo only supplied the email addresses.
- **Future production handbook:** the founder has not put the final handbook in Drive yet.
  Stage 3 must eventually read that Drive document from the private GCP worker; the local
  handbook draft and settings are not the production source. Do not request a Drive link
  or turn on drafting before the document exists.
- **Never overwrite the founder's columns** in the Sheet; identify rows by the system's Lead ID.
- **Never invent** a company fact; every company-specific statement traces to a stored quote.
- **Research the company, not the person's private life.** Preserve separate, verified facts
  about its products/services, markets and projects for later draft personalization; an ICP
  fit verdict alone is not enough to write an email.
- **A draft needs an OK email check and a QUALIFIED fit** (`outreach/eligibility.py`). Email
  risk and company fit are separate columns; a RISKY address never gets a draft.
- **Secrets live in `.secrets/` (git-ignored) or Secret Manager**, never in a commit.
- Commit locally. Push only when the founder asks.

## Where things are

- GCP project: `lakshyaa-outreach` (org `lakshyaa.ai`), signed in as `admin@lakshyaa.ai`.
- Leads Sheet: https://docs.google.com/spreadsheets/d/1eEVkxc0gJMFptYSr_u9prQ5O850TOX28AEq17CKaFiA/edit
- Build order: `docs/ARCHITECTURE.md` §11.
- **What is actually built: `docs/AS_BUILT.md`. Update it after every change** — stage
  status, resources, Sheet columns, rules, and a dated change-log line. A change is not done
  until that file says so.
