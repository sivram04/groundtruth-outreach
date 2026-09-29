"""Where one lead stands, worked out only from its recorded events. No Google access.

A sequence is an initial email and at most two follow-ups in the same thread. It starts with the
first email sent to a lead with a certain match, and again only after that address bounced. A
reply, a request to stop, a bounce, HOLD or the Suppression list ends it.

Founder decisions this follows:
- 2026-09-22: follow-up 1 is due on the third business day after the initial email was
  actually sent, follow-up 2 on the third business day after follow-up 1 was sent; at most two.
- 2026-09-28: only a sequence whose initial email was one of this system's drafts gets follow-up
  drafts. A thread the founder started by hand gets a reminder in Next action, never a draft.
"""

from datetime import datetime, timedelta

from outreach.business_days import FOLLOWUP_GAP, NEW_YORK, add_business_days, new_york_date
from outreach.sheet import SYNC_COLUMNS, TRACKING_COLUMNS

SENT, REPLIED, AUTO_REPLY, OPT_OUT, BOUNCED, DELAYED = (
    "SENT", "REPLIED", "AUTO_REPLY", "OPT_OUT", "BOUNCED", "DELAYED")
DRAFTED, FOLLOWUP_DRAFTED = "DRAFTED", "FOLLOWUP_DRAFTED"
OPEN, CLICK = "OPEN", "CLICK"
TRACKED = "tracked"  # the word a drafted event's detail carries when its draft was tracked
HEAD = "HEAD request"  # the word a click's detail carries when it was only a HEAD request
# Mail scanners follow links as soon as a message arrives. A click this soon after the send is
# taken as a scanner and not counted. One minute is this system's choice.
SCANNER_WINDOW = timedelta(minutes=1)

# How a message was tied to a lead. Only the first three can start or advance a sequence.
CONFIDENT = ("DRAFT", "ADDRESS", "THREAD")
UNCERTAIN = ("DOMAIN", "SEVERAL")

INITIAL = "INITIAL"
FOLLOWUPS = ("FOLLOWUP_1", "FOLLOWUP_2")
LATER, CONVERSATION, OTHER_THREAD, UNCONFIRMED = "LATER", "CONVERSATION", "OTHER_THREAD", "UNCONFIRMED"
SYSTEM, HAND = "SYSTEM", "HAND"

OCCURRED = "Occurred at (UTC)"


def when(event):
    return datetime.fromisoformat(event[OCCURRED].replace("Z", "+00:00"))


def _order(event):
    return event[OCCURRED], event.get("Event key", "")


def moment_text(event):
    return when(event).astimezone(NEW_YORK).strftime("%Y-%m-%d %H:%M ET")


def day_text(day):
    return day.strftime("%a %Y-%m-%d")


def event_day(event):
    return day_text(new_york_date(when(event)))


def current_sequence(events):
    """The sequence running now, from a lead's events, or None."""
    sequence = None
    for event in sorted(events, key=_order):
        kind = event["Event"]
        if kind == SENT and event["Match"] in CONFIDENT and event["Step"] == INITIAL:
            sequence = {"start": event, "thread": event["Thread ID"], "address": event["Address"],
                        "origin": SYSTEM if event["Match"] == "DRAFT" else HAND,
                        "sends": [event], "bounced": None}
        elif sequence is None:
            continue
        elif kind == SENT and event["Thread ID"] == sequence["thread"] and event["Step"] in FOLLOWUPS:
            sequence["sends"].append(event)
        elif kind == BOUNCED and (event["Address"] == sequence["address"]
                                  or event["Thread ID"] == sequence["thread"]):
            sequence["bounced"] = sequence["bounced"] or event
    return sequence


def step_for_send(prior, thread_id, at):
    """Which email of the sequence a newly seen send (with a certain match) is."""
    earlier = [e for e in prior if when(e) <= at]
    sequence = current_sequence(earlier)
    if sequence is None or sequence["bounced"]:
        return INITIAL
    if thread_id != sequence["thread"]:
        return OTHER_THREAD
    started = when(sequence["start"])
    if any(e["Event"] in (REPLIED, OPT_OUT) and when(e) >= started for e in earlier):
        return CONVERSATION
    followups = len(sequence["sends"]) - 1
    return FOLLOWUPS[followups] if followups < len(FOLLOWUPS) else LATER


def lead_state(row, events, *, suppressed, today, draft_gone=None):
    """Everything the Sheet should say about one lead, and the follow-up it is waiting for.

    Returns {"status", "cells", "sequence", "due"}. `due` is set only for a sequence this system
    started, still running, with its next follow-up not yet reserved or drafted: {"step", "date",
    "thread", "address", "after_message"}. `draft_gone` says which of this system's drafts were
    looked for in Gmail and are no longer there: {"initial": bool, "followup": bool}.
    """
    draft_gone = draft_gone or {}
    ordered = sorted(events, key=_order)
    sequence = current_sequence(ordered)
    stopped_by = [e for e in ordered if e["Event"] == OPT_OUT]
    replies = [e for e in ordered if e["Event"] in (REPLIED, OPT_OUT)]
    unconfirmed = [e for e in ordered if e["Event"] == SENT and e["Match"] in UNCERTAIN]
    sends = [e for e in ordered if e["Event"] == SENT]
    hold = bool(row.get("HOLD", "").strip())
    due = None

    def uncertain_note(event):
        if event["Match"] in UNCERTAIN:
            return (f" Check it concerns this company: it was matched to {event['Address']} "
                    f"by the company's domain, not by an address on this row.")
        return ""

    if stopped_by:
        event = stopped_by[-1]
        status = "OPTED_OUT"
        action = (f"Asked to stop on {event_day(event)} ({event['Detail'] or 'a reply'}). "
                  f"Never contact again.")
    elif replies:
        event = replies[0]
        status = "REPLIED"
        action = f"Replied on {event_day(event)}. Answer by hand." + uncertain_note(event)
    elif sequence and sequence["bounced"]:
        status = "BOUNCED"
        action = (f"{sequence['address']} bounced on {event_day(sequence['bounced'])}. "
                  f"Find another address.")
    elif sequence:
        status = "SENT"
        action, due = _schedule(row, sequence, today, hold=hold, suppressed=suppressed,
                                draft_gone=draft_gone.get("followup", False))
    elif unconfirmed:
        event = unconfirmed[-1]
        status = "REVIEW_NEEDED"
        would_be = add_business_days(new_york_date(when(event)), FOLLOWUP_GAP)
        bounced = [e for e in ordered if e["Event"] == BOUNCED and e["Address"] == event["Address"]]
        action = (f"Check the match: you emailed {event['Address']} on {event_day(event)}, which is "
                  f"not an address on this row.")
        action += (f" It bounced on {event_day(bounced[-1])}." if bounced else
                   f" If it is this company, follow-up 1 {_due_words(would_be, today)}.")
    elif row.get("Draft status") == "CREATED":
        status = "DRAFTED"
        action = ("The initial draft is no longer in Gmail and was not sent."
                  if draft_gone.get("initial") else
                  "The initial draft is in Gmail: review it and press Send.")
    else:
        status, action = "", ""

    autos = [e for e in ordered if e["Event"] == AUTO_REPLY]
    if status == "SENT" and autos and when(autos[-1]) >= when(sequence["sends"][-1]):
        auto = autos[-1]
        note = f"Auto-reply on {event_day(auto)}" + (f" {auto['Detail']}" if auto["Detail"] else "")
        action = note + ". " + action

    anchor = sequence["start"] if sequence else (unconfirmed[-1] if unconfirmed else None)
    cells = {
        "Outreach status": status,
        "Sent to": anchor["Address"] if anchor else "",
        "Sent at": moment_text(anchor) if anchor else "",
        "Replied at": moment_text(replies[0]) if replies else "",
        "Follow-ups sent": str(len(sequence["sends"]) - 1) if sequence else "",
        "Last event": (f"{ordered[-1]['Event']} {moment_text(ordered[-1])}" if ordered else ""),
        "Next action": action,
    }
    cells.update(tracking_cells(ordered))
    assert list(cells) == SYNC_COLUMNS + TRACKING_COLUMNS
    return {"status": status, "cells": cells, "sequence": sequence, "due": due,
            "sends": len(sends)}


def tracking_cells(events):
    """Tracked sends, opens and clicks for one lead, from its events.

    Blank when no email of the running sequence came from a tracked draft: a blank is "not
    tracked", never "no opens". A hit counts only for the email its draft became, and only after
    that email was sent — the founder looking at the draft first is not an open. An open is an
    estimate. A click counts from a minute after the send, and never a HEAD request.
    """
    ordered = sorted(events, key=_order)
    running = current_sequence(ordered)
    tracked = {e["Step"] for e in ordered if e["Event"] in (DRAFTED, FOLLOWUP_DRAFTED)
               and TRACKED in [part.strip() for part in e["Detail"].split(",")]}
    sends = [s for s in (running["sends"] if running else []) if s["Step"] in tracked]
    if not sends:
        return dict.fromkeys(TRACKING_COLUMNS, "")
    opens = clicks = 0
    for send in sends:
        sent_at = when(send)
        for hit in ordered:
            if hit["Step"] != send["Step"] or when(hit) < sent_at:
                continue
            if hit["Event"] == OPEN:
                opens += 1
            elif (hit["Event"] == CLICK and when(hit) - sent_at >= SCANNER_WINDOW
                  and HEAD not in hit["Detail"]):
                clicks += 1
    return {"Tracked sends": str(len(sends)), "Opens (est.)": str(opens), "Clicks": str(clicks)}


def _due_words(due, today):
    if due == today:
        return "is due today"
    return f"was due {day_text(due)}" if due < today else f"is due {day_text(due)}"


def next_followup(sequence):
    """(step, due date) of the next follow-up of a running sequence, or None once both are sent.

    Follow-up N is due FOLLOWUP_GAP business days after the sequence's last email was sent,
    whoever started the thread; whether it is drafted or only reminded of is decided elsewhere."""
    followups_sent = len(sequence["sends"]) - 1
    if followups_sent >= len(FOLLOWUPS):
        return None
    last = sequence["sends"][-1]
    return followups_sent + 1, add_business_days(new_york_date(when(last)), FOLLOWUP_GAP)


def _schedule(row, sequence, today, *, hold, suppressed, draft_gone):
    """(Next action, follow-up waiting to be drafted or None) for a running sequence."""
    last = sequence["sends"][-1]
    if hold:
        return "On hold: no follow-ups.", None
    if suppressed:
        return "On the Suppression list: no follow-ups.", None
    upcoming = next_followup(sequence)
    if upcoming is None:
        return f"Both follow-ups sent, the last on {event_day(last)}. No reply yet.", None
    step, due_date = upcoming
    words = _due_words(due_date, today)
    if sequence["origin"] == HAND:
        return (f"Follow-up {step} {words}. You started this thread by hand, so write it "
                f"yourself in the same thread."), None
    action_step = row.get("Follow-up step", "")
    action_status = row.get("Follow-up status", "")
    if action_step == str(step) and action_status == "CREATED":
        if draft_gone:
            return (f"The follow-up {step} draft was deleted without being sent; it will not be "
                    f"drafted again."), None
        return f"Follow-up {step} is in Gmail drafts: review it and press Send.", None
    if action_step == str(step) and action_status == "RESERVED":
        return (f"Follow-up {step} was reserved but Gmail did not confirm the draft: "
                f"reconcile it before anything else."), None
    due = {"step": step, "date": due_date, "thread": sequence["thread"],
           "address": sequence["address"], "after_message": last["Gmail message ID"]}
    if due_date > today:
        return f"Follow-up {step} {words}; it will be drafted then.", due
    return f"Follow-up {step} {words}; waiting to be drafted.", due
