"""outreach/google_connect.py's KMSVault, against a fake low-level KMS client (the piece every
other test in this branch deliberately swaps out for a trivial fake vault). Proves the request
shape and the response-integrity checks: a tampered/truncated reply from "KMS" is refused, never
trusted."""

import google_crc32c
import pytest

from outreach import google_connect as gc

KEY = "projects/p/locations/l/keyRings/r/cryptoKeys/k"
ACCOUNT, KIND, SUBJECT = "acct-1", "gmail", "g-subject-1"


class _Reply:
    def __init__(self, **kw):
        self.__dict__.update(kw)


class FakeKMSClient:
    """Mimics google.cloud.kms_v1.KeyManagementServiceClient just enough: encrypt/decrypt read
    the request dict, and can be told to return a tampered/truncated reply for the refusal tests."""

    def __init__(self):
        self.encrypt_calls, self.decrypt_calls = [], []
        self.corrupt_ciphertext_crc = False
        self.corrupt_plaintext_crc = False
        self.wrong_key_name_in_reply = False

    def encrypt(self, request, timeout=None):
        self.encrypt_calls.append(request)
        ciphertext = b"CIPHER(" + request["plaintext"] + b")"
        return _Reply(
            ciphertext=ciphertext,
            ciphertext_crc32c=(google_crc32c.value(ciphertext) + 1) if self.corrupt_ciphertext_crc
                              else google_crc32c.value(ciphertext),
            verified_plaintext_crc32c=True, verified_additional_authenticated_data_crc32c=True,
            name=(KEY + "/wrong-path") if self.wrong_key_name_in_reply
                 else (KEY + "/cryptoKeyVersions/1"))

    def decrypt(self, request, timeout=None):
        self.decrypt_calls.append(request)
        ciphertext = request["ciphertext"]
        plaintext = ciphertext.removeprefix(b"CIPHER(").removesuffix(b")")
        return _Reply(
            plaintext=plaintext,
            plaintext_crc32c=(google_crc32c.value(plaintext) + 1) if self.corrupt_plaintext_crc
                             else google_crc32c.value(plaintext))


def test_encrypt_sends_the_plaintext_and_an_account_kind_subject_bound_aad():
    client = FakeKMSClient()
    vault = gc.KMSVault(KEY, client=client)
    vault.encrypt("a-refresh-token", ACCOUNT, KIND, SUBJECT)
    request = client.encrypt_calls[0]
    assert request["plaintext"] == b"a-refresh-token"
    assert request["additional_authenticated_data"] == gc._aad(ACCOUNT, KIND, SUBJECT)


def test_encrypt_then_decrypt_round_trips():
    client = FakeKMSClient()
    vault = gc.KMSVault(KEY, client=client)
    ciphertext = vault.encrypt("a-refresh-token", ACCOUNT, KIND, SUBJECT)
    assert vault.decrypt(ciphertext, ACCOUNT, KIND, SUBJECT) == "a-refresh-token"


def test_decrypt_uses_the_same_aad_so_a_different_subject_would_fail_against_real_kms():
    # This fake doesn't itself enforce AAD-bound decryption (real KMS does); it proves the AAD
    # sent on decrypt matches encrypt's exactly, which is what makes that enforcement possible.
    client = FakeKMSClient()
    vault = gc.KMSVault(KEY, client=client)
    ciphertext = vault.encrypt("a-refresh-token", ACCOUNT, KIND, SUBJECT)
    vault.decrypt(ciphertext, ACCOUNT, KIND, SUBJECT)
    enc_aad = client.encrypt_calls[0]["additional_authenticated_data"]
    dec_aad = client.decrypt_calls[0]["additional_authenticated_data"]
    assert enc_aad == dec_aad == gc._aad(ACCOUNT, KIND, SUBJECT)


def test_encrypt_refuses_a_tampered_ciphertext_crc():
    client = FakeKMSClient()
    client.corrupt_ciphertext_crc = True
    vault = gc.KMSVault(KEY, client=client)
    with pytest.raises(gc.Refused, match="encryption failed"):
        vault.encrypt("a-refresh-token", ACCOUNT, KIND, SUBJECT)


def test_encrypt_refuses_a_reply_naming_the_wrong_key():
    client = FakeKMSClient()
    client.wrong_key_name_in_reply = True
    vault = gc.KMSVault(KEY, client=client)
    with pytest.raises(gc.Refused, match="encryption failed"):
        vault.encrypt("a-refresh-token", ACCOUNT, KIND, SUBJECT)


def test_decrypt_refuses_a_tampered_plaintext_crc():
    client = FakeKMSClient()
    vault = gc.KMSVault(KEY, client=client)
    ciphertext = vault.encrypt("a-refresh-token", ACCOUNT, KIND, SUBJECT)
    client.corrupt_plaintext_crc = True
    with pytest.raises(gc.Refused, match="decryption failed"):
        vault.decrypt(ciphertext, ACCOUNT, KIND, SUBJECT)


def test_decrypt_refuses_an_invalid_stored_key_name():
    client = FakeKMSClient()
    vault = gc.KMSVault(KEY, client=client)
    with pytest.raises(gc.Refused, match="key is invalid"):
        vault.decrypt(b"whatever", ACCOUNT, KIND, SUBJECT, key_name="not-a-real-key-resource-name")


@pytest.mark.parametrize("bad_key", ["", "not-a-key", "projects/p/locations/l/keyRings/r"])
def test_constructing_a_vault_requires_a_well_formed_key_name(bad_key):
    with pytest.raises(ValueError):
        gc.KMSVault(bad_key, client=FakeKMSClient())


def test_a_client_exception_is_never_leaked_as_the_refusal_message():
    class ExplodingClient:
        def encrypt(self, request, timeout=None):
            raise RuntimeError("some internal GCP detail, a secret project id, a stack trace")

    vault = gc.KMSVault(KEY, client=ExplodingClient())
    with pytest.raises(gc.Refused) as exc_info:
        vault.encrypt("a-refresh-token", ACCOUNT, KIND, SUBJECT)
    assert "some internal GCP detail" not in str(exc_info.value)
