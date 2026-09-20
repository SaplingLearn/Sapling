"""Unit tests for services/quiz_context_service.py.

Pins the encryption boundary (context_json is ciphertext at rest, plaintext
in the return shape) and the Finding-2 read-boundary guard: get_quiz_context
must degrade to None on a corrupt/undecryptable context_json rather than
raise — routes/quiz.py's submit_quiz calls it AFTER the mastery/score write
commits, so an unguarded raise would 500 a request whose side effects
already landed, and every retry would then 409 (completed_at already set)
with no way to recover the context.
"""
from __future__ import annotations

from unittest.mock import patch

from services.encryption import decrypt_json, encrypt_json
from services.quiz_distractors import DIGEST_SCHEMA_VERSION
from services.quiz_context_service import get_quiz_context, save_quiz_context


class FakeTable:
    """Minimal stand-in for db.connection.table() returning recorded calls."""

    def __init__(self, rows=None):
        self.rows = rows or []
        self.upserted = []
        self.upsert_on_conflict = []
        self.select_calls = []

    def select(self, *args, **kwargs):
        self.select_calls.append((args, kwargs))
        return list(self.rows)

    def upsert(self, data, on_conflict="id"):
        self.upserted.append(data)
        self.upsert_on_conflict.append(on_conflict)
        return [data]


def test_save_quiz_context_upserts_ciphertext():
    fake = FakeTable()
    context = {"weak_areas": ["recursion base case"], "recommended_difficulty": "hard"}
    with patch("services.quiz_context_service.table", return_value=fake):
        save_quiz_context("u1", "concept1", context)

    assert fake.upserted, "upsert was not called"
    row = fake.upserted[0]
    # context_json must be ciphertext, not the plaintext dict/string.
    assert isinstance(row["context_json"], str)
    assert row["context_json"] != str(context)
    # The caller's context, plus the server-stamped digest version (#554).
    # Stamped here rather than on the agent's output schema: the digest prompt
    # feeds the previous context back to the model, so a model-owned version
    # field would drift on its own.
    assert decrypt_json(row["context_json"]) == {
        **context, "schema_version": DIGEST_SCHEMA_VERSION,
    }
    assert row["user_id"] == "u1"
    assert row["concept_node_id"] == "concept1"
    # Upsert must key on the (user_id, concept_node_id) unique constraint.
    assert fake.upsert_on_conflict == ["user_id,concept_node_id"]


def test_get_quiz_context_decrypts_ciphertext():
    context = {"weak_areas": ["loops"], "questions_seen_summary": "iteration basics"}
    fake = FakeTable(rows=[{"context_json": encrypt_json(context)}])
    with patch("services.quiz_context_service.table", return_value=fake):
        out = get_quiz_context("u1", "concept1")
    assert out == context


def test_get_quiz_context_passes_legacy_plaintext_dict():
    """Pre-backfill rows store context_json as a raw dict (legacy JSONB),
    not ciphertext. decrypt_json_column must pass those through unchanged."""
    context = {"weak_areas": ["loops"]}
    fake = FakeTable(rows=[{"context_json": context}])
    with patch("services.quiz_context_service.table", return_value=fake):
        out = get_quiz_context("u1", "concept1")
    assert out == context


def test_get_quiz_context_degrades_to_none_on_corrupt_string():
    """Finding 2: a corrupt context_json (neither valid ciphertext nor
    valid plaintext JSON) must not raise — it degrades to None so
    submit_quiz's post-commit read can't 500 a request whose mastery/score
    writes already landed. MUST fail if the try/except guard is reverted."""
    fake = FakeTable(rows=[{"context_json": "corrupt-not-json-not-b64"}])
    with patch("services.quiz_context_service.table", return_value=fake):
        out = get_quiz_context("u1", "concept1")
    assert out is None
