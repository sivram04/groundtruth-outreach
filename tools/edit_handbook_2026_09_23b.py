"""One-off, founder-instructed (2026-09-23): two edits to the handbook Doc.

1. Remove the "I'd like to invite you to ..." sentence from the INITIAL email template only,
   so each email makes one ask, in its closing question. Both follow-ups stay as they are.
2. Add a writing rule preferring a concrete, verified activity over a market list or a
   self-promotional phrase.

The worker's stored credentials stay read-only for Drive. This tool asks for its own one-time
Google Docs sign-in, held in memory for this run and never written to disk or Secret Manager.
It reads before and after, and refuses to leave the document short of any kept section.

    python -m tools.edit_handbook_2026_09_23b <document_id>            # read-only check
    python -m tools.edit_handbook_2026_09_23b <document_id> --apply
"""

import re
import sys
from pathlib import Path

from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

from outreach import handbook_drive

CLIENT_FILE = Path(__file__).resolve().parent.parent / ".secrets" / "client_secret.json"
EDIT_SCOPE = "https://www.googleapis.com/auth/documents"
ACCOUNT = "admin@lakshyaa.ai"

# The sentence to remove, with either apostrophe. It appears only in the initial email:
# follow-up 1 says "If you choose to ...", follow-up 2 "If you'd like to ...".
REMOVE = re.compile(r"\s*I[’']d like to invite you to \[NEXT_WEEK_ACTION\] and hear where this "
                    r"direction does or doesn[’']t fit the way your team works\.")
RULE_AFTER = "5."  # the paragraph the new rule follows
RULE = ("6. Prefer a concrete, verified activity the company performs over a list of the markets "
        "it serves or a self-promotional phrase such as “first-class” or “oldest "
        "and finest.” Say what they do, not how they describe themselves.")
MUST_KEEP = ["Writing rules", "Fields to fill before using the templates", "Initial email",
             "Follow-up 1", "Follow-up 2", "no thanks", "Draft offer values for founder review",
             "[INTENDED_USE]", "[NEXT_WEEK_ACTION]", "[CTA_QUESTION]",
             "If you choose to [NEXT_WEEK_ACTION]"]


def runs(doc):
    """(doc_index, character) for every character of text, in order."""
    mapped = []
    for element in doc.get("body", {}).get("content", []):
        for run in element.get("paragraph", {}).get("elements", []):
            start = run.get("startIndex")
            for offset, char in enumerate(run.get("textRun", {}).get("content", "")):
                mapped.append((start + offset, char))
    return mapped


def paragraphs(doc):
    out = []
    for element in doc.get("body", {}).get("content", []):
        para = element.get("paragraph")
        if not para:
            continue
        text = "".join(r.get("textRun", {}).get("content", "") for r in para.get("elements", []))
        out.append((element["startIndex"], element["endIndex"], text))
    return out


def sign_in():
    flow = InstalledAppFlow.from_client_secrets_file(str(CLIENT_FILE), [EDIT_SCOPE])
    creds = flow.run_local_server(
        port=0, prompt="consent", login_hint=ACCOUNT,
        authorization_prompt_message="Opening the browser to authorise these edits:\n{url}\n",
        success_message="Authorised. You can close this tab.")
    return build("docs", "v1", credentials=creds, cache_discovery=False)


def report(text, label):
    print(f"\n{label}: {len(text)} characters")
    for section in MUST_KEEP:
        print(f"  {'present' if section in text else 'MISSING'}: {section}")
    print(f"  {'present' if REMOVE.search(text) else 'gone   '}: the invite sentence")
    print(f"  {'present' if RULE[:40] in text else 'absent '}: the new rule")


def main(document_id, apply):
    before = handbook_drive.load({"handbook_doc_id": document_id})
    print(f'Document "{before["name"]}" hash {before["content_hash"][:16]}')
    report(before["text"], "BEFORE")
    if not apply:
        print("\nread-only check: nothing written")
        return

    docs = sign_in()
    doc = docs.documents().get(documentId=document_id).execute()

    mapped = runs(doc)
    joined = "".join(char for _, char in mapped)
    hits = list(REMOVE.finditer(joined))
    if len(hits) != 1:
        sys.exit(f"expected the invite sentence exactly once, found {len(hits)}")
    start, end = mapped[hits[0].start()][0], mapped[hits[0].end() - 1][0] + 1
    docs.documents().batchUpdate(documentId=document_id, body={"requests": [
        {"deleteContentRange": {"range": {"startIndex": start, "endIndex": end}}}]}).execute()

    doc = docs.documents().get(documentId=document_id).execute()
    anchors = [p for p in paragraphs(doc) if p[2].strip().startswith(RULE_AFTER)]
    if len(anchors) != 1:
        sys.exit(f"expected one paragraph starting {RULE_AFTER!r}, found {len(anchors)}")
    docs.documents().batchUpdate(documentId=document_id, body={"requests": [
        {"insertText": {"location": {"index": anchors[0][1] - 1}, "text": "\n" + RULE}}]}).execute()

    after = handbook_drive.load({"handbook_doc_id": document_id})
    report(after["text"], "AFTER")
    print(f'\nhash {before["content_hash"][:16]} -> {after["content_hash"][:16]}')
    missing = [s for s in MUST_KEEP if s not in after["text"]]
    if missing:
        sys.exit(f"SECTIONS LOST: {missing}")
    if REMOVE.search(after["text"]):
        sys.exit("the invite sentence is still present")
    if RULE[:40] not in after["text"]:
        sys.exit("the new rule did not land")
    print("verified: one ask per email, new rule added, follow-ups and sections intact")


if __name__ == "__main__":
    main(sys.argv[1], "--apply" in sys.argv)
