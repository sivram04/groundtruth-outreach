"""The account-aware console entry point: sign in with Google (today, no verification wait -
this is a basic identity check, not a restricted scope), then connect Gmail/Drive (the
restricted-scope flow in ``outreach/google_connect.py``, inert until Google approves the app).

Deliberately a SEPARATE app from ``outreach/console.py``: that one is gated by IAP and reads one
hardcoded founder identity; this one has its own sign-in because IAP only ever identifies people
inside one Google Workspace org, never an arbitrary external user signing up for an account.

"Sign in" and "connect" are two different OAuth concepts, worth keeping distinct:
  * Sign-in only answers "who is this person" - an unrestricted scope (openid, email), approved
    for any app instantly, no Google review. Done here via Google Identity Services: the
    browser's "Sign in with Google" button hands this backend a signed credential JWT directly,
    which is verified and resolved to an account. No OAuth redirect dance for this step.
  * Connect answers "may this app read/draft in this person's Gmail or Drive" - a restricted
    scope, gated behind Google's verification (``docs/OAUTH_VERIFICATION_CHECKLIST.md``). The
    connect routes below exist and are fully wired/tested now, so there is nothing left to build
    the day that clears - they will simply start working.

A browser session can hold SEVERAL signed-in accounts at once, with one marked active - the
founder's own use case (one person, two of their own accounts for two different purposes, e.g.
a leads mailbox and a referral mailbox, each signed in and connected separately) needs this: one
browser, switch between "acting as" each account, without logging out and back in every time.
Each account's own data stays exactly as isolated as before (the RLS fix in ``tenancy.py``
scopes by the ACTIVE account_id on every request; holding several in one session cookie is only
a client-side convenience, not a database-level relaxation).

Every route takes its dependencies by injection (``conn_factory``, ``verify_credential``,
``connector``), matching this repo's convention everywhere else, so this is fully testable
offline.
"""

import logging
import os
from functools import wraps
from pathlib import Path
from urllib.parse import quote

from flask import Flask, jsonify, redirect, request, send_from_directory, session

from outreach import google_connect, job_auto, job_draft, tenancy, tenant_google, tenant_sheet
from outreach.sheet import LEAD_TABS

log = logging.getLogger("outreach.tenant_console")

ACCOUNTS_KEY = "accounts"  # {account_id: {"email":, "name":, "provider_subject":}}
ACTIVE_KEY = "active_account_id"
ASSET_CACHE = "private, max-age=31536000, immutable"
NO_STORE = "no-store"
DEFAULT_STATIC = Path(__file__).resolve().parent.parent / "tenant-console_dist"


def create_app(*, conn_factory, verify_credential, connector=None, secret_key=None,
              static_dir=None, google_client_id=""):
    """``conn_factory()`` returns a DB connection per call (closed by the caller - see
    ``_with_conn``). ``verify_credential(credential_jwt) -> {"sub", "email", "email_verified"}``
    checks a Google Identity Services credential; real use wraps
    ``google.oauth2.id_token.verify_oauth2_token``. ``connector`` is a
    ``google_connect.Connector`` (or ``None`` until the OAuth client exists, in which case the
    connect routes correctly refuse with 503 rather than crash). ``google_client_id`` is the
    OAuth client's public id - safe to expose to the browser (unlike the client secret) - read
    by the frontend from ``GET /api/config`` to render Google's own Sign-In button."""
    app = Flask(__name__, static_folder=None)
    static = Path(static_dir).resolve() if static_dir else DEFAULT_STATIC
    # A random per-process secret is fine for tests; production needs one real, persisted secret
    # (e.g. Secret Manager) - a restart that changes it logs out every session.
    app.secret_key = secret_key or os.urandom(32)

    def _with_conn(fn):
        @wraps(fn)
        def wrapped(*a, **kw):
            conn = conn_factory()
            try:
                result = fn(conn, *a, **kw)
            except Exception:
                rollback = getattr(conn, "rollback", None)
                if rollback:
                    rollback()
                raise
            else:
                # A real DB-API connection (psycopg among them) opens an implicit transaction on
                # the first statement and defaults to autocommit=False - closing it uncommitted
                # silently discards every write the route just made, which looked like success
                # (no exception) right up until the next request referenced data that was never
                # actually persisted. Every route wrapped by this must commit on success.
                commit = getattr(conn, "commit", None)
                if commit:
                    commit()
                return result
            finally:
                close = getattr(conn, "close", None)
                if close:
                    close()
        return wrapped

    def _signed_in(fn):
        @wraps(fn)
        def wrapped(*a, **kw):
            if not session.get(ACTIVE_KEY):
                return jsonify(error="Sign in first."), 401
            return fn(*a, **kw)
        return wrapped

    def _accounts_view():
        active = session.get(ACTIVE_KEY)
        return [{"account_id": aid, **info, "active": aid == active}
               for aid, info in session.get(ACCOUNTS_KEY, {}).items()]

    @app.get("/api/config")
    def config():
        return jsonify(google_client_id=google_client_id)

    @app.get("/")
    def page():
        if not (static / "index.html").is_file():
            return jsonify(error="The console's pages have not been built."), 503
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

    @app.post("/api/session/google")
    @_with_conn
    def sign_in(conn):
        """Verify a Google Identity Services credential, resolve/create the account, add it to
        this browser's signed-in accounts (keeping any others already signed in), and make it
        the active one. Signing in again with an account already in the session just re-selects
        it - no duplicate, no data re-read needed from Google."""
        credential = (request.get_json(silent=True) or {}).get("credential", "")
        if not credential or not isinstance(credential, str):
            return jsonify(error="A Google credential is required."), 400
        try:
            identity = verify_credential(credential)
        except Exception:
            return jsonify(error="That Google credential could not be verified."), 401
        subject, email = str(identity.get("sub", "")), str(identity.get("email", "")).strip().lower()
        if not subject or not email or identity.get("email_verified") is not True:
            return jsonify(error="That Google credential could not be verified."), 401
        try:
            account = tenancy.resolve_identity(conn, subject, email,
                                               display_name=identity.get("name"))
        except tenancy.TenancyError as exc:
            return jsonify(error=str(exc)), 400
        accounts = dict(session.get(ACCOUNTS_KEY, {}))
        accounts[account.id] = {"email": email, "name": account.name, "provider_subject": subject}
        session[ACCOUNTS_KEY] = accounts
        session[ACTIVE_KEY] = account.id
        return jsonify(account_id=account.id, name=account.name, email=email,
                       accounts=_accounts_view())

    @app.get("/api/session")
    def current_session():
        active = session.get(ACTIVE_KEY)
        if not active:
            return jsonify(signed_in=False, accounts=[])
        return jsonify(signed_in=True, account_id=active, accounts=_accounts_view())

    @app.post("/api/session/switch")
    def switch_account():
        """Make a DIFFERENT already-signed-in account active, with no re-authentication - the
        account must already be in this session (added by a prior /api/session/google), so this
        can never make an account active that this browser never actually signed into."""
        account_id = (request.get_json(silent=True) or {}).get("account_id", "")
        accounts = session.get(ACCOUNTS_KEY, {})
        if account_id not in accounts:
            return jsonify(error="Sign in to that account in this browser first."), 400
        session[ACTIVE_KEY] = account_id
        return jsonify(signed_in=True, account_id=account_id, accounts=_accounts_view())

    @app.post("/api/session/logout")
    def logout():
        """With an ``account_id``: sign that one account out of this browser only, switching the
        active account to another still-signed-in one if any remain. With no ``account_id`` (or
        ``{"all": true}``): sign everything out of this browser."""
        body = request.get_json(silent=True) or {}
        account_id = body.get("account_id")
        if not account_id or body.get("all"):
            session.clear()
            return jsonify(ok=True, accounts=[])
        accounts = dict(session.get(ACCOUNTS_KEY, {}))
        accounts.pop(account_id, None)
        session[ACCOUNTS_KEY] = accounts
        if session.get(ACTIVE_KEY) == account_id:
            session[ACTIVE_KEY] = next(iter(accounts), None)
        return jsonify(ok=True, accounts=_accounts_view())

    @app.post("/api/connections/<kind>/start")
    @_signed_in
    @_with_conn
    def connect_start(conn, kind):
        if connector is None:
            return jsonify(error="Google connections are not configured yet."), 503
        if kind not in google_connect.SCOPES:
            return jsonify(error="Choose gmail or drive."), 400
        active = session[ACTIVE_KEY]
        subject = session[ACCOUNTS_KEY][active]["provider_subject"]
        try:
            url = connector.begin(conn, active, subject, kind)
        except (google_connect.Refused, ValueError) as exc:
            log.warning("connect_start(%s) refused for account %s: %s", kind, active, exc, exc_info=True)
            return jsonify(error=str(exc)), 400
        return jsonify(authorization_url=url)

    @app.get("/api/tenant/google/callback")
    @_signed_in
    @_with_conn
    def connect_callback(conn):
        """Google redirects the browser here after consent - a page navigation, not a fetch()
        call - so this sends the browser back to the app itself (never raw JSON, which left the
        founder stranded on a blank JSON page with no way back to the Dashboard) with the
        outcome in the query string for the frontend to show as a notice."""
        if connector is None:
            return redirect("/?connect_error=" + quote("Google connections are not configured yet."))
        active = session[ACTIVE_KEY]
        subject = session[ACCOUNTS_KEY][active]["provider_subject"]
        state, code = request.args.get("state", ""), request.args.get("code", "")
        try:
            result = connector.complete(conn, active, subject, state, code)
        except google_connect.Refused as exc:
            log.warning("connect_callback refused for account %s: %s", active, exc, exc_info=True)
            return redirect("/?connect_error=" + quote(str(exc)))
        return redirect("/?connected=" + quote(result["kind"]))

    def _sheets_api(conn, account_id):
        """This account's own Sheets client, or None with a (message, status) pair explaining
        why not - never the founder's, and never raised past the route as a 500."""
        if connector is None:
            return None, ("Google connections are not configured yet.", 503)
        try:
            return tenant_google.sheets_api(connector, conn, account_id), None
        except tenant_google.NotConnected:
            return None, ("Connect Google Sheets for this account first.", 400)
        except google_connect.Refused as exc:
            log.warning("sheets_api refused for account %s: %s", account_id, exc, exc_info=True)
            return None, (str(exc), 400)

    def _gmail_api(conn, account_id):
        if connector is None:
            return None, ("Google connections are not configured yet.", 503)
        try:
            return tenant_google.gmail_api(connector, conn, account_id), None
        except tenant_google.NotConnected:
            return None, ("Connect Gmail for this account first.", 400)
        except google_connect.Refused as exc:
            log.warning("gmail_api refused for account %s: %s", account_id, exc, exc_info=True)
            return None, (str(exc), 400)

    @app.get("/api/account/connections")
    @_signed_in
    @_with_conn
    def connections(conn):
        """Which Google connection kinds the active account actually has, for the Dashboard to
        show "Connected" instead of always showing the same two buttons with no state."""
        active = session[ACTIVE_KEY]
        return jsonify({kind: tenancy.latest_connection_id(conn, active, kind) is not None
                        for kind in google_connect.SCOPES})

    @app.post("/api/account/sheet")
    @_signed_in
    @_with_conn
    def link_sheet(conn):
        """Give the active account its own Sheet: links the one named by `sheet_id` in the
        request body (verified readable with this account's own credential before it's trusted),
        or creates a brand-new blank one if none is given. Idempotent - an account that already
        has a Sheet keeps it (see `tenant_sheet.ensure_sheet`)."""
        active = session[ACTIVE_KEY]
        api, failure = _sheets_api(conn, active)
        if failure:
            return jsonify(error=failure[0]), failure[1]
        link_sheet_id = (request.get_json(silent=True) or {}).get("sheet_id") or None
        try:
            sheet_id = tenant_sheet.ensure_sheet(api, conn, active, link_sheet_id=link_sheet_id)
        except tenant_sheet.LinkRefused as exc:
            return jsonify(error=str(exc)), 400
        return jsonify(sheet_id=sheet_id)

    @app.get("/api/account/sheet")
    @_signed_in
    @_with_conn
    def get_sheet(conn):
        return jsonify(sheet_id=tenancy.get_sheet_id(conn, session[ACTIVE_KEY]))

    @app.delete("/api/account/sheet")
    @_signed_in
    @_with_conn
    def unlink_sheet(conn):
        """Unlink the active account's Sheet (the Sheet itself is untouched, only the stored
        reference is removed) - lets a wrong link/create be undone without touching data."""
        tenancy.clear_sheet_id(conn, session[ACTIVE_KEY])
        return jsonify(ok=True)

    @app.delete("/api/connections/<kind>")
    @_signed_in
    @_with_conn
    def disconnect(conn, kind):
        """Revoke the active account's connection of this kind. Does not touch the Sheet (a
        Drive/Sheets disconnect and a Sheet link are independent - disconnecting Google access
        does not un-link a Sheet already recorded, since the Sheet itself is unaffected)."""
        if kind not in google_connect.SCOPES:
            return jsonify(error="Choose gmail or drive."), 400
        active = session[ACTIVE_KEY]
        connection_id = tenancy.latest_connection_id(conn, active, kind)
        if connection_id is None:
            return jsonify(ok=True)  # already disconnected - same end state, no error
        tenancy.revoke_connection(conn, active, connection_id)
        return jsonify(ok=True)

    def _sheet_context(conn, account_id):
        """(sheet_id, api, lead_tabs) for this account's own Sheet, or None with a (message,
        status) pair - every /api/jobs/* route below needs all three, and none is ever the
        founder's. `lead_tabs` falls back to the system default (outreach.sheet.LEAD_TABS) until
        the account configures its own via PUT /api/account/lead-tabs."""
        sheet_id = tenancy.get_sheet_id(conn, account_id)
        if not sheet_id:
            return None, ("This account has no Sheet yet; call POST /api/account/sheet first.", 400)
        api, failure = _sheets_api(conn, account_id)
        if failure:
            return None, failure
        lead_tabs = tenancy.get_lead_tabs(conn, account_id) or LEAD_TABS
        return (sheet_id, api, lead_tabs), None

    @app.get("/api/account/lead-tabs")
    @_signed_in
    @_with_conn
    def get_lead_tabs_route(conn):
        """This account's lead-tab layout - its own if configured, else the system default -
        and whether it's a custom one (so the frontend can offer "reset to default")."""
        active = session[ACTIVE_KEY]
        custom = tenancy.get_lead_tabs(conn, active)
        return jsonify(lead_tabs=custom or LEAD_TABS, is_custom=custom is not None)

    @app.put("/api/account/lead-tabs")
    @_signed_in
    @_with_conn
    def set_lead_tabs_route(conn):
        """Set this account's own lead-tab layout ({tab name: Lead ID prefix}) - lets different
        accounts organize their Sheet differently instead of all sharing one hardcoded layout."""
        active = session[ACTIVE_KEY]
        lead_tabs = (request.get_json(silent=True) or {}).get("lead_tabs")
        try:
            tenancy.set_lead_tabs(conn, active, lead_tabs)
        except tenancy.TenancyError as exc:
            return jsonify(error=str(exc)), 400
        return jsonify(lead_tabs=lead_tabs, is_custom=True)

    @app.delete("/api/account/lead-tabs")
    @_signed_in
    @_with_conn
    def clear_lead_tabs_route(conn):
        """Reset this account back to the system default lead-tab layout."""
        tenancy.clear_lead_tabs(conn, session[ACTIVE_KEY])
        return jsonify(lead_tabs=LEAD_TABS, is_custom=False)

    @app.post("/api/jobs/auto")
    @_signed_in
    @_with_conn
    def jobs_auto(conn):
        """Run check, research and profile for the active account's own leads - the same three
        stages `job_auto.run` always chains, just against this account's own Sheet (and its own
        lead-tab layout) instead of the founder's."""
        active = session[ACTIVE_KEY]
        context, failure = _sheet_context(conn, active)
        if failure:
            return jsonify(error=failure[0]), failure[1]
        sheet_id, api, lead_tabs = context
        return jsonify(job_auto.run("tenant-console", api=api, sheet_id=sheet_id, lead_tabs=lead_tabs))

    @app.post("/api/jobs/draft/preview")
    @_signed_in
    @_with_conn
    def jobs_draft_preview(conn):
        active = session[ACTIVE_KEY]
        context, failure = _sheet_context(conn, active)
        if failure:
            return jsonify(error=failure[0]), failure[1]
        sheet_id, api, lead_tabs = context
        body = request.get_json(silent=True) or {}
        ids = body.get("ids") or []
        try:
            result = job_draft.previews(ids, api=api, sheet_id=sheet_id, lead_tabs=lead_tabs,
                                        write=bool(body.get("write")), quote_choices=body.get("quote_choices"))
        except job_draft.DraftBlocked as exc:
            return jsonify(error=str(exc)), 400
        return jsonify(previews=result)

    @app.post("/api/jobs/draft/create")
    @_signed_in
    @_with_conn
    def jobs_draft_create(conn):
        active = session[ACTIVE_KEY]
        context, failure = _sheet_context(conn, active)
        if failure:
            return jsonify(error=failure[0]), failure[1]
        sheet_id, api, lead_tabs = context
        gmail, failure = _gmail_api(conn, active)
        if failure:
            return jsonify(error=failure[0]), failure[1]
        body = request.get_json(silent=True) or {}
        try:
            result = job_draft.create(body.get("lead_id"), body.get("approved_hash"),
                                      written=body.get("written"), api=api, gmail=gmail,
                                      sheet_id=sheet_id, lead_tabs=lead_tabs)
        except job_draft.DraftBlocked as exc:
            return jsonify(error=str(exc)), 400
        return jsonify(result)

    # Deliberately no /api/jobs/send route here: outreach/send.py - the one sanctioned send path
    # - may only be imported by outreach/console.py (a human's "Approve and send" click) and
    # outreach/auto_send.py (the scheduled, cap-limited drip), both pinned by
    # tests/test_no_send.py per the founder's explicit decision (see CLAUDE.md). Adding a third
    # caller here, even behind a signed-in check, would be exactly the kind of change that rule
    # requires a founder decision for - not something to wire in quietly while threading sheet_id
    # through the rest of the engine. check/research/profile/draft all stop short of sending
    # (job_draft.create only creates a Gmail DRAFT); actually sending for a tenant account needs
    # its own explicit decision, matching how the founder's own single-tenant send path was added.

    return app


def _conn_factory():
    """A real Postgres connection to the tenant database, per request (closed by `_with_conn`).

    Only ever called lazily, inside a request - importing this module, or building the app with
    `_deployed()`, never opens a connection or requires these env vars to be set (same convention
    as `outreach.sheet._api()`/`outreach.google_auth.founder_credentials()`: real I/O deferred
    until something actually needs it).

    On Cloud Run, `TENANT_DB_SOCKET` (the Cloud SQL Auth Proxy's Unix socket directory, e.g.
    ``/cloudsql/lakshyaa-outreach:us-central1:outreach-tenant``, mounted automatically by
    `--add-cloudsql-instances`) is preferred over `TENANT_DB_HOST` - the socket never depends on
    an authorized-networks IP allowlist, unlike the public IP a local/dev connection uses."""
    import psycopg
    socket_dir = os.environ.get("TENANT_DB_SOCKET")
    host = socket_dir if socket_dir else os.environ["TENANT_DB_HOST"]
    kwargs = {} if socket_dir else {"sslmode": os.environ.get("TENANT_DB_SSLMODE", "require")}
    return psycopg.connect(
        host=host,
        dbname=os.environ.get("TENANT_DB_NAME", "postgres"),
        user=os.environ.get("TENANT_DB_USER", "postgres"),
        password=os.environ["TENANT_DB_PASSWORD"],
        **kwargs,
    )


def _verify_credential(credential):
    """Verifies a Google Identity Services credential JWT against the real OAuth client's id -
    the same id the frontend was handed via GET /api/config, so a credential issued for a
    different app is refused."""
    from google.auth.transport import requests as google_requests
    from google.oauth2 import id_token
    return id_token.verify_oauth2_token(credential, google_requests.Request(),
                                        os.environ.get("GOOGLE_OAUTH_CLIENT_ID"))


def _deployed():
    """The real, production app: a real Postgres connection factory, a real Google credential
    verifier, and a real Connector when the OAuth client's env vars/secrets are present
    (`google_connect.from_environment()` returns None otherwise, and the connect routes then
    correctly refuse with 503 rather than crash - see their docstrings)."""
    logging.basicConfig(level=logging.INFO)
    return create_app(
        conn_factory=_conn_factory,
        verify_credential=_verify_credential,
        connector=google_connect.from_environment(),
        secret_key=(os.environ.get("TENANT_CONSOLE_SECRET_KEY") or "").encode() or None,
        static_dir=os.environ.get("TENANT_CONSOLE_STATIC_DIR") or None,
        google_client_id=os.environ.get("GOOGLE_OAUTH_CLIENT_ID", ""),
    )


app = _deployed()
