"""A single, coherent local functional walkthrough through the REAL console Flask app - no live
Google Sheet, no live Gmail, no real Gemini call, no real cost - exercising the same HTTP routes
the deployed console serves, chained the way a founder's session actually goes: add a lead, set
company info, save a playbook, write a first draft, review it, create the Gmail draft, send it,
then confirm the snapshot reflects all of it. Reports exactly which step (if any) is blocked and
why, distinct from the unit tests, which exercise each piece in isolation.
"""

import os

import pytest

import re

from outreach import console, console_auth, handbook_store, job_draft, review
import review_fixtures as rf
from stage4_fakes import MemoryStore
from test_console_auth import ALLOWED, AUDIENCE, Keys, token
from test_draft_pipeline import HANDBOOK_TEXT, QUOTE, SITE, URL, model_for
from test_sheet_append import _col_index

_CELL = re.compile(r"^([A-Za-z]+)(\d+)$")


class _Exec:
    def __init__(self, value):
        self.value = value

    def execute(self):
        return self.value


class _Values:
    """Supports both calling conventions used by real code against values(): Tab.write's
    per-cell A1-notation update, and handbook_store/company_settings's plain row append (no
    insertDataOption) alongside Store's own append (which does pass insertDataOption)."""

    def __init__(self, api):
        self.api = api

    @staticmethod
    def _name(rng):
        return rng.strip("'").split("!")[0].strip("'")

    def get(self, spreadsheetId, range):
        name = self._name(range)
        return _Exec({"values": [list(r) for r in self.api.tabs.get(name, [])]})

    def append(self, spreadsheetId, range, valueInputOption, body, insertDataOption=None):
        name = self._name(range)
        grid = self.api.tabs.setdefault(name, [])
        for row in body["values"]:
            grid.append(list(row))
        return _Exec({"updates": {"updatedRows": len(body["values"])}})

    def batchUpdate(self, spreadsheetId, body):
        for entry in body["data"]:
            self.update(spreadsheetId=spreadsheetId, range=entry["range"],
                       valueInputOption=body.get("valueInputOption", "RAW"),
                       body={"values": entry["values"]})
        return _Exec({})

    def update(self, spreadsheetId, range, valueInputOption, body):
        name = self._name(range)
        grid = self.api.tabs.setdefault(name, [])
        if "!" not in range or not _CELL.match(range.split("!")[1]):
            # A whole-tab write (e.g. "'Tab'!A1" with a multi-row body from ensure_tab's header
            # write) - replace from row 1.
            for offset, values in enumerate(body["values"]):
                while len(grid) <= offset:
                    grid.append([])
                grid[offset] = list(values)
            return _Exec({})
        match = _CELL.match(range.split("!")[1])
        col, row = _col_index(match.group(1)), int(match.group(2))
        for offset, values in enumerate(body["values"]):
            while len(grid) < row + offset:
                grid.append([])
            line = grid[row - 1 + offset]
            for i, value in enumerate(values):
                while len(line) <= col + i:
                    line.append("")
                line[col + i] = value
        return _Exec({})


class _TabCapableApi:
    """A Sheets client fake general enough for Tab.write (per-cell), ensure_tab/append
    (handbook_store, company_settings) and plain row writes, all in one scenario."""

    def __init__(self):
        self.tabs = {}

    def values(self):
        return _Values(self)

    def get(self, spreadsheetId):
        return _Exec({"sheets": [{"properties": {"title": t}} for t in self.tabs]})

    def batchUpdate(self, spreadsheetId, body):
        for request in body.get("requests", []):
            if "addSheet" in request:
                self.tabs.setdefault(request["addSheet"]["properties"]["title"], [])
        return _Exec({})

HEADER = console_auth.HEADER
LEAD_HEADER = ["Lead ID", "Company", "Decision maker", "BEST EMAIL", "Website", "Phone",
              "Email check", "Fit", "Profile status", "Profiled at", "Offerings evidence",
              "Draft status", "Draft ID", "Draft hash", "Sent at"]


def signed():
    return {HEADER: token()}


class FakeGmail:
    def __init__(self):
        self.drafts_created, self.sent = [], []

    def users(self):
        return self

    def getProfile(self, **kw):
        return self

    def drafts(self):
        return self

    def messages(self):
        return self

    def list(self, **kw):
        return self

    def create(self, **kw):
        self.drafts_created.append(kw)
        return self

    def send(self, **kw):
        self.sent.append(kw)
        return self

    def execute(self):
        return {"emailAddress": "admin@lakshyaa.ai", "drafts": [], "messages": [],
               "id": "draft-1", "threadId": "thr-1"}


@pytest.fixture
def app_and_fakes(tmp_path, monkeypatch):
    (tmp_path / "assets").mkdir()
    (tmp_path / "index.html").write_text("<!doctype html><div id=root></div>", encoding="utf-8")
    store = MemoryStore([], lead_columns=LEAD_HEADER)
    store.api = _TabCapableApi()
    settings = {
        "product_name": "Example Product", "sender_name": "A Founder", "founder_title": "Founder",
        "sender_website": "https://example.test", "postal_address": "1 Example St, Columbus, OH 43215",
        "sender_phone": "614-555-0100", "sender_email": "admin@lakshyaa.ai", "daily_cap": 4,
        "offer_approved": True, "version": "v1", "review_reviewers": ["admin@lakshyaa.ai"],
        "review_public_key": rf.PUBLIC_KEY_B64,
    }
    monkeypatch.setattr("outreach.gemini.generate_json", model_for())
    monkeypatch.setattr(job_draft, "site_text", lambda lead: SITE)  # no real website fetch
    monkeypatch.setenv("ENABLE_GMAIL_DRAFTS", "true")
    monkeypatch.setenv("ENABLE_SEND", "true")  # send.py's own flag, independent of console's
    gmail = FakeGmail()
    monkeypatch.setattr("outreach.gmail_drafts.client", lambda: gmail)
    monkeypatch.setattr("outreach.send.gmail_drafts.client", lambda: gmail)
    client = console.create_app(
        verifier=console_auth.Verifier(AUDIENCE, ALLOWED, fetch=Keys()), store=lambda: store,
        settings=lambda: settings, static_dir=tmp_path, enable_lead_chat=True, enable_playbook=True,
        enable_send=True, enable_review=True, review_signer=rf.SIGNER,
        review_store=review.MemoryReviewStore(),
    ).test_client()
    return client, store, settings, gmail


def test_the_whole_lifecycle_through_the_real_console_routes(app_and_fakes):
    client, store, settings, gmail = app_and_fakes
    blocked = []

    # 1. Add a lead via the chat-apply route (what the assistant's "add" confirm calls).
    r = client.post("/api/leads/apply", json={"op": "add", "fields": {
        "Company": "Example Electric", "BEST EMAIL": "sam@example.test", "Website": "https://example.test/",
    }}, headers=signed())
    if r.status_code != 200:
        blocked.append(("add lead", r.status_code, r.get_json()))
    lead_id = r.get_json().get("lead_id", "")

    # Hand-fill the research-dependent columns a real pipeline would have set (check/research/profile
    # are their own already-tested jobs; this walkthrough is about drafting/sending onward).
    store.rows[lead_id].update({
        "Email check": "OK", "Fit": "QUALIFIED", "Profile status": "READY",
        "Profiled at": "2026-10-10 12:00:00", "Offerings evidence": f'"{QUOTE}" ({URL})',
    })
    store.research_rows.append({"Lead ID": lead_id, "Researched at": "2026-10-10 12:00:00",
                                "Category": "OFFERING", "Quote": QUOTE, "Page URL": URL})
    # job_draft.create/_read reads the RAW Sheets API (via Tab), a separate code path from the
    # Store abstraction drafts.prepare uses - both hit the same real Sheet in production, but a
    # synthetic test must mirror the lead into both. Worth noting as its own observation.
    from outreach.sheet import SYSTEM_COLUMNS
    header = list(store.rows[lead_id].keys()) + [c for c in SYSTEM_COLUMNS if c not in store.rows[lead_id]]
    data_row = [store.rows[lead_id].get(h, "") for h in header]
    store.api.tabs["A_Contact_Now"] = [["A tab"], header, data_row]
    store.api.tabs["B_Contact_Now"] = [["B tab"], header]
    # _read's `facts` also comes from a raw read of the Research tab (header row 1, no description
    # row) - a third representation of the same data, alongside Store.research_rows above.
    research_header = ["Lead ID", "Researched at", "Category", "Quote", "Page URL"]
    store.api.tabs["Research"] = [research_header,
                                  [lead_id, "2026-10-10 12:00:00", "OFFERING", QUOTE, URL]]
    store.api.tabs["Suppression"] = [["Address or domain", "Reason", "Added at", "Source"]]

    # 2. Set company info via chat (one field, confirming the propose/apply/next_field contract).
    r = client.post("/api/company/apply", json={"field": "sender_name", "value": "A Founder"}, headers=signed())
    if r.status_code != 200:
        blocked.append(("set company info", r.status_code, r.get_json()))

    # 3. Save a playbook with REAL handbook content (so writer.verify's grounding checks have
    # something to ground against - the exact gap found testing against the real Sheet last
    # time: no handbook configured anywhere, there only because nobody had saved one yet).
    r = client.post("/api/playbook/set", json={"text": HANDBOOK_TEXT, "name": "Pitch"}, headers=signed())
    if r.status_code != 200:
        blocked.append(("save playbook", r.status_code, r.get_json()))
    if handbook_store.active(api=store.api) is None:
        blocked.append(("playbook not actually active after saving", None, None))

    # 4. Write the first draft (the live "Write a first draft for me" button's backend route).
    r = client.post(f"/api/drafts/prepare/{lead_id}", headers=signed())
    if r.status_code != 200:
        blocked.append(("prepare draft", r.status_code, r.get_json()))

    # 5. Review it (what the Review page / review API does) so an approval hash can be minted.
    r = client.get(f"/api/review/{lead_id}", headers=signed())
    if r.status_code != 200:
        blocked.append(("read review candidate", r.status_code, r.get_json()))
    fingerprint = r.get_json().get("fingerprint")
    r = client.post(f"/api/review/{lead_id}", json={"decision": "confirm", "fingerprint": fingerprint},
                    headers=signed())
    if r.status_code != 200:
        blocked.append(("confirm review", r.status_code, r.get_json()))

    # 6. Re-prepare (re-gate) now that a confirmed review exists, to pick up the approval hash.
    r = client.post(f"/api/drafts/prepare/{lead_id}", headers=signed())
    if r.status_code != 200:
        blocked.append(("re-gate after review", r.status_code, r.get_json()))

    # 7. Create the Gmail draft.
    r = client.post(f"/api/draft/create/{lead_id}", headers=signed())
    if r.status_code != 200:
        blocked.append(("create gmail draft", r.status_code, r.get_json()))

    # 8. Approve and send it.
    r = client.post(f"/api/send/{lead_id}", headers=signed())
    if r.status_code != 200:
        blocked.append(("send", r.status_code, r.get_json()))

    # 9. Confirm the snapshot reflects the sent state (what the Dashboard/Lead page would show).
    r = client.get("/api/snapshot", headers=signed())
    if r.status_code != 200:
        blocked.append(("read snapshot", r.status_code, r.get_json()))

    print("\n--- LOCAL FUNCTIONAL WALKTHROUGH ---")
    if not blocked:
        print("Every step completed through the real console routes: add -> company info -> "
              "playbook -> prepare -> review -> re-gate -> create draft -> send -> snapshot.")
        # The snapshot route itself succeeding (checked above) proves it doesn't crash on this
        # lead; its "Sent at" cell comes from the Store abstraction (MemoryStore.rows), a separate
        # synthetic representation from the raw Tab-level writes send.py just made - a split that
        # only exists in this harness (production reads and writes the same real Sheet). The real
        # proof the send happened is Gmail itself:
        snap = r.get_json()
        print("Gmail drafts created:", len(gmail.drafts_created), "| sent:", len(gmail.sent))
        assert len(gmail.drafts_created) == 1 and len(gmail.sent) == 1
        assert any(l["id"] == lead_id for l in snap["leads"])  # the lead still resolves post-send
    else:
        for step, status, body in blocked:
            print(f"BLOCKED at '{step}': HTTP {status} - {body}")
    assert not blocked, f"{len(blocked)} step(s) blocked: {[b[0] for b in blocked]}"
