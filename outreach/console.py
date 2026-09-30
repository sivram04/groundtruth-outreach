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
import uuid
from datetime import datetime, timezone
from pathlib import Path

from flask import Flask, g, jsonify, request, send_from_directory

from outreach import assistant, calls, channels, console_auth, console_model, importer, job_draft, review
from outreach.sheet import LEAD_TABS, DestinationMismatch, Store

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


# A single import at once is a small list, and an upload is capped so a huge file cannot be posted.
MAX_IMPORT_BYTES = 2_000_000


def create_app(*, verifier=_UNSET, store=Store, settings=job_draft.load_settings, clock=_now,
               static_dir=None, handbook_doc_id="", review_store=None, enable_review=False,
               review_signer=None, enable_import=False, enable_calls=False):
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
                                              handbook_doc_id=handbook_doc_id,
                                              calls_enabled=enable_calls)
        except Exception:
            log.exception("the Sheet could not be read")
            return None, refuse(502, "The Sheet could not be read just now. Nothing was "
                                     "changed; try again in a minute.")
        data["signed_in_as"] = g.email
        data["build"] = built()
        data["import_enabled"] = enable_import
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
            fingerprint = review.candidate_fingerprint(candidate, None, chosen)
            # The current status is resolved from the SIGNED chain with the trusted verifier, so a
            # conflicted, tampered or unverifiable history never shows as current approval.
            status = review.resolved_status(reviews, lead_id, fingerprint,
                                            review.configured_verifier(chosen))
            return jsonify(review.review_view(candidate, None, chosen, status=status))

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
            if review_signer is None:
                # No signing authority configured: an authenticated review cannot be recorded, and we
                # do not fall back to an unsigned write.
                return refuse(503, "Review signing is not configured, so a review cannot be recorded.")
            # SAVE the review, signed. The reviewer is the IAP-verified signed-in identity (g.email),
            # never a body field.
            try:
                (review.record_confirmation if decision == "confirm"
                 else review.record_rejection)(reviews, lead_id, g.email, fingerprint, now=clock(),
                                               signer=review_signer)
            except review.ReviewsUncertain:
                # The write MAY have landed; never claim nothing changed.
                log.exception("the review outcome is uncertain")
                return refuse(502, "The review may or may not have been recorded - the outcome is "
                                   "uncertain. Reload to check before acting; do not assume it was "
                                   "or was not saved, and do not retry blindly.")
            except Exception:
                # The save failed; nothing was recorded.
                log.exception("the review could not be recorded")
                return refuse(502, "The review could not be recorded just now. Nothing was changed.")
            # The save SUCCEEDED. Reading the current status back is a SEPARATE step, resolved from the
            # signed chain: if it cannot be verified/read, the review is still recorded - never say
            # "nothing was changed" or show approval as current.
            status = review.resolved_status(reviews, lead_id, fingerprint,
                                            review.configured_verifier(chosen))
            # A clean, readable tip ("resolved") is the only status we show as current. Anything else
            # - unreadable, unverifiable, or a conflicted/tampered history - means the save landed but
            # the current decision cannot be trusted, so we acknowledge the save and flag the status
            # unavailable rather than render a failed history as a decision.
            if status.get("state") != review.RESOLVED:
                return jsonify(recorded=True, status_unavailable=True,
                               message="Your review was recorded, but its current status could not "
                                       "be loaded. Reload before continuing.")
            log.info("review %s by %s for %s", decision, g.email, lead_id)
            return jsonify(review.review_view(candidate, None, chosen, status=status))

    if enable_import:
        # Lead import writes new rows to the Sheet, so it is OFF by default and in deployment; a test
        # holds every other route to GET. Two steps: a preview that writes nothing, then a commit that
        # appends only new rows. Neither ever rewrites a founder's existing row.
        def _prefix(value):
            prefix = str(value or "A").strip().upper() or "A"
            return prefix if prefix in set(LEAD_TABS.values()) else None

        @app.post("/api/import/preview")
        def import_preview():
            """Read the uploaded/pasted list and show what would be stored. Writes nothing."""
            upload = request.files.get("file")
            if upload is not None:
                data = upload.read(MAX_IMPORT_BYTES + 1)
                if len(data) > MAX_IMPORT_BYTES:
                    return refuse(413, "That file is too large. Import a smaller list (under 2 MB).")
                prefix = _prefix(request.form.get("prefix", "A"))
                try:
                    records = importer.records_from_file(upload.filename, data)
                except ValueError as exc:
                    return refuse(400, str(exc))
                except Exception:
                    log.exception("an uploaded file could not be read")
                    return refuse(400, "That file could not be read. Check it is a valid CSV, TSV or "
                                       "XLSX file.")
            else:
                body = request.get_json(silent=True) or {}
                text = str(body.get("text", ""))
                if len(text.encode("utf-8", "ignore")) > MAX_IMPORT_BYTES:
                    return refuse(413, "That is too much text to import at once. Import a smaller list.")
                prefix = _prefix(body.get("prefix", "A"))
                records = importer.records_from_csv(text)
            if prefix is None:
                return refuse(400, "Choose which tab to import into (A or B).")
            if not records:
                return refuse(400, "No rows to import were found. Paste rows with a header line, or "
                                   "choose a file.")
            if len(records) > importer.MAX_ROWS:
                return refuse(413, f"That is {len(records)} rows; import at most {importer.MAX_ROWS} "
                                   f"at a time.")
            try:
                with reading:
                    st = store()
                    existing, columns = st.leads(), st.lead_columns(prefix)
            except Exception:
                log.exception("the Sheet could not be read for an import preview")
                return refuse(502, "The Sheet could not be read just now. Nothing was changed; try "
                                   "again in a minute.")
            return jsonify(importer.import_leads(records, existing, prefix=prefix,
                                                 destination_columns=columns))

        @app.post("/api/import/commit")
        def import_commit():
            """Append the previewed rows once, coordinating concurrent and repeated attempts.

            The Lead IDs were assigned at preview and travel in the rows; the destination schema is
            revalidated. `idempotency_key` names the logical import (durable, reused on a resume); each
            request is one **attempt** (a fresh token), so two attempts of the SAME operation submitted
            at once still resolve to a single writer. Outcomes are explicit: done, pending (an earlier
            attempt of this import owns some leads - resume to finish), or uncertain (a write could not
            be confirmed - never reported as "nothing written")."""
            body = request.get_json(silent=True) or {}
            prefix = _prefix(body.get("prefix", "A"))
            rows = body.get("rows")
            op_key = str(body.get("idempotency_key", "")).strip()
            attempt = uuid.uuid4().hex  # this execution; distinct even when op_key is reused
            if prefix is None or not isinstance(rows, list) or not op_key:
                return refuse(400, "The import to confirm was not understood. Preview it again.")
            with reading:
                try:
                    st = store()
                    existing = st.leads()
                    columns = st.lead_columns(prefix)
                except Exception:
                    log.exception("the Sheet could not be read for an import commit")
                    return refuse(502, "The Sheet could not be read just now. Nothing was changed; "
                                       "try again in a minute.")
                if importer.fingerprint(rows, prefix, columns) != body.get("fingerprint", ""):
                    return refuse(409, "This preview is out of date (the rows or the destination's "
                                       "columns changed). Preview the list again before confirming.")
                to_append, already = importer.prepare_commit(rows, existing, prefix=prefix)
                if not to_append:
                    return jsonify(outcome="done", written=0, already_present=len(already),
                                   claimed_elsewhere=0, pending=0, lead_ids=[])
                try:
                    claim = st.claim_leads([row["Lead ID"] for row in to_append], op_key, attempt)
                except Exception:
                    log.exception("an import could not be coordinated")
                    return refuse(502, "The import could not be coordinated just now. Nothing was "
                                       "changed; try again in a minute.")
                won = [row for row in to_append if claim.get(row["Lead ID"]) == "won"]
                mine_prior = [row for row in to_append if claim.get(row["Lead ID"]) == "mine_prior"]
                other = [row for row in to_append if claim.get(row["Lead ID"]) == "other"]
                # EXCLUSIVE WRITE OWNERSHIP: only the earliest claim (this attempt won it) may write.
                # A resume does NOT take over its own earlier attempt's leads - append-only Sheets cannot
                # prove that earlier attempt has stopped, so a takeover could double-write it. Resume is
                # read-only reconciliation: `mine_prior` leads are reported pending, never written.
                writable = won
                pending = mine_prior
                if not writable:
                    # Nothing this attempt may write: pending (our own earlier attempt owns them and
                    # has not finished - check again once it does) or blocked (another operation owns
                    # them). Never "done", and never written by this request.
                    outcome = "pending" if pending else ("blocked" if other else "done")
                    return jsonify(outcome=outcome, written=0, already_present=len(already),
                                   claimed_elsewhere=len(other), pending=len(pending), lead_ids=[])
                try:
                    lead_ids = st.append_leads(prefix, writable)
                except DestinationMismatch as exc:
                    log.info("import refused: %s", exc)
                    return refuse(409, "The destination's columns changed since the preview, so a "
                                       "field would be lost. Nothing was written; preview again.")
                except Exception:
                    log.exception("an import append is uncertain; reconciling by lead id")
                    # NEVER equate an unreadable store with an absent row. Only a SUCCESSFUL read that
                    # shows absence means "nothing written"; a failed read is an explicit unknown.
                    try:
                        landed = store().leads()
                    except Exception:
                        log.exception("the reconciliation read also failed; outcome is unknown")
                        return jsonify(outcome="uncertain", written=None, already_present=len(already),
                                       claimed_elsewhere=len(other), pending=len(pending),
                                       message="The import could not be confirmed: the store could not "
                                               "be read after the write, so it may or may not have "
                                               "saved. Reload to check; do not assume it did or did "
                                               "not, and do not blindly repeat it."), 200
                    present = [row["Lead ID"] for row in writable if row["Lead ID"] in landed]
                    if present and len(present) == len(writable):
                        log.info("import reconciled: the write had landed despite the error")
                        return jsonify(outcome="done", written=len(present), already_present=len(already),
                                       claimed_elsewhere=len(other), pending=len(pending),
                                       lead_ids=present, reconciled=True)
                    if not present:
                        return refuse(502, "The import could not be saved. Nothing was written; "
                                           "confirming again is safe - already-saved rows are not "
                                           "added twice.")
                    return jsonify(outcome="uncertain", written=len(present),
                                   already_present=len(already), claimed_elsewhere=len(other),
                                   pending=len(pending), lead_ids=present,
                                   message="Some rows may not be saved. Reload to check; confirming "
                                           "again is safe, as already-saved rows are not added twice."), 200
            outcome = ("pending" if pending
                       else "blocked" if (other and not lead_ids) else "done")
            log.info("import: %s rows into %s by %s (%s)", len(lead_ids), prefix, g.email, outcome)
            return jsonify(outcome=outcome, written=len(lead_ids), already_present=len(already),
                           claimed_elsewhere=len(other), pending=len(pending), lead_ids=lead_ids)

    if enable_calls:
        # Recording a call outcome writes to the Sheet (the Call log, and Suppression for a stop), so it
        # is OFF by default and in deployment. It never sends or drafts anything.
        def _call_state_for(st, lead_id, now):
            events = [e for e in st.call_events() if e.get("Lead ID") == lead_id]
            state = calls.call_state(events, now=now)
            return {"task": console_model.call_task_view(state["task"]),
                    "history": console_model.call_history_view(state["history"]),
                    "effect": state["email_effect"]}

        @app.post("/api/calls/<lead_id>/outcome")
        def call_outcome(lead_id):
            """Record a call outcome and schedule the next call. Idempotent: the same outcome twice
            adds no second task. A do-not-contact/not-interested outcome also suppresses the email."""
            body = request.get_json(silent=True) or {}
            outcome = str(body.get("outcome", "")).strip().upper()
            if outcome not in calls.OUTCOMES:
                return refuse(400, "That is not a call outcome I recognise.")
            chosen = _chosen_settings()
            try:
                rule = int(chosen.get("call_no_answer_business_days",
                                      calls.DEFAULT_NO_ANSWER_BUSINESS_DAYS))
            except (TypeError, ValueError):
                rule = calls.DEFAULT_NO_ANSWER_BUSINESS_DAYS
            now = clock()
            called_at = str(body.get("called_at", "")).strip() or now.isoformat()
            try:
                event = calls.outcome_event(lead_id, outcome, body.get("note", ""), called_at,
                                            no_answer_business_days=rule,
                                            callback_at=body.get("callback_at"), now=now)
            except ValueError as exc:
                return refuse(400, str(exc))  # e.g. a callback with no explicit time
            with reading:
                try:
                    st = store()
                    leads = st.leads()
                except Exception:
                    log.exception("the Sheet could not be read to record a call")
                    return refuse(502, "The Sheet could not be read just now. Nothing was changed.")
                if lead_id not in leads:
                    return refuse(404, "There is no such lead.")
                try:
                    st.append_call_events([event])
                except Exception:
                    log.exception("a call outcome could not be recorded")
                    return refuse(502, "The call could not be recorded just now. Try again; recording "
                                       "the same outcome twice does not create a duplicate task.")
                if calls.email_effect(outcome) == calls.STOP:
                    email = channels.email_of(leads.get(lead_id, {}))
                    if email:
                        try:
                            st.append_suppression([{
                                "Address or domain": email,
                                "Reason": f"call: {outcome.lower().replace('_', ' ')}",
                                "Added at": now.astimezone(timezone.utc).isoformat(),
                                "Source": f"call: {lead_id}"}])
                        except Exception:  # the call is recorded; suppression is best-effort here
                            log.exception("the call's suppression entry could not be written")
                state = _call_state_for(st, lead_id, now)
            log.info("call %s for %s by %s", outcome, lead_id, g.email)
            return jsonify(recorded=True, **state)

        @app.post("/api/calls/<lead_id>/task")
        def call_task_action(lead_id):
            """Complete, snooze or cancel the lead's current call task. Idempotent per task."""
            body = request.get_json(silent=True) or {}
            action = str(body.get("action", "")).strip().upper()
            if action not in calls.ACTIONS:
                return refuse(400, "That is not a task action I recognise.")
            now = clock()
            with reading:
                try:
                    st = store()
                    events = [e for e in st.call_events() if e.get("Lead ID") == lead_id]
                except Exception:
                    log.exception("the Sheet could not be read to act on a call task")
                    return refuse(502, "The Sheet could not be read just now. Nothing was changed.")
                task = calls.call_state(events, now=now)["task"]
                if not task or task["status"] != "scheduled":
                    return refuse(409, "There is no open call task for this lead. Reload and try again.")
                try:
                    event = calls.action_event(lead_id, action, task["id"],
                                               snooze_to=body.get("snooze_to"), now=now)
                except ValueError as exc:
                    return refuse(400, str(exc))
                try:
                    st.append_call_events([event])
                except Exception:
                    log.exception("a call task action could not be recorded")
                    return refuse(502, "The task could not be updated just now. Try again.")
                result = _call_state_for(st, lead_id, now)
            log.info("call task %s for %s by %s", action, lead_id, g.email)
            return jsonify(recorded=True, **result)

    return app


def _deployed():
    logging.basicConfig(level=logging.INFO)
    # The review flow is OFF unless explicitly switched on. The store comes from the one review
    # contract (`review.store_from_env`): fail-closed by default, `REVIEW_STORE=sheet` for the
    # production adapter, a `REVIEW_STORE_PATH` for a local file. `verifier` is not passed, so the
    # app uses the real IAP verifier from the environment; there is no configuration that installs
    # a test/stub verifier - that override is a `create_app` argument only tests pass. Drafting and
    # sending stay disabled regardless (ENABLE_GMAIL_DRAFTS on the worker).
    enable_review = os.environ.get("ENABLE_REVIEW") == "true"
    # The signer (private key) comes from the console's own environment only, never the worker's
    # settings; None (unconfigured) blocks review writes. The verifier (public key) is read per
    # request from the drafting settings.
    return create_app(static_dir=os.environ.get("CONSOLE_STATIC_DIR") or None,
                      handbook_doc_id=os.environ.get("HANDBOOK_DOC_ID", ""),
                      enable_review=enable_review, review_store=review.store_from_env(),
                      review_signer=review.configured_signer_from_env())


app = _deployed()
