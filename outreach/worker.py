"""Cloud Run worker. Private: only authenticated callers (Cloud Scheduler) reach it."""

import os

from flask import Flask, jsonify, request

from outreach import job_check, job_draft, job_profile, job_research, sheet

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


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))
