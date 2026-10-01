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
| 3 | Upload a PDF/DOCX playbook (initial emails, follow-ups, rules) | **Partial (local, flag-gated)** | A founder uploads a PDF or DOCX, sees the extracted text and the identified initial-email / follow-up / timing rules and what is missing/ambiguous, selects an immutable version by content hash, and previews a candidate from it (`outreach/playbook_extract.py`, `outreach/playbook.py`, `POST /api/playbook/review` + `/preview`, the **Playbook** page). Local parsers only; flag-gated `enable_playbook`, off by default and in deploy; read-only — no Gmail draft, no send, and the Drive handbook stays authoritative for production. The preview requires a server-minted, founder-bound, time-bounded selection token (`outreach/playbook_select.py`): a caller cannot get a "selected" preview by posting arbitrary text + hash, a changed file is refused (403), and both routes are size-bounded before parsing. **Not built (documented blocker):** durable cross-session selection — a Sheets cell holds ≤ 50,000 chars but a playbook may be 60,000, so the text cannot be persisted safely; selection is per-session (in-memory token, dies on restart). Multi-playbook and the Drive-handbook rule (conflict #4) remain open. See `docs/testing/playbook-2026-10-01.md`. |
| 4 | Generate researched, personalized emails with inspectable evidence | **Implemented (email leads)** | `research.py`, `drafting.py`, `drafts.py`, `job_draft.py`; candidate + cited evidence surfaced for review. |
| 5 | Review drafts; manual approval or configured automation; daily limits, scheduling, follow-up timing | **Partial** | Review + signed decision done (`review.py`, `Review.tsx`). Manual approval only; automation/sending is out of scope by rule. Daily cap/scheduling/follow-up timing exist as settings + `followup.py`/`business_days.py`. |
| 6 | Handle replies: stop bad follow-ups; draft responses; booking link | **Partial** | Reply/opt-out/bounce stop the sequence (`sequence.py`, `sync.py`). Drafting a reply and a booking link are not built. |
| 7 | Record a call outcome (dashboard or chat); save to the lead; draft email if address exists; schedule next call per playbook; phone-only leads usable | **Partial** | From the lead page a founder records an outcome (no answer / interested / not interested / callback / wrong number / do not contact); it is saved durably (`outreach/calls.py`, the Call log tab) and schedules the next call — no-answer by a configurable business-day rule, a callback by the explicit time. Phone-only and email+phone leads are both callable. **A post-call email candidate** is now offered for a lead with an email (inspect / edit / discard on the lead page, grounded in the saved call outcome/note, the company's cited words and the offer approved in settings, with the handbook version recorded; only for no-answer/interested/callback, and only when the effective call decision is not a stop and the offer is approved; says "today" only when the call is today; never claims a conversation or invents words; candidate-only — no send, no Gmail draft, no persistence; a HOLD still blocks the ordinary sequence; it is withdrawn when the lead's call state or suppression/offer/handbook changes). **Chat-based call logging** is now built: the founder types a short note on the dashboard, the console identifies the lead and outcome and shows the exact lead, saved note and next-call date to confirm, writing only on confirm through the existing outcome route (read-only interpret, separate from the general assistant; several matches → choose; a callback needs an explicit time, never inferred; a do-not-contact is shown as a sticky stop). **Done for this milestone.** |
| 8 | Keep overdue call tasks visible; no notification spam; coordinate calls with email | **Partial** | Tasks are due/overdue with complete / snooze / cancel and survive reload; they persist in the Sheet, not a notification queue (no spam). The email effect is persisted per outcome and **now enforced in the offline eligibility paths and at the real initial-draft boundary (`job_draft.create`, re-read there)**: a STOP (do not contact / not interested) or HOLD (interested / callback) skips a lead in `drafts.first_draft_blockers` / `followup.due_now` and blocks `job_draft.create`, and unreadable call history fails closed. Do-not-contact is a sticky per-lead block. A task action requires a nonempty `task_id` and is bound to the exact task shown (missing → 400, stale → 409, never applied to a newer task); a call submission is retry-stable through the UI; a partial success (suppression write failed) is shown with a retry that reuses the submission id. **The dashboard now has a call queue** ("Calls to make": overdue first, then due today, upcoming separate — upcoming items carry company/contact/phone/due/reason/note and a link to the lead; Complete/Snooze/Cancel reusing the task identity, with a Reload recovery that retargets the refreshed task after a stale 409; **suppressed/opted-out leads are left out**, and an unavailable state is shown when the call log **or** the suppression list is unreadable, never "no calls due"). See `docs/testing/calls-review-2026-09-30.md`. **Not built:** notification delivery (email/push). |
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
  id); (3) invalid contact values are preserved as validation feedback, never discarded. **Coordination:**
  the claim ledger separates the **operation** (a durable idempotency key) from each **attempt** (per
  request); for any lead, **only the request holding the earliest claim (`won`) ever writes it** — every
  other request (a concurrent attempt, a resume, or a different op) does read-only reconciliation and is
  reported `pending` / `blocked`, never written. This is the ownership guarantee: two requests can never
  both append the same lead, regardless of pausing/overlap. An append whose response is lost and cannot
  be reconciled is an explicit **uncertain** outcome, never "nothing written". The commit reports **done
  / pending / blocked / uncertain** and the UI shows each honestly. The `Store.append_leads` /
  `claim_leads` adapters are tested against a **simulated Sheets API** (including a reproduced
  original-vs-resume overlap that now writes the lead once); the `MemoryStore` tests are kept.
  **Corrected milestone record:** duplicate-prevention/concurrency (incl. overlap) **passes** locally;
  **automatic recovery of an abandoned pre-write claim is NOT available** (a resume reports it pending;
  safe takeover needs coordination stronger than append-only Sheets — a fenced lease / CAS — a separate
  architecture decision), so local recovery is **incomplete** for that case by explicit design (no
  duplicate over an unsafe takeover). Disabling import in deploy prevents live exposure but does **not**
  prove concurrency safety. **Live verification is a separate milestone and NOT done** (a real Sheet
  write / signed-in browser / real API latency), `enable_import` off in deploy.
- **M3 Call tasks (this change, partial):** through the real routes and the lead page, a founder
  records a call outcome that saves durably (Lead ID, note, call time, outcome) and schedules the next
  call — no-answer by a configurable business-day rule, a callback by the explicit time given, never a
  time inferred from the note. Due/overdue tasks show with complete / snooze / cancel and survive reload
  (overdue verified on a controlled clock, New York dates). A repeated submission makes no duplicate.
  Phone-only and email+phone leads are both callable. Do-not-contact stops the email (a Suppression
  entry, honoured by the scheduler) and is distinct from not-interested; suppression and holds are
  respected. The email effect of each outcome is persisted (STOP / HOLD / CONTINUE). Verified in
  containers (`test_calls.py`, `test_console_calls.py`, `CallPanel.test.tsx`) and browser-verified
  through the actual local API (no-answer → dated task → reload → complete). **Write routes are flag-gated
  (`enable_calls`), off by default and in deploy.** A follow-up review (`docs/testing/calls-review-2026-09-30.md`)
  found four correctness defects, all now fixed and regression-tested through the real routes and the pure state
  machine (Python 920, frontend 76): (1) STOP/HOLD is enforced in the initial-email and follow-up eligibility paths,
  unreadable call history fails closed, and a failed suppression write is reported (the STOP is still enforced by the
  recorded call event); (2) do-not-contact is a sticky per-lead block a later routine outcome cannot undo; (3) a task
  action is bound to the exact task shown (a stale action is refused, replay honours the target); (4) a call submission
  is retry-stable through the UI (a stable submission id, not the server clock, is the identity). A follow-up recheck
  then closed three enforcement-boundary gaps (Python 925, frontend 78): call STOP/HOLD is now enforced at
  `job_draft.create` (the real initial-draft boundary the worker route calls, re-read there so an approval granted
  before a call decision cannot bypass it); a task action requires a nonempty `task_id` (no current-task fallback);
  and CallPanel shows the partial-success warning with a retry that reuses the submission id. A later change aligned the
  call-history contract (`_call_effect` vs `Store.call_events`: absent = no calls, valid-header-no-events = no calls,
  present-without-header = block) and added the **dashboard call queue** (overdue-first / due-today / upcoming, reusing
  the task identity + Complete/Snooze/Cancel, an unavailable state when the Call log is unreadable; Python 931,
  frontend 83, browser-verified: record → appears → complete → gone after reload). **Remaining in the
  call milestone:** notification delivery
  (email/push). (The dashboard overdue/call queue is now built.) **Live verification is separate and NOT done** (a real
  Sheet write / signed-in browser / real API latency), `enable_calls` off in deploy.
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
