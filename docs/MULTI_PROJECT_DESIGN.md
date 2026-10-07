# Multi-project outreach: design

Status: **in progress on the `multi-project` branch, isolated in a separate worktree.** Nothing here
is on `main` or deployed. When it is complete and tested in isolation, it is pushed/merged.

One account, many **projects**. Each project is a use case — referrals, leads, investors, anything —
and the same engine serves all of them. What differs per project is only its **handbook**, its
**inputs**, and its **template**; the research → draft → human-approve → send → track loop is shared.

## The core idea (and what it is NOT)

The AI does **not** train or fine-tune. It **reads the project's handbook + the target's inputs and
drafts, grounded, every time** — exactly as the construction drafting already works. Swapping the
handbook changes what it writes. "Self-learning" here means *the handbook is the configuration*, not
model training. This keeps it safe (no invented figures, every claim traceable) and simple (no ML
pipeline).

## A project = { type, handbook, inputs, template }

| | Referrals | Leads | Investors |
|---|---|---|---|
| **Who** | people who can refer you | prospect companies | investors |
| **Inputs** | resume, JD, job URL | company research, offer | deck/demo link, company info |
| **Handbook** | how you ask for a referral | the sales offer wording | the investor intro wording |
| **Draft uses** | resume + JD + handbook | research + offer + handbook | deck/demo + research + handbook |

The columns are examples; a project declares its own **input schema** (which fields it needs) and its
**template** (how the draft is shaped). New project types are added by declaring these, not by new
engine code.

## Data model

- **Project**: `id`, `name`, `type` (referral | lead | investor | custom), `handbook_doc_id`,
  `offer`/template settings, `input_schema` (the fields its targets need), `created_at`. Stored in a
  **Projects tab** (one row per project), read like the other config tabs.
- **Target** (a lead/contact/referrer): gains a **`Project` column** naming which project it belongs
  to. Every existing lead defaults to the current single project, so nothing breaks.
- **Handbook**: per project (`handbook_doc_id` on the project), not one global doc.

## How each step becomes project-aware

1. **Research** — still researches the recipient/company; a project may skip or extend it (an investor
   project may research the fund; a referral project may need none).
2. **Draft** — `job_draft` / `drafting` select the **project's** handbook + template + the target's
   inputs, instead of the one global handbook. The grounding/evidence rules are unchanged.
3. **Review + Approve-and-send** — unchanged. The signed-review gate and the one send path already
   built apply to every project.
4. **Track** — opens/clicks/replies per project; metrics and A/B are reported per project.

## The chat assistant picks the project and gathers inputs

"Referral for the data-eng role at Acme: JD <url>, contact dana@acme.test" → the assistant identifies
the **project** (referrals), the **target**, and the **inputs** (JD url, contact), shows the proposed
draft-to-be, and — on confirm — files it under that project. Same propose-then-confirm safety as the
lead-management chat; it never sends and never invents.

## What stays the same (non-negotiable)

- Every send is a human's approval (the Ed25519-signed review gate + the single send path).
- No figure/claim is invented; every draft traces to the handbook + a cited input.
- Tracking is a property of outreach this system drafted, not of a pasted email.

## What changes / new work per type

- Per-project **input schema + template** (referral/lead/investor each need theirs).
- Per-project **research** (investor/referral research differs from company research for leads).
- A **Projects tab** + a `Project` column on targets + migration defaulting existing leads.
- Chat **project-selection** + input gathering.

## Multi-USER is separate

Multi-**project** is one account running several use cases — buildable without new auth. Multi-**user**
(other people, each with their own Gmail/Drive) still needs the Google OAuth restricted-scope
verification + CASA from `MULTI_TENANT_PLAN.md`. The two are independent; this doc is multi-project only.

## Build order (incremental, each tested in isolation)

1. **Project model + Projects store** (this tab, read-only first). ← starting here
2. **`Project` column on targets** + default every existing lead to the current project (migration).
3. **Project-aware drafting**: select handbook/template/inputs by the target's project (leads first —
   proves the generalization with the existing type).
4. **A second project type** (referrals): its input schema (resume/JD/job URL) + template.
5. **Chat project-selection + input gathering.**
6. **Investor type**; per-project metrics/A/B; console project switcher.
