"""Who may open the console: only a token Google's sign-in gate signed, for this console, for an
allowed address. Tokens here are signed with keys made for the test; nothing reaches Google."""

import base64
import json
import time

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from google.auth import jwt
from google.auth.crypt import es256

from outreach import console_auth
from outreach.console_auth import ISSUER, Refused, Verifier

AUDIENCE = "/projects/123456/locations/us-central1/services/outreach-console"
ALLOWED = frozenset({"admin@lakshyaa.ai"})


def keypair():
    key = ec.generate_private_key(ec.SECP256R1())
    private = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                serialization.NoEncryption())
    public = key.public_key().public_bytes(serialization.Encoding.PEM,
                                           serialization.PublicFormat.SubjectPublicKeyInfo)
    return private, public.decode()


PRIVATE, PUBLIC = keypair()
OTHER_PRIVATE, _ = keypair()


def token(private=PRIVATE, kid="key-1", **claims):
    now = int(time.time())
    payload = {"iss": ISSUER, "aud": AUDIENCE, "iat": now, "exp": now + 600,
               "email": "admin@lakshyaa.ai", "sub": "accounts.google.com:1234"}
    payload.update(claims)
    signer = es256.ES256Signer.from_string(private, key_id=kid)
    return jwt.encode(signer, payload).decode()


class Keys:
    """IAP's public keys, as the verifier would fetch them; counts the fetches."""

    def __init__(self, keys=None, fail=False):
        self.keys = {"key-1": PUBLIC} if keys is None else keys
        self.fail, self.fetches = fail, 0

    def __call__(self):
        self.fetches += 1
        if self.fail:
            raise OSError("network down")
        return dict(self.keys)


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


def verifier(keys=None, clock=None):
    return Verifier(AUDIENCE, ALLOWED, fetch=keys or Keys(), clock=clock or Clock())


def refused(check, assertion):
    with pytest.raises(Refused) as caught:
        check.email(assertion)
    return caught.value


def test_a_token_iap_signed_for_this_console_and_an_allowed_address_is_accepted():
    assert jwt.decode_header(token())["alg"] == "ES256"
    assert verifier().email(token()) == "admin@lakshyaa.ai"


def test_the_address_is_read_with_or_without_googles_account_prefix():
    assert verifier().email(token(email="accounts.google.com:ADMIN@lakshyaa.ai")) == "admin@lakshyaa.ai"


def test_a_signed_in_address_not_on_the_list_is_forbidden_not_unknown():
    error = refused(verifier(), token(email="someone@lakshyaa.ai"))
    assert error.status == 403


@pytest.mark.parametrize("assertion", [None, "", "not-a-token", "a.b.c"])
def test_no_token_or_an_unreadable_one_is_refused(assertion):
    assert refused(verifier(), assertion).status == 401


def test_a_token_for_another_service_is_refused():
    other = "/projects/123456/locations/us-central1/services/outreach-worker"
    assert refused(verifier(), token(aud=other)).status == 401


def test_an_expired_token_is_refused():
    past = int(time.time()) - 7200
    assert refused(verifier(), token(iat=past, exp=past + 600)).status == 401


def test_a_token_not_issued_by_iap_is_refused():
    assert refused(verifier(), token(iss="https://accounts.google.com")).status == 401


def test_a_token_signed_with_another_key_under_iaps_key_id_is_refused():
    assert refused(verifier(), token(private=OTHER_PRIVATE)).status == 401


def encode(part):
    return base64.urlsafe_b64encode(json.dumps(part).encode()).decode().rstrip("=")


@pytest.mark.parametrize("header", [{"alg": "none", "kid": "key-1"}, {"alg": "HS256", "kid": "key-1"},
                                    {"alg": "RS256", "kid": "key-1"}, {"alg": "ES256"}])
def test_a_token_not_signed_the_way_iap_signs_is_refused(header):
    body = {"iss": ISSUER, "aud": AUDIENCE, "email": "admin@lakshyaa.ai",
            "iat": int(time.time()), "exp": int(time.time()) + 600}
    forged = f"{encode(header)}.{encode(body)}.{encode('sig')}"
    assert refused(verifier(), forged).status == 401


def test_only_es256_is_accepted_even_with_a_valid_signature_by_a_listed_key():
    """IAP signs with ES256 only. A token signed another way is refused before its signature is
    even looked at, even if the key set held a key that could check it."""
    from cryptography.hazmat.primitives.asymmetric import rsa
    from google.auth import crypt

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                serialization.NoEncryption())
    public = key.public_key().public_bytes(serialization.Encoding.PEM,
                                           serialization.PublicFormat.SubjectPublicKeyInfo).decode()
    now = int(time.time())
    signed = jwt.encode(crypt.RSASigner.from_string(private, key_id="rsa-1"),
                        {"iss": ISSUER, "aud": AUDIENCE, "iat": now, "exp": now + 600,
                         "email": "admin@lakshyaa.ai"}).decode()
    assert jwt.decode_header(signed)["alg"] == "RS256"
    assert jwt.decode(signed, certs={"rsa-1": public}, audience=AUDIENCE)  # a good signature
    keys = Keys({"key-1": PUBLIC, "rsa-1": public})
    assert refused(verifier(keys), signed).status == 401


def test_a_key_not_yet_seen_makes_the_keys_be_read_again_once():
    keys = Keys()
    check = verifier(keys)
    assert check.email(token()) == "admin@lakshyaa.ai"
    assert keys.fetches == 1
    assert refused(check, token(kid="key-2")).status == 401
    assert keys.fetches == 2  # read again, once, for the unknown key
    keys.keys["key-2"] = PUBLIC
    assert check.email(token(kid="key-2")) == "admin@lakshyaa.ai"


def test_the_keys_are_kept_for_an_hour_then_read_again():
    keys, clock = Keys(), Clock()
    check = verifier(keys, clock)
    check.email(token())
    clock.now += console_auth.CERTS_TTL_SECONDS - 1
    check.email(token())
    assert keys.fetches == 1
    clock.now += 2
    check.email(token())
    assert keys.fetches == 2


def test_when_iaps_keys_cannot_be_read_the_request_is_refused_as_unavailable():
    assert refused(verifier(Keys(fail=True)), token()).status == 503


def test_a_verifier_needs_a_real_audience_and_someone_to_let_in():
    with pytest.raises(ValueError):
        Verifier("outreach-console", ALLOWED)
    with pytest.raises(ValueError):
        Verifier(AUDIENCE, frozenset())


def test_the_deployed_setting_is_read_from_the_environment_or_nothing_opens():
    assert console_auth.from_environment({}) is None
    assert console_auth.from_environment({"CONSOLE_IAP_AUDIENCE": AUDIENCE}) is None
    made = console_auth.from_environment({"CONSOLE_IAP_AUDIENCE": AUDIENCE,
                                          "CONSOLE_ALLOWED_EMAILS": " Admin@Lakshyaa.ai, ,"})
    assert made.audience == AUDIENCE and made.allowed == ALLOWED
