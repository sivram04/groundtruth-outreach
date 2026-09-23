# Stage 3 automated drafting pipeline — build brief

The automated drafting pipeline is **not built yet**. Implement it in this
repository. Read `CLAUDE.md`, `docs/ARCHITECTURE.md`, `docs/AS_BUILT.md`,
`docs/PILOT_READINESS_AUDIT.md`, and `docs/OUTREACH_HANDBOOK_DRAFT.md` first.
The existing worker checks addresses and researches companies; there is no
draft job, Gmail draft writer, sent-mail sync, follow-up job, tracker, or web
dashboard. Do not describe any of those as already working.

## Scope for this build

Build **Stage 3, initial-email drafts**. Begin with a local/offline dry-run
that produces a subject, body, lead ID, and the exact company-site quote and
URL supporting each personalized observation. The founder must be able to
review a small pilot (up to four explicitly selected, previously profiled
leads) before any Gmail draft is made. Add a Gmail **draft creation** path, but
make its final write fail closed until all handbook/sender fields are filled,
the draft passes validation, and the founder has approved that preview. Do not
create live drafts during this build or deploy it.

Use the company's verified products/services, markets, or projects. Never
claim to know an individual's private situation or the company's cash flow,
software, pain, savings, or current need. A relevant invitation may discuss a
workflow without pretending the prospect has that problem. Subject lines
must be customizable and truthful. The MVP is still unfinished, so the
current pilot copy invites a conversation next week; it must not promise a
live trial or completed demo. Replies can come immediately.

The Sheet remains the only outreach business record. Preserve the founder's
columns, locate rows by Lead ID, and use the existing write safeguards.
Recheck immediately before a Gmail write: OK email, QUALIFIED fit, reviewed
company evidence, no HOLD, prior manual send, suppression, existing draft, or
uncertain action. Enforce a small explicit pilot limit and a daily cap. Use a
durable action ID and reconcile uncertain Gmail/Sheets outcomes so retries do
not duplicate drafts. A Sheet row and a Gmail draft are not one transaction.
Do not log message bodies, credentials, or recipient addresses in Runs.

The system must **never send email**. Do not add send calls, SMTP, automatic
follow-up sending, or a recurring schedule. Keep both existing schedules
paused. Do not touch GCP, Gmail, or the live Sheet during implementation and
offline verification. The founder reviews and sends every email manually.
Stage 4 sent/reply sync and business-day follow-up drafting, tracking,
dashboard, and A/B outcome reporting are separate later work; leave clear
interfaces or documentation rather than claiming them complete.

## Acceptance and handoff

- The preview path works offline with fixtures for the four reviewed company
  profiles, and clearly marks any unresolved handbook field. It must not
  invent a missing field or emit a send-ready draft containing a placeholder.
- Tests cover gating, quote provenance, unsupported claims, subject and footer
  validation, manual-send exclusion, suppression, retry/idempotency, and the
  no-send invariant. Keep tests meaningful and focused.
- Use the repository's container test workflow. Run tests and a build/lint
  check where available; report exact results and anything unverified.
- Update `docs/AS_BUILT.md` with precisely what exists, what remains blocked,
  and a dated change-log entry. Commit locally only; no push or deploy.
- In the handoff, show where the preview command/output is, what inputs the
  founder still owes (including actual invitation and postal address), and
  what was not exercised against live Gmail.
