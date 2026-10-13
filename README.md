# groundtruth-outreach

A cold-email outreach engine that never says anything about a company it can't prove.
Built for trade subcontractors — now growing into a multi-tenant platform anyone can sign into with their own Google account.

## Why this exists

Cold outreach is usually a numbers game: blast a template at everyone, hope something sticks.
This system takes the opposite bet — every email it drafts is grounded in a real, verified
quote from the company's own website. No fabricated claims, no guessed facts. If the system
can't find evidence, it refuses to draft rather than make something up.

That single rule — **never invent a company fact; every claim traces to a stored quote** —
shapes almost every design decision in this codebase.

## What it actually does

```
┌─────────────┐     ┌──────────────┐     ┌───────────────┐     ┌─────────────┐     ┌──────────┐
│  1. Import   │────▶│  2. Check    │────▶│  3. Research   │────▶│  4. Draft   │────▶│ 5. Send  │
│    leads     │     │  the email   │     │  the company   │     │  the email  │     │ (1 click)│
└─────────────┘     └──────────────┘     └───────────────┘     └─────────────┘     └──────────┘
      │                     │                     │                     │                 │
      ▼                     ▼                     ▼                     ▼                 ▼
 Lead ID assigned     MX/catch-all/      Gemini reads the      Grounded draft,      Human reads
 to every row         disposable         company's real        approval hash        and approves —
                       checks — OK /      site; stores          required before      the system never
                       RISKY / blocked    verified quotes       Gmail draft is       sends on its own
                                          only — no guessing     created
```

Five stages, each one reading only what the previous stage actually proved:

1. **Check** — validates every email address (MX records, catch-all detection, disposable-domain
   blocklist) before anything else happens. A risky address never gets a draft.
2. **Research** — an LLM reads the company's own website and extracts verified quotes about what
   they do, their markets, their projects. Nothing it can't point to a URL for survives.
3. **Profile** — expands that research into structured facts a draft can cite.
4. **Draft** — composes an email using *only* the stored quotes, gated behind a human evidence
   review. A draft with no valid review never gets an approval hash — and without that hash,
   nothing can be sent.
5. **Send** — exactly two sanctioned paths can trigger a real send: a human's one click, or a
   scheduled, cap-limited drip of already-approved drafts. Nothing else in the codebase is
   allowed to touch Gmail's send API — this is enforced by a dedicated test that scans the
   entire codebase for it.

Every lead's full journey — checked, researched, drafted, sent, replied to — lives in a Google
Sheet, not a hidden database. The founder can open the spreadsheet at any time and see exactly
what the system did and why.

## The multi-tenant engine

The system started as a single founder's tool, hardcoded to one Google account and one
spreadsheet. It's being extended into something anyone can sign into with their own Google
account — each person gets their own isolated Sheet, their own Gmail connection, their own data,
with zero chance of seeing anyone else's.

```
                    ┌────────────────────────────────────────┐
                    │         Google Identity Services         │
                    │   (sign-in — who is this person, today)  │
                    └───────────────────┬────────────────────┘
                                         ▼
                    ┌────────────────────────────────────────┐
                    │             Account resolved             │
                    │   (same person, multiple accounts OK —   │
                    │    switch without re-logging in)          │
                    └───────────────────┬────────────────────┘
                                         ▼
                 ┌───────────────────────┴───────────────────────┐
                 ▼                                                 ▼
    ┌─────────────────────────┐                     ┌─────────────────────────┐
    │   Connect Gmail/Sheets    │                     │   Row-level security     │
    │   (OAuth, encrypted       │                     │   scopes every query to  │
    │   refresh token via KMS)  │                     │   this account only —    │
    └─────────────────────────┘                     │   enforced by Postgres   │
                                                       │   itself, not app code   │
                                                       └─────────────────────────┘
                                         ▼
                    ┌────────────────────────────────────────┐
                    │   The same check/research/draft engine,   │
                    │   now pointed at THIS account's own        │
                    │   Sheet and THIS account's own Gmail       │
                    └────────────────────────────────────────┘
```

Why it's built this way:

- **Row-level security at the database layer** — isolation isn't just "the app remembers to
  filter by account_id." Postgres itself refuses to return another account's row, even if the
  application code had a bug. Defense in depth, proven live against a real database (one account
  genuinely cannot read another's connection).
- **Envelope encryption via Cloud KMS** — a connected account's Gmail/Sheets refresh token is
  never stored in plaintext; it's encrypted with a key bound to exactly that account, kind, and
  Google identity, so a stolen ciphertext can't be replayed into a different row.
- **Per-account everything** — not just data, but which Sheet tabs count as "leads," what the
  sender identity is, which Gmail account drafts go out from. No two accounts are forced into
  the same shape.
- **The founder's own sending rule still holds** — even in the multi-tenant version, nothing
  sends email except through the same two sanctioned paths. Extending that to tenant accounts
  is deliberately held back as its own explicit decision, not something that happened quietly
  while everything else was being built.

## Stack

- **Backend**: Python / Flask, Google Sheets as the system of record (single-tenant) or Postgres
  + per-account Sheets (multi-tenant)
- **Frontend**: React + TypeScript + Vite
- **AI**: Gemini (Vertex AI) for research and drafting — never for deciding what to send
- **Infra**: Google Cloud Run, Cloud SQL, Cloud KMS, Secret Manager
- **Auth**: Google Identity Services (sign-in) + OAuth 2.0 PKCE (Gmail/Sheets access)
