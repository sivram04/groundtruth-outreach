"""Gmail draft-only boundary. No message-send operation belongs in this module."""

import base64
from email import policy
from email.message import EmailMessage
from email.parser import BytesParser

from googleapiclient.discovery import build

from outreach.google_auth import founder_credentials

ACTION_HEADER = "X-Lakshyaa-Draft-Action"


def client():
    return build("gmail", "v1", credentials=founder_credentials(), cache_discovery=False)


def _message(raw):
    data = base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4))
    return BytesParser(policy=policy.default).parsebytes(data)


def existing_drafts(gmail, recipient):
    """Conservative: any draft addressed to the recipient blocks a new pilot draft."""
    found, page = [], None
    while True:
        args = {"userId": "me", "q": f"to:{recipient}", "maxResults": 500}
        if page:
            args["pageToken"] = page
        result = gmail.users().drafts().list(**args).execute()
        found.extend(result.get("drafts", []))
        page = result.get("nextPageToken")
        if not page:
            return found


def prior_sends(gmail, recipient):
    result = gmail.users().messages().list(
        userId="me", q=f"in:sent to:{recipient}", maxResults=1).execute()
    return bool(result.get("messages"))


def drafts_for_action(gmail, action_id):
    """Reconcile an uncertain create by inspecting draft MIME headers.

    Search is a read. Never create again for an existing RESERVED action, even when
    this search returns nothing: Gmail or Sheets may have been eventually consistent.
    """
    found, page = [], None
    while True:
        args = {"userId": "me", "maxResults": 500}
        if page:
            args["pageToken"] = page
        result = gmail.users().drafts().list(**args).execute()
        for item in result.get("drafts", []):
            draft = gmail.users().drafts().get(
                userId="me", id=item["id"], format="raw").execute()
            raw = draft.get("message", {}).get("raw", "")
            if raw and _message(raw).get(ACTION_HEADER) == action_id:
                found.append(draft)
        page = result.get("nextPageToken")
        if not page:
            return found


def create(gmail, *, to, from_address, subject, body, action_id, thread_id=None,
           in_reply_to=None, references=None):
    """Create one draft. With `thread_id` it is an answer inside that thread: Gmail files it
    there when the thread id, the In-Reply-To and References headers and the subject agree."""
    message = EmailMessage()
    message["To"] = to
    message["From"] = from_address
    message["Subject"] = subject
    if in_reply_to:
        message["In-Reply-To"] = in_reply_to
    if references:
        message["References"] = references
    message[ACTION_HEADER] = action_id
    message.set_content(body)
    raw = base64.urlsafe_b64encode(message.as_bytes()).decode().rstrip("=")
    draft = {"raw": raw}
    if thread_id:
        draft["threadId"] = thread_id
    return gmail.users().drafts().create(userId="me", body={"message": draft}).execute()
