"""Tests for backend/services/encryption.py.

The encryption key is set in conftest.py so the module imports cleanly.
"""
import json

import pytest

from services import encryption


# ── Round-trip ────────────────────────────────────────────────────────────────

def test_encrypt_decrypt_round_trip_ascii():
    ct = encryption.encrypt("hello world")
    assert encryption.decrypt(ct) == "hello world"


def test_encrypt_decrypt_round_trip_unicode():
    plain = "Andrés López — résumé €"
    assert encryption.decrypt(encryption.encrypt(plain)) == plain


def test_encrypt_decrypt_round_trip_long():
    plain = "x" * 5000
    assert encryption.decrypt(encryption.encrypt(plain)) == plain


def test_encrypt_decrypt_empty_string():
    ct = encryption.encrypt("")
    assert encryption.decrypt(ct) == ""


# ── JSON helpers ──────────────────────────────────────────────────────────────

def test_encrypt_decrypt_json_dict():
    payload = {"a": 1, "b": [1, 2, 3], "c": {"nested": True}}
    ct = encryption.encrypt_json(payload)
    assert encryption.decrypt_json(ct) == payload


def test_encrypt_decrypt_json_list():
    payload = [{"name": "X", "description": "Y"}, {"name": "Z", "description": "W"}]
    assert encryption.decrypt_json(encryption.encrypt_json(payload)) == payload


# ── Numeric helper ────────────────────────────────────────────────────────────

def test_decrypt_numeric_returns_float():
    ct = encryption.encrypt("87.5")
    out = encryption.decrypt_numeric(ct)
    assert isinstance(out, float)
    assert out == pytest.approx(87.5)


def test_decrypt_numeric_none_passthrough():
    assert encryption.decrypt_numeric(None) is None


# ── _if_present helpers ───────────────────────────────────────────────────────

def test_encrypt_if_present_none():
    assert encryption.encrypt_if_present(None) is None


def test_encrypt_if_present_value():
    out = encryption.encrypt_if_present("foo")
    assert out is not None and out != "foo"
    assert encryption.decrypt(out) == "foo"


def test_encrypt_if_present_coerces_non_string():
    out = encryption.encrypt_if_present(42)
    assert encryption.decrypt(out) == "42"


def test_decrypt_if_present_none():
    assert encryption.decrypt_if_present(None) is None


def test_decrypt_if_present_legacy_plaintext_passthrough(caplog):
    # Legacy unencrypted rows must not break reads — they pass through with a warning.
    out = encryption.decrypt_if_present("plain unencrypted text")
    assert out == "plain unencrypted text"
    assert any("decrypt" in rec.message.lower() for rec in caplog.records)


# ── Nonce randomness ──────────────────────────────────────────────────────────

def test_two_encryptions_of_same_value_differ():
    a = encryption.encrypt("same")
    b = encryption.encrypt("same")
    assert a != b
    assert encryption.decrypt(a) == encryption.decrypt(b) == "same"


# ── Tamper detection ──────────────────────────────────────────────────────────

def test_tampered_ciphertext_raises():
    import base64
    ct = encryption.encrypt("secret")
    raw = bytearray(base64.b64decode(ct))
    raw[-1] ^= 0x01  # flip one bit in the tag
    tampered = base64.b64encode(bytes(raw)).decode()
    with pytest.raises(Exception):
        encryption.decrypt(tampered)
