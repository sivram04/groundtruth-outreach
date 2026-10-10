# Privacy policy — draft for publication

**Status: DRAFT. Not yet published anywhere.** This is the text Google's OAuth verification
process requires at a real, publicly-reachable URL (e.g. `https://lakshyaa.ai/privacy`) before
it will review an app requesting restricted scopes (`gmail.readonly`, `gmail.compose`, `drive`).
Review and edit before publishing — in particular, confirm the legal entity name, the postal
address, and whether any detail here needs a lawyer's review before it is binding.

Placeholder values used below, pulled from the founder's own saved settings as of 2026-10-10 —
confirm each is correct to publish:
- Company / product name: **Lakshyaa**
- Contact: **admin@lakshyaa.ai**
- Postal address: **175 S 3rd St, Suite 200, Columbus, OH 43215**
- Founder: **Sivaram Vangavolu, Founder / CEO**

---

## Privacy Policy

**Last updated: [DATE OF PUBLICATION]**

Lakshyaa ("we," "us," "our") provides an outreach tool that helps a business draft, review and
send email outreach from their own Gmail account, using data from their own Google Sheets or
Google Drive. This policy explains what we access, why, and how it is handled.

### What we access, and why

When you connect your Google account to Lakshyaa, you grant us permission to:

- **Read your Gmail inbox** (`gmail.readonly`) — to detect replies, bounces, and opt-out requests
  to outreach sent through Lakshyaa, so we can stop further emails to anyone who asks and show you
  who has responded.
- **Create draft emails in your Gmail account** (`gmail.compose`) — to prepare outreach emails for
  your review. **Lakshyaa never sends an email without your explicit action** — every email is a
  draft you review, edit if you choose, and approve to send yourself.
- **Read your Google Drive / Sheets** (`drive`) — to read the lead list and messaging guidelines
  (your "handbook" or "playbook") you provide, and to read/write the spreadsheet that records your
  outreach activity (who was contacted, when, and the outcome).

We request only the scopes above. We do not request access to send email directly on your behalf
without a corresponding draft-approval step, and we do not request access to any Google data
outside Gmail, Sheets and Drive.

### What we store

- **OAuth tokens**: your Google account's refresh token, encrypted at rest, used only to act on
  your behalf for the purposes above. [Confirm storage/encryption approach before publishing —
  this should describe however tokens are actually stored once that work is built.]
- **Your outreach data**: the lead list, message content, and activity records you provide or
  that Lakshyaa generates while helping you, stored in your own connected Google Sheet or in
  Lakshyaa's own database, scoped to your account only.
- **We do not sell your data.** We do not use your Gmail or Drive content to train AI models
  beyond generating your own outreach drafts for you.

### How to disconnect

You can revoke Lakshyaa's access at any time from [your account settings page] or directly from
your [Google Account's third-party access page](https://myaccount.google.com/permissions).
Revoking access stops all further reads and draft creation; previously sent emails are
unaffected, as they are already in your own Sent mail.

### Data retention

[Confirm actual retention policy before publishing — e.g., "Lead and activity data is retained
for as long as your account is active, and deleted within [N] days of account closure or
disconnection, whichever you request."]

### Changes to this policy

We will post any changes to this policy on this page, with an updated "Last updated" date.

### Contact

Questions about this policy: **admin@lakshyaa.ai**.
Lakshyaa, 175 S 3rd St, Suite 200, Columbus, OH 43215.

---

## Before publishing, resolve these placeholders

1. Confirm the legal entity name (is "Lakshyaa" the registered business name, or a dba?).
2. Confirm the postal address is the one you want public (it will be, verifiable by anyone).
3. Decide and describe the actual token storage/encryption approach once built (don't publish a
   promise the system doesn't keep).
4. Decide an actual data-retention period, and build deletion to match it before publishing a
   number.
5. Have this reviewed by a lawyer if you have any doubt about enforceability or scope - this
   document creates real obligations once published and referenced in Google's OAuth consent
   screen.
