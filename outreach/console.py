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
import secrets
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path

from flask import Flask, g, jsonify, request, send_from_directory
from werkzeug.exceptions import RequestEntityTooLarge

from outreach import (assistant, call_log_chat, calls, channels, company_chat, company_settings,
                      console_auth, console_model, drafts, experiments, followup, handbook_store,
                      importer, job_draft, lead_chat, playbook, playbook_extract, playbook_select,
                      post_call, reply, review, suppression, sync)
from outreach import gmail_drafts
from outreach import send as send_mod
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
               review_signer=None, enable_import=False, enable_calls=False, enable_playbook=False,
               enable_experiments=False, enable_reply=False, enable_send=False,
               enable_lead_chat=False, gmail_client=None):
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
        chosen = _chosen_settings()  # merges any chat-set company field over the base settings
        try:
            with reading:
                data = console_model.snapshot(store(), settings=chosen, now=clock(),
                                              handbook_doc_id=handbook_doc_id,
                                              calls_enabled=enable_calls,
                                              experiments_enabled=enable_experiments)
        except Exception:
            log.exception("the Sheet could not be read")
            return None, refuse(502, "The Sheet could not be read just now. Nothing was "
                                     "changed; try again in a minute.")
        data["signed_in_as"] = g.email
        data["build"] = built()
        data["import_enabled"] = enable_import
        data["playbook_enabled"] = enable_playbook
        data["experiments_enabled"] = enable_experiments
        data["reply_enabled"] = enable_reply
        data["send_enabled"] = enable_send
        data["lead_chat_enabled"] = enable_lead_chat
        if enable_lead_chat:
            still_missing = company_settings.next_missing(chosen)
            data["company_next_field"] = still_missing[0] if still_missing else None
            data["company_next_label"] = still_missing[1] if still_missing else None
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
            base = settings() or {}
        except Exception:
            log.exception("the drafting settings could not be read")
            return {}
        # A field set via the chat assistant (company_settings, stored on the Sheet) overrides the
        # same field in the base secret/file - same pattern as the stored playbook overriding Drive.
        # Only consulted when a live Sheets client is available, so every settings=lambda: {...}
        # test fixture is unaffected. A broken store (unreadable Sheet) must not break settings
        # resolution either - the caller's own Sheet read will separately report that failure.
        try:
            api = getattr(store(), "api", None)
            if api is not None:
                base = {**base, **company_settings.overrides(api=api)}
        except Exception:
            log.exception("company settings could not be read")
        return base

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

        @app.post("/api/drafts/prepare/<lead_id>")
        def prepare_draft(lead_id):
            """Prepare ONE lead's candidate into the Drafts tab so it can be reviewed, and so a
            confirmed review mints its approval hash. Writes the Drafts tab only - no Gmail, no send.

            A candidate already stored is RE-GATED, never re-composed: re-clicking this after a review
            must pick up the confirmation (-> READY), not replace the approved words with a fresh model
            body (which would change the fingerprint and silently void the review). Only a lead with no
            stored candidate yet is composed (one model call). Returns its resulting status/why."""
            chosen = _chosen_settings()
            with reading:
                try:
                    st = store()
                    picked = drafts.regate_one(st, lead_id, settings=chosen, review_store=reviews)
                    if picked is None:
                        report = drafts.prepare(st, settings=chosen, review_store=reviews,
                                                only=[lead_id], refresh=True)
                        picked = report.get("written", {}).get(lead_id)
                except drafts.DraftsBlocked as exc:
                    return refuse(409, f"The candidate could not be prepared ({exc}).")
                except Exception:
                    log.exception("the candidate could not be prepared")
                    return refuse(502, "The candidate could not be prepared just now.")
            if not picked:
                return refuse(404, "This lead is not ready for a first draft, so no candidate was written.")
            log.info("candidate prepared for %s by %s: %s", lead_id, g.email, picked.get("status"))
            return jsonify(ok=True, lead_id=lead_id, **picked)

        @app.post("/api/draft/create/<lead_id>")
        def create_gmail_draft(lead_id):
            """Turn the reviewed, READY candidate into one Gmail draft (never sent). Re-gates this one
            lead first (reusing its stored words, no model call) so a confirmed review mints its approval
            hash, then reads the stored candidate and creates the draft through the gated job_draft.create
            (ENABLE_GMAIL_DRAFTS must be set). It must NOT re-compose: recomposing would change the body
            and void the very review this step depends on."""
            chosen = _chosen_settings()
            with reading:
                try:
                    st = store()
                    drafts.regate_one(st, lead_id, settings=chosen, review_store=reviews)
                    rows = st.drafts()
                except drafts.DraftsBlocked as exc:
                    return refuse(409, f"The candidate could not be prepared ({exc}).")
                except Exception:
                    log.exception("the Sheet could not be read to create a draft")
                    return refuse(502, "The Sheet could not be read just now. Nothing was created.")
            row = next((r for _, r in rows if r.get("Lead ID") == lead_id), None)
            if row is None:
                return refuse(404, "There is no prepared candidate for this lead.")
            approved_hash = (row.get("Approval hash") or "").strip()
            written_raw = (row.get("Written") or "").strip()
            if not approved_hash or not written_raw:
                why = (row.get("Why") or "").strip() or "it has not been reviewed or the offer is not approved"
                return refuse(409, f"The candidate is not ready to send ({why}).")
            try:
                written = json.loads(written_raw)
            except ValueError:
                return refuse(502, "The stored candidate could not be read.")
            client = (gmail_client or gmail_drafts.client)()
            try:
                result = job_draft.create(lead_id, approved_hash, written=written, settings=chosen,
                                          api=st.api, gmail=client, review_store=reviews)
            except job_draft.DraftBlocked as exc:
                return refuse(409, f"The draft could not be created ({exc}).")
            except Exception:
                log.exception("a Gmail draft could not be created")
                return refuse(502, "The draft could not be created just now. Nothing was sent.")
            log.info("gmail draft created for %s by %s", lead_id, g.email)
            return jsonify(ok=True, **result)

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
            submission_id = str(body.get("submission_id", "")).strip() or None
            try:
                event = calls.outcome_event(lead_id, outcome, body.get("note", ""), called_at,
                                            no_answer_business_days=rule,
                                            callback_at=body.get("callback_at"), now=now,
                                            submission_id=submission_id)
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
                # The recorded outcome is what the drafting and follow-up eligibility paths read, so a
                # STOP is enforced by the Call log itself. The Suppression entry is a redundant hard stop
                # on the email path; if it cannot be written the stop is still enforced, and we report the
                # partial rather than claiming a clean success.
                suppression_written = None
                if calls.email_effect(outcome) == calls.STOP:
                    email = channels.email_of(leads.get(lead_id, {}))
                    if email:
                        try:
                            st.append_suppression([{
                                "Address or domain": email,
                                "Reason": f"call: {outcome.lower().replace('_', ' ')}",
                                "Added at": now.astimezone(timezone.utc).isoformat(),
                                "Source": f"call: {lead_id}"}])
                            suppression_written = True
                        except Exception:
                            log.exception("the call's suppression entry could not be written")
                            suppression_written = False
                state = _call_state_for(st, lead_id, now)
            log.info("call %s for %s by %s", outcome, lead_id, g.email)
            partial = {} if suppression_written is not False else {
                "warning": "The stop was recorded and is enforced, but its Suppression entry could not "
                           "be written. The email suppression list may be incomplete until you retry."}
            return jsonify(recorded=True, suppression_written=suppression_written, **partial, **state)

        @app.post("/api/calls/<lead_id>/task")
        def call_task_action(lead_id):
            """Complete, snooze or cancel the lead's current call task. Idempotent per task."""
            body = request.get_json(silent=True) or {}
            action = str(body.get("action", "")).strip().upper()
            if action not in calls.ACTIONS:
                return refuse(400, "That is not a task action I recognise.")
            client_task_id = str(body.get("task_id", "")).strip()
            # Every action must name the exact task it applies to; there is no "current task" fallback,
            # so a payload that omits the id can never act on whatever task happens to be open now.
            if not client_task_id:
                return refuse(400, "This action must name the task it applies to. Reload and try again.")
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
                # Act only on the exact task the founder was shown. If it has been superseded (a newer
                # outcome opened a different task since the page loaded), refuse rather than silently
                # closing the newer one. The action carries its target so replay stays correct too.
                if client_task_id != task["id"]:
                    return refuse(409, "This call task changed since you loaded it. Reload and try again.")
                try:
                    event = calls.action_event(lead_id, action, client_task_id,
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

        @app.get("/api/calls/<lead_id>/candidate")
        def call_candidate(lead_id):
            """A post-call email candidate for the founder to inspect, edit or discard. Reads only; it
            never sends, never creates a Gmail draft, never writes. Separate from the initial email and the
            follow-up sequence, and it does not authorise anything: a HOLD still blocks the ordinary
            sequence. Returns {candidate} or {candidate:null, reason, unavailable?}."""
            chosen = _chosen_settings()
            with reading:
                try:
                    st = store()
                    leads = st.leads()
                except Exception:
                    log.exception("the Sheet could not be read for a post-call candidate")
                    return refuse(502, "The Sheet could not be read just now.")
                if lead_id not in leads:
                    return refuse(404, "There is no such lead.")
                row = leads[lead_id]
                try:
                    events = [e for e in st.call_events() if e.get("Lead ID") == lead_id]
                except Exception:
                    log.exception("the Call log could not be read for a post-call candidate")
                    return jsonify(candidate=None, unavailable=True, reason="call_log_unreadable")
                try:
                    entries = st.suppression()
                except suppression.Unreadable:
                    # Who opted out is unknown: never offer an outreach candidate that might reach them.
                    return jsonify(candidate=None, unavailable=True, reason="suppression_unreadable")
            latest = post_call.latest_call(events)
            if latest is None or not post_call.eligible_outcome(latest["outcome"]):
                return jsonify(candidate=None, reason="outcome_not_eligible")
            # The EFFECTIVE call decision, not just the latest outcome: a sticky do-not-contact (STOP) blocks
            # the candidate even after a later no-answer, whether or not the Suppression write landed.
            effect = calls.outreach_effect(events)
            if effect == calls.STOP:
                return jsonify(candidate=None, reason="call_stop")
            email = channels.email_of(row)
            if not email:  # a phone-only lead keeps its task and history, but gets no email candidate
                return jsonify(candidate=None, reason="no_email")
            if suppression.covers(entries, email):  # the ordinary suppression check is kept too
                return jsonify(candidate=None, reason="suppressed")
            book, _why = job_draft._handbook(chosen, api=getattr(st, "api", None))
            if book is None:  # grounded in the current handbook, or not offered at all
                return jsonify(candidate=None, unavailable=True, reason="handbook_unavailable")
            try:
                cand = post_call.candidate(row, latest, chosen, handbook=book, now=clock(), effect=effect)
            except post_call.NotEligible as exc:
                return jsonify(candidate=None, reason=exc.reason)
            log.info("post-call candidate shown for %s to %s", lead_id, g.email)
            return jsonify(candidate=cand)

        @app.post("/api/calls/interpret")
        def call_interpret():
            """Read a typed note about a call into a proposal the founder confirms. READ-ONLY: it writes
            nothing (the confirm goes to POST /api/calls/<lead>/outcome, which applies the STOP/HOLD and
            sticky do-not-contact rules). Separate from the general assistant, which stays read-only too."""
            body = request.get_json(silent=True) or {}
            note = str(body.get("note", "")).strip()
            if not note:
                return refuse(400, "Type a short note about the call.")
            chosen = _chosen_settings()
            try:
                rule = int(chosen.get("call_no_answer_business_days",
                                      calls.DEFAULT_NO_ANSWER_BUSINESS_DAYS))
            except (TypeError, ValueError):
                rule = calls.DEFAULT_NO_ANSWER_BUSINESS_DAYS
            with reading:
                try:
                    leads = store().leads()
                except Exception:
                    log.exception("the Sheet could not be read to interpret a call note")
                    return refuse(502, "The Sheet could not be read just now.")
            proposal = call_log_chat.interpret(
                note, leads, now=clock(), rule=rule,
                chosen_lead_id=str(body.get("lead_id", "")).strip() or None,
                callback_at=str(body.get("callback_at", "")).strip() or None)
            log.info("call-note interpreted for %s: %s", g.email, proposal.get("status"))
            return jsonify(proposal)

    if enable_reply:
        # A reply-draft candidate (#6) for a lead that wrote back. READ-ONLY: it never sends, never
        # creates a Gmail draft, never writes. Flag-gated and off in deployment. Grounded in the recorded
        # reply, the company's cited words and the approved offer; it never states what the reply said.
        @app.get("/api/reply/<lead_id>/candidate")
        def reply_candidate(lead_id):
            """Returns {candidate} or {candidate:null, reason, unavailable?}. Fails closed: an unreadable
            Events tab, Call log or Suppression list yields no candidate, never an unguarded one."""
            chosen = _chosen_settings()
            with reading:
                try:
                    st = store()
                    leads = st.leads()
                except Exception:
                    log.exception("the Sheet could not be read for a reply candidate")
                    return refuse(502, "The Sheet could not be read just now.")
                if lead_id not in leads:
                    return refuse(404, "There is no such lead.")
                row = leads[lead_id]
                try:
                    events = [e for e in sync.unique(st.events()) if e.get("Lead ID") == lead_id]
                except Exception:
                    log.exception("the Events tab could not be read for a reply candidate")
                    return jsonify(candidate=None, unavailable=True, reason="events_unreadable")
                try:
                    call_events = [e for e in st.call_events() if e.get("Lead ID") == lead_id]
                except Exception:
                    # Unreadable call history must not silently permit outreach: a STOP could be hidden.
                    log.exception("the Call log could not be read for a reply candidate")
                    return jsonify(candidate=None, unavailable=True, reason="call_log_unreadable")
                try:
                    entries = st.suppression()
                except suppression.Unreadable:
                    return jsonify(candidate=None, unavailable=True, reason="suppression_unreadable")
            inbound = reply.latest_inbound(events)
            if inbound is None:
                return jsonify(candidate=None, reason="no_reply")
            effect = calls.outreach_effect(call_events)
            email = channels.email_of(row)
            suppressed = bool(email) and suppression.covers(entries, email)
            book, _why = job_draft._handbook(chosen, api=getattr(st, "api", None))
            if book is None:  # grounded in the current handbook, or not offered at all
                return jsonify(candidate=None, unavailable=True, reason="handbook_unavailable")
            try:
                cand = reply.candidate(row, inbound, chosen, handbook=book, effect=effect,
                                       suppressed=suppressed)
            except reply.NotEligible as exc:
                return jsonify(candidate=None, reason=exc.reason)
            log.info("reply candidate shown for %s to %s", lead_id, g.email)
            return jsonify(candidate=cand)

        @app.post("/api/reply/<lead_id>/draft")
        def reply_draft(lead_id):
            """Create the reviewed reply as an in-thread Gmail DRAFT for the founder to send by hand.
            Writes a Gmail draft only - never sends. Re-checks the guards at the write boundary and also
            requires ENABLE_GMAIL_DRAFTS=true (the flag alone never creates a draft). No tracking is added."""
            body = request.get_json(silent=True) or {}
            subject = str(body.get("subject", ""))
            message = str(body.get("body", ""))
            chosen = _chosen_settings()
            with reading:
                try:
                    st = store()
                    leads = st.leads()
                except Exception:
                    log.exception("the Sheet could not be read to create a reply draft")
                    return refuse(502, "The Sheet could not be read just now. Nothing was changed.")
                if lead_id not in leads:
                    return refuse(404, "There is no such lead.")
                row = leads[lead_id]
                try:
                    events = [e for e in sync.unique(st.events()) if e.get("Lead ID") == lead_id]
                    call_events = [e for e in st.call_events() if e.get("Lead ID") == lead_id]
                    entries = st.suppression()
                except suppression.Unreadable:
                    return refuse(502, "The suppression list could not be read; no draft was created.")
                except Exception:
                    log.exception("a safety source could not be read for a reply draft")
                    return refuse(502, "A safety source could not be read; no draft was created.")
            inbound = reply.latest_inbound(events)
            effect = calls.outreach_effect(call_events)
            email = channels.email_of(row)
            suppressed = bool(email) and suppression.covers(entries, email)
            client = (gmail_client or gmail_drafts.client)()
            try:
                made = reply.create(row, inbound, subject, message, settings=chosen, gmail=client,
                                    effect=effect, suppressed=suppressed)
            except reply.ReplyBlocked as exc:
                # A guard refusal (stop/suppressed/no reply/draft exists/disabled) is a 409, not a 500.
                return refuse(409, f"No reply draft was created ({exc.reason}).")
            except Exception:
                log.exception("a reply draft could not be created")
                return refuse(502, "The reply draft could not be created just now. Nothing was sent.")
            log.info("reply draft created for %s by %s (thread %s)", lead_id, g.email, made.get("thread_id"))
            return jsonify(created=True, **made)

    if enable_send:
        # The ONE sanctioned send. "Approve and send" turns a draft this system already created into
        # a real email, on the signed-in founder's click - the single exception to the no-send rule
        # (outreach/send.py). Flag-gated and off in deployment by default; send.py also requires its
        # own ENABLE_SEND, so the flag here alone never sends. One click sends exactly one email; a
        # lead already sent (or in flight) is refused, so a repeat never sends twice. The approver is
        # the IAP-verified identity (g.email), never a value the client supplies.
        @app.post("/api/send/<lead_id>")
        def approve_and_send(lead_id):
            """Send the created draft for this lead on the founder's approval. Returns the sent
            message id and thread id, or a refusal (404 unknown lead, 409 nothing to send / already
            sent, 502 the Sheet or Gmail could not be reached)."""
            with reading:
                try:
                    st = store()
                    leads = st.leads()
                except Exception:
                    log.exception("the Sheet could not be read to send a draft")
                    return refuse(502, "The Sheet could not be read just now. Nothing was sent.")
                if lead_id not in leads:
                    return refuse(404, "There is no such lead.")
            client = (gmail_client or gmail_drafts.client)()
            try:
                result = send_mod.send_created_draft(lead_id, sent_by=g.email, api=st.api, gmail=client)
            except send_mod.SendBlocked as exc:
                return refuse(409, f"Nothing was sent ({exc}).")
            except Exception:
                log.exception("a draft could not be sent")
                return refuse(502, "The email could not be sent just now.")
            log.info("sent %s on approval by %s (message %s)", lead_id, g.email, result.get("message_id"))
            return jsonify(**result)

        @app.post("/api/send-edited/<lead_id>")
        def approve_and_send_edited(lead_id):
            """Create a Gmail draft from the founder's OWN final subject/body (edited in the console)
            and send it on the founder's approval - the single editable 'approve and send'. The words
            are the founder's, so no model-grounding or review gate applies here; the no-spam guards and
            at-most-once still do, and the opt-out line is always kept. 404 unknown lead, 409 could not
            prepare/send, 502 the Sheet or Gmail could not be reached."""
            payload = request.get_json(silent=True) or {}
            subject, body = str(payload.get("subject", "")), str(payload.get("body", ""))
            with reading:
                try:
                    st = store()
                    leads = st.leads()
                except Exception:
                    log.exception("the Sheet could not be read to send an edited draft")
                    return refuse(502, "The Sheet could not be read just now. Nothing was sent.")
                if lead_id not in leads:
                    return refuse(404, "There is no such lead.")
            client = (gmail_client or gmail_drafts.client)()
            chosen = _chosen_settings()
            try:
                job_draft.create_edited(lead_id, subject, body, approver=g.email,
                                        settings=chosen, api=st.api, gmail=client)
            except job_draft.DraftBlocked as exc:
                return refuse(409, f"The email could not be prepared to send ({exc}).")
            except Exception:
                log.exception("an edited draft could not be created")
                return refuse(502, "The email could not be prepared just now. Nothing was sent.")
            try:
                result = send_mod.send_created_draft(lead_id, sent_by=g.email, api=st.api, gmail=client)
            except send_mod.SendBlocked as exc:
                return refuse(409, f"Nothing was sent ({exc}).")
            except Exception:
                log.exception("an edited draft could not be sent")
                return refuse(502, "The email could not be sent just now.")
            log.info("sent edited %s on approval by %s (message %s)", lead_id, g.email,
                     result.get("message_id"))
            return jsonify(**result)

    if enable_lead_chat:
        # Manage leads by a typed instruction, propose-then-confirm (like the call-logging chat). The
        # interpret step is READ-ONLY and never calls a model; the apply step writes only on the founder's
        # confirm and re-validates server-side, so the client is never trusted. A new lead is appended; an
        # existing lead's SYSTEM columns are updated, and its founder columns stay protected. Flag-gated,
        # off by default and in deploy.
        @app.post("/api/leads/interpret")
        def leads_interpret():
            note = str((request.get_json(silent=True) or {}).get("note", ""))
            with reading:
                try:
                    st = store()
                    leads, columns = st.leads(), st.lead_columns("A")
                except Exception:
                    log.exception("the Sheet could not be read to interpret a lead instruction")
                    return refuse(502, "The Sheet could not be read just now.")
            return jsonify(lead_chat.interpret(note, leads, columns=columns))

        @app.post("/api/leads/apply")
        def leads_apply():
            body = request.get_json(silent=True) or {}
            op, lead_id = str(body.get("op", "")), (str(body.get("lead_id", "")) or None)
            fields = body.get("fields")
            if not isinstance(fields, dict):
                return refuse(400, "A lead change must carry fields.")
            with reading:
                try:
                    st = store()
                    leads, columns = st.leads(), st.lead_columns("A")
                except Exception:
                    log.exception("the Sheet could not be read to apply a lead change")
                    return refuse(502, "The Sheet could not be read just now. Nothing was changed.")
            reason = lead_chat.validate(op, lead_id=lead_id, fields=fields, leads=leads, columns=columns)
            if reason:
                return refuse(409, f"Nothing was changed ({reason}).")
            try:
                if op == "add":
                    ids = st.append_leads("A", [lead_chat.build_add_row(fields)])
                    log.info("lead added %s by %s", ids, g.email)
                    return jsonify(ok=True, op="add", lead_id=(ids[0] if ids else ""))
                written, _skipped = st.write_leads({lead_id: fields}, list(fields))
                if written != 1:
                    return refuse(409, "The lead changed before the update; nothing was written.")
                log.info("lead %s updated by %s", lead_id, g.email)
                return jsonify(ok=True, op="update", lead_id=lead_id)
            except Exception:
                log.exception("a lead change could not be applied")
                return refuse(502, "The change could not be saved just now.")

        # The founder's own sender/company identity (name, title, email, phone, website, postal
        # address, product name, daily cap) by the same propose-then-confirm shape, so it no longer
        # needs a hand-edited secret. interpret is read-only; apply writes one field, on confirm,
        # to the durable Company tab (company_settings.py) - the same resolver _chosen_settings
        # already merges over the base settings whenever a live Sheets client is available.
        @app.post("/api/company/interpret")
        def company_interpret():
            note = str((request.get_json(silent=True) or {}).get("note", ""))
            return jsonify(company_chat.interpret(note, _chosen_settings()))

        @app.post("/api/company/apply")
        def company_apply():
            body = request.get_json(silent=True) or {}
            field, value = str(body.get("field", "")), str(body.get("value", ""))
            try:
                with reading:
                    api = getattr(store(), "api", None)
                clean = company_settings.set_field(field, value, set_by=g.email, api=api)
            except company_settings.InvalidField as exc:
                return refuse(422, str(exc))
            except Exception:
                log.exception("a company field could not be saved")
                return refuse(502, "That could not be saved just now.")
            log.info("company field %s set by %s", field, g.email)
            still_missing = company_settings.next_missing(_chosen_settings())
            return jsonify(ok=True, field=field, value=clean,
                           next_field=(still_missing[0] if still_missing else None),
                           next_label=(still_missing[1] if still_missing else None))

    if enable_experiments:
        # Defining an experiment and assigning leads writes to the Sheet (the A/B tests tab), so this is
        # OFF by default and in deployment. It never sends, drafts, or touches a founder column, and it
        # is not connected to production drafting: a variant is a NAME only and changes no email.
        def _ab_now():
            return clock().astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")

        @app.post("/api/experiments/define")
        def experiment_define():
            """Define an experiment's two named variants. Idempotent: the same definition writes
            nothing new. It assigns no leads and drafts nothing."""
            body = request.get_json(silent=True) or {}
            try:
                rows = experiments.define_rows(body.get("experiment", ""), body.get("variant_a", ""),
                                               body.get("variant_b", ""), _ab_now())
            except ValueError as exc:
                return refuse(400, str(exc))
            with reading:
                try:
                    written = store().append_ab_records(rows)
                except Exception:
                    log.exception("an experiment definition could not be written")
                    return refuse(502, "The experiment could not be saved just now. Nothing was "
                                       "changed; try again in a minute.")
            name = rows[0]["Experiment"]
            log.info("experiment %r defined by %s (%s new rows)", name, g.email, len(written))
            return jsonify(recorded=True, name=name,
                           variants=[rows[0]["Variant"], rows[1]["Variant"]], written=len(written))

        @app.post("/api/experiments/assign")
        def experiment_assign():
            """Assign every eligible, not-yet-assigned lead to a variant of a defined experiment. The
            variant is deterministic and the write is idempotent, so a lead is assigned once and never
            moves. A lead is assigned only if it is NOT on the Suppression list and NOT in a call
            STOP/HOLD state; if either safety source cannot be read, NOBODY is assigned (an unreadable
            safety source is never permission). Returns how many were newly assigned, already assigned,
            or not eligible."""
            body = request.get_json(silent=True) or {}
            experiment = str(body.get("experiment", "")).strip()
            if not experiment:
                return refuse(400, "Name the experiment to assign leads to.")
            with reading:
                try:
                    st = store()
                    leads = st.leads()
                    state = experiments.read(st.ab_records()).get(experiment)
                except Exception:
                    log.exception("the Sheet could not be read to assign an experiment")
                    return refuse(502, "The Sheet could not be read just now. Nothing was changed; "
                                       "try again in a minute.")
                if state is None or not state["defined"]:
                    return refuse(400, "Define the experiment's two variants before assigning leads.")
                # Fail closed: both safety sources must be readable before anyone is assigned.
                try:
                    entries = st.suppression()
                except suppression.Unreadable:
                    log.exception("the Suppression list could not be read to assign an experiment")
                    return refuse(502, "The Suppression list could not be read, so no lead was "
                                       "assigned. A lead is assigned only when it is known not to be "
                                       "suppressed. Try again in a minute.")
                try:
                    call_rows = st.call_events()
                except Exception:
                    log.exception("the Call log could not be read to assign an experiment")
                    return refuse(502, "The Call log could not be read, so no lead was assigned. A "
                                       "lead is assigned only when its call state is known not to be a "
                                       "stop or a hold. Try again in a minute.")
                by_call = {}
                for event in call_rows:
                    by_call.setdefault(event.get("Lead ID", ""), []).append(event)

                def _safe(lead_id, row):
                    email = channels.email_of(row)
                    suppressed = bool(email and suppression.covers(entries, email))
                    effect = calls.outreach_effect(by_call.get(lead_id, []))
                    return experiments.safe_to_assign(row, suppressed=suppressed, call_effect=effect)

                already = set(state["assignments"])
                eligible = sorted(lid for lid, row in leads.items() if _safe(lid, row))
                to_assign = [lid for lid in eligible if lid not in already]
                rows = experiments.assign_rows(experiment, state["variants"], to_assign, _ab_now())
                try:
                    written = st.append_ab_records(rows)
                except Exception:
                    log.exception("experiment assignments could not be written")
                    return refuse(502, "The assignments could not be saved just now. Some may not be "
                                       "saved; reassigning is safe, as an assigned lead is never "
                                       "moved. Try again in a minute.")
            log.info("experiment %r: %s leads assigned by %s", experiment, len(written), g.email)
            return jsonify(recorded=True, name=experiment, assigned=len(written),
                           already_assigned=len(already),
                           eligible=len(eligible), ineligible=len(leads) - len(eligible))

    if enable_playbook:
        # Upload, review, select and preview a playbook the founder is drafting. READ-ONLY and LOCAL: it
        # extracts and parses the file and previews a candidate from it, but writes nothing, creates no Gmail
        # draft, and does not change the production handbook (the Drive document stays authoritative). Off by
        # default and in deploy. The uploaded text is parsed as data only, never run as instructions.
        #
        # Review and selection are separate. The per-process secret signs two kinds of token. `/review` mints
        # a REVIEW token (proof the server read this founder's exact text); the founder's explicit `/select`
        # exchanges it for a SELECT token; `/preview` requires a SELECT token. So a reviewed-but-never-selected
        # version is refused, and no one can forge selection, reuse it for changed text, use another founder's
        # token, or use an expired one. No token survives a restart - the choice is in-session and never durable.
        playbook_secret = secrets.token_bytes(32)

        def _bounded_json():
            """Parse the JSON body with the request bounded BEFORE parsing (works even without a usable
            Content-Length). Raises RequestEntityTooLarge if the body is over the playbook size limit."""
            request.max_content_length = playbook_extract.MAX_BYTES
            return request.get_json(silent=True) or {}

        @app.post("/api/playbook/review")
        def playbook_review():
            # Bound the whole request before multipart parsing (Werkzeug enforces this during form parsing,
            # even with no Content-Length), so a huge upload cannot be buffered.
            request.max_content_length = playbook_extract.MAX_BYTES
            try:
                upload = request.files.get("file")
            except RequestEntityTooLarge:
                return jsonify(rejected=True, reason="too_large",
                               error=f"that file is over {playbook_extract.MAX_BYTES // 1_000_000} MB."), 413
            if upload is None:
                return refuse(400, "Attach a PDF or DOCX file.")
            try:
                text, kind = playbook_extract.extract(upload.filename, upload.read())
            except playbook_extract.PlaybookRejected as exc:
                return jsonify(rejected=True, reason=exc.reason, error=str(exc)), 422
            result = playbook.review(text)
            review_token = playbook_select.mint(playbook_secret, playbook_select.REVIEW,
                                                result["content_hash"], g.email)
            log.info("playbook reviewed by %s: %s (%s)", g.email, result["content_hash"][:8], kind)
            # A review token proves the review only; it is NOT a selection. The founder selects via /select.
            return jsonify(kind=kind, text=text, review=result, review_token=review_token)

        @app.post("/api/playbook/select")
        def playbook_select_version():
            """The founder's explicit Select action: exchange a valid review token for a select token bound to
            this exact reviewed content and founder. Writes nothing; grants only a local, time-bounded preview."""
            try:
                body = _bounded_json()
            except RequestEntityTooLarge:
                return refuse(413, "That playbook is too large.")
            text = str(body.get("text", ""))
            review_token = str(body.get("review_token", "")).strip()
            if not text.strip() or not review_token:
                return refuse(400, "Review a playbook before selecting it.")
            if len(text) > playbook_extract.MAX_CHARS:
                return refuse(413, "That playbook is too long.")
            content_hash = playbook.content_hash(text)
            if not playbook_select.verify(playbook_secret, review_token, playbook_select.REVIEW,
                                          content_hash, g.email):
                return refuse(403, "This version has not been reviewed, or the review changed or expired. "
                                   "Upload and review it again.")
            token = playbook_select.mint(playbook_secret, playbook_select.SELECT, content_hash, g.email)
            log.info("playbook selected by %s: %s", g.email, content_hash[:8])
            return jsonify(content_hash=content_hash, selection_token=token)

        @app.post("/api/playbook/preview")
        def playbook_preview():
            """Preview a candidate (follow-up 1) from a SELECTED playbook version, using the existing
            follow-up drafting boundary. Requires the select token from /select for this founder and this
            exact content: a review-only token, a forged token, a changed file, another founder, or an
            expired selection is refused. No Gmail, no Drive, no send."""
            try:
                body = _bounded_json()
            except RequestEntityTooLarge:
                return refuse(413, "That playbook is too large to preview.")
            text = str(body.get("text", ""))
            token = str(body.get("selection_token", "")).strip()
            if not text.strip() or not token:
                return refuse(400, "Select a reviewed playbook version first.")
            if len(text) > playbook_extract.MAX_CHARS:  # cap before hashing or rendering
                return refuse(413, "That playbook is too long to preview.")
            selected = playbook.content_hash(text)
            if not playbook_select.verify(playbook_secret, token, playbook_select.SELECT, selected, g.email):
                return refuse(403, "This playbook was not selected, or the selection changed or expired. "
                                   "Select the version again.")
            first_name = str(body.get("first_name", "")).strip() or "there"
            draft, problems = followup.render(1, text, _chosen_settings(), first_name)
            log.info("playbook preview for %s: %s", g.email, "drafted" if draft else "blocked")
            return jsonify(step=1, content_hash=selected, body=draft, problems=problems)

        @app.post("/api/playbook/set")
        def playbook_set():
            """Persist the founder's playbook text as the LIVE source every draft reads from (the
            durable Playbook tab). The text is the founder's own, saved on their authenticated action;
            it is stored verbatim, never run as instructions. Returns the new content hash and whether
            the stored playbook is actually in use yet (the `playbook_store_enabled` settings flag)."""
            try:
                body = _bounded_json()
            except RequestEntityTooLarge:
                return refuse(413, "That playbook is too large.")
            text = str(body.get("text", ""))
            name = str(body.get("name", "")).strip()[:120]
            if len(text) > playbook_extract.MAX_CHARS:
                return refuse(413, "That playbook is too long.")
            try:
                with reading:
                    api = store().api
                content_hash = handbook_store.set_active(text, set_by=g.email, name=name,
                                                         source="console", api=api)
            except ValueError as exc:
                return refuse(422, str(exc))
            except Exception:
                log.exception("the playbook could not be saved")
                return refuse(502, "The playbook could not be saved just now.")
            log.info("playbook set as live by %s: %s", g.email, content_hash[:8])
            return jsonify(ok=True, content_hash=content_hash,
                           enabled=_chosen_settings().get("playbook_store_enabled") is True)

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
                      review_signer=review.configured_signer_from_env(),
                      enable_send=os.environ.get("ENABLE_SEND") == "true",
                      enable_lead_chat=os.environ.get("ENABLE_LEAD_CHAT") == "true",
                      enable_playbook=os.environ.get("ENABLE_PLAYBOOK") == "true",
                      enable_import=os.environ.get("ENABLE_IMPORT") == "true",
                      enable_calls=os.environ.get("ENABLE_CALLS") == "true",
                      enable_experiments=os.environ.get("ENABLE_EXPERIMENTS") == "true",
                      enable_reply=os.environ.get("ENABLE_REPLY") == "true")


app = _deployed()
