"""Offline stand-ins for Gmail and the Sheet, for the stage 4 tests. Nothing here touches Google."""

import base64
import copy
import re
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import httplib2
from googleapiclient.errors import HttpError

SENDER = "admin@lakshyaa.ai"


def at(text):
    """'2026-09-22 13:18' on a New York clock -> an aware datetime."""
    return datetime.strptime(text, "%Y-%m-%d %H:%M").replace(
        tzinfo=ZoneInfo("America/New_York")).astimezone(timezone.utc)


def b64(text):
    return base64.urlsafe_b64encode(text.encode()).decode().rstrip("=")


def message(message_id, *, thread, when, sender, to, subject="A question", labels=("INBOX",),
            body="", html=None, headers=(), parts=None):
    head = [{"name": "From", "value": sender}, {"name": "To", "value": to},
            {"name": "Subject", "value": subject},
            {"name": "Message-ID", "value": f"<{message_id}@mail.test>"}]
    head += [{"name": name, "value": value} for name, value in headers]
    if parts is not None:
        payload = {"mimeType": "multipart/report", "headers": head, "body": {}, "parts": parts}
    elif html is not None:
        payload = {"mimeType": "multipart/alternative", "headers": head, "body": {},
                   "parts": [{"mimeType": "text/html", "body": {"data": b64(html)}}]}
    else:
        payload = {"mimeType": "text/plain", "headers": head, "body": {"data": b64(body)}}
    return {"id": message_id, "threadId": thread, "labelIds": list(labels),
            "internalDate": str(int(when.timestamp() * 1000)), "payload": payload}


def sent(message_id, *, thread, when, to, subject="A question", headers=()):
    return message(message_id, thread=thread, when=when, sender=f"Admin Lakshyaa <{SENDER}>",
                   to=to, subject=subject, labels=("SENT",), headers=headers)


def bounce_notice(message_id, *, thread, when, failed, status="5.1.1",
                  subject="Delivery Status Notification (Failure)"):
    report = (f"Reporting-MTA: dns; googlemail.com\n\nFinal-Recipient: rfc822; {failed}\n"
              f"Action: failed\nStatus: {status}\n")
    parts = [{"mimeType": "text/plain",
              "body": {"data": b64(f"Your message wasn't delivered to {failed}.")}},
             {"mimeType": "message/delivery-status", "body": {"data": b64(report)}}]
    return message(message_id, thread=thread, when=when,
                   sender="Mail Delivery Subsystem <mailer-daemon@googlemail.com>", to=SENDER,
                   subject=subject, headers=[("X-Failed-Recipients", failed)], parts=parts)


def not_found():
    return HttpError(httplib2.Response({"status": "404"}), b"not found")


class Call:
    def __init__(self, run):
        self.run = run

    def execute(self):
        return self.run()


class FakeGmail:
    """The parts of the Gmail API the stage 4 code uses. `box` holds messages, `draft_box` drafts."""

    def __init__(self, messages=(), drafts=None, address=SENDER):
        self.box = {m["id"]: m for m in messages}
        self.draft_box = dict(drafts or {})
        self.address = address
        self.created, self.full_reads, self.queries, self.spam_and_trash = [], [], [], []
        self.fail_create = None

    def users(self):
        return self

    def getProfile(self, userId):
        return Call(lambda: {"emailAddress": self.address})

    def messages(self):
        return _Messages(self)

    def threads(self):
        return _Threads(self)

    def drafts(self):
        return _Drafts(self)


class _Messages:
    def __init__(self, gmail):
        self.gmail = gmail

    def list(self, userId, q, maxResults=100, includeSpamTrash=False, pageToken=None):
        self.gmail.queries.append(q)
        self.gmail.spam_and_trash.append(includeSpamTrash)
        after = int(re.search(r"after:(\d+)", q).group(1))
        ids = [m["id"] for m in self.gmail.box.values() if int(m["internalDate"]) // 1000 > after]
        return Call(lambda: {"messages": [{"id": i} for i in ids]} if ids else {})

    def get(self, userId, id, format="full", metadataHeaders=None):
        def run():
            if id not in self.gmail.box:
                raise not_found()
            found = copy.deepcopy(self.gmail.box[id])
            if format == "metadata":
                found["payload"] = {"headers": found["payload"]["headers"],
                                    "mimeType": found["payload"].get("mimeType")}
            else:
                self.gmail.full_reads.append(id)
            return found
        return Call(run)


class _Threads:
    def __init__(self, gmail):
        self.gmail = gmail

    def get(self, userId, id, format="full", metadataHeaders=None):
        def run():
            found = sorted((m for m in self.gmail.box.values() if m["threadId"] == id),
                           key=lambda m: int(m["internalDate"]))
            if not found:
                raise not_found()
            out = []
            for item in found:
                item = copy.deepcopy(item)
                item["payload"] = {"headers": item["payload"]["headers"]}
                out.append(item)
            return {"id": id, "messages": out}
        return Call(run)


class _Drafts:
    def __init__(self, gmail):
        self.gmail = gmail

    def list(self, userId, maxResults=100, pageToken=None, q=None):
        return Call(lambda: {"drafts": [
            {"id": draft_id, "message": {"id": d["message"]["id"],
                                         "threadId": d["message"].get("threadId", "")}}
            for draft_id, d in self.gmail.draft_box.items()]})

    def get(self, userId, id, format="full"):
        def run():
            if id not in self.gmail.draft_box:
                raise not_found()
            return copy.deepcopy(self.gmail.draft_box[id])
        return Call(run)

    def create(self, userId, body):
        def run():
            self.gmail.created.append(copy.deepcopy(body["message"]))
            if self.gmail.fail_create:
                raise self.gmail.fail_create
            number = len(self.gmail.created)
            draft_id = f"draft-{number}"
            thread = body["message"].get("threadId") or f"thread-new-{number}"
            self.gmail.draft_box[draft_id] = {"id": draft_id, "message": {
                "id": f"m-{draft_id}", "threadId": thread, "raw": body["message"]["raw"]}}
            return {"id": draft_id, "message": {"id": f"m-{draft_id}", "threadId": thread}}
        return Call(run)


def parsed(created):
    """The email a draft request carries, parsed: headers and text."""
    from email import policy
    from email.parser import BytesParser
    data = created["raw"]
    return BytesParser(policy=policy.default).parsebytes(
        base64.urlsafe_b64decode(data + "=" * (-len(data) % 4)))


class MemoryTab:
    """One lead row of the in-memory Sheet, with the Tab methods the follow-up job calls."""

    def __init__(self, store, lead_id):
        self.store, self.lead_id = store, lead_id

    def ensure_columns(self, names):
        self.store.columns_added.append(list(names))

    def write(self, updates):
        (_, cells), = updates.items()
        if self.store.refuse_writes:
            return {"written": 0, "skipped": [(3, "changed")]}
        self.store.rows[self.lead_id].update(cells)
        self.store.lead_writes.append((self.lead_id, dict(cells)))
        return {"written": 1, "skipped": []}


class MemoryStore:
    """The Sheet as `outreach.sheet.Store` presents it, held in memory."""

    def __init__(self, rows, events=(), suppression=(), runs=()):
        self.rows = {row["Lead ID"]: dict(row) for row in rows}
        self.event_rows = [dict(e) for e in events]
        self.entries = None if suppression is None else [dict(s) for s in suppression]
        self.runs = [dict(r) for r in runs]
        self.lead_writes, self.columns_added = [], []
        self.refuse_writes = False

    def leads(self):
        return {lead_id: dict(row) for lead_id, row in self.rows.items()}

    def events(self):
        return [dict(e) for e in self.event_rows]

    def suppression(self):
        return None if self.entries is None else [dict(e) for e in self.entries]

    def run_rows(self):
        return [dict(r) for r in self.runs]

    def last_cursor(self):
        from outreach.sheet import CURSOR
        for row in reversed(self.runs):
            if row.get("Job") == "sync" and row.get("Result") in ("OK", "PARTIAL"):
                found = CURSOR.search(row.get("Detail", ""))
                if found:
                    return datetime.fromisoformat(found.group(1).replace("Z", "+00:00"))
        return None

    def append_events(self, events):
        self.event_rows += [dict(e) for e in events]

    def append_suppression(self, entries):
        self.entries = (self.entries or []) + [dict(e) for e in entries]

    def write_leads(self, updates, columns):
        for lead_id, cells in updates.items():
            self.rows[lead_id].update(cells)
            self.lead_writes.append((lead_id, dict(cells)))
        return len(updates), []

    def fresh_lead(self, lead_id):
        return MemoryTab(self, lead_id), 3, dict(self.rows[lead_id])

    def run_row(self, job, where, result, detail):
        self.runs.append({"Job": job, "Where": where, "Result": result, "Detail": detail})


def lead(lead_id="A-0001", **changes):
    row = {"Lead ID": lead_id, "Company": "Example Electric", "BEST EMAIL": "sam@example-electric.test",
           "Their email": "sam@example-electric.test", "Decision maker": "Sam Rivers",
           "Website": "https://example-electric.test/", "Emails we already had": "",
           "Email check": "OK", "Fit": "QUALIFIED", "Sent by hand": ""}
    row.update(changes)
    return row
