"""What the console shows, worked out from the Sheet's rows alone. No Google access here.

`build` returns plain JSON data for the React pages: strings, numbers, true/false, lists, maps
and null. A date is an ISO string, and anything that refers to a lead does so by its Lead ID.

Where each lead stands is worked out with the scheduled sync's own function
(`sequence.lead_state`), for today, from the Events tab, so the console and the lead tabs say
the same thing. One difference: the console does not look in Gmail, so a draft deleted there
shows as deleted only in the Sheet, after the next sync.

The counts use the Sheet Dashboard's definitions: a lead is emailed once it has a "Sent at", a
reply includes a request to stop, and open and click rates are over the leads with a tracked
email, never over everyone emailed.
"""

from collections import defaultdict
from datetime import date, datetime, timezone
from urllib.parse import quote, urlparse

from outreach import calls, channels
from outreach import drafts as drafts_tab
from outreach import sequence, suppression, sync
from outreach.business_days import NEW_YORK, add_business_days, new_york_date
from outreach.dashboard import NOTES
from outreach.dashboard import TIERS as SHEET_TIERS
from outreach.sheet import SHEET_ID

VERSION = 2  # the shape of what `build` returns; the React pages check it
SHEET_URL = f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/edit"
TIERS = [(prefix.rstrip("-"), label) for _, prefix, label in SHEET_TIERS]
TIER_LABELS = dict(TIERS)
# "Coming up" lists follow-ups due within this many business days after today. This system's
# choice, not a founder decision.
COMING_UP_BUSINESS_DAYS = 5

CALL_OUTCOME_LABELS = {
    calls.NO_ANSWER: "No answer", calls.INTERESTED: "Interested",
    calls.NOT_INTERESTED: "Not interested", calls.CALLBACK: "Callback requested",
    calls.WRONG_NUMBER: "Wrong number", calls.DO_NOT_CONTACT: "Do not contact",
}
CALL_ACTION_LABELS = {calls.COMPLETE: "Completed", calls.SNOOZE: "Snoozed", calls.CANCEL: "Cancelled"}
CALL_EFFECT_SAID = {
    calls.STOP: "Email stopped by the call outcome",
    calls.HOLD: "Email paused by the call outcome",
    calls.CONTINUE: "",
}

STATUS_LABELS = {
    "": "Not emailed",
    "DRAFTED": "Draft in Gmail",
    "SENT": "Emailed",
    "REPLIED": "Replied",
    "OPTED_OUT": "Asked to stop",
    "BOUNCED": "Bounced",
    "REVIEW_NEEDED": "Match to check",
}
EVENT_LABELS = {
    sequence.SENT: "Sent", sequence.REPLIED: "Replied", sequence.AUTO_REPLY: "Auto-reply",
    sequence.OPT_OUT: "Asked to stop", sequence.BOUNCED: "Bounced",
    sequence.DELAYED: "Delivery delayed", sequence.DRAFTED: "Drafted",
    sequence.FOLLOWUP_DRAFTED: "Follow-up drafted", sequence.OPEN: "Opened (est.)",
    sequence.CLICK: "Clicked",
}
STEP_LABELS = {
    sequence.INITIAL: "First email", "FOLLOWUP_1": "Follow-up 1", "FOLLOWUP_2": "Follow-up 2",
    sequence.LATER: "A later email", sequence.CONVERSATION: "In the conversation",
    sequence.OTHER_THREAD: "Another thread", sequence.UNCONFIRMED: "Not confirmed",
}
MATCH_LABELS = {
    "DRAFT": "this system's draft", "ADDRESS": "an address on the lead's row",
    "THREAD": "the same thread", "DOMAIN": "the company's domain only",
    "SEVERAL": "more than one lead",
}
DRAFT_LABELS = {drafts_tab.READY: "Ready to approve", drafts_tab.WAITING: "Waiting for you",
                drafts_tab.HELD: "Held"}
DRAFT_ORDER = {drafts_tab.READY: 0, drafts_tab.WAITING: 1, drafts_tab.HELD: 2}
# Needs-you order: an answer first, then what is late, then drafts, then checks.
REPLY, FOLLOWUP_DUE, DRAFT_WAITING, CHECK = 0, 1, 2, 3
NEED_LABELS = {REPLY: "Reply to answer", FOLLOWUP_DUE: "Follow-up due",
               DRAFT_WAITING: "Draft waiting", CHECK: "To check"}


def tier_of(lead_id):
    prefix = str(lead_id).split("-", 1)[0]
    return prefix if prefix in TIER_LABELS else ""


def _lead_order(lead_id):
    prefix, _, number = str(lead_id).partition("-")
    return (prefix, int(number) if number.isdigit() else 0, str(lead_id))


def _number(text):
    try:
        return int(str(text).strip() or 0)
    except ValueError:
        return 0


def percent(top, bottom):
    """A whole percent, as the Sheet Dashboard shows it; '-' when there is nothing to divide by."""
    if not bottom:
        return "-"
    return f"{round(100 * top / bottom)}%"


def moment(text):
    """A UTC time written by this system ('2026-09-28 16:06:01' or ISO) on a New York clock."""
    raw = str(text or "").strip()
    if not raw:
        return ""
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return raw
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(NEW_YORK).strftime("%Y-%m-%d %H:%M ET")


def ago(text, now):
    """How long ago a moment this system recorded was, in words: "2 hours ago", "3 days ago".

    Rounded down to the largest whole unit, because an exact figure adds nothing here; the exact
    time is still shown beside it. A moment that cannot be read gives nothing."""
    raw = str(text or "").strip()
    if not raw:
        return ""
    try:
        moment = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return ""
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    seconds = (now - moment).total_seconds()
    if seconds < 0:
        return ""
    for length, one, many in ((86400 * 7, "week", "weeks"), (86400, "day", "days"),
                              (3600, "hour", "hours"), (60, "minute", "minutes")):
        if seconds >= length:
            count = int(seconds // length)
            return f"{count} {one if count == 1 else many} ago"
    return "just now"


def safe_href(url):
    """The address itself when it is an http(s) link, else "": a cell reading 'javascript:...'
    must never become a link on the page."""
    text = str(url or "").strip()
    parsed = urlparse(text)
    return text if parsed.scheme in ("http", "https") and parsed.netloc else ""


def event_view(event):
    try:
        when = sequence.moment_text(event)
    except (ValueError, KeyError, TypeError, AttributeError):
        when = str(event.get(sequence.OCCURRED, ""))
    return {"when": when, "event": EVENT_LABELS.get(event.get("Event"), event.get("Event", "")),
            "step": STEP_LABELS.get(event.get("Step"), event.get("Step", "")),
            "address": event.get("Address", ""),
            "match": MATCH_LABELS.get(event.get("Match"), event.get("Match", "")),
            "detail": event.get("Detail", "")}


def _call_due_text(due, kind):
    if not due:
        return ""
    if kind == "DATE":
        try:
            return sequence.day_text(date.fromisoformat(due))
        except ValueError:
            return due
    return moment(due)  # a TIME (a requested callback): the New York clock time


def _call_when(due, due_kind, overdue, today):
    """Which queue bucket a scheduled task is in: OVERDUE (already past), TODAY (due on today's New York
    date and not yet overdue), or UPCOMING (a later day). Uses the same New York clock as `overdue`."""
    if overdue:
        return "OVERDUE"
    try:
        if due_kind == "DATE":
            due_day = date.fromisoformat(due)
        else:
            when = calls._parse(due)
            due_day = when.astimezone(NEW_YORK).date() if when else None
    except (ValueError, TypeError):
        due_day = None
    return "TODAY" if due_day == today else "UPCOMING"


def call_task_view(task):
    """One lead's current call task as the pages show it, or None when there is no task."""
    if not task:
        return None
    return {
        "id": task.get("id", ""),
        "status": task["status"], "outcome": task["outcome"],
        "why": CALL_OUTCOME_LABELS.get(task["outcome"], task["outcome"]),
        "note": task.get("note", ""), "due": task.get("due", ""),
        "due_kind": task.get("due_kind", ""),
        "due_text": _call_due_text(task.get("due", ""), task.get("due_kind", "")),
        "overdue": bool(task.get("overdue")), "snoozed": bool(task.get("snoozed")),
        "called_at": moment(task.get("called_at", "")),
    }


def call_history_view(history):
    out = []
    for item in history:
        what = (CALL_OUTCOME_LABELS.get(item["outcome"], item["outcome"]) if item.get("outcome")
                else CALL_ACTION_LABELS.get(item.get("detail", ""), item.get("detail", "")))
        out.append({"when": moment(item.get("when", "")), "what": what, "note": item.get("note", "")})
    return out


def _in_order(events):
    try:
        return sorted(events, key=sequence._order)
    except (KeyError, TypeError):
        return list(events)


def _drafts_of(row, sends, sent_steps):
    """This system's drafts the Sheet knows about for one lead and that were not yet sent."""
    found = []
    if row.get("Draft status") in ("RESERVED", "CREATED") and not sends:
        found.append({"kind": "First email", "status": row["Draft status"],
                      "at": moment(row.get("Drafted at") or row.get("Draft action at")),
                      "tracked": row.get("Draft tracked") == "yes"})
    step = row.get("Follow-up step", "")
    if (row.get("Follow-up status") in ("RESERVED", "CREATED")
            and f"FOLLOWUP_{step}" not in sent_steps):
        found.append({"kind": f"Follow-up {step}", "status": row["Follow-up status"],
                      "at": moment(row.get("Follow-up action at")), "tracked": False})
    return found


def _lead(lead_id, row, events, entries, today, now=None, call_events=()):
    """(what the pages show about one lead, its next follow-up as (step, date) or None)."""
    tier = tier_of(lead_id)
    view = {
        "id": lead_id, "tier": tier, "tier_label": TIER_LABELS.get(tier, ""),
        "company": row.get("Company", ""), "contact": row.get("Decision maker", ""),
        "email": row.get("BEST EMAIL", "").strip(), "website": row.get("Website", "").strip(),
        "phone": channels.phone_of(row), "channel": channels.channel_of(row),
        "website_href": safe_href(row.get("Website", "")),
        "email_check": row.get("Email check", ""), "email_reason": row.get("Reason", ""),
        "fit": row.get("Fit", ""), "fit_reason": row.get("Fit reason", ""),
        "profile": row.get("Profile status", ""), "hold": row.get("HOLD", "").strip(),
        "sent_by_hand": row.get("Sent by hand", "").strip(),
        "status": "", "status_label": STATUS_LABELS[""], "action": "", "cells": {},
        "origin": None, "next_followup": None, "suppressed": None, "gmail_drafts": [],
        "ready": False, "blockers": [], "error": None, "draft": None, "sent_ago": "",
        "events": [event_view(e) for e in _in_order(events)],
        "columns": [[column, value] for column, value in row.items()],
        "call_task": None, "call_history": [], "call_effect": "", "call_effect_said": "",
    }
    if now is not None and call_events:
        state = calls.call_state(call_events, now=now)
        view["call_task"] = call_task_view(state["task"])
        view["call_history"] = call_history_view(state["history"])
        view["call_effect"] = state["email_effect"]
        view["call_effect_said"] = CALL_EFFECT_SAID.get(state["email_effect"], "")
    try:
        suppressed = None if entries is None else sync.lead_suppressed(entries, row, events)
        state = sequence.lead_state(row, events, suppressed=bool(suppressed), today=today)
    except (ValueError, KeyError, TypeError, AttributeError) as exc:
        view["error"] = f"its events could not be worked out ({type(exc).__name__}: {exc})"
        view["status_label"] = "Could not be worked out"
        return view, None
    running = state["sequence"]
    upcoming = sequence.next_followup(running) if running else None
    first = running["sends"][0] if running else None
    view["sent_ago"] = ago(first[sequence.OCCURRED], now) if first and now else ""
    view.update(
        status=state["status"], status_label=STATUS_LABELS.get(state["status"], state["status"]),
        action=state["cells"]["Next action"], cells=state["cells"], suppressed=suppressed,
        origin=running["origin"] if running else None,
        next_followup=({"step": upcoming[0], "date": upcoming[1].isoformat(),
                        "day": sequence.day_text(upcoming[1])} if upcoming else None),
        gmail_drafts=_drafts_of(row, state["sends"],
                          {e["Step"] for e in running["sends"]} if running else set()))
    # A lead with no email to draft is not a dead end: show the correct next action so it stays
    # usable. Only for a lead nothing has happened to yet (status ""), and never over a hold. This is
    # display only - it is not the "Next action" the sync writes to the Sheet (that stays about email).
    if view["channel"] != channels.EMAIL and view["status"] == "" and not view["hold"]:
        view["action"] = channels.next_action(view["channel"], view["company"])
    blockers = drafts_tab.first_draft_blockers(row, events, entries, call_events)
    view["blockers"] = blockers
    view["ready"] = not blockers
    return view, upcoming


def _needs_you(view, upcoming, today):
    """(order, sort key, what to do) when this lead needs the founder, else None."""
    status, action = view["status"], view["action"]
    if view["error"]:
        return CHECK, "", "The console could not work out where this lead stands: " + view["error"]
    if status == "REPLIED":
        return REPLY, view["cells"].get("Replied at", ""), action
    if status == "REVIEW_NEEDED":
        return CHECK, view["cells"].get("Sent at", ""), action
    if status == "BOUNCED":
        return CHECK, "", action
    if status == "DRAFTED":
        return DRAFT_WAITING, "", action
    if status != "SENT" or view["hold"] or view["suppressed"]:
        return None
    if view["gmail_drafts"]:
        return DRAFT_WAITING, "", action
    if upcoming and upcoming[1] <= today:
        return FOLLOWUP_DUE, upcoming[1].isoformat(), action
    return None


def _tier_counts(views, events, prefix):
    mine = [v for v in views if prefix is None or v["tier"] == prefix]
    statuses = [v["status"] for v in mine]
    emailed = sum(1 for v in mine if v["cells"].get("Sent at"))
    replied = statuses.count("REPLIED") + statuses.count("OPTED_OUT")
    tracked = sum(1 for v in mine if _number(v["cells"].get("Tracked sends")) > 0)
    opened = sum(1 for v in mine if _number(v["cells"].get("Opens (est.)")) > 0)
    clicked = sum(1 for v in mine if _number(v["cells"].get("Clicks")) > 0)
    sent = sum(1 for e in events if e.get("Event") == sequence.SENT
               and tier_of(e.get("Lead ID", ""))
               and (prefix is None or tier_of(e["Lead ID"]) == prefix))
    return {
        "leads": len(mine), "checked_ok": sum(1 for v in mine if v["email_check"] == "OK"),
        "qualified": sum(1 for v in mine if v["fit"] == "QUALIFIED"),
        "profiled": sum(1 for v in mine if v["profile"] == "READY"),
        "drafted": sum(1 for v in mine if v["draft"]),
        "ready": sum(1 for v in mine if v["ready"]), "emailed": emailed,
        "emails_sent": sent, "replied": replied, "reply_rate": percent(replied, emailed),
        "opted_out": statuses.count("OPTED_OUT"), "bounced": statuses.count("BOUNCED"),
        "review_needed": statuses.count("REVIEW_NEEDED"), "tracked": tracked,
        "coverage": percent(tracked, emailed), "opened": opened,
        "open_rate": percent(opened, tracked), "clicked": clicked,
        "click_rate": percent(clicked, tracked),
    }


def _last_run(runs, job):
    for row in reversed(runs):
        if row.get("Job") == job:
            return {"at": moment(row.get("Run at (UTC)")), "result": row.get("Result", ""),
                    "detail": row.get("Detail", "")}
    return None


def approvals(settings):
    """What the drafting settings say, and nothing else from them: never the founder's postal
    address, phone or signature. None when the console was given no settings."""
    if not settings:
        return None
    cap = settings.get("daily_cap")
    return {
        "offer": settings.get("offer_approved") is True,
        "followups": bool(str(settings.get("followup_approved_handbook_hash", "")).strip()),
        "tracking": settings.get("tracking_enabled") is True,
        "daily_cap": cap if isinstance(cap, int) and not isinstance(cap, bool) else None,
        "sender": str(settings.get("sender_email", "")).strip(),
    }


# The drafting step's reasons are written about the founder; the pages speak to them.
OFFER_NOT_APPROVED_SAID = "You have not approved the offer wording yet"
REASONS_SAID = {drafts_tab.OFFER_NOT_APPROVED: OFFER_NOT_APPROVED_SAID}


def draft_view(row, lead, now=None):
    """One row of the Drafts tab as the pages show it. Never the approval hash or the stored
    writer output: the pages only show the words."""
    status = row.get("Status", "")
    reasons = [part.strip() for part in row.get("Why", "").splitlines() if part.strip()]
    return {
        "lead_id": row.get("Lead ID", ""), "kind": row.get("Email", ""), "to": row.get("To", ""),
        "company": row.get("Company") or (lead or {}).get("company", ""),
        "contact": (lead or {}).get("contact", ""), "tier": tier_of(row.get("Lead ID", "")),
        "subject": row.get("Subject", ""), "body": row.get("Body", ""),
        "quote": row.get("Opening quote", ""), "quote_page": row.get("Quote page", ""),
        "quote_href": safe_href(row.get("Quote page", "")),
        "status": status, "status_label": DRAFT_LABELS.get(status, status or "Unknown"),
        "why": [REASONS_SAID.get(reason, reason) for reason in reasons],
        "prepared_at": moment(row.get("Prepared at (UTC)")),
        "prepared_ago": ago(row.get("Prepared at (UTC)"), now) if now else "",
    }


def build(leads, events, entries, runs, *, settings, now, handbook_doc_id="", draft_rows=(),
          drafts_error=None, suppression_error=None, call_events=(), calls_enabled=False):
    """The whole console, worked out once per request. `draft_rows` is the Drafts tab's rows,
    or None when it could not be read (`drafts_error` says why); `entries` is None when the
    Suppression list could not be read (`suppression_error` says why); `call_events` are the Call log
    rows, and `calls_enabled` says whether the call-task flow is switched on for this server."""
    today = new_york_date(now)
    events = sync.unique(events)
    by_lead = defaultdict(list)
    for event in events:
        by_lead[event.get("Lead ID", "")].append(event)
    # call_events is None when the Call log could not be read: fail closed so unreadable call history
    # never means unrestricted outreach (a lead is then blocked from a first draft).
    calls_unreadable = call_events is None
    by_call = defaultdict(list)
    for event in call_events or ():
        by_call[event.get("Lead ID", "")].append(event)

    views, needs_you, coming_up = [], [], []
    horizon = add_business_days(today, COMING_UP_BUSINESS_DAYS)
    for lead_id, row in sorted(leads.items(), key=lambda item: _lead_order(item[0])):
        view, upcoming = _lead(lead_id, row, by_lead.get(lead_id, []), entries, today, now,
                               call_events=None if calls_unreadable else by_call.get(lead_id, []))
        views.append(view)
        need = _needs_you(view, upcoming, today)
        if need:
            order, sort_key, text = need
            needs_you.append({"order": order, "label": NEED_LABELS[order], "lead_id": lead_id,
                              "text": text,
                              "address": view["cells"].get("Sent to") or view["email"],
                              "_sort": sort_key})
        if (view["status"] == "SENT" and not view["hold"] and not view["suppressed"]
                and not view["gmail_drafts"] and upcoming and today < upcoming[1] <= horizon):
            coming_up.append({"lead_id": lead_id, "step": upcoming[0],
                              "date": upcoming[1].isoformat(),
                              "day": sequence.day_text(upcoming[1]), "text": view["action"]})
    needs_you.sort(key=lambda item: (item["order"], item["_sort"], _lead_order(item["lead_id"])))
    for item in needs_you:
        del item["_sort"]
    coming_up.sort(key=lambda item: (item["date"], _lead_order(item["lead_id"])))

    warnings = []
    if entries is None:
        warnings.append("The Suppression tab cannot be read, so nobody is shown as ready for a "
                        "first draft and a suppressed address may not be marked."
                        + (f" {suppression_error[:1].upper()}{suppression_error[1:]}."
                           if suppression_error else ""))
    broken = [v["id"] for v in views if v["error"]]
    if broken:
        warnings.append("Where these leads stand could not be worked out from their events: "
                        + ", ".join(broken) + ".")

    by_id = {v["id"]: v for v in views}
    drafts = [draft_view(row, by_id.get(row.get("Lead ID")), now) for row in (draft_rows or [])]
    drafts.sort(key=lambda d: (DRAFT_ORDER.get(d["status"], 3), _lead_order(d["lead_id"])))
    for draft in drafts:
        if draft["lead_id"] in by_id and by_id[draft["lead_id"]]["draft"] is None:
            by_id[draft["lead_id"]]["draft"] = draft["status"]
    if draft_rows is None:
        warnings.append("The Drafts tab cannot be read" + (f": {drafts_error}" if drafts_error else "")
                        + ". No draft is shown.")
    waiting_for_offer = sum(1 for d in drafts if d["status"] == drafts_tab.WAITING
                            and OFFER_NOT_APPROVED_SAID in d["why"])

    tiers = [{"prefix": prefix, "label": label, **_tier_counts(views, events, prefix)}
             for prefix, label in TIERS]
    tiers.append({"prefix": "", "label": "A and B", **_tier_counts(views, events, None)})

    # The call tasks that are open, overdue first then by due date, so they stay visible until acted on.
    # Each carries a `when` bucket (OVERDUE / TODAY / UPCOMING) worked out from the New York date, so the
    # dashboard queue can show overdue and due-today together and keep upcoming separate.
    #
    # Suppression is honoured here: a lead that opted out (or is otherwise on the Suppression list) is not
    # an actionable call, so it is left out of the queue - its call history still shows on the lead page.
    # If the Suppression list could not be read we cannot tell who opted out, so the whole queue is
    # unavailable (empty + flagged), never an apparently-usable list that might include a suppressed lead.
    suppression_unreadable = entries is None
    call_tasks = []
    for view in views:
        task = view["call_task"]
        if not (task and task["status"] == "scheduled"):
            continue
        if suppression_unreadable or view["suppressed"]:
            continue
        call_tasks.append({"id": task.get("id", ""), "lead_id": view["id"],
                           "company": view["company"], "contact": view["contact"],
                           "phone": view["phone"], "why": task["why"], "note": task["note"],
                           "due": task["due"], "due_kind": task.get("due_kind", ""),
                           "due_text": task["due_text"], "overdue": task["overdue"],
                           "when": _call_when(task["due"], task.get("due_kind", ""),
                                              task["overdue"], today)})
    call_tasks.sort(key=lambda t: (not t["overdue"], t["due"], _lead_order(t["lead_id"])))

    chosen = approvals(settings)
    doc = str(handbook_doc_id or "").strip()
    return {
        "version": VERSION,
        "read_at": now.astimezone(NEW_YORK).strftime("%Y-%m-%d %H:%M ET"),
        "today": today.isoformat(), "today_text": sequence.day_text(today),
        "warnings": warnings, "leads": views, "needs_you": needs_you, "coming_up": coming_up,
        "coming_up_days": COMING_UP_BUSINESS_DAYS, "tiers": tiers, "notes": list(NOTES),
        "calls_enabled": calls_enabled, "call_tasks": call_tasks,
        "calls_overdue": sum(1 for t in call_tasks if t["overdue"]),
        "calls_due_today": sum(1 for t in call_tasks if t["when"] == "TODAY"),
        # The Call log or the Suppression list could not be read: the queue shows an unavailable state,
        # never "no calls due" (which could hide a real or a wrongly-included call).
        "calls_unreadable": calls_unreadable,
        "suppression_unreadable": suppression_unreadable,
        "drafts": drafts,
        "drafts_summary": {"ready": sum(1 for d in drafts if d["status"] == drafts_tab.READY),
                           "waiting": sum(1 for d in drafts if d["status"] == drafts_tab.WAITING),
                           "held": sum(1 for d in drafts if d["status"] == drafts_tab.HELD),
                           "waiting_for_offer": waiting_for_offer},
        "gmail_drafts": [dict(draft, lead_id=view["id"]) for view in views
                         for draft in view["gmail_drafts"]],
        "ready": None if entries is None else [v["id"] for v in views if v["ready"]],
        "approvals": chosen,
        "sync": _last_run(runs, "sync"), "tracking_run": _last_run(runs, "tracking"),
        "event_count": len(events),
        "suppression_count": None if entries is None else len(entries),
        "links": {"sheet": SHEET_URL,
                  "handbook": f"https://docs.google.com/document/d/{quote(doc)}/edit" if doc else "",
                  "gmail_account": (chosen or {}).get("sender", "")},
    }


def snapshot(store, *, settings, now, handbook_doc_id="", calls_enabled=False):
    """Read the Sheet once through `store` and work the console out. A Drafts tab that cannot
    be read is said, and the rest is still shown."""
    try:
        draft_rows, drafts_error = [row for _, row in store.drafts()], None
    except RuntimeError as exc:
        draft_rows, drafts_error = None, str(exc)
    try:
        entries, suppression_error = store.suppression(), None
    except suppression.Unreadable as exc:
        entries, suppression_error = None, exc.reason
    try:
        call_events = store.call_events()
    except RuntimeError:
        call_events = None  # the Call log exists but could not be read: fail closed (block outreach)
    except AttributeError:
        call_events = ()  # this store has no Call log at all (an older store): calls simply absent
    return build(store.leads(), store.events(), entries, store.run_rows(),
                 settings=settings, now=now, handbook_doc_id=handbook_doc_id,
                 draft_rows=draft_rows, drafts_error=drafts_error,
                 suppression_error=suppression_error, call_events=call_events,
                 calls_enabled=calls_enabled)
