"""The outreach console: a private web app over the leads Sheet.

The pages are a React app (built with Vite, in `console/`), served from here as files. They are
given the console worked out from the Sheet by `console_model` (`GET /api/snapshot`), and one
question at a time may be put to the assistant (`POST /api/ask`, `outreach/assistant.py`).

**Nothing here writes**, to the Sheet or to Gmail. The one route that is not a GET only reads
the Sheet and asks the model; a test holds every other route to GET.

Only the accounts on the allow-list can open it. Google's sign-in gate (IAP) stands in front of
the service, and `console_auth` checks the gate's signed token on every request, the page files
included; without a valid token nothing is read or served.

    gunicorn outreach.console:app      # on Cloud Run, behind IAP (deploy/deploy_console.sh)
"""

import logging
import os
import threading
from datetime import datetime, timezone
from pathlib import Path

from flask import Flask, g, jsonify, request, send_from_directory

from outreach import assistant, console_auth, console_model, job_draft
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
_UNSET = object()
log = logging.getLogger("outreach.console")


def _now():
    return datetime.now(timezone.utc)


def create_app(*, verifier=_UNSET, store=Store, settings=job_draft.load_settings, clock=_now,
               static_dir=None, handbook_doc_id=""):
    """The console. `store`, `settings` and `clock` are called once per data request, and a test
    passes stand-ins for them. `verifier` None means not configured: every request is refused."""
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
        return send_from_directory(static, "index.html", max_age=0)

    @app.get("/assets/<path:name>")
    def asset(name):
        response = send_from_directory(static / "assets", name)
        response.headers["Cache-Control"] = ASSET_CACHE
        return response

    return app


def _deployed():
    logging.basicConfig(level=logging.INFO)
    return create_app(static_dir=os.environ.get("CONSOLE_STATIC_DIR") or None,
                      handbook_doc_id=os.environ.get("HANDBOOK_DOC_ID", ""))


app = _deployed()
