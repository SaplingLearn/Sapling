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


# ── #200: columns retyped NUMERIC/JSONB -> TEXT in the canonical schema ─────────
# These hold encrypted base64 *text*, so the value each column stores must survive
# the exact write->read helpers the routes use. The route-level coverage for
# documents.concept_notes lives in the test_documents_routes module quarantined
# under #210, so assert the round-trip here (non-quarantined) before that change
# lands. summary_json/concept_notes -> encrypt_json/decrypt_json; points ->
# encrypt_if_present/decrypt_numeric (see routes/learn.py, routes/documents.py,
# routes/gradebook.py).

def test_summary_json_text_column_round_trip():
    # sessions.summary_json — a JSON object (learn.py writes encrypt_json(summary))
    summary = {"concepts": ["limits", "derivatives"], "score": 0.82, "notes": "ünïcode"}
    assert encryption.decrypt_json(encryption.encrypt_json(summary)) == summary


def test_concept_notes_text_column_round_trip():
    # documents.concept_notes — a JSON array of {name, description}
    # (documents.py writes encrypt_json(concept_notes))
    concept_notes = [
        {"name": "Eigenvalue", "description": "Scalar λ with Av = λv."},
        {"name": "Span", "description": "All linear combinations of a set."},
    ]
    assert encryption.decrypt_json(encryption.encrypt_json(concept_notes)) == concept_notes


def test_points_text_column_round_trip():
    # assignments.points_possible / points_earned — numbers written via
    # encrypt_if_present and read back via decrypt_numeric.
    for value in (100, 95.5, 0):
        ct = encryption.encrypt_if_present(value)
        assert isinstance(ct, str)  # stored as TEXT, not NUMERIC
        assert encryption.decrypt_numeric(ct) == float(value)
    assert encryption.encrypt_if_present(None) is None
    assert encryption.decrypt_numeric(None) is None
