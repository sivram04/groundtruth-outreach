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

Every route takes its dependencies by injection (``conn_factory``, ``verify_credential``,
``connector``), matching this repo's convention everywhere else, so this is fully testable
offline.
"""

import os
from functools import wraps

from flask import Flask, jsonify, request, session

from outreach import google_connect, tenancy

SESSION_KEY = "account_id"


def create_app(*, conn_factory, verify_credential, connector=None, secret_key=None,
              static_dir=None):
    """``conn_factory()`` returns a DB connection per call (closed by the caller - see
    ``_with_conn``). ``verify_credential(credential_jwt) -> {"sub", "email", "email_verified"}``
    checks a Google Identity Services credential; real use wraps
    ``google.oauth2.id_token.verify_oauth2_token``. ``connector`` is a
    ``google_connect.Connector`` (or ``None`` until the OAuth client exists, in which case the
    connect routes correctly refuse with 503 rather than crash)."""
    app = Flask(__name__, static_folder=static_dir)
    # A random per-process secret is fine for tests; production needs one real, persisted secret
    # (e.g. Secret Manager) - a restart that changes it logs out every session.
    app.secret_key = secret_key or os.urandom(32)

    def _with_conn(fn):
        @wraps(fn)
        def wrapped(*a, **kw):
            conn = conn_factory()
            try:
                return fn(conn, *a, **kw)
            finally:
                close = getattr(conn, "close", None)
                if close:
                    close()
        return wrapped

    def _signed_in(fn):
        @wraps(fn)
        def wrapped(*a, **kw):
            if SESSION_KEY not in session:
                return jsonify(error="Sign in first."), 401
            return fn(*a, **kw)
        return wrapped

    @app.post("/api/session/google")
    @_with_conn
    def sign_in(conn):
        """Verify a Google Identity Services credential and resolve/create the account."""
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
        session[SESSION_KEY] = account.id
        session["provider_subject"] = subject
        return jsonify(account_id=account.id, name=account.name, email=email)

    @app.get("/api/session")
    def current_session():
        if SESSION_KEY not in session:
            return jsonify(signed_in=False)
        return jsonify(signed_in=True, account_id=session[SESSION_KEY])

    @app.post("/api/session/logout")
    def logout():
        session.clear()
        return jsonify(ok=True)

    @app.post("/api/connections/<kind>/start")
    @_signed_in
    @_with_conn
    def connect_start(conn, kind):
        if connector is None:
            return jsonify(error="Google connections are not configured yet."), 503
        if kind not in google_connect.SCOPES:
            return jsonify(error="Choose gmail or drive."), 400
        try:
            url = connector.begin(conn, session[SESSION_KEY], session["provider_subject"], kind)
        except (google_connect.Refused, ValueError) as exc:
            return jsonify(error=str(exc)), 400
        return jsonify(authorization_url=url)

    @app.get("/api/tenant/google/callback")
    @_signed_in
    @_with_conn
    def connect_callback(conn):
        if connector is None:
            return jsonify(error="Google connections are not configured yet."), 503
        state, code = request.args.get("state", ""), request.args.get("code", "")
        try:
            result = connector.complete(conn, session[SESSION_KEY], session["provider_subject"],
                                        state, code)
        except google_connect.Refused as exc:
            return jsonify(error=str(exc)), 400
        return jsonify(ok=True, **result)

    return app
