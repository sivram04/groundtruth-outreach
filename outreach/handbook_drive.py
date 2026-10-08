"""Read-only loader for the founder's handbook in Google Drive.

The Drive document is the only production source of writing guidance. It is never cached to
disk and never silently replaced by a local file: if it cannot be read, drafting stops.

Every preview and draft records the document's content hash, so a handbook edited after the
founder approved a preview invalidates that approval (the hash no longer matches).

Reading needs the `drive.readonly` scope, which the current sign-in does not hold. Until the
founder adds it, `load` raises HandbookUnavailable and previews are blocked. That is the
intended fail-closed behaviour, not an error to work around.
"""

import hashlib
import os
import re

from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from outreach.google_auth import founder_credentials

SCOPE = "https://www.googleapis.com/auth/drive.readonly"
GOOGLE_DOC = "application/vnd.google-apps.document"
# A handbook must be text. A spreadsheet, slide deck or PDF is a configuration mistake.
EXPORTABLE = {GOOGLE_DOC: "text/plain"}
PLAIN = {"text/plain", "text/markdown", "text/x-markdown"}
MAX_CHARS = 60_000
MIN_CHARS = 200


class HandbookUnavailable(RuntimeError):
    """The production handbook could not be read. Drafting must stop, not fall back."""


def document_id(settings=None, *, override=None):
    """The Drive document ID to load. With `override` (a project's own handbook) that id is used,
    validated the same way; otherwise the environment first, then settings. No default."""
    if override is not None:
        value = str(override).strip()
    else:
        value = (os.environ.get("HANDBOOK_DOC_ID") or (settings or {}).get("handbook_doc_id") or "").strip()
    if not value:
        raise HandbookUnavailable("no handbook document ID is configured")
    if not re.fullmatch(r"[A-Za-z0-9_-]{10,}", value):
        raise HandbookUnavailable("the configured handbook document ID is not a Drive file ID")
    return value


def client():
    return build("drive", "v3", credentials=founder_credentials(), cache_discovery=False)


def load(settings=None, *, drive=None, doc_id=None):
    """Return the handbook's text and identity. With `doc_id` that specific document is loaded (a
    project's own handbook); otherwise the configured one. Raises HandbookUnavailable on any doubt."""
    file_id = document_id(settings, override=doc_id)
    drive = drive or client()
    try:
        meta = drive.files().get(fileId=file_id, fields="id,name,mimeType,modifiedTime,version").execute()
        mime = meta.get("mimeType", "")
        if mime in EXPORTABLE:
            raw = drive.files().export(fileId=file_id, mimeType=EXPORTABLE[mime]).execute()
        elif mime in PLAIN:
            raw = drive.files().get_media(fileId=file_id).execute()
        else:
            raise HandbookUnavailable(f"the handbook must be a Google Doc or text file, not {mime}")
    except HttpError as exc:
        status = getattr(exc.resp, "status", "?")
        if status == 403:
            raise HandbookUnavailable(
                "Drive refused the read; the sign-in may lack the drive.readonly scope") from exc
        if status == 404:
            raise HandbookUnavailable("the handbook document was not found or is not shared") from exc
        raise HandbookUnavailable(f"Drive returned HTTP {status}") from exc

    data = raw if isinstance(raw, bytes) else str(raw).encode("utf-8")
    content_hash = hashlib.sha256(data).hexdigest()
    text = data.decode("utf-8", errors="replace").replace("\r\n", "\n").replace("﻿", "").strip()
    if len(text) < MIN_CHARS:
        raise HandbookUnavailable("the handbook document is empty or too short to be the real one")
    if len(text) > MAX_CHARS:
        raise HandbookUnavailable("the handbook document is larger than this pilot accepts")
    return {"document_id": meta["id"], "name": meta.get("name", ""), "text": text,
            "content_hash": content_hash, "modified": meta.get("modifiedTime", ""),
            "version": str(meta.get("version", "")), "source": "drive"}
