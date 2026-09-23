# Stage 3 draft pilot — local runbook

Status: local code only. It has **not** been deployed or run against the founder's
Sheet or Gmail. The production worker remains on the older revision, the check
schedule stays paused, and no draft schedule exists. The system never sends mail.

## What the preview does

For 1–4 explicit Lead IDs, it reads the current lead rows and matching Research
quotes. It requires an OK email check, QUALIFIED fit, a READY company profile,
and a current offering quote that appears in both the Research tab and the
lead's evidence cell. It checks HOLD, the manual-send marker, existing draft
action, and Suppression. The initial email uses the reviewed pre-launch wording
in `outreach/handbook/prelaunch_initial.txt`, quoting the company's own site
verbatim and displaying the source URL beside the proposed email. The subject
can be changed with `subject_template` (for example, `Question for [COMPANY]?`).
No inference about a prospect's private situation or finances is made.

To see a **synthetic, offline** example (no Google access):

```sh
docker build -f deploy/test.Dockerfile -t lakshyaa-outreach-draft-test .
docker run --rm --network none lakshyaa-outreach-draft-test python -m outreach.job_draft \
  --ids A-0001 --fixture examples/draft_preview_fixture.json \
  --settings examples/draft_preview_settings.json
```

For real previews later, put the founder-approved values in
`.secrets/pilot_handbook.json` using the keys shown in the synthetic settings
example. This file is ignored by Git. Fill the intended use, next-week action,
CTA, sender name/title/website/email, valid postal address, version, and daily
cap. Set `offer_approved` to the JSON boolean `true` only after reviewing the
wording. Without a field, the preview shows a blocker and has no approvable
hash. The code cannot infer these details from the product repo. The
`Suppression` tab must exist with an `Address or domain` header before a real
preview can be approved. The current live Sheet has no such tab yet.

The preview command without `--fixture` is a read-only Sheet path in code;
it has **not** been exercised. The controlled live pilot needs the project
container and existing Google sign-in configured before using it. Use the
Lead IDs of the reviewed company profiles, then review the subject, body,
exact quote, source URL, date and any blockers. Approval hashes expire after
the New York date changes. Do not use a hash from a synthetic fixture to
create a real draft.

## Gmail draft creation (disabled)

Local code has a private worker endpoint that takes a single Lead ID and the
exact `preview_hash` approved by the founder. It recomputes the preview from
current Sheet values, checks the signed-in Gmail mailbox, prior sent mail and
drafts, and the daily cap. It then reserves the action in Sheet columns before
calling Gmail's **draft create** method. If Gmail's response is uncertain,
the action stays `RESERVED` and a repeated create is blocked. The separate
reconciliation endpoint searches existing drafts by action ID; it never
creates a replacement. This cross-service path needs a controlled live pilot
before it can be described as verified.

`ENABLE_GMAIL_DRAFTS` defaults off. Do not turn it on, deploy, or schedule it
until the founder has reviewed the real previews and the remaining gates.
The founder edits and sends every draft manually. Sent/reply matching and
follow-up drafting are Stage 4 and do not exist yet.
