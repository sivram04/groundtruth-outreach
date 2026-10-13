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

## The full end-to-end workflow

It's not a one-shot "send and forget" pipeline — a lead moves through a loop that keeps
responding to whatever actually happens, and a human reviews every word before anything goes out.

```
                              ┌──────────────┐
                              │  1. Import    │
                              │    leads      │
                              └───────┬──────┘
                                      ▼
                              ┌──────────────┐
                              │  2. Check     │  MX / catch-all / disposable-domain checks
                              │  the email    │  → OK / RISKY / blocked
                              └───────┬──────┘
                                      ▼
                              ┌──────────────┐
                              │  3. Research  │  Gemini reads the company's real site,
                              │  the company  │  stores only verified quotes — no guessing
                              └───────┬──────┘
                                      ▼
                              ┌──────────────┐
                              │  4. Draft the │  Grounded in stored quotes only.
                              │ initial email │  Needs a human evidence review before
                              └───────┬──────┘  it's allowed an approval hash.
                                      ▼
                              ┌──────────────┐
                              │ 5. Human      │  One click — the ONLY two places in the
                              │  approves &   │  whole codebase allowed to touch Gmail's
                              │    sends      │  send API (enforced by a dedicated test)
                              └───────┬──────┘
                                      ▼
                    ┌─────────────────┼─────────────────┐
                    ▼                 ▼                 ▼
            ┌──────────────┐  ┌──────────────┐  ┌──────────────┐
            │  No reply     │  │   Lead        │  │   A sales     │
            │  by the due    │  │   replies      │  │   call         │
            │  business day  │  │                │  │   happens       │
            └───────┬──────┘  └───────┬──────┘  └───────┬──────┘
                    ▼                 ▼                 ▼
          ┌──────────────────┐ ┌──────────────────┐ ┌──────────────────┐
          │  Follow-up 1, then  │ │  Reply-draft       │ │  Outcome recorded  │
          │  Follow-up 2 —       │ │  candidate          │ │  (calls.py), then   │
          │  drafted from the    │ │  composed from       │ │  a post-call email   │
          │  founder's OWN        │ │  saved evidence —     │ │  drafted from what   │
          │  handbook templates,  │ │  founder reads,        │ │  was actually said   │
          │  never AI-written      │ │  edits or discards     │ │                       │
          └───────┬──────────┘ └───────┬──────────┘ └───────┬──────────┘
                    └─────────────────┴─────────────────┘
                                      ▼
                              ┌──────────────┐
                              │  Back to      │  A reply, a STOP request, a bounce, or
                              │  "human        │  the suppression list ends the sequence
                              │  approves"     │  for that lead immediately.
                              └──────────────┘
```

A chat layer sits alongside this the whole time — not part of the pipeline itself, but how the
founder steers it day to day:

- **Ask the assistant** — read-only Q&A over the Sheet's own data ("how many leads are stuck at
  research?"). It can answer and link to a page; it can never send, draft, or change anything.
- **Talk to a lead's row** — type a short instruction ("mark this as sent by hand") and get back
  a structured proposal to confirm — nothing is written until the founder confirms it.
- **Talk to company settings** — set the sender identity, daily cap, or product name by typing
  it, instead of hand-editing a config file.

## What each stage actually is, and why it's built that way

1. **Check** — validates every email address before anything else happens. A risky address
   never gets a draft; dead ends get cut as early as possible.
2. **Research** — an LLM reads the company's own website and extracts verified quotes. Nothing
   it can't point to a URL for survives into the next stage.
3. **Profile** — expands that research into structured facts a draft can actually cite.
4. **Draft (initial)** — composes an email using *only* the stored quotes, gated behind a human
   evidence review. No valid review, no approval hash. No approval hash, nothing can be sent.
5. **Approve & send** — exactly two sanctioned paths can trigger a real send: a human's one
   click, or a scheduled, cap-limited drip of already-approved drafts. A dedicated test scans
   the entire codebase to guarantee nothing else can reach Gmail's send API.
6. **Sequence & follow-ups** — once sent, a lead's status (never sent / follow-up due / replied
   / stopped) is worked out purely from its recorded events — no hidden state. Follow-up 1 and
   Follow-up 2 are due on fixed business-day schedules, and their wording comes from the
   founder's own handbook templates, filled with real offer values — never freshly AI-written.
7. **Reply drafting** — when a lead writes back, a reply candidate is composed on demand from
   already-saved evidence. It's never sent, never auto-drafted into Gmail, never persisted —
   just something to read next to the evidence it's grounded in.
8. **Call outcomes → post-call email** — a recorded call outcome (interested, callback, not
   interested) can generate a post-call follow-up candidate grounded in what was actually said
   on the call plus the company's own evidence — same "founder reviews, never auto-sends" rule.

Every lead's full journey — checked, researched, drafted, sent, followed up, replied to, called
— lives in a Google Sheet, not a hidden database. The founder can open the spreadsheet at any
time and see exactly what the system did and why.

## The multi-tenant engine

The system started as a single founder's tool, hardcoded to one Google account and one
spreadsheet. It's being extended into something anyone can sign into with their own Google
account — each person gets their own isolated Sheet, their own Gmail connection, their own data,
with zero chance of seeing anyone else's.

**Current status: the check → research → profile → draft pipeline (stages 1–4 above) has been
ported to work per-account.** Sequencing, follow-ups, reply drafting, call-based drafting and the
chat layer still only exist in the single-tenant product — they haven't been extended to
multi-tenant accounts yet.

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
- **AI**: Gemini (Vertex AI) for research, drafting and the chat assistant — never for deciding
  what to send
- **Infra**: Google Cloud Run, Cloud SQL, Cloud KMS, Secret Manager
- **Auth**: Google Identity Services (sign-in) + OAuth 2.0 PKCE (Gmail/Sheets access)
