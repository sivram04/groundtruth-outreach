"""The outreach console: a private web app over the leads Sheet.

The pages are a React app (built with Vite, in `console/`), served from here as files. They are
given the console worked out from the Sheet by `console_model` (`GET /api/snapshot`), and one
question at a time may be put to the assistant (`POST /api/ask`, `outreach/assistant.py`).

**Nothing here writes to the Sheet or to Gmail.** By default the one route that is not a GET only
reads the Sheet and asks the model; a test holds every other route to GET. When, and only when,
the review flow is explicitly switched on (`enable_review`, off in the deployed console), two more
routes appear so a person can read a candidate beside its cited evidence and confirm or reject it;
that decision is written to the injected review store (a local file in the local flow), never to
the live Sheet, and it neither sends nor drafts anything.

Only the accounts on the allow-list can open it. Google's sign-in gate (IAP) stands in front of
the service, and `console_auth` checks the gate's signed token on every request, the page files
included; without a valid token nothing is read or served.

    gunicorn outreach.console:app      # on Cloud Run, behind IAP (deploy/deploy_console.sh)
"""

import json
import logging
import os
import re
import threading
from datetime import datetime, timezone
from pathlib import Path

from flask import Flask, g, jsonify, request, send_from_directory

from outreach import assistant, console_auth, console_model, job_draft, review
from outreach.sheet import Store

DEFAULT_STATIC = Path(__file__).resolve().parent.parent / "console" / "dist"
SECURITY_HEADERS = {
    # Scripts and styles only from the console's own files; nothing may frame it.
    "Content-Security-Policy": ("default-src 'none'; script-src 'self'; style-src 'self'; "
                                "img-src 'self' data:; font-src 'self'; connect-src 'self'; "
                                "base-uri 'none'; form-action 'self'; frame-ancestors 'none'"),
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
}
# The built files' names carry a hash of their content, so a browser may keep them; the page
# itself and the data are never kept.
ASSET_CACHE = "private, max-age=31536000, immutable"
NO_STORE = "no-store"
# The built page names its own script, e.g. <script src="/assets/index-a1b2c3.js">.
BUILT_SCRIPT = re.compile(r'src="/assets/(index-[^"]+.js)"')
_UNSET = object()
log = logging.getLogger("outreach.console")


def _now():
    return datetime.now(timezone.utc)


def create_app(*, verifier=_UNSET, store=Store, settings=job_draft.load_settings, clock=_now,
               static_dir=None, handbook_doc_id="", review_store=None, enable_review=False):
    """The console. `store`, `settings` and `clock` are called once per data request, and a test
    passes stand-ins for them. `verifier` None means not configured: every request is refused.

    `enable_review` adds the human evidence-review flow (a candidate beside its cited evidence, and
    confirm/reject actions writing to `review_store`). It is off in the deployed console, so the
    read-only guarantee holds there; when on, review decisions go to the injected store, never to
    the live Sheet."""
    app = Flask(__name__, static_folder=None)
    checker = console_auth.from_environment() if verifier is _UNSET else verifier
    static = Path(static_dir) if static_dir else DEFAULT_STATIC
    # One Sheets client serves the whole process and is not safe to use from two threads at once.
    reading = threading.Lock()

    def refuse(status, why):
        if request.path.startswith("/api/"):
            response = jsonify(error=why)
        else:
            response = app.response_class(why + "\n", mimetype="text/plain")
        response.status_code = status
        return response

    @app.before_request
    def signed_in():
        if checker is None:
            return refuse(503, "The console is not configured, so it opens for nobody.")
        try:
            g.email = checker.email(request.headers.get(console_auth.HEADER))
        except console_auth.Refused as exc:
            log.info("refused %s %s: %s", request.method, request.path, exc)
            return refuse(exc.status, str(exc))
        return None

    @app.after_request
    def headers(response):
        response.headers.update(SECURITY_HEADERS)
        response.headers.setdefault("Cache-Control", NO_STORE)
        return response

    @app.errorhandler(404)
    def not_found(_):
        return refuse(404, "There is no such page.")

    @app.errorhandler(405)
    def not_allowed(_):
        return refuse(405, "The console only reads: nothing else can be sent to it.")

    def built():
        """The name of the pages' own script, which changes with every build."""
        try:
            found = BUILT_SCRIPT.search((static / "index.html").read_text(encoding="utf-8"))
        except OSError:
            return ""
        return found.group(1) if found else ""

    def console():
        """The console worked out from the Sheet now, or a refusal to show instead."""
        try:
            chosen = settings() or {}
        except Exception:  # unreadable settings must not close the whole console
            log.exception("the drafting settings could not be read")
            chosen = {}
        try:
            with reading:
                data = console_model.snapshot(store(), settings=chosen, now=clock(),
                                              handbook_doc_id=handbook_doc_id)
        except Exception:
            log.exception("the Sheet could not be read")
            return None, refuse(502, "The Sheet could not be read just now. Nothing was "
                                     "changed; try again in a minute.")
        data["signed_in_as"] = g.email
        data["build"] = built()
        return data, None

    @app.get("/api/snapshot")
    def snapshot():
        data, refused = console()
        return refused or jsonify(data)

    @app.post("/api/ask")
    def ask():
        """The assistant answers one question about the founder's own outreach. It reads the
        Sheet, puts the question to the model with that data, and shows nothing the data does
        not support. It writes nothing, here or anywhere."""
        question = (request.get_json(silent=True) or {}).get("question", "")
        data, refused = console()
        if refused:
            return refused
        try:
            answered = assistant.ask(question, data)
        except assistant.Refused as exc:
            log.info("assistant refused for %s: %s", g.email, exc.why)
            return jsonify(answer=exc.said, refused=True), 200
        log.info("assistant answered for %s (%s tokens)", g.email, answered.get("tokens"))
        return jsonify(**answered, refused=False)

    @app.get("/")
    def page():
        if not (static / "index.html").is_file():
            return refuse(503, "The console's pages have not been built.")
        answer = send_from_directory(static, "index.html", max_age=0)
        # Never kept, not even for a moment: a browser holding this page would keep running an
        # older console after a deploy, and the founder would see no change.
        answer.headers["Cache-Control"] = NO_STORE
        answer.headers.pop("ETag", None)
        answer.headers.pop("Last-Modified", None)
        return answer

    @app.get("/assets/<path:name>")
    def asset(name):
        response = send_from_directory(static / "assets", name)
        response.headers["Cache-Control"] = ASSET_CACHE
        return response

    def _candidate(lead_id):
        """The stored candidate for a lead, or (None, refusal). Reads the Drafts tab only."""
        try:
            with reading:
                rows = store().drafts()
        except Exception:
            log.exception("the Drafts tab could not be read")
            return None, refuse(502, "The Sheet could not be read just now.")
        row = next((r for _, r in rows if r.get("Lead ID") == lead_id), None)
        if row is None or not (row.get("Written") or "").strip():
            return None, refuse(404, "There is no candidate to review for this lead.")
        try:
            written = json.loads(row["Written"])
        except (ValueError, KeyError):
            return None, refuse(502, "The stored candidate could not be read.")
        return ({"lead_id": row.get("Lead ID", ""), "to": row.get("To", ""),
                 "subject": row.get("Subject", ""), "body": row.get("Body", ""),
                 "handbook_hash": row.get("Handbook hash", ""),
                 "evidence": (written or {}).get("evidence"), "written": written}), None

    def _chosen_settings():
        try:
            return settings() or {}
        except Exception:
            log.exception("the drafting settings could not be read")
            return {}

    if enable_review:
        reviews = review.default_store() if review_store is None else review_store

        @app.get("/api/review/<lead_id>")
        def review_candidate(lead_id):
            candidate, refused = _candidate(lead_id)
            if refused:
                return refused
            chosen = _chosen_settings()
            existing = reviews.get(lead_id)
            return jsonify(review.review_view(candidate, None, chosen, existing=existing))

        @app.post("/api/review/<lead_id>")
        def record_review(lead_id):
            candidate, refused = _candidate(lead_id)
            if refused:
                return refused
            chosen = _chosen_settings()
            fingerprint = review.candidate_fingerprint(candidate, None, chosen)
            body = request.get_json(silent=True) or {}
            decision = str(body.get("decision", "")).strip().lower()
            if body.get("fingerprint") != fingerprint:
                return refuse(409, "The candidate changed since it was shown; reload and review it "
                                   "again.")
            if decision not in ("confirm", "reject"):
                return refuse(400, "A review is either confirm or reject.")
            record = (review.record_confirmation if decision == "confirm"
                      else review.record_rejection)(reviews, lead_id, g.email, fingerprint,
                                                    now=clock())
            log.info("review %s by %s for %s", record["decision"], g.email, lead_id)
            return jsonify(review.review_view(candidate, None, chosen, existing=reviews.get(lead_id)))

    return app


def _deployed():
    logging.basicConfig(level=logging.INFO)
    # The review flow is off unless explicitly switched on. Even when on, its store is fail-closed
    # (the Sheet's Reviews tab is not migrated) unless a local file is configured, so it never
    # writes to the live Sheet.
    enable_review = os.environ.get("ENABLE_REVIEW") == "true"
    review_path = os.environ.get("REVIEW_STORE_PATH", "").strip()
    review_store = review.JsonFileReviewStore(review_path) if review_path else None
    return create_app(static_dir=os.environ.get("CONSOLE_STATIC_DIR") or None,
                      handbook_doc_id=os.environ.get("HANDBOOK_DOC_ID", ""),
                      enable_review=enable_review, review_store=review_store)


app = _deployed()
