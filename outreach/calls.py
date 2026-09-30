"""Call outcomes and the call tasks they schedule, worked out from an append-only event log.

Like `outreach/sequence.py` for email, this is pure: it turns a lead's recorded call events into the
one current call task and a history, and it decides how each outcome affects the email sequence. It
never sends, drafts, or reads Google. Timing is explicit - a "no answer" schedules the next call by a
configurable business-day rule, a requested callback uses the time the founder gave - and a free-text
note is never parsed for a time.

Events are rows in the Call log tab (`outreach/sheet.py`):
  Kind OUTCOME - a recorded call result (no answer / interested / not interested / callback / wrong
  number / do not contact), with the note, the call time, the computed due time and the email effect;
  Kind ACTION - COMPLETE / SNOOZE / CANCEL applied to the current task.
Each event carries an Event ID that makes a repeated submission a no-op (one task, not two).
"""

import hashlib
import json
from datetime import date, datetime, timezone

from outreach.business_days import NEW_YORK, add_business_days, new_york_date

# Outcomes a founder can record from the lead page.
NO_ANSWER = "NO_ANSWER"
INTERESTED = "INTERESTED"
NOT_INTERESTED = "NOT_INTERESTED"
CALLBACK = "CALLBACK"
WRONG_NUMBER = "WRONG_NUMBER"
DO_NOT_CONTACT = "DO_NOT_CONTACT"
OUTCOMES = (NO_ANSWER, INTERESTED, NOT_INTERESTED, CALLBACK, WRONG_NUMBER, DO_NOT_CONTACT)

# What may be done to the current task.
COMPLETE = "COMPLETE"
SNOOZE = "SNOOZE"
CANCEL = "CANCEL"
ACTIONS = (COMPLETE, SNOOZE, CANCEL)

# How an outcome affects the email sequence, persisted so a scheduler cannot ignore it.
STOP = "STOP"          # never email again (also written to Suppression for hard enforcement)
HOLD = "HOLD"          # pause automated email; the founder handles this lead by hand
CONTINUE = "CONTINUE"  # calling does not change the email sequence
EMAIL_EFFECT = {
    NO_ANSWER: CONTINUE, WRONG_NUMBER: CONTINUE,
    INTERESTED: HOLD, CALLBACK: HOLD,
    NOT_INTERESTED: STOP, DO_NOT_CONTACT: STOP,
}
# Outcomes that schedule a next call.
SCHEDULES = (NO_ANSWER, CALLBACK)
DEFAULT_NO_ANSWER_BUSINESS_DAYS = 3


def email_effect(outcome):
    return EMAIL_EFFECT.get(outcome, CONTINUE)


def _parse(text):
    """An aware datetime from an ISO string (a bare date or a naive time is read as UTC)."""
    raw = str(text or "").strip()
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _event_id(*parts):
    return hashlib.sha256(json.dumps(parts, ensure_ascii=False).encode("utf-8")).hexdigest()[:16]


def next_due(outcome, called_at, *, no_answer_business_days, callback_at=None):
    """(due, due_kind) for an outcome, or (None, None) when it schedules no call.

    NO_ANSWER: the n-th business day after the call's New York date (a DATE). CALLBACK: the explicit
    time the founder gave (a TIME, in UTC). Nothing is ever inferred from the note."""
    if outcome == NO_ANSWER:
        called = _parse(called_at)
        if called is None:
            raise ValueError("a call time is needed to schedule the next call")
        due = add_business_days(new_york_date(called), int(no_answer_business_days))
        return due.isoformat(), "DATE"
    if outcome == CALLBACK:
        when = _parse(callback_at)
        if when is None:
            raise ValueError("a callback needs an explicit date and time")
        return when.astimezone(timezone.utc).isoformat(), "TIME"
    return None, None


def outcome_event(lead_id, outcome, note, called_at, *, no_answer_business_days,
                  callback_at=None, now, submission_id=None):
    """A Call log OUTCOME row. Raises ValueError for an unknown outcome or a callback with no time.

    When `submission_id` is given the Event ID is that identity alone, so a retry through the UI - which
    omits `called_at`, letting the server stamp a fresh time each attempt - is still one logical
    submission (one row), even if a successful write's response was lost. A genuinely new call carries a
    new submission_id, so it is recorded. Without a submission_id the Event ID is a content hash
    (including the call time), which keeps a programmatic caller that supplies a fixed `called_at`
    idempotent."""
    if outcome not in OUTCOMES:
        raise ValueError(f"unknown call outcome {outcome!r}")
    called = _parse(called_at) or now
    called_iso = called.astimezone(timezone.utc).isoformat()
    due, kind = next_due(outcome, called_iso, no_answer_business_days=no_answer_business_days,
                         callback_at=callback_at)
    submission = str(submission_id or "").strip()
    event_id = (_event_id("OUTCOME", lead_id, submission) if submission
                else _event_id("OUTCOME", lead_id, outcome, called_iso, str(note or ""),
                               str(callback_at or "")))
    return {
        "Event ID": event_id,
        "Lead ID": lead_id, "Recorded at (UTC)": now.astimezone(timezone.utc).isoformat(),
        "Kind": "OUTCOME", "Outcome": outcome, "Note": str(note or ""), "Called at (UTC)": called_iso,
        "Due": due or "", "Due kind": kind or "", "Email effect": email_effect(outcome), "Detail": "",
        "Task ID": "",
    }


def action_event(lead_id, action, task_id, *, snooze_to=None, now):
    """A Call log ACTION row acting on the task identified by `task_id`. The target is both folded into
    the Event ID (so repeating the same action on the same task is a no-op) and persisted in the Task ID
    column, so replay applies the action only to the task it was aimed at - a stale action can never
    close a newer task, even for delayed or interleaved events."""
    if action not in ACTIONS:
        raise ValueError(f"unknown task action {action!r}")
    due, kind = "", ""
    if action == SNOOZE:
        when = _parse(snooze_to)
        if when is None:
            raise ValueError("a snooze needs a date or time to snooze to")
        due, kind = when.astimezone(timezone.utc).isoformat(), "TIME"
    return {
        "Event ID": _event_id("ACTION", lead_id, action, task_id or "", due),
        "Lead ID": lead_id, "Recorded at (UTC)": now.astimezone(timezone.utc).isoformat(),
        "Kind": "ACTION", "Outcome": "", "Note": "", "Called at (UTC)": "",
        "Due": due, "Due kind": kind, "Email effect": "", "Detail": action,
        "Task ID": task_id or "",
    }


def _order(event):
    # Sort by when it was recorded only; the sort is stable, so events recorded in the same second keep
    # their append order (the Store returns rows oldest-first) - an action never sorts before its outcome.
    return str(event.get("Recorded at (UTC)", ""))


def _overdue(due, kind, now):
    if kind == "DATE":
        try:
            return new_york_date(now) > date.fromisoformat(due)
        except ValueError:
            return False
    when = _parse(due)
    return bool(when and now >= when)


def call_state(events, *, now):
    """The lead's current call task, its call history, the latest email effect, and whether the lead is
    do-not-contact.

    Returns {"task": task or None, "history": [...], "email_effect": STOP/HOLD/CONTINUE,
    "do_not_contact": bool}. `task` is the single current task worked out by replaying the events in
    order: a scheduling outcome opens it, a later scheduling outcome replaces it, COMPLETE/CANCEL close
    it and SNOOZE moves its due. An ACTION applies only to the task it named (its Task ID), so a stale
    action never closes a newer task.

    Do-not-contact is a sticky, per-lead block: once recorded it forces the email effect to STOP and no
    later ordinary outcome (a routine no-answer, say) can reopen a call task or lift the STOP - logging
    later history stays possible, but scheduling new outreach does not. `overdue` is set from `now`."""
    task, history, effect, dnc = None, [], CONTINUE, False
    for event in sorted(events, key=_order):
        kind = event.get("Kind")
        if kind == "OUTCOME":
            outcome = event.get("Outcome", "")
            history.append({"when": event.get("Recorded at (UTC)", ""), "outcome": outcome,
                            "note": event.get("Note", ""), "detail": ""})
            if outcome == DO_NOT_CONTACT:
                dnc = True
            if dnc:
                effect, task = STOP, None  # a recorded stop is permanent; no new task, no lift
                continue
            effect = event.get("Email effect") or email_effect(outcome)
            if outcome in SCHEDULES and event.get("Due"):
                task = {"id": event.get("Event ID", ""), "outcome": outcome,
                        "note": event.get("Note", ""), "called_at": event.get("Called at (UTC)", ""),
                        "due": event["Due"], "due_kind": event.get("Due kind", "DATE"),
                        "status": "scheduled", "snoozed": False}
            else:
                task = None  # a non-scheduling outcome (e.g. not interested) closes the task
        elif kind == "ACTION":
            action = event.get("Detail", "")
            history.append({"when": event.get("Recorded at (UTC)", ""), "outcome": "",
                            "note": "", "detail": action})
            target = event.get("Task ID", "")
            # Apply only to the task this action named. An empty target is a legacy action (before Task
            # ID was persisted) and applies to the current task, as it used to.
            if task and task["status"] == "scheduled" and (not target or target == task["id"]):
                if action == COMPLETE:
                    task["status"] = "done"
                elif action == CANCEL:
                    task["status"] = "cancelled"
                elif action == SNOOZE and event.get("Due"):
                    task["due"] = event["Due"]
                    task["due_kind"] = event.get("Due kind", "TIME")
                    task["snoozed"] = True
    if task and task["status"] == "scheduled":
        task["overdue"] = _overdue(task["due"], task["due_kind"], now)
    elif task:
        task["overdue"] = False
    return {"task": task, "history": history, "email_effect": effect, "do_not_contact": dnc}


def outreach_effect(events):
    """The lead's email effect (STOP / HOLD / CONTINUE) from its call events alone, without a clock.

    This is what the email-drafting and follow-up eligibility paths read so a recorded call decision is
    enforced: STOP (do-not-contact / not-interested) or HOLD (interested / callback - the founder is
    handling this lead by hand) both block automated email. Do-not-contact is sticky (see `call_state`),
    so a later routine outcome cannot lift it."""
    dnc, effect = False, CONTINUE
    for event in sorted(events, key=_order):
        if event.get("Kind") != "OUTCOME":
            continue
        outcome = event.get("Outcome", "")
        if outcome == DO_NOT_CONTACT:
            dnc = True
        effect = STOP if dnc else (event.get("Email effect") or email_effect(outcome))
    return STOP if dnc else effect


def blocks_outreach(effect):
    """True when a call effect should stop automated email (a STOP or a HOLD)."""
    return effect in (STOP, HOLD)
