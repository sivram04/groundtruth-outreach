"""Cloud Run worker. Private: only authenticated callers (Cloud Scheduler) reach it."""

import os

from flask import Flask, jsonify

from outreach import sheet

app = Flask(__name__)


@app.post("/jobs/ping")
def ping():
    counts = sheet.ping(where="cloud-run")
    return jsonify(ok=True, leads=counts)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))
