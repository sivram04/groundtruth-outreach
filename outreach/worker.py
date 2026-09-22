"""Cloud Run worker. Private: only authenticated callers (Cloud Scheduler) reach it."""

import os

from flask import Flask, jsonify, request

from outreach import job_check, job_research, sheet

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


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))
