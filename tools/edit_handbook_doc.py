"""One-off, founder-instructed: insert draft offer values into the handbook Doc (2026-09-23).

The worker's stored credentials stay read-only. This tool asks for a separate, one-time Google
Docs sign-in whose token is held in memory for this run and never written to Secret Manager or
to disk.

It reads the document first, inserts immediately after the paragraph beginning "Status:", then
reads it back and checks that the insertion is present and the rules, the initial-email
template and both follow-ups are untouched.

    python -m tools.edit_handbook_doc <document_id>            # read-only check
    python -m tools.edit_handbook_doc <document_id> --apply
"""

import sys
from pathlib import Path

from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

from outreach import handbook_drive

CLIENT_FILE = Path(__file__).resolve().parent.parent / ".secrets" / "client_secret.json"
EDIT_SCOPE = "https://www.googleapis.com/auth/documents"
ACCOUNT = "admin@lakshyaa.ai"
ANCHOR = "Status:"
INSERT = """Draft offer values for founder review
[INTENDED_USE]: use bank balances, open invoices and bills, payroll dates, fixed costs, and \
upcoming job billings to compare scenarios and explain recommended next steps
[NEXT_WEEK_ACTION]: have a twenty minute conversation about the early preview
[CTA_QUESTION]: Would you be open to a twenty minute conversation next week about the early preview?
"""
# Sections that must survive the edit untouched.
MUST_KEEP = ["Writing rules", "Fields to fill before using the templates", "Initial email",
             "Follow-up 1", "Follow-up 2", "no thanks"]


def paragraphs(doc):
    """(start_index, end_index, text) for each paragraph, in document order."""
    out = []
    for element in doc.get("body", {}).get("content", []):
        para = element.get("paragraph")
        if not para:
            continue
        text = "".join(run.get("textRun", {}).get("content", "") for run in para.get("elements", []))
        out.append((element["startIndex"], element["endIndex"], text))
    return out


def sign_in():
    flow = InstalledAppFlow.from_client_secrets_file(str(CLIENT_FILE), [EDIT_SCOPE])
    creds = flow.run_local_server(
        port=0, prompt="consent", login_hint=ACCOUNT,
        authorization_prompt_message="Opening the browser to authorise this one edit:\n{url}\n",
        success_message="Authorised. You can close this tab.")
    return build("docs", "v1", credentials=creds, cache_discovery=False)


def report(text, label):
    print(f"\n{label}: {len(text)} characters")
    for section in MUST_KEEP:
        print(f"  {'present' if section in text else 'MISSING'}: {section}")
    for line in INSERT.strip().splitlines():
        key = line.split(":")[0]
        print(f"  {'present' if line.strip() in text else 'absent '}: {key}")


def main(document_id, apply):
    before = handbook_drive.load({"handbook_doc_id": document_id})
    print(f'Document {before["document_id"]} "{before["name"]}"')
    print(f'hash {before["content_hash"]} modified {before["modified"]}')
    report(before["text"], "BEFORE")
    if any(line.strip() in before["text"] for line in INSERT.strip().splitlines()[1:]):
        sys.exit("\nThe offer values are already in the document; nothing to insert.")
    if not apply:
        print("\nread-only check: nothing written")
        return

    docs = sign_in()
    doc = docs.documents().get(documentId=document_id).execute()
    anchors = [p for p in paragraphs(doc) if p[2].strip().startswith(ANCHOR)]
    if len(anchors) != 1:
        sys.exit(f"expected exactly one paragraph starting {ANCHOR!r}, found {len(anchors)}")
    at = anchors[0][1] - 1  # end of the Status paragraph, before its newline
    docs.documents().batchUpdate(documentId=document_id, body={"requests": [
        {"insertText": {"location": {"index": at}, "text": "\n" + INSERT.rstrip("\n")}}]}).execute()

    after = handbook_drive.load({"handbook_doc_id": document_id})
    report(after["text"], "AFTER")
    print(f'\nhash {before["content_hash"][:16]} -> {after["content_hash"][:16]}')
    missing = [s for s in MUST_KEEP if s not in after["text"]]
    if missing:
        sys.exit(f"SECTIONS LOST: {missing}")
    if not all(line.strip() in after["text"] for line in INSERT.strip().splitlines()):
        sys.exit("the insertion did not land as written")
    print("verified: values inserted, every kept section still present")


if __name__ == "__main__":
    main(sys.argv[1], "--apply" in sys.argv)
