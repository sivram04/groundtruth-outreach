# A/B tests and variant-level reporting (local, flag-gated) — 2026-10-01

MVP capability #9. The founder defines two named variants, assigns eligible leads to them with a
stable, immutable rule, and reads a variant-level report with explicit denominators and honest
labels. Local and flag-gated (`enable_experiments`, off by default and in deploy); it writes only to
the Sheet's own append-only `A/B tests` tab, never a founder column, and it is **not connected to
drafting** — a variant is a name only and changes no email.

## What is built

### Stable, immutable assignment (`outreach/experiments.py`)

- An experiment is a name and **exactly two** variant names. `define_rows` refuses empty or equal
  names.
- A lead's variant is **deterministic** — `variant_index = sha256(experiment ∥ lead_id) & 1` — so a
  refresh, a retry or a follow-up recomputes the same variant. It is never random.
- The assignment is **immutable**. The Record ID of an assignment is a hash of `(experiment,
  lead_id)` only — no index, name or time — so re-assigning a lead is the *same* row and is skipped
  on append; a lead can never be recorded under two variants. If two rows for one lead ever did
  exist, reading takes the **earliest** (append order) and ignores the rest.
- Reporting groups leads by a stable **variant index** (0/1), not by the recorded name, and labels
  each group with the experiment's current definition. So renaming a variant changes only the
  label, never which leads are in it.
- Eligibility: a lead that could get a drafted email — an OK address, a qualified fit, not on hold,
  not already emailed by hand — and that actually has an email address.

### Persistence boundary (`outreach/sheet.py`)

- One append-only tab `A/B tests` (`AB_HEADER`): `Record ID | Experiment | Kind | Variant | Variant
  index | Lead ID | Recorded at (UTC)`. `Kind` is `DEFINE` or `ASSIGN`.
- `Store.ab_records()` reads it (refusing a tab whose columns were changed, so a record is never
  read from the wrong column); `Store.append_ab_records()` appends, skipping any Record ID already
  present. The `MemoryStore` test double mirrors both.

### Routes (`outreach/console.py`, under `enable_experiments`)

- `POST /api/experiments/define` — save two named variants (400 on empty/equal names; idempotent).
- `POST /api/experiments/assign` — assign every eligible, not-yet-assigned lead (400 before a
  definition exists; reports `assigned` / `already_assigned` / `eligible` / `ineligible`).
- Both are **off by default and in deploy** (`_deployed()` does not pass the flag). With the flag
  off the routes are absent (404) and a test holds the default app to its read-only routes.

### Report (`outreach/experiments.report`, surfaced in the snapshot and the console)

Per variant, each metric carries an **explicit denominator** and a rate, or is marked **not
available** when no recorded signal exists:

| Metric | Denominator | Notes |
|---|---|---|
| Assigned | — | base |
| Drafted | assigned | |
| Confirmed sent | assigned | "a recorded send, not a confirmed delivery" — delivery is distinct; a bounce is the only delivery signal |
| Replies | confirmed sent | human replies; excludes auto-replies and requests to stop |
| Positive replies | replies | **not available** until a real positive-reply event is recorded |
| Opt-outs | confirmed sent | |
| Calls made | assigned | leads with a recorded call outcome |
| Follow-up emails sent | confirmed sent | counts follow-up sends, not call tasks |
| Meetings | confirmed sent | **not available** unless a real recorded meeting event exists |
| Opens | tracked sends | labelled **(est.)** — an estimate |

- **This is observed activity by assigned group, not A/B performance** (`basis: "observed_activity"`).
  Variant content does not yet change any email and no exposure is recorded, so the two groups are not
  comparable (`comparison.comparable` is false, `winner` always null), and **reaching a number of sends
  does not make them comparable** — the report says so and no send threshold is used.
- Positive replies and meetings read **"not available"**, not a misleading `0`, because the pipeline
  records no such signal yet; they become available the moment such events exist (the report already
  recognises `MEETING` / `POSITIVE_REPLY` events).
- A lead assigned and later suppressed is still counted as assigned (the assignment is immutable) and
  shown as a separate "assigned, now suppressed" context count. An unreadable Call log or Suppression
  list is flagged, never guessed.

### Console UI

- An **A/B tests** page (`console/src/pages/Experiments.tsx`): define the two variants, assign
  eligible leads, and a results table with the denominators and honest labels above. The nav entry
  and the page are gated by `experiments_enabled` (NotFound otherwise).
- Each lead's assignment is shown on the **Leads** list and the **Lead** page (an "A/B: <variant>"
  chip).

## Verified (network-disabled containers)

- Python: `test_experiments.py` (23) and `test_console_experiments.py` (15), whole suite **1050
  passed** (`deploy/test.Dockerfile`, `--network none`). *(Counts include the recheck regressions
  below.)*
- Frontend: `Experiments.test.tsx` (7), whole suite **117 passed**, typecheck and build clean
  (`deploy/console-test.Dockerfile`, `--network none`).
- Real loopback-HTTP, through the real Flask app and the Store boundary: `define → assign →
  snapshot` shows each lead's variant and the report (3 assigned, 2 ineligible, winner null); a
  **second assign moves nobody** (`assigned 0`, `already_assigned 3`, assignments byte-identical) —
  stable across a real retry.

Tests cover: stable assignment across reload/retry (and across a rename), record deduplication, the
suppression context count, unreadable Call log / Suppression / A/B tab, the "not available" metrics,
and the refusal to declare a winner.

## Recheck remediation (2026-10-01)

A recheck of `a2e427a` found three correctness gaps; all are fixed, with regressions through the real
snapshot/API.

1. **Outcomes before assignment were counted.** A lead assigned on Oct 1 with a Sept 30 send and
   reply had both counted in its variant's results. Now `read()` keeps each lead's assignment time
   and the report counts an outcome **only when it is reliably at or after that time**. An event (or
   call) before the assignment, or one whose time — or the assignment's own time — cannot be read, is
   **not counted** and is tallied as excluded (`variants[].excluded` and `report.excluded`:
   `before_assignment` / `undated`), with a note explaining the exclusion. Proven end to end through
   `GET /api/snapshot` for a previously-emailed lead: the old send and reply are excluded (totals 0,
   `excluded.before_assignment == 2`) while the lead stays assigned.
2. **Calls read as 0 when the Call log was unreadable.** The calls metric is now **unavailable**
   (`available: false`, no count), not a zero that could hide real calls or skew a variant.
3. **Assignment ignored the safety sources.** `POST /api/experiments/assign` now assigns a lead only
   when it is **not on the Suppression list** and **not in a call STOP/HOLD state**
   (`experiments.safe_to_assign`). If the Suppression list **or** the Call log cannot be read, the
   whole assignment is **refused (502) and nobody is assigned** — an unreadable safety source is never
   treated as permission.

Regressions: `test_experiments.py` (before-assignment, undated, no-assignment-time, calls-unavailable,
`safe_to_assign` STOP/HOLD/suppressed) and `test_console_experiments.py` (the previously-emailed lead
through the real snapshot; calls unavailable in the snapshot; a suppressed lead and a STOP/HOLD lead
not assigned; an unreadable safety source refusing the whole assignment). Verified no-network: Python
**1050**, frontend **117**, typecheck + build; and a real loopback-HTTP run confirming the excluded
pre-assignment outcomes and the fail-closed assignment.

## Second recheck remediation (2026-10-01)

A further recheck found one more attribution case and asked for a framing change.

1. **A reply (or other downstream outcome) after assignment, to a send made before assignment, was
   counted.** A downstream email outcome — a reply, opt-out, open, or follow-up send — is caused by a
   send, not by assignment alone, so it now counts **only when it links to a qualifying post-assignment
   send**: the same thread, after that send. The report finds each lead's qualifying send (the earliest
   INITIAL confident send recorded at or after assignment) and attributes downstream outcomes to it. An
   after-assignment reply whose only send predates assignment, or is on a different thread, is now a
   third kind of exclusion, **`unattributable`** (shown alongside `before_assignment` and `undated`),
   never a result. Reproduced through `GET /api/snapshot` (send 2026-09-30, assigned 2026-10-01, reply
   2026-10-02 on the same thread): sent and replies totals 0, `excluded.before_assignment == 1`,
   `excluded.unattributable == 1`.
2. **The report is labelled observed activity by assigned group, not A/B performance.** Until a
   variant's content actually changes a draft and that exposure is recorded, the two groups are not an
   A/B comparison. `report.basis` is `"observed_activity"`; `comparison.comparable` is false and
   `winner` null; the note says the groups are not comparable and that **reaching a number of sends
   would not make them comparable** (the previous send-threshold "can_compare" language and
   `MIN_SENDS_TO_COMPARE` are removed). The console page is titled "Observed activity by assigned group"
   with a "Not A/B performance" marker.

Regressions: `test_experiments.py` (reply-after-assignment-to-a-pre-assignment-send; a reply linked to
a post-assignment send counted; a reply on a different thread excluded; a follow-up on a pre-assignment
thread excluded; the observed-activity framing) and `test_console_experiments.py` (the reply-to-a-
pre-assignment-send case through the real snapshot). Verified no-network: Python **1055**, frontend
**117**, typecheck + build; and a real loopback-HTTP run confirming the excluded reply and the
observed-activity framing.

## Not done / out of scope

- **Not connected to drafting.** A variant is a name; it carries no outreach copy and feeds no email.
  The final Drive handbook and the approved offer — the only things that could feed real drafting —
  are untouched. Wiring variant content into drafting waits until the handbook and offer exist and
  is a separate, founder-gated step.
- **Positive replies and meetings** have no recorded signal in the pipeline yet, so they are "not
  available" rather than counted.
- **Nothing signed-in, deployed, or live.** `enable_experiments` is off by default and in deploy; no
  live Sheet read or write, no Gmail, no send. The no-send rule and the playbook approval gates are
  unchanged.
