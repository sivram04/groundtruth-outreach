"""Cloud Run worker. Private: only authenticated callers (Cloud Scheduler) reach it."""

import os

from flask import Flask, jsonify, request

from outreach import (auto_send, followup, job_auto, job_check, job_draft, job_profile,
                      job_research, sheet, sync, tracking_job)

app = Flask(__name__)


@app.post("/jobs/ping")
def ping():
    counts = sheet.ping(where="cloud-run")
    return jsonify(ok=True, leads=counts)


@app.post("/jobs/check")
def check():
    return jsonify(ok=True, **job_check.run(where="cloud-run"))


@app.post("/jobs/research")
def research():
    limit = int(request.args.get("limit", job_research.DEFAULT_LIMIT))
    ids = set(request.args["ids"].split(",")) if request.args.get("ids") else None
    return jsonify(ok=True, **job_research.run(where="cloud-run", limit=limit, ids=ids))


@app.post("/jobs/profile")
def profile():
    try:
        limit = int(request.args.get("limit", job_profile.MAX_LIMIT))
    except ValueError:
        return jsonify(ok=False, error="invalid limit"), 400
    ids = set(request.args["ids"].split(",")) if request.args.get("ids") else None
    if not 1 <= limit <= job_profile.MAX_LIMIT or (ids is not None and len(ids) > job_profile.MAX_LIMIT):
        return jsonify(ok=False, error="profile limit is five leads"), 400
    return jsonify(ok=True, **job_profile.run(where="cloud-run", limit=limit, ids=ids,
                                             dry_run=request.args.get("dry_run") == "1"))


@app.post("/jobs/auto")
def auto_research():
    """Roadmap #5: check, research and profile whatever is pending, in one pass, so a lead added
    by Import or the chat assistant is assessed without anyone calling a job by hand."""
    return jsonify(ok=True, **job_auto.run(where="cloud-run"))


@app.post("/jobs/draft/preview")
def draft_preview():
    ids = request.get_json(silent=True) or {}
    try:
        # Every live preview must use the Drive handbook and Gemini writer.
        return jsonify(ok=True, previews=job_draft.previews(
            ids.get("ids", []), write=True))
    except job_draft.DraftBlocked as exc:
        return jsonify(ok=False, error=str(exc)), 400


@app.post("/jobs/draft/create")
def draft_create():
    # Keep live Gmail writes disabled until the founder reviews the pilot previews.
    if os.environ.get("ENABLE_GMAIL_DRAFTS") != "true":
        return jsonify(ok=False, error="Gmail draft creation is disabled"), 403
    body = request.get_json(silent=True) or {}
    try:
        result = job_draft.create(body.get("lead_id", ""), body.get("approved_hash", ""),
                                  written=body.get("written"))
        return jsonify(ok=True, **result)
    except job_draft.DraftBlocked as exc:
        return jsonify(ok=False, error=str(exc)), 400


@app.post("/jobs/draft/reconcile")
def draft_reconcile():
    if os.environ.get("ENABLE_GMAIL_DRAFTS") != "true":
        return jsonify(ok=False, error="Gmail draft reconciliation is disabled"), 403
    body = request.get_json(silent=True) or {}
    try:
        return jsonify(ok=True, **job_draft.reconcile(body.get("lead_id", "")))
    except job_draft.DraftBlocked as exc:
        return jsonify(ok=False, error=str(exc)), 400


@app.post("/jobs/sync")
def sync_job():
    """Stage 4: record sends, replies, bounces and opt-outs. `?dry_run=1` writes nothing."""
    try:
        return jsonify(ok=True, **sync.run(where="cloud-run",
                                           dry_run=request.args.get("dry_run") == "1"))
    except sync.SyncBlocked as exc:
        return jsonify(ok=False, error=str(exc)), 400


@app.post("/jobs/tracking")
def tracking_run():
    """Stage 5: queued tracker hits become OPEN and CLICK events. Acknowledged after writing."""
    return jsonify(ok=True, **tracking_job.run(where="cloud-run"))


@app.post("/jobs/followup")
def followup_job():
    """Stage 4: draft the follow-ups that are due. `?dry_run=1` only reports who is due."""
    dry_run = request.args.get("dry_run") == "1"
    if not dry_run and os.environ.get("ENABLE_GMAIL_DRAFTS") != "true":
        return jsonify(ok=False, error="Gmail draft creation is disabled"), 403
    try:
        return jsonify(ok=True, **followup.run(where="cloud-run", dry_run=dry_run))
    except followup.FollowupBlocked as exc:
        return jsonify(ok=False, error=str(exc)), 400


@app.post("/jobs/send")
def send_job():
    """Send as many already-created, already-approved drafts as today's cap allows.

    The one scheduled job allowed to reach ``outreach.send``. Off unless ENABLE_AUTO_SEND is set;
    ``outreach.auto_send.run`` also requires the daily cap in settings and re-checks the call log
    and suppression list for every lead at send time, not just at draft-creation time.
    """
    try:
        return jsonify(ok=True, **auto_send.run())
    except auto_send.AutoSendBlocked as exc:
        return jsonify(ok=False, error=str(exc)), 403


@app.post("/jobs/followup/preview")
def followup_preview():
    return jsonify(ok=True, **followup.preview())


@app.post("/jobs/followup/reconcile")
def followup_reconcile():
    if os.environ.get("ENABLE_GMAIL_DRAFTS") != "true":
        return jsonify(ok=False, error="Gmail draft reconciliation is disabled"), 403
    body = request.get_json(silent=True) or {}
    try:
        return jsonify(ok=True, **followup.reconcile(body.get("lead_id", "")))
    except followup.FollowupBlocked as exc:
        return jsonify(ok=False, error=str(exc)), 400


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))
