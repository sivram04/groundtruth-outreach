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
| 1 | Import leads from Sheets/Excel, incl. company-only and phone-only | **Partial** | `outreach/importer.py` parses/normalizes/classifies a small CSV/records list (email, phone-only, company-only), assigns Lead IDs, dedupes, and reports. No upload route/UI yet, and no live write. Excel (.xlsx) blocked (see conflicts). |
| 2 | Enrich missing contacts via the founder's Apollo/Hunter | **Missing / blocked** | Conflicts with "no third-party tools". Not built. |
| 3 | Upload a PDF/DOCX playbook (initial emails, follow-ups, rules) | **Missing / blocked** | Handbook today is one Drive/local doc; no upload, no PDF/DOCX parse, no multi-playbook. Conflicts with the Drive-handbook rule and "no third-party". |
| 4 | Generate researched, personalized emails with inspectable evidence | **Implemented (email leads)** | `research.py`, `drafting.py`, `drafts.py`, `job_draft.py`; candidate + cited evidence surfaced for review. |
| 5 | Review drafts; manual approval or configured automation; daily limits, scheduling, follow-up timing | **Partial** | Review + signed decision done (`review.py`, `Review.tsx`). Manual approval only; automation/sending is out of scope by rule. Daily cap/scheduling/follow-up timing exist as settings + `followup.py`/`business_days.py`. |
| 6 | Handle replies: stop bad follow-ups; draft responses; booking link | **Partial** | Reply/opt-out/bounce stop the sequence (`sequence.py`, `sync.py`). Drafting a reply and a booking link are not built. |
| 7 | Record a call outcome (dashboard or chat); save to the lead; draft email if address exists; schedule next call per playbook; phone-only leads usable | **Partial** | Phone-only/company-only leads are now first-class with a correct next action (this milestone). Call-outcome capture, next-call scheduling and the chat entry are not built. |
| 8 | Keep overdue call tasks visible; no notification spam; coordinate calls with email | **Missing** | Needs a call-task record and schedule; depends on #7. |
| 9 | A/B tests and reporting (delivery, replies, positive, meetings, opt-outs, calls, follow-ups); honest open/click labels | **Partial** | Reporting on emails/replies/opens/clicks exists in `console_model`/`dashboard.py`, opens labelled "(est.)". A/B assignment, meetings, calls and follow-up-completion reporting not built. |

## Exact conflicts with existing repository rules (not overridden here)

These are real tensions the MVP requirements create with `CLAUDE.md`. None is silently overridden;
each needs a founder decision before the conflicting capability ships.

1. **"No third-party tools. Only Google."** vs **#2 Apollo/Hunter enrichment** and **#3 PDF/DOCX
   playbook parsing** (PDF/DOCX need a parsing library). Enrichment also means sending lead data to a
   third party under the founder's credentials. Blocked pending a decision to allow specific
   third-party integrations, per-customer and opt-in.
2. **"Google Sheets is the only record … No database."** vs a multi-tenant product with per-customer
   playbooks, credentials and call tasks. For the founder's own funnel the Sheet is fine; a sellable
   product will need a store decision. Import here targets the `Store` boundary, not a new DB.
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
2. **Import core (this milestone, partial).** Parse/normalize/classify/dedupe a small list; assign
   Lead IDs. *Done as a pure module.* **Next:** a flag-gated import route + `Store` append boundary
   (append-only, new rows), following the review-flow safety pattern, verified with a fake store.
3. **Call tasks (#7/#8).** A call-task record (per lead, due date, state open/snoozed/cancelled/done),
   outcome capture (dashboard + a short chat message), next-call scheduling from the playbook, and
   coordination with the email sequence. Phone-only leads drive this.
4. **Playbook selection (#3).** Multiple playbooks; a decision on PDF/DOCX parsing (conflict #1).
5. **Reply drafting + booking link (#6).**
6. **Enrichment (#2)** — blocked on conflict #1.
7. **A/B + fuller reporting (#9).**

## Acceptance criteria per milestone

- **M1 Lead channels (this change):** `console_model` gives every lead a `channel`
  (`EMAIL`/`CALL`/`COMPANY_ONLY`); a not-emailed phone-only lead's next action is a call and a
  company-only lead's is "find a contact"; an email lead is unchanged; verified through the real
  `console_model.build` with synthetic rows and shown on the console's Leads/Lead pages in the demo
  build (browser).
- **M2 Import core (this change, partial):** from a small CSV/records list, `importer.import_leads`
  returns normalized rows (channel set, Lead IDs assigned without collision, founder columns blank),
  a de-duplicated set (by email, else phone, else company+website), and a report naming every skipped
  record with a reason; unit-verified with synthetic data. **Not accepted until wired:** a route/UI and
  a `Store` append boundary that appends new rows to the correct tab and is verified end to end through
  a fake store into `console_model`.
- **M3 Call tasks:** a call outcome recorded through a real route saves to the correct lead (incl.
  phone-only), drafts an email only when an address exists, schedules the next call per the playbook,
  and the task stays visible until done/snoozed/cancelled without repeat notifications.
- Later milestones: criteria defined when reached.

## Local completion vs production / live verification

- **Local (allowed here):** container tests (`deploy/test.Dockerfile`, `deploy/console-test.Dockerfile`,
  `--network none`), synthetic leads, fake `Store`, simulated providers, and browser checks against the
  demo build. This proves the code and the journey shape.
- **Production / live (separate, not done here):** real Sheet writes, real Apollo/Hunter/Gmail, IAP
  sign-in, deploys, schedules and any sending. These remain unverified and require the founder plus the
  rule decisions above. Nothing in this plan provisions resources, changes permissions, deploys,
  activates schedules or sends.
