# tests/test_fingerprint.py — ACRCloud signature building and response parsing

import base64
import hashlib
import hmac

from fingerprint import _build_signature

# ── Signature generation ──────────────────────────────────────────────────────


def test_build_signature_matches_manual_computation():
    key = "testkey"
    secret = "testsecret"
    timestamp = "1700000000"

    string_to_sign = "\n".join(["POST", "/v1/identify", key, "audio", "1", timestamp])
    expected = base64.b64encode(
        hmac.new(secret.encode(), string_to_sign.encode(), hashlib.sha1).digest()
    ).decode()

    assert _build_signature(timestamp, key, secret) == expected


def test_build_signature_is_deterministic():
    sig1 = _build_signature("12345", "key", "secret")
    sig2 = _build_signature("12345", "key", "secret")
    assert sig1 == sig2


def test_build_signature_differs_on_timestamp():
    sig1 = _build_signature("1000", "key", "secret")
    sig2 = _build_signature("2000", "key", "secret")
    assert sig1 != sig2


def test_build_signature_differs_on_key():
    sig1 = _build_signature("1000", "key_a", "secret")
    sig2 = _build_signature("1000", "key_b", "secret")
    assert sig1 != sig2


def test_build_signature_differs_on_secret():
    sig1 = _build_signature("1000", "key", "secret_a")
    sig2 = _build_signature("1000", "key", "secret_b")
    assert sig1 != sig2


def test_build_signature_is_base64():
    sig = _build_signature("1700000000", "key", "secret")
    # Should decode without error
    decoded = base64.b64decode(sig)
    assert len(decoded) == 20  # SHA-1 digest is 20 bytes
