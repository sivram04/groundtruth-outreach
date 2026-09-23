"""One-time Google sign-in for the outreach worker.

Opens a browser, the founder signs in as the sending account, and the resulting
long-lived token goes straight into Secret Manager. Nothing is written to disk.

    python -m outreach.signin
"""

import json
import shutil
import subprocess
import sys
from pathlib import Path

from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

PROJECT = "lakshyaa-outreach"
ACCOUNT = "admin@lakshyaa.ai"
SECRET = "google-signin-token"
CLIENT_FILE = Path(__file__).resolve().parent.parent / ".secrets" / "client_secret.json"

# gmail.compose creates drafts. It also permits sending; this codebase never sends.
# drive.readonly is read-only by definition: it lets the worker read the founder's handbook
# document and nothing else. Added 2026-09-23 when that handbook was created.
SCOPES = [
    "https://www.googleapis.com/auth/gmail.compose",
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive.readonly",
]


def gcloud(*args, stdin=None):
    exe = shutil.which("gcloud") or shutil.which("gcloud.cmd")
    return subprocess.run(
        [exe, *args, f"--project={PROJECT}"],
        input=stdin, capture_output=True, text=True,
    )


def main():
    if not CLIENT_FILE.exists():
        sys.exit(f"Missing {CLIENT_FILE}")

    flow = InstalledAppFlow.from_client_secrets_file(str(CLIENT_FILE), SCOPES)
    creds = flow.run_local_server(
        port=0, access_type="offline", prompt="consent", login_hint=ACCOUNT,
        authorization_prompt_message="Opening the browser. If it does not open, visit:\n{url}\n",
        success_message="Signed in. You can close this tab.",
    )
    if not creds.refresh_token:
        sys.exit("Google returned no long-lived token; nothing stored.")

    email = build("gmail", "v1", credentials=creds).users().getProfile(userId="me").execute()["emailAddress"]
    if email.lower() != ACCOUNT:
        sys.exit(f"Signed in as {email}, expected {ACCOUNT}. Nothing stored.")

    client = json.loads(CLIENT_FILE.read_text())["installed"]
    payload = json.dumps({
        "account": email,
        "client_id": client["client_id"],
        "client_secret": client["client_secret"],
        "refresh_token": creds.refresh_token,
        "scopes": SCOPES,
    })

    if gcloud("secrets", "describe", SECRET).returncode != 0:
        made = gcloud("secrets", "create", SECRET, "--replication-policy=automatic")
        if made.returncode != 0:
            sys.exit(made.stderr)
    added = gcloud("secrets", "versions", "add", SECRET, "--data-file=-", stdin=payload)
    if added.returncode != 0:
        sys.exit(added.stderr)

    print(f"Signed in as {email}. Token stored in Secret Manager as '{SECRET}'.")


if __name__ == "__main__":
    main()
