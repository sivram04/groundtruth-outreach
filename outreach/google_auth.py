"""Credentials for the founder's Gmail and Sheets.

On Cloud Run the token arrives as the GOOGLE_SIGNIN_TOKEN environment variable, mounted from
Secret Manager. Locally it is read from Secret Manager through gcloud. Never from disk.
"""

import json
import os
import shutil
import subprocess

from google.oauth2.credentials import Credentials

PROJECT = "lakshyaa-outreach"
SECRET = "google-signin-token"


def _read_secret() -> dict:
    mounted = os.environ.get("GOOGLE_SIGNIN_TOKEN")
    if mounted:
        return json.loads(mounted)
    exe = shutil.which("gcloud") or shutil.which("gcloud.cmd")
    out = subprocess.run(
        [exe, "secrets", "versions", "access", "latest", f"--secret={SECRET}", f"--project={PROJECT}"],
        capture_output=True, text=True, check=True,
    )
    return json.loads(out.stdout)


def founder_credentials() -> Credentials:
    s = _read_secret()
    return Credentials(
        token=None,
        refresh_token=s["refresh_token"],
        client_id=s["client_id"],
        client_secret=s["client_secret"],
        token_uri="https://oauth2.googleapis.com/token",
        scopes=s["scopes"],
    )
