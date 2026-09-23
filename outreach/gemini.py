"""Gemini on Vertex AI, in the outreach project. JSON in, JSON out."""

import json
import shutil
import subprocess
import time

import google.auth
import google.auth.transport.requests
import requests

PROJECT = "lakshyaa-outreach"
MODEL = "gemini-2.5-flash"  # GA; confirmed callable in this project 2026-09-22
URL = (f"https://aiplatform.googleapis.com/v1/projects/{PROJECT}/locations/global/"
       f"publishers/google/models/{MODEL}:generateContent")


def _token():
    try:
        creds, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
        creds.refresh(google.auth.transport.requests.Request())
        return creds.token
    except Exception:
        # Local runs without application-default credentials use the gcloud sign-in.
        exe = shutil.which("gcloud") or shutil.which("gcloud.cmd")
        if not exe:
            raise RuntimeError("no Google credentials: neither application-default nor gcloud")
        return subprocess.run([exe, "auth", "print-access-token"], capture_output=True,
                              text=True, check=True).stdout.strip()


def generate_json(prompt, schema, attempts=3):
    """Returns (parsed_json, usage). Raises after `attempts` failures."""
    body = {
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0, "responseMimeType": "application/json",
                             "responseSchema": schema},
    }
    last = None
    for attempt in range(attempts):
        if attempt:
            time.sleep(2 ** attempt)  # back off; bursts of previews can be rate limited
        try:
            r = requests.post(URL, json=body, timeout=120, headers={"Authorization": f"Bearer {_token()}"})
            r.raise_for_status()
            data = r.json()
            text = "".join(p.get("text", "") for p in data["candidates"][0]["content"]["parts"])
            return json.loads(text), data.get("usageMetadata", {})
        except (requests.RequestException, KeyError, IndexError, ValueError) as e:
            last = e
    raise RuntimeError(f"Gemini failed: {last}")
