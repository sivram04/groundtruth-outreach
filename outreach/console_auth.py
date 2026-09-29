"""Who may open the console.

Google's sign-in gate (Identity-Aware Proxy, IAP) stands in front of the service and lets
through only the accounts given access. Each request it lets through carries a token it signed,
in the X-Goog-IAP-JWT-Assertion header. The console checks that token on every request, so the
data stays closed even if the gate were ever switched off by mistake:

  - signed by Google's IAP keys, with ES256, the only algorithm IAP uses;
  - issued by IAP, for this one service (the audience), and not expired;
  - for an address on this console's own allow-list.

Anything that cannot be checked is refused. The plain X-Goog-Authenticated-User-Email header is
never trusted: anyone can send it when the gate is not there.
"""

import os
import time

import requests
from google.auth import exceptions as auth_exceptions
from google.auth import jwt

HEADER = "X-Goog-IAP-JWT-Assertion"
ISSUER = "https://cloud.google.com/iap"
CERTS_URL = "https://www.gstatic.com/iap/verify/public_key"
ALGORITHM = "ES256"
# IAP rotates its keys. The keys are read again after an hour, and at once when a token names a
# key not yet seen. Both numbers are this system's choice.
CERTS_TTL_SECONDS = 3600
CLOCK_SKEW_SECONDS = 30
EMAIL_PREFIX = "accounts.google.com:"


class Refused(Exception):
    """The request did not prove who sent it, or the person may not use the console.

    `status` is 401 when the proof is missing or bad, 403 when it is good but the account is not
    allowed."""

    def __init__(self, why, status=401):
        super().__init__(why)
        self.status = status


def fetch_certs():
    """IAP's current public keys: {key id: PEM}."""
    response = requests.get(CERTS_URL, timeout=10)
    response.raise_for_status()
    certs = response.json()
    if not isinstance(certs, dict) or not certs:
        raise RuntimeError("IAP's public keys could not be read")
    return certs


def allowed_emails(text):
    """The allow-list from a comma-separated setting, lower case, blanks dropped."""
    return frozenset(part.strip().lower() for part in (text or "").split(",") if part.strip())


class Verifier:
    """Checks one request's IAP token. `fetch` and `clock` are replaceable for tests."""

    def __init__(self, audience, allowed, *, fetch=fetch_certs, clock=time.monotonic):
        if not audience or not audience.startswith("/projects/"):
            raise ValueError("the IAP audience must be /projects/NUMBER/locations/REGION/"
                             "services/SERVICE")
        if not allowed:
            raise ValueError("at least one allowed email is required")
        self.audience = audience
        self.allowed = frozenset(allowed)
        self.fetch, self.clock = fetch, clock
        self._certs, self._read_at = None, None

    def _keys(self, kid):
        stale = self._certs is None or self.clock() - self._read_at > CERTS_TTL_SECONDS
        if stale or kid not in self._certs:
            self._certs, self._read_at = dict(self.fetch()), self.clock()
        return self._certs

    def email(self, assertion):
        """The signed-in, allowed address the token proves, or Refused."""
        if not assertion:
            raise Refused("no sign-in token: open the console through its Google sign-in")
        try:
            header = jwt.decode_header(assertion)
        except (ValueError, TypeError, auth_exceptions.GoogleAuthError):
            raise Refused("the sign-in token cannot be read") from None
        if header.get("alg") != ALGORITHM:
            raise Refused("the sign-in token is not signed the way IAP signs")
        kid = header.get("kid")
        if not kid:
            raise Refused("the sign-in token names no key")
        try:
            keys = self._keys(kid)
        except Exception:
            raise Refused("IAP's public keys could not be read", status=503) from None
        if kid not in keys:
            raise Refused("the sign-in token names a key IAP does not use")
        try:
            claims = jwt.decode(assertion, certs={kid: keys[kid]}, audience=self.audience,
                                clock_skew_in_seconds=CLOCK_SKEW_SECONDS)
        except (ValueError, TypeError, auth_exceptions.GoogleAuthError):
            raise Refused("the sign-in token is not valid for this console") from None
        if claims.get("iss") != ISSUER:
            raise Refused("the sign-in token was not issued by IAP")
        email = str(claims.get("email", "")).strip().lower()
        if email.startswith(EMAIL_PREFIX):
            email = email[len(EMAIL_PREFIX):]
        if not email or email not in self.allowed:
            raise Refused("this account may not use the console", status=403)
        return email


def from_environment(environ=None):
    """The verifier the deployed console uses, or None when it is not configured (every request
    is then refused)."""
    environ = os.environ if environ is None else environ
    audience = environ.get("CONSOLE_IAP_AUDIENCE", "").strip()
    allowed = allowed_emails(environ.get("CONSOLE_ALLOWED_EMAILS", ""))
    if not audience or not allowed:
        return None
    return Verifier(audience, allowed)
