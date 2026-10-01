"""A/B tests over the leads: two named variants, a stable per-lead assignment, and variant-level
reporting with explicit denominators. Pure, like `sequence.py` and `calls.py`: it turns the recorded
rows into assignments and counts and never reads Google.

An experiment is a name and exactly two variant names. A lead is assigned to one variant, and the
assignment is IMMUTABLE once recorded. Two things guarantee a lead can never silently move between
variants:

  * the variant is DETERMINISTIC — a hash of the experiment name and the Lead ID, not random — so a
    refresh, a retry or a follow-up recomputes the same variant; and
  * the assignment is recorded by a content-hash Record ID of (experiment, lead), so a second
    assignment of the same lead is the same row and is skipped on append; and if two rows ever did
    exist for one lead, reading takes the EARLIEST (append order) and ignores the rest.

Reporting groups leads by a stable **variant index** (0/1), not by the recorded name, and labels each
group with the experiment's current definition. So renaming a variant changes only the label, never
which leads are in it.

Nothing here is connected to drafting. A variant has a NAME only; it carries no outreach copy, and
choosing it changes no email. The final Drive handbook and the approved offer — the only things that
feed real drafting — are untouched. The content a variant stands for is defined elsewhere, by the
founder, when the handbook and offer exist; this milestone assigns and measures, it does not draft.
"""

import hashlib
from collections import defaultdict

from outreach import calls, channels, eligibility
from outreach import sequence

# One append-only tab holds both the definition of an experiment and its assignments; a Kind column
# tells them apart (see `outreach/sheet.py`).
KIND_DEFINE = "DEFINE"
KIND_ASSIGN = "ASSIGN"

# Event types that would carry a "positive reply" or a "meeting". The pipeline does not produce
# either today, so both are reported as "not available" rather than a misleading zero, until a real
# recorded event of that type exists. Recognising them now means the report counts them the moment
# such events are recorded, without a code change.
MEETING = "MEETING"
POSITIVE_REPLY = "POSITIVE_REPLY"

# Below this many confirmed sends per variant, the report refuses to compare the two at all. Above
# it, it still does not declare a winner — a rate gap is not a significance test. This threshold is
# this system's choice, stated on screen, not a founder decision.
MIN_SENDS_TO_COMPARE = 30


def _hash(*parts):
    return hashlib.sha256("\x1f".join(str(p) for p in parts).encode("utf-8")).hexdigest()[:16]


def variant_index(experiment, lead_id):
    """Which variant (0 or 1) a lead takes in an experiment: deterministic, never random, so it is
    identical on every recomputation."""
    return int(_hash(experiment, lead_id), 16) & 1


def define_record_id(experiment, index, name):
    return _hash(KIND_DEFINE, experiment, index, name)


def assign_record_id(experiment, lead_id):
    # No index, name or time in the id: the SAME (experiment, lead) always has the SAME id, so a
    # re-assignment is skipped on append and a lead can never be recorded under two variants.
    return _hash(KIND_ASSIGN, experiment, lead_id)


def define_rows(experiment, variant_a, variant_b, now):
    """The two DEFINE rows for an experiment, or a ValueError if the names are not two distinct,
    non-empty strings. Appending them is idempotent: the same definition writes nothing new."""
    experiment = str(experiment or "").strip()
    names = [str(variant_a or "").strip(), str(variant_b or "").strip()]
    if not experiment:
        raise ValueError("name the experiment")
    if not names[0] or not names[1]:
        raise ValueError("give both variants a name")
    if names[0] == names[1]:
        raise ValueError("the two variants need different names")
    return [{"Record ID": define_record_id(experiment, index, name), "Experiment": experiment,
             "Kind": KIND_DEFINE, "Variant": name, "Variant index": str(index), "Lead ID": "",
             "Recorded at (UTC)": now}
            for index, name in enumerate(names)]


def assign_rows(experiment, variants, lead_ids, now):
    """ASSIGN rows for `lead_ids`, each at its deterministic variant. `variants` is the two current
    names, in index order. Appending is idempotent by Record ID."""
    experiment = str(experiment or "").strip()
    rows = []
    for lead_id in lead_ids:
        index = variant_index(experiment, lead_id)
        rows.append({"Record ID": assign_record_id(experiment, lead_id), "Experiment": experiment,
                     "Kind": KIND_ASSIGN, "Variant": variants[index], "Variant index": str(index),
                     "Lead ID": lead_id, "Recorded at (UTC)": now})
    return rows


def eligible(row):
    """Whether a lead may be assigned to a variant for an email A/B test: it must be a lead that
    could get a drafted email (an OK address, a qualified fit, not on hold, not already emailed by
    hand) and must actually have an email address."""
    ok, _why = eligibility.draft_eligible(row)
    return bool(ok and channels.email_of(row))


def read(records):
    """Parse the A/B tab's rows into {experiment: state}. `records` is in append order (oldest first).

    state = {"name", "variants": [name0, name1], "defined": bool, "assignments": {lead_id: index},
             "assigned_names": {lead_id: recorded name}, "define_order": int}.
    The latest DEFINE per (experiment, index) wins (a rename updates the label). The EARLIEST ASSIGN
    per (experiment, lead) wins (a lead never moves)."""
    defines = defaultdict(dict)   # experiment -> {index: name}
    define_seen = {}              # experiment -> position of its last DEFINE row (for "current")
    assigns = defaultdict(dict)   # experiment -> {lead_id: index}  (earliest wins)
    assigned_names = defaultdict(dict)
    for position, record in enumerate(records):
        experiment = str(record.get("Experiment", "")).strip()
        kind = str(record.get("Kind", "")).strip()
        if not experiment:
            continue
        if kind == KIND_DEFINE:
            try:
                index = int(str(record.get("Variant index", "")).strip())
            except ValueError:
                continue
            if index in (0, 1):
                defines[experiment][index] = str(record.get("Variant", ""))
                define_seen[experiment] = position
        elif kind == KIND_ASSIGN:
            lead_id = str(record.get("Lead ID", "")).strip()
            if not lead_id or lead_id in assigns[experiment]:
                continue  # earliest assignment wins; a later row for the same lead is ignored
            try:
                index = int(str(record.get("Variant index", "")).strip())
            except ValueError:
                continue
            if index in (0, 1):
                assigns[experiment][lead_id] = index
                assigned_names[experiment][lead_id] = str(record.get("Variant", ""))

    out = {}
    names = set(defines) | set(assigns)
    for experiment in names:
        variants = [defines[experiment].get(0, ""), defines[experiment].get(1, "")]
        out[experiment] = {
            "name": experiment,
            "variants": variants,
            "defined": bool(variants[0] and variants[1]),
            "assignments": dict(assigns[experiment]),
            "assigned_names": dict(assigned_names[experiment]),
            "define_order": define_seen.get(experiment, -1),
        }
    return out


def current(experiments):
    """The experiment to show: the one most recently defined, else (none defined) the one with the
    most assignments, else None."""
    if not experiments:
        return None
    defined = [s for s in experiments.values() if s["define_order"] >= 0]
    if defined:
        return max(defined, key=lambda s: s["define_order"])["name"]
    return max(experiments.values(), key=lambda s: len(s["assignments"]))["name"]


def variant_name(state, lead_id):
    """The current label for a lead's variant in an experiment, or "" if it is not assigned. Uses the
    current definition's name for the lead's stable index, falling back to the recorded name."""
    index = state["assignments"].get(lead_id)
    if index is None:
        return ""
    name = state["variants"][index] if index < len(state["variants"]) else ""
    return name or state["assigned_names"].get(lead_id, "")


def _lead_signals(lead_ids, by_event, by_call):
    """Per-lead booleans/counts worked out from the recorded events, for the given leads."""
    signals = {}
    for lead_id in lead_ids:
        events = by_event.get(lead_id, [])
        kinds = [e.get("Event") for e in events]
        tracked = any(e.get("Event") in (sequence.DRAFTED, sequence.FOLLOWUP_DRAFTED)
                      and sequence.TRACKED in [p.strip() for p in str(e.get("Detail", "")).split(",")]
                      for e in events)
        sent = any(e.get("Event") == sequence.SENT and e.get("Step") == sequence.INITIAL
                   and e.get("Match") in sequence.CONFIDENT for e in events)
        followups = sum(1 for e in events if e.get("Event") == sequence.SENT
                        and e.get("Step") in sequence.FOLLOWUPS)
        calls_made = any(c.get("Kind") == "OUTCOME" for c in by_call.get(lead_id, []))
        signals[lead_id] = {
            "drafted": sequence.DRAFTED in kinds,
            "sent": sent,
            "replied": sequence.REPLIED in kinds,
            "opted_out": sequence.OPT_OUT in kinds,
            "followups_sent": followups,
            "tracked": tracked,
            "opened": sequence.OPEN in kinds,
            "meeting": MEETING in kinds,
            "positive": POSITIVE_REPLY in kinds,
            "called": calls_made,
        }
    return signals


def percent(top, bottom):
    """A whole percent as the console shows it; '-' when there is nothing to divide by. Same rule as
    `console_model.percent`, kept here so this pure module does not import the model."""
    if not bottom:
        return "-"
    return f"{round(100 * top / bottom)}%"


def _metric(key, label, count, denominator, denominator_label, **extra):
    return {"key": key, "label": label, "available": True, "count": count,
            "denominator": denominator, "denominator_label": denominator_label,
            "rate": percent(count, denominator), **extra}


def _unavailable(key, label, why, **extra):
    return {"key": key, "label": label, "available": False, "why": why, **extra}


def _variant_metrics(lead_ids, signals, suppressed, *, meetings_recorded, positives_recorded):
    """The ordered metric rows for one variant's leads, each with its explicit denominator."""
    assigned = len(lead_ids)
    sig = [signals[lid] for lid in lead_ids]
    drafted = sum(1 for s in sig if s["drafted"])
    sent = sum(1 for s in sig if s["sent"])
    replies = sum(1 for s in sig if s["replied"])
    opt_outs = sum(1 for s in sig if s["opted_out"])
    calls_made = sum(1 for s in sig if s["called"])
    followups = sum(s["followups_sent"] for s in sig)
    tracked = sum(1 for s in sig if s["tracked"])
    opened = sum(1 for s in sig if s["opened"])
    positives = sum(1 for s in sig if s["positive"])
    meetings = sum(1 for s in sig if s["meeting"])

    metrics = [
        _metric("assigned", "Assigned", assigned, assigned, "assigned"),
        _metric("drafted", "Drafted", drafted, assigned, "assigned"),
        _metric("sent", "Confirmed sent", sent, assigned, "assigned",
                note="a recorded send, not a confirmed delivery"),
        _metric("replies", "Replies", replies, sent, "confirmed sent",
                note="human replies; excludes auto-replies and requests to stop"),
        _metric("opt_outs", "Opt-outs", opt_outs, sent, "confirmed sent"),
        _metric("calls", "Calls made", calls_made, assigned, "assigned"),
        _metric("followups", "Follow-up emails sent", followups, sent, "confirmed sent"),
        _metric("opens", "Opens", opened, tracked, "tracked sends", estimate=True,
                note="an estimate: images load on their own in some mail apps and are blocked in others"),
    ]
    # Positive replies and meetings need a real recorded signal. The pipeline does not produce either
    # yet, so they are "not available" rather than a zero that would read as "we checked and found
    # none". They become available automatically once such events are recorded.
    positive_metric = (_metric("positive_replies", "Positive replies", positives, replies, "replies")
                       if positives_recorded else
                       _unavailable("positive_replies", "Positive replies",
                                    "no positive-reply signal is recorded yet"))
    meeting_metric = (_metric("meetings", "Meetings", meetings, sent, "confirmed sent")
                      if meetings_recorded else
                      _unavailable("meetings", "Meetings",
                                   "no meeting is recorded; a meeting is counted only from a real "
                                   "recorded meeting event"))
    # Order: funnel, then replies/positive/opt-outs, then calls/follow-ups, then meetings, then opens.
    metrics = (metrics[:4] + [positive_metric] + metrics[4:7] + [meeting_metric] + [metrics[7]])
    return assigned, sent, metrics, suppressed


def report(state, leads, events, call_events, entries, *, now=None):
    """The variant-level report for one experiment. `leads` is {lead_id: row}; `events` the Events
    rows; `call_events` the Call log rows (or None if unreadable); `entries` the Suppression entries
    (or None if unreadable). Counts and rates only — no probability, no declared winner."""
    by_event = defaultdict(list)
    for event in events:
        by_event[event.get("Lead ID", "")].append(event)
    calls_unreadable = call_events is None
    by_call = defaultdict(list)
    for event in call_events or ():
        by_call[event.get("Lead ID", "")].append(event)

    meetings_recorded = any(e.get("Event") == MEETING for e in events)
    positives_recorded = any(e.get("Event") == POSITIVE_REPLY for e in events)

    assignments = state["assignments"]
    all_assigned = list(assignments)
    signals = _lead_signals(all_assigned, by_event, by_call)

    # Suppressed-but-assigned, for context only (an assignment is immutable; a lead later suppressed
    # is still counted as assigned, and flagged so the founder can read the number honestly).
    suppressed_unknown = entries is None
    suppressed_of = {}
    if not suppressed_unknown:
        from outreach import suppression as suppression_contract
        for lead_id in all_assigned:
            email = channels.email_of(leads.get(lead_id, {}))
            suppressed_of[lead_id] = bool(email and suppression_contract.covers(entries, email))

    variants_out, sends = [], []
    for index in (0, 1):
        lead_ids = [lid for lid in all_assigned if assignments[lid] == index]
        suppressed = (None if suppressed_unknown
                      else sum(1 for lid in lead_ids if suppressed_of.get(lid)))
        assigned, sent, metrics, suppressed = _variant_metrics(
            lead_ids, signals, suppressed,
            meetings_recorded=meetings_recorded, positives_recorded=positives_recorded)
        name = state["variants"][index] if index < len(state["variants"]) else ""
        variants_out.append({"index": index, "name": name or f"Variant {index + 1}",
                             "assigned": assigned, "suppressed": suppressed,
                             "lead_ids": lead_ids, "metrics": metrics})
        sends.append(sent)

    can_compare = all(s >= MIN_SENDS_TO_COMPARE for s in sends)
    comparison = {
        "winner": None, "can_compare": can_compare, "min_sends_to_compare": MIN_SENDS_TO_COMPARE,
        "note": ("Each variant has enough confirmed sends to compare, but no winner is declared: a "
                 "difference in these rates is not a statistical significance test."
                 if can_compare else
                 f"Too few confirmed sends to compare: each variant needs at least "
                 f"{MIN_SENDS_TO_COMPARE}. The counts above are shown without a verdict."),
    }
    notes = [
        "Confirmed sent means a send was recorded, not that it was delivered; a bounce is the only "
        "delivery signal and is counted against the lead, not here.",
        "Opens are an estimate and are labelled so.",
        "A lead's variant never changes once assigned, so a refresh or a follow-up cannot move it.",
    ]
    if calls_unreadable:
        notes.append("The Call log could not be read, so calls are shown as 0; reload to try again.")
    if suppressed_unknown:
        notes.append("The Suppression list could not be read, so suppressed-but-assigned counts are "
                     "not shown.")
    return {"name": state["name"], "defined": state["defined"],
            "variants": variants_out, "comparison": comparison, "notes": notes,
            "calls_unreadable": calls_unreadable, "suppression_unreadable": suppressed_unknown}
