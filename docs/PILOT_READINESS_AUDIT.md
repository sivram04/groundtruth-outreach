# Outreach draft pilot — readiness audit

Checked 2026-09-23T00:00Z (2026-09-22 in America/New_York). Scope: a small,
founder-reviewed **Gmail-draft** pilot, not a full tracking or web-dashboard launch.

**Verdict: blocked (40/100).** The email check and company-research foundation runs,
but there is no draft generator or Gmail synchronization. The 138 passing offline tests
cover existing behavior, not the proposed draft-to-send-to-follow-up path.

## Evidence checked

- Clean local `main` at `4d18c53` before this audit; no pre-existing changes.
- `docker build -f deploy/test.Dockerfile -t lakshyaa-outreach-pilot-audit-test .`
  succeeded; `docker run --rm --network none lakshyaa-outreach-pilot-audit-test`
  passed 138/138 tests.
- Cloud Run `outreach-worker` serves revision `outreach-worker-00013-6vx` at 100%.
  Revision `outreach-worker-00016-rop` carries the `profile-review` tag at 0%.
- Cloud Scheduler contains only `outreach-check`, and it is `PAUSED`.
- `docs/OUTREACH_HANDBOOK_DRAFT.md` is placeholder-only in this checkout. It does not
  yet provide a verified MVP capability, concrete trial action, CTA, sender signature,
  or postal address for a real draft.

## Blockers for a real draft pilot

1. **No final render inputs.** Confirm the filled handbook or provide its location.
   A placeholder value must never enter Gmail. Keep the sender's actual mailbox,
   postal address, offer, trial experience and CTA together with a version ID.
2. **No draft job.** Build a dry-run preview first: select at most four currently
   eligible and reviewed company profiles, show the source quote and proposed
   observation beside each subject/body, validate every claim and footer, and hold
   weak evidence for human review. The `Profile status=READY` check alone is not
   sufficient: Gateway's earlier generic profile was held back manually.
3. **No safe Gmail draft write.** Before any draft is created, recheck the lead's
   current Sheet state, suppression/hold, prior sends and existing drafts. Store a
   durable action ID and reconcile uncertain Gmail/Sheet outcomes so retries cannot
   create duplicates. The founder reviews and sends; no automatic sending path.
4. **No Sent/reply sync.** The existing `Sent by hand` marker is not a timestamped
   thread match. To follow up on founder-sent emails from September 22 onward, read
   Gmail Sent, associate each message with exactly one lead and thread, and leave
   ambiguous matches for review. Start the timer only from a confirmed sent date.
5. **No follow-up job.** Prepare follow-up 1 on the third business date after the
   initial send, and follow-up 2 on the third business date after follow-up 1 is
   actually sent. Count Monday–Friday in America/New_York; stop for reply, bounce,
   opt-out or hold. Holiday exclusions remain undecided. A September 22 send is
   due September 25; a September 23 send is due September 28 under this rule.

## Later stages, not pilot blockers

- Open/click tracking and a web dashboard do not exist. They belong after the draft
  quality and send/reply association pilot; the Sheet remains the business record.
- A/B assignment and reporting do not exist. Persist a variant per initial draft,
  and compare replies per confirmed send. Do not declare a winner from a handful of
  pilot emails. Open hits are estimates, and recipient-specific spam placement is
  not observable from the sending mailbox.

## Next gate

First produce **four dry-run draft previews** from the reviewed profiles with the
filled handbook. The founder should judge whether each is worth sending with little
or no editing. Only then create the corresponding Gmail drafts. Reconcile sent mail
before enabling follow-up scheduling. Keep all existing schedules paused until those
end-to-end checks pass.
