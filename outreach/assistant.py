"""The console's assistant: it answers questions about the founder's own outreach, and only
from what the Sheet says.

It reads. It cannot send, draft, approve or change anything, and it is never given a way to:
the only thing it is handed is a summary of the console's own data (`facts`), and the only
thing it may return is a short answer, the leads it is about, and a link to a page this app
already has.

Nothing it writes is trusted on its own. Before an answer is shown:
  - every run of digits in it must already appear in the facts, so it cannot invent a count,
    an amount or a date;
  - every email address in it must be one the facts carry;
  - every lead it names must exist, and any link must be a page of this app.
An answer that fails a check is not shown; the question is refused and the reason is logged.
"""

import json
import re
import time
from collections import deque

from outreach import gemini

MAX_QUESTION = 400  # characters; longer is refused unread
MAX_ANSWER = 600
MAX_LEADS = 120  # leads described to the model; the rest are counted, never hidden
MAX_NEEDS = 25
# A per-process bound on how often the model is called at all, so a stuck page or a mistake
# cannot run up the bill. This system's choice, not a founder decision.
MAX_QUESTIONS_AN_HOUR = 60

DIGITS = re.compile(r"\d+")
EMAIL = re.compile(r"[^\s@<>,;:\"']+@[^\s@<>,;:\"'.]+\.[^\s@<>,;:\"']+")
PAGES = ("dashboard", "drafts", "leads", "lead", "sources")
# The Leads page's own filters (console/src/filters.ts). A test holds the two lists equal.
SHOWS = ("all", "needs", "ready", "emailed", "not-emailed", "replied", "stopped", "bounced", "check")

SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "answer": {"type": "STRING"},
        "lead_ids": {"type": "ARRAY", "items": {"type": "STRING"}},
        "link": {
            "type": "OBJECT",
            "properties": {
                "page": {"type": "STRING", "enum": list(PAGES)},
                "lead_id": {"type": "STRING"},
                "show": {"type": "STRING"},
                "label": {"type": "STRING"},
            },
            "required": ["page", "label"],
        },
    },
    "required": ["answer"],
}

PROMPT = """You are the assistant inside a founder's own cold-email console. You answer their
questions about their outreach.

WHAT YOU MAY DO
- Answer from FACTS below, and from nothing else.
- Point to a page of this console when the founder would see more there.

WHAT YOU CANNOT DO
- You cannot send an email, write or change a draft, approve anything, or change the Sheet.
  If asked, say plainly that you only read, and say where in the console they can do it
  themselves (drafts are on the Drafts page; sending comes in a later version).
- You cannot look anything up outside FACTS: no company research, no web, no guessing.

HOW TO ANSWER
- Every number, date, company, name and address you write must already appear in FACTS,
  exactly. Never work out a new number, a total, a rate or an average that FACTS does not
  state. If FACTS does not answer the question, say what you cannot see instead.
- At most three sentences. Plain words, no jargon, no bullet points, no markdown.
- Speak to the founder as "you". Never invent an apology or a promise.
- Set lead_ids to the leads your answer is about, if any, using their Lead IDs from FACTS.
- Set link only to a page that helps: {"page": "drafts", "label": "Open the drafts"},
  {"page": "lead", "lead_id": "A-0007", "label": "Open Lakeside Concrete"},
  {"page": "leads", "show": "needs", "label": "See what needs you"}, or "dashboard" or
  "sources". The show values are: all, needs, ready, emailed, not-emailed, replied, stopped,
  bounced, check. Leave link out when no page is better than the answer itself.

FACTS
{facts}

THE FOUNDER ASKS
{question}
"""


class Refused(Exception):
    """The question was not answered. `said` is what the founder is told; `why` is for the log."""

    def __init__(self, said, why=None):
        super().__init__(said)
        self.said = said
        self.why = why or said


def facts(data):
    """What the model is given: the console's own data, cut down and flattened.

    Only what is on the founder's own pages, and never the drafting settings' postal address or
    phone, which the console itself does not carry."""
    leads = [lead for lead in data.get("leads", [])
             if lead.get("status") or lead.get("ready") or lead.get("draft")]
    shown, left_out = leads[:MAX_LEADS], max(0, len(leads) - MAX_LEADS)
    drafts = data.get("drafts", [])
    return {
        "today": data.get("today_text", ""),
        "read_at": data.get("read_at", ""),
        "counts_by_tier": [
            {key: tier[key] for key in ("label", "leads", "ready", "drafted", "emailed",
                                        "emails_sent", "replied", "reply_rate", "opted_out",
                                        "bounced", "review_needed", "tracked", "opened",
                                        "open_rate", "clicked", "click_rate")
             if key in tier}
            for tier in data.get("tiers", [])],
        "drafts_by_status": data.get("drafts_summary", {}),
        "needs_you": [{"lead_id": item["lead_id"], "what": item["label"], "detail": item["text"]}
                      for item in data.get("needs_you", [])[:MAX_NEEDS]],
        "follow_ups_coming_up": [{"lead_id": item["lead_id"], "day": item["day"],
                                  "detail": item["text"]}
                                 for item in data.get("coming_up", [])],
        "drafts": [{"lead_id": draft["lead_id"], "company": draft["company"], "to": draft["to"],
                    "status": draft["status_label"], "subject": draft["subject"],
                    "waiting_for": draft["why"], "opening_quote": draft["quote"]}
                   for draft in drafts],
        "leads": [{"lead_id": lead["id"], "company": lead["company"], "contact": lead["contact"],
                   "email": lead["email"], "where_it_stands": lead["status_label"],
                   "next": lead["action"], "email_check": lead["email_check"], "fit": lead["fit"],
                   "ready_for_a_first_draft": lead["ready"], "why_not_ready": lead["blockers"],
                   "draft": lead["draft"], "first_sent": lead["cells"].get("Sent at", ""),
                   "replied_at": lead["cells"].get("Replied at", "")}
                  for lead in shown],
        "leads_left_out_of_this_list": left_out,
        "leads_never_touched": len(data.get("leads", [])) - len(leads),
        "what_drafting_waits_for": data.get("approvals"),
        "last_mailbox_sync": data.get("sync"),
        "nothing_here_can_send": True,
    }


def _runs(text):
    return set(DIGITS.findall(text))


def _checked(said, data, known):
    """The model's answer, checked against the facts, or Refused."""
    answer = " ".join(str(said.get("answer", "")).split())
    if not answer:
        raise Refused("I could not answer that.", "the model returned no answer")
    if len(answer) > MAX_ANSWER:
        raise Refused("I could not answer that briefly enough.", "answer too long")
    allowed = _runs(json.dumps(data, default=str))
    invented = sorted(_runs(answer) - allowed)
    if invented:
        raise Refused("I could not answer that from your Sheet without working out a figure "
                      "nobody recorded, so I have not answered.",
                      f"numbers not in the facts: {', '.join(invented)}")
    # An address at the end of a sentence keeps its full stop; compare without the punctuation.
    def bare(address):
        return address.lower().rstrip(".,;:!?)\"'")

    addresses = {bare(address) for address in EMAIL.findall(json.dumps(data, default=str))}
    strangers = sorted({bare(a) for a in EMAIL.findall(answer) if bare(a) not in addresses})
    if strangers:
        raise Refused("I could not answer that without naming an address your Sheet does not "
                      "have, so I have not answered.", f"addresses not in the facts: {strangers}")

    lead_ids = [str(lead_id) for lead_id in (said.get("lead_ids") or []) if str(lead_id) in known]
    link = said.get("link") or None
    if link:
        page = str(link.get("page", ""))
        label = " ".join(str(link.get("label", "")).split())[:60]
        lead_id = str(link.get("lead_id", ""))
        show = str(link.get("show", ""))
        if page not in PAGES or not label:
            link = None
        elif page == "lead" and lead_id not in known:
            link = None
        else:
            link = {"page": page, "label": label,
                    "lead_id": lead_id if page == "lead" else "",
                    "show": show if page == "leads" and show in SHOWS else ""}
    return {"answer": answer, "lead_ids": lead_ids[:12], "link": link}


class Limit:
    """How many questions this process may put to the model in an hour."""

    def __init__(self, most=MAX_QUESTIONS_AN_HOUR, clock=time.monotonic):
        self.most, self.clock, self.asked = most, clock, deque()

    def take(self):
        now = self.clock()
        while self.asked and now - self.asked[0] > 3600:
            self.asked.popleft()
        if len(self.asked) >= self.most:
            raise Refused("I have answered as many questions as I may in an hour. Try again "
                          "later.", "the hourly limit was reached")
        self.asked.append(now)


_limit = Limit()


def ask(question, data, *, model=None, limit=None):
    """Answer one question about `data` (a console snapshot). Raises Refused, never guesses."""
    question = " ".join(str(question or "").split())
    if not question:
        raise Refused("Ask me something about your outreach.", "empty question")
    if len(question) > MAX_QUESTION:
        raise Refused(f"That is longer than I can read. Keep a question under {MAX_QUESTION} "
                      f"characters.", "question too long")
    (limit or _limit).take()
    given = facts(data)
    known = {lead["lead_id"] for lead in given["leads"]} | {d["lead_id"] for d in given["drafts"]}
    prompt = PROMPT.replace("{facts}", json.dumps(given, indent=1, default=str)).replace(
        "{question}", question)
    try:
        said, usage = (model or gemini.generate_json)(prompt, SCHEMA)
    except Exception as exc:  # a model or network failure is never an answer
        raise Refused("I could not reach the model just now. Try again in a minute.",
                      f"{type(exc).__name__}: {exc}") from None
    answered = _checked(said if isinstance(said, dict) else {}, given, known)
    answered["tokens"] = (usage or {}).get("totalTokenCount")
    return answered
