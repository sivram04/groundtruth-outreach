# Outreach MVP — delivery plan and status

One page for "is the MVP usable end to end". The authoritative build record stays `docs/AS_BUILT.md`;
this file tracks the **founder's MVP capabilities** against what exists, in dependency order, with
acceptance criteria and the local-vs-production line. Updated 2026-09-30.

## The journey we are driving to work end to end

Import a small list → select a playbook → generate a candidate → review it → persist the decision →
show the correct next action. Email **and** phone-only leads. Through the real routes and the real
persistence boundary (the `Store`); verified locally with synthetic data and simulated providers,
never the live Sheet.

## Capability status

| # | Capability | Status | Where |
|---|------------|--------|-------|
| 1 | Import leads from Sheets/Excel, incl. company-only and phone-only | **Implemented (local)** | `outreach/importer.py` parses CSV/TSV **and XLSX** (local libraries, no external service), maps the founder's headers to the destination tab's columns, preserves every contact field, classifies channel, assigns Lead IDs and dedupes. A flag-gated `POST /api/import/preview` + `/commit` and an Import page do upload → preview → confirm → persist through the real routes, verified with synthetic storage. Not run against the live Sheet. |
| 2 | Enrich missing contacts via the founder's Apollo/Hunter | **Missing / blocked** | Genuinely conflicts: Apollo/Hunter are **external network services** that receive lead data. Not built (conflict #1). |
| 3 | Upload a PDF/DOCX playbook (initial emails, follow-ups, rules) | **Missing** | Handbook today is one Drive/local doc; no upload, no PDF/DOCX parse, no multi-playbook. Parsing PDF/DOCX **locally** is allowed (a library is not an external service); the open question is the Drive-handbook rule and multi-playbook (conflict #4), not parsing. |
| 4 | Generate researched, personalized emails with inspectable evidence | **Implemented (email leads)** | `research.py`, `drafting.py`, `drafts.py`, `job_draft.py`; candidate + cited evidence surfaced for review. |
| 5 | Review drafts; manual approval or configured automation; daily limits, scheduling, follow-up timing | **Partial** | Review + signed decision done (`review.py`, `Review.tsx`). Manual approval only; automation/sending is out of scope by rule. Daily cap/scheduling/follow-up timing exist as settings + `followup.py`/`business_days.py`. |
| 6 | Handle replies: stop bad follow-ups; draft responses; booking link | **Partial** | Reply/opt-out/bounce stop the sequence (`sequence.py`, `sync.py`). Drafting a reply and a booking link are not built. |
| 7 | Record a call outcome (dashboard or chat); save to the lead; draft email if address exists; schedule next call per playbook; phone-only leads usable | **Partial** | Phone-only/company-only leads are now first-class with a correct next action (this milestone). Call-outcome capture, next-call scheduling and the chat entry are not built. |
| 8 | Keep overdue call tasks visible; no notification spam; coordinate calls with email | **Missing** | Needs a call-task record and schedule; depends on #7. |
| 9 | A/B tests and reporting (delivery, replies, positive, meetings, opt-outs, calls, follow-ups); honest open/click labels | **Partial** | Reporting on emails/replies/opens/clicks exists in `console_model`/`dashboard.py`, opens labelled "(est.)". A/B assignment, meetings, calls and follow-up-completion reporting not built. |

**Email and phone are independent contact capabilities.** A lead may have an email, a phone, both, or
neither. `channel` (`EMAIL` / `CALL` / `COMPANY_ONLY`) is only the **primary suggested next action** for
a lead that has not been emailed; it is not an exclusive permission. A lead with both is reachable both
ways and stays callable, and import preserves every contact field it is given.

## Exact conflicts with existing repository rules (not overridden here)

These are real tensions the MVP requirements create with `CLAUDE.md`. None is silently overridden;
each needs a founder decision before the conflicting capability ships.

1. **"No third-party tools. Only Google."** — this is about **external services**, not local
   libraries. Reading an Excel/PDF/DOCX file with a parsing library sends nothing to anyone and does
   **not** conflict; only **#2 Apollo/Hunter enrichment** conflicts, because those are external network
   services that receive the founder's lead data under the founder's credentials. Blocked pending a
   decision to allow a specific, opt-in, per-customer integration. (Local parsing dependencies are
   installed only in the project's container workflow — `requirements.txt` — never a runtime call out.)
2. **"Google Sheets is the only record … No database."** — kept as-is for this MVP. There is **no**
   database and **no** multi-tenant redesign here; import writes through the existing `Store` boundary
   to the Sheet's own lead tabs. A future sellable product may revisit storage, but that is out of
   scope and nothing here assumes it.
3. **"The system never sends email."** vs **#5 configured automation** and **#6 drafting/sending
   replies**. Drafting is allowed; sending is not, except the already-planned console step-3 "Approve
   sends this one email". Automated sending is out of scope until that rule is rewritten by the
   founder.
4. **"Future production handbook" (one Drive doc; do not request a link or enable drafting before it
   exists)** vs **#3 upload a playbook**. Playbook upload is a different mechanism; it must not silently
   enable drafting.
5. **Console is read-only ("Nothing here writes to the Sheet or to Gmail"; a test holds every
   non-review route to GET).** vs **#1 import** and **#7 record a call outcome**, which write. Any write
   route must follow the review-flow pattern: explicitly flag-gated, off in deploy, writing to an
   injected store, never the live Sheet, fully tested with fakes.
6. **"Never overwrite the founder's columns; identify rows by Lead ID."** Import must only *append*
   new rows and set system columns; it must never touch the founder's existing columns.

## Remaining work in dependency order

1. **Lead channels + correct next action (this milestone).** Email / phone-only / company-only are
   first-class; the journey's tail shows the right next action for each. *Done in this change.*
2. **Import as a usable workflow (this milestone).** Upload CSV/TSV/XLSX → preview mapped fields and
   validation → inspect duplicates/skipped/unstorable fields → confirm → persist → reload. Flag-gated
   (`enable_import`, off in deploy), append-only through `Store.append_leads`, revalidated at commit.
   *Done in this change; verified with synthetic storage, not the live Sheet.*
3. **Call tasks (#7/#8).** A call-task record (per lead, due date, state open/snoozed/cancelled/done),
   outcome capture (dashboard + a short chat message), next-call scheduling from the playbook, and
   coordination with the email sequence. Phone-only leads drive this.
4. **Playbook selection (#3).** Multiple playbooks; local PDF/DOCX parsing (allowed) and the
   Drive-handbook decision (conflict #4).
5. **Reply drafting + booking link (#6).**
6. **Enrichment (#2)** — blocked on conflict #1.
7. **A/B + fuller reporting (#9).**

## Acceptance criteria per milestone

- **M1 Lead channels (this change):** `console_model` gives every lead a `channel`
  (`EMAIL`/`CALL`/`COMPANY_ONLY`); a not-emailed phone-only lead's next action is a call and a
  company-only lead's is "find a contact"; an email lead is unchanged; verified through the real
  `console_model.build` with synthetic rows and shown on the console's Leads/Lead pages in the demo
  build (browser).
- **M2 Import as a usable workflow (this change):** through the real routes and the Import page, a
  founder uploads a small mixed list (CSV/TSV/XLSX), sees the fields as they will be stored, the
  validation results (including **invalid contact values, with why**), the duplicates and the
  skipped/unstorable fields, confirms **once**, and after reload sees the imported leads with their
  correct next actions — **without a developer script**. Company-only, phone-only, email-only and
  email+phone records are all preserved. Only new rows are written; founder data is never overwritten.
  Three acceptance failures found by review (`docs/testing/import-review-2026-09-30.md`) are fixed:
  (1) the preview is bound to the destination **schema** and a changed destination is refused (409),
  with the adapter refusing field loss rather than dropping; (2) each lead gets a **stable, immutable
  content-hash Lead ID** assigned before the write and written in a single append (a hex namespace, so
  no collision with an existing numeric id; no second position-based write, so a sort cannot move an
  id), retries reconcile by id, and a **claim ledger** (an append-only Sheet tab, earliest claim wins,
  gated by a required client idempotency key) makes two independent instances write **each lead exactly
  once**; (3) invalid contact values are preserved as validation feedback, never discarded. The
  production `Store.append_leads` / `claim_leads` adapters are tested against a **simulated Sheets API**,
  and the `MemoryStore` tests are kept. Browser sanity-checked through the actual local API with
  synthetic storage. **Remaining bounded limits:** a claim winner that fails and never retries leaves a
  lead unwritten until re-imported (bounded fix: a claim TTL + sweep; not built); **no live Sheet
  write** is verified and `enable_import` is off in deploy.
- **M3 Call tasks:** a call outcome recorded through a real route saves to the correct lead (incl.
  phone-only), drafts an email only when an address exists, schedules the next call per the playbook,
  and the task stays visible until done/snoozed/cancelled without repeat notifications.
- Later milestones: criteria defined when reached.

## Local completion vs production / live verification

- **Local (allowed here):** container tests (`deploy/test.Dockerfile`, `deploy/console-test.Dockerfile`,
  `--network none`), synthetic leads, a synthetic in-memory `Store`, a simulated Sheets API, and browser
  checks — for a write journey, against the **actual local API** (the real Flask with synthetic storage),
  not only the static demo. This proves the code and the journey shape.
- **Production / live (separate, not done here):** real Sheet writes, real Apollo/Hunter/Gmail, IAP
  sign-in, deploys, schedules and any sending. These remain unverified and require the founder plus the
  rule decisions above. Nothing in this plan provisions resources, changes permissions, deploys,
  activates schedules or sends.
