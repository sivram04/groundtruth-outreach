"""The active playbook, stored durably so an uploaded or chat-set playbook - not only a fixed Google
Drive doc - can be the live source every draft reads from.

Stored as an append-only ``Playbook`` tab on the leads Sheet: each set appends a row, and the latest
row is the active playbook. This mirrors the other append-only logs (``Reviews``, ``Research``) and
needs no new secret - the console already writes the Sheet with the founder's OAuth.

The returned handbook has the SAME shape the Drive loader returns ({text, content_hash, document_id,
version, name, source}), so every approval hash and candidate fingerprint stays consistent, and a
changed playbook is a new content hash that re-opens approval exactly as a changed Drive doc would.

A saved playbook is live immediately: ``active`` returns the latest stored row whenever one exists,
so the moment the founder saves a playbook it is the source; until then (no row) the Drive doc
remains the source and nothing else changes. ``active`` is only ever consulted by ``job_draft._handbook``
when a caller hands it a Sheets client, so a draft path that holds its own handbook (tests, and
re-gates) never reads the store.
"""

from datetime import datetime, timezone

from outreach import playbook
from outreach.sheet import SHEET_ID, _api, ensure_tab

TAB = "Playbook"
HEADER = ["Set at (UTC)", "Set by", "Source", "Name", "Content hash", "Text"]
MIN_CHARS = 200
MAX_CHARS = 60_000


def _rows(api, sheet_id=SHEET_ID):
    try:
        return (api.values().get(spreadsheetId=sheet_id, range=f"'{TAB}'")
                .execute().get("values", []))
    except Exception:
        return []


def active(*, api=None, sheet_id=SHEET_ID):
    """The active stored playbook as a handbook dict, or None.

    None when the tab is absent or empty, its header is not exactly the schema, or the latest row's
    text is too short to be a playbook. A None result means the Drive handbook stays the source.
    """
    values = _rows(api or _api(), sheet_id)
    if len(values) < 2 or values[0] != HEADER:
        return None
    row = dict(zip(HEADER, values[-1]))  # append order is the authority; the latest row is active
    text = playbook.normalize(row.get("Text", ""))
    if len(text) < MIN_CHARS:
        return None
    content_hash = (row.get("Content hash") or "").strip() or playbook.content_hash(text)
    return {"document_id": "playbook:" + content_hash[:12],
            "name": (row.get("Name") or "").strip() or "Playbook",
            "text": text, "content_hash": content_hash,
            "modified": (row.get("Set at (UTC)") or "").strip(),
            "version": content_hash[:12], "source": "stored"}


def set_active(text, *, set_by, name="", source="upload", api=None, now=None, sheet_id=SHEET_ID):
    """Append a new active playbook row from the founder's own text. Returns its content hash.

    The text is the founder's product/outreach guidance (uploaded or typed); it is stored verbatim
    (normalised) and never treated as instructions. Raises ValueError if it is too short or too long.
    """
    text = playbook.normalize(text)
    if not (MIN_CHARS <= len(text) <= MAX_CHARS):
        raise ValueError(f"a playbook must be between {MIN_CHARS} and {MAX_CHARS} characters "
                         f"(got {len(text)})")
    if not (set_by or "").strip():
        raise ValueError("a playbook change must name who set it")
    api = api or _api()
    ensure_tab(api, TAB, HEADER, sheet_id)
    content_hash = playbook.content_hash(text)
    stamp = (now or datetime.now(timezone.utc)).isoformat()
    api.values().append(
        spreadsheetId=sheet_id, range=f"'{TAB}'!A1", valueInputOption="RAW",
        body={"values": [[stamp, set_by, source, name, content_hash, text]]}).execute()
    return content_hash
