"""AES-GCM associated data: a 🔒 value opens only in its own cell (finding M13).

docs/security/encryption-aad-plan.md, "Tests the implementation must carry".
The suite runs with ENCRYPTION_WRITE_V2=on (tests/conftest.py).
"""
from __future__ import annotations

import base64
import os
from unittest.mock import MagicMock

import pytest

from services import encryption as enc
from services import encryption_canary
from services.encryption import (
    BindingMismatch,
    LegacyRefused,
    bind,
    decrypt,
    decrypt_bytes,
    decrypt_if_present,
    decrypt_json,
    decrypt_json_column,
    decrypt_numeric,
    encrypt,
    encrypt_bytes,
    encrypt_if_present,
    encrypt_json,
)

ALICE = bind("user_profiles", "name", {"user_id": "user_alice"})
BOB = bind("user_profiles", "name", {"user_id": "user_bob"})


@pytest.fixture(autouse=True)
def _defaults(monkeypatch):
    monkeypatch.setenv("ENCRYPTION_WRITE_V2", "on")
    monkeypatch.delenv("ENCRYPTION_LEGACY_READS", raising=False)
    monkeypatch.delenv("ENCRYPTION_STRICT_TABLES", raising=False)
    enc.reset_security_counts()
    yield
    enc.reset_security_counts()


@pytest.fixture
def events(monkeypatch):
    calls: list[tuple[str, dict]] = []
    from services import events_service

    monkeypatch.setattr(events_service, "log_event",
                        lambda name, **kw: calls.append((name, kw)))
    return calls


def _v1(plain: str) -> str:
    """A value exactly as pre-M13 code wrote it."""
    return encrypt(plain, v2=False)


# ── Round trips, every helper ───────────────────────────────────────────────


def test_text_round_trip_is_v2_and_bound():
    ct = encrypt("Alice Liddell", bind=ALICE)
    assert ct.startswith("enc2:0:")
    assert decrypt(ct, bind=ALICE) == "Alice Liddell"
    assert encrypt_if_present("Alice", bind=ALICE).startswith("enc2:")
    assert decrypt_if_present(encrypt_if_present("Alice", bind=ALICE), bind=ALICE) == "Alice"
    assert encrypt_if_present(None, bind=ALICE) is None
    assert decrypt_if_present(None, bind=ALICE) is None


def test_numeric_round_trip():
    b = bind("assignments", "points_earned", {"id": "a1"})
    assert decrypt_numeric(encrypt_if_present(17.5, bind=b), bind=b) == 17.5
    assert decrypt_numeric(None, bind=b) is None


def test_json_round_trip():
    b = bind("quiz_attempts", "questions_json", "att1")
    payload = {"q": [1, 2, {"k": "v"}]}
    ct = encrypt_json(payload, bind=b)
    assert ct.startswith("enc2:")
    assert decrypt_json(ct, bind=b) == payload
    assert decrypt_json_column(ct, bind=b) == payload
    assert decrypt_json_column(None, bind=b) is None


def test_bytes_round_trip():
    b = bind("document_uploads", "file_data", "up1")
    blob = os.urandom(300)
    ct = encrypt_bytes(blob, bind=b)
    assert ct.startswith("enc2:")
    assert decrypt_bytes(ct, bind=b) == blob


def test_composite_and_redirected_bindings():
    b = bind("quiz_responses", "answer_text", {"attempt_id": "a", "question_index": 3})
    assert b.row_key == "a|3"
    assert bind("quiz_responses", "answer_text", ("a", 3)) == b
    # The pending greeting is sealed for the messages row SQL copies it into.
    pending = bind("tutor_pending_sessions", "assistant_reply", {"session_id": "s1"})
    assert pending == bind("messages", "content", {"session_id": "s1"})


def test_bind_refuses_unknown_columns_and_partial_keys():
    with pytest.raises(enc.UnknownColumn):
        bind("users", "password", "u1")
    with pytest.raises(enc.MissingRowKey):
        bind("notes", "body", {"title": "no id"})
    with pytest.raises(enc.MissingRowKey):
        bind("quiz_responses", "answer_text", {"attempt_id": "a"})
    with pytest.raises(enc.MissingRowKey):
        bind("notes", "body", "")


# ── Moves and swaps fail ────────────────────────────────────────────────────


def test_swapping_a_value_between_two_users_fails(events):
    alice_ct = encrypt("Alice", bind=ALICE)
    # An attacker with DB write access copies Alice's name into Bob's row.
    with pytest.raises(BindingMismatch):
        decrypt(alice_ct, bind=BOB)
    assert decrypt_if_present(alice_ct, bind=BOB) is None  # never the ciphertext
    assert events and events[0][0] == "encryption.binding_mismatch"
    name, kw = events[0]
    assert kw["category"] == "system"
    assert kw["payload"] == {"table": "user_profiles", "column": "name",
                             "reason": "auth_failed", "version": "v2"}
    assert "user_id" not in kw or kw.get("user_id") is None
    # Two refused reads, two counts; no payload carries the value or plaintext.
    assert enc.security_counts() == {("binding_mismatch", "user_profiles", "name"): 2}
    assert all(alice_ct not in repr(kw) and "Alice" not in repr(kw) for _, kw in events)


@pytest.mark.parametrize("victim", [
    bind("messages", "content", {"session_id": "s2"}),          # another session
    bind("oauth_tokens", "access_token", {"user_id": "user_alice"}),  # another table
    bind("user_profiles", "bio", {"user_id": "user_alice"}),    # another column
])
def test_moving_a_value_to_another_row_table_or_column_fails(victim):
    ct = encrypt("secret", bind=bind("messages", "content", {"session_id": "s1"}))
    assert decrypt_if_present(ct, bind=victim) is None


def test_oauth_tokens_swapped_between_accounts_do_not_open():
    a = bind("oauth_tokens", "refresh_token", "user_a")
    b = bind("oauth_tokens", "refresh_token", "user_b")
    ta, tb = encrypt("tok-a", bind=a), encrypt("tok-b", bind=b)
    assert decrypt_if_present(tb, bind=a) is None
    assert decrypt_if_present(ta, bind=b) is None


def test_grades_and_json_swaps_fail_closed_in_every_helper():
    pa = bind("assignments", "points_earned", "asg1")
    pb = bind("assignments", "points_earned", "asg2")
    assert decrypt_numeric(encrypt_if_present(100, bind=pa), bind=pb) is None
    ja = bind("quiz_responses", "answer_text", ("att", 0))
    jb = bind("quiz_responses", "answer_text", ("att", 1))
    ct = encrypt_json({"text": "x"}, bind=ja)
    with pytest.raises(BindingMismatch):
        decrypt_json(ct, bind=jb)
    assert decrypt_json_column(ct, bind=jb) is None
    fa = bind("document_uploads", "file_data", "up1")
    with pytest.raises(BindingMismatch):
        decrypt_bytes(encrypt_bytes(b"pdf", bind=fa), bind=bind("document_uploads", "file_data", "up2"))


def test_v2_read_without_a_binding_fails():
    ct = encrypt("x", bind=ALICE)
    with pytest.raises(BindingMismatch):
        decrypt(ct)
    assert decrypt_if_present(ct) is None
    assert decrypt_json_column(encrypt_json({"a": 1}, bind=ALICE)) is None


def test_tampered_or_unknown_kid_fails():
    ct = encrypt("x", bind=ALICE)
    raw = bytearray(base64.b64decode(ct.split(":", 2)[2]))
    raw[-1] ^= 1
    tampered = "enc2:0:" + base64.b64encode(bytes(raw)).decode()
    assert decrypt_if_present(tampered, bind=ALICE) is None
    assert decrypt_if_present(ct.replace("enc2:0:", "enc2:9:"), bind=ALICE) is None
    assert decrypt_if_present("enc2:0", bind=ALICE) is None


# ── Legacy v1 during the migration, refused after ───────────────────────────


def test_v1_still_reads_while_legacy_is_allowed():
    old = _v1("Alice")
    assert not old.startswith("enc2:")
    assert decrypt(old) == "Alice"
    assert decrypt(old, bind=ALICE) == "Alice"
    assert decrypt_if_present(old, bind=ALICE) == "Alice"
    assert decrypt_numeric(_v1("12"), bind=bind("assignments", "points_possible", "a")) == 12.0
    assert decrypt_json_column(_v1('{"a":1}'), bind=bind("sessions", "summary_json", "s")) == {"a": 1}
    # Legacy plaintext keeps today's soft fallback while allowed.
    assert decrypt_if_present("plain name", bind=ALICE) == "plain name"
    assert decrypt_json_column({"legacy": True}, bind=bind("quiz_context", "context_json", ("u", "c"))) \
        == {"legacy": True}


def test_v1_and_plaintext_refused_when_legacy_reads_are_off(monkeypatch, events):
    monkeypatch.setenv("ENCRYPTION_LEGACY_READS", "refuse")
    old = _v1("Alice")
    with pytest.raises(LegacyRefused):
        decrypt(old, bind=ALICE)
    assert decrypt_if_present(old, bind=ALICE) is None
    assert decrypt_if_present("injected plaintext", bind=ALICE) is None
    pts = bind("assignments", "points_earned", "a")
    assert decrypt_numeric(_v1("99"), bind=pts) is None
    assert decrypt_numeric(99, bind=pts) is None
    b = bind("sessions", "summary_json", "s")
    assert decrypt_json_column({"injected": True}, bind=b) is None
    with pytest.raises(LegacyRefused):
        decrypt_json(_v1("{}"), bind=b)
    assert {e[0] for e in events} == {"encryption.legacy_refused"}
    # v2 is unaffected.
    assert decrypt_if_present(encrypt("Alice", bind=ALICE), bind=ALICE) == "Alice"


def test_strict_tables_refuse_one_table_at_a_time(monkeypatch):
    monkeypatch.setenv("ENCRYPTION_STRICT_TABLES", "messages, oauth_tokens")
    msg = bind("messages", "content", "s1")
    assert decrypt_if_present(_v1("hi"), bind=msg) is None
    assert decrypt_if_present(_v1("Alice"), bind=ALICE) == "Alice"


def test_a_misspelt_legacy_setting_refuses(monkeypatch):
    monkeypatch.setenv("ENCRYPTION_LEGACY_READS", "refused")
    assert enc.legacy_reads_allowed("users") is False
    monkeypatch.setenv("ENCRYPTION_LEGACY_READS", " Allow ")
    assert enc.legacy_reads_allowed("users") is True


def test_unbound_legacy_reads_are_unaffected_by_the_switch(monkeypatch):
    """The few allowlisted unbound sites (offline scripts) keep the v1 path."""
    monkeypatch.setenv("ENCRYPTION_LEGACY_READS", "refuse")
    assert decrypt(_v1("x")) == "x"


# ── Prefix dispatch and the write switch ────────────────────────────────────


def test_no_v1_value_can_begin_with_the_v2_prefix():
    alphabet = set("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/=")
    assert ":" not in alphabet
    for i in range(200):
        assert not _v1("x" * i).startswith("enc2:")


def test_writes_stay_v1_until_the_switch_is_on(monkeypatch):
    monkeypatch.setenv("ENCRYPTION_WRITE_V2", "off")
    ct = encrypt("Alice", bind=ALICE)
    assert not ct.startswith("enc2:")
    assert decrypt(ct) == "Alice"  # what pre-M13 readers do
    monkeypatch.setenv("ENCRYPTION_WRITE_V2", "on")
    assert encrypt("Alice").startswith("enc2:") is False  # unbound: always v1
    with pytest.raises(ValueError):
        encrypt("Alice", v2=True)  # v2 needs a binding


# ── The key canary keeps its semantics ──────────────────────────────────────


def _canary_table(value):
    t = MagicMock()
    t.select.return_value = [{"canary": value}]
    return t


def test_canary_v1_still_verifies_even_with_legacy_reads_off(monkeypatch):
    monkeypatch.setenv("ENCRYPTION_LEGACY_READS", "refuse")
    t = _canary_table(_v1(encryption_canary.CANARY_PLAINTEXT))
    monkeypatch.setattr(encryption_canary, "table", lambda name: t)
    assert encryption_canary.verify_encryption_key() == "ok"


def test_canary_seeds_v2_and_verifies(monkeypatch):
    seeded = {}
    t = MagicMock()
    t.select.side_effect = lambda *a, **k: [{"canary": seeded["canary"]}] if seeded else []
    t.upsert.side_effect = lambda data, **k: seeded.update(data)
    monkeypatch.setattr(encryption_canary, "table", lambda name: t)
    assert encryption_canary.verify_encryption_key() == "seeded"
    assert seeded["canary"].startswith("enc2:")
    assert encryption_canary.verify_encryption_key() == "ok"


def test_canary_moved_from_another_cell_does_not_verify(monkeypatch):
    elsewhere = encrypt(encryption_canary.CANARY_PLAINTEXT, bind=ALICE)
    t = _canary_table(elsewhere)
    monkeypatch.setattr(encryption_canary, "table", lambda name: t)
    with pytest.raises(encryption_canary.EncryptionKeyMismatch):
        encryption_canary.verify_encryption_key()
