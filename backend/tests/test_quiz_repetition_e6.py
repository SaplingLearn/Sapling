"""E6: the repetition guard's read side.

Past `questions_json` was never re-read by anything, so a student could be
served the same question over and over with nothing in the system able to
notice. This pulls the recently-asked items for one (student, concept) so
generation can be told not to repeat them.
"""

import json
from unittest.mock import MagicMock, patch

import pytest

from services.encryption import encrypt_json
from services.quiz_identity import question_hash
from services.quiz_repetition import (
    RECENT_QUESTION_LIMIT,
    recent_question_identities,
)


def _q(n, *, opts=None):
    """One stored wire question."""
    texts = opts or [f"q{n} a", f"q{n} b", f"q{n} c", f"q{n} d"]
    return {
        "id": n,
        "question": f"Question {n}?",
        "options": [
            {"label": chr(65 + i), "text": t, "correct": i == 0}
            for i, t in enumerate(texts)
        ],
        "explanation": "e",
        "concept_tested": "Recursion",
        "difficulty": "medium",
    }


def _attempts(*question_lists, encrypted=True):
    """Newest-first attempt rows, each holding its questions_json."""
    return [
        {
            "id": f"a{i}",
            "questions_json": encrypt_json(qs) if encrypted else qs,
        }
        for i, qs in enumerate(question_lists)
    ]


def _table(rows, *, raises=False):
    def factory(name):
        m = MagicMock()
        if raises:
            m.select.side_effect = RuntimeError("postgrest down")
        else:
            m.select.return_value = rows
        return m
    return patch("services.quiz_repetition.table", side_effect=factory)


# ── Happy path ──────────────────────────────────────────────────────────────


def test_returns_identities_for_recently_asked_questions():
    with _table(_attempts([_q(1), _q(2)])):
        out = recent_question_identities("u1", "n1")
    assert [r.stem for r in out] == ["Question 1?", "Question 2?"]
    assert out[0].question_hash == question_hash(
        "Question 1?", ["q1 a", "q1 b", "q1 c", "q1 d"]
    )


def test_reads_across_multiple_attempts_newest_first():
    with _table(_attempts([_q(9)], [_q(8)], [_q(7)])):
        out = recent_question_identities("u1", "n1")
    assert [r.stem for r in out] == ["Question 9?", "Question 8?", "Question 7?"]


def test_caps_at_the_recent_limit():
    """Bounded because this text goes into the prompt — an unbounded
    do-not-repeat list would eat the budget the material block needs."""
    many = [_q(n) for n in range(40)]
    with _table(_attempts(many)):
        out = recent_question_identities("u1", "n1")
    assert len(out) == RECENT_QUESTION_LIMIT


def test_explicit_limit_is_honoured():
    with _table(_attempts([_q(n) for n in range(10)])):
        assert len(recent_question_identities("u1", "n1", limit=3)) == 3


def test_deduplicates_repeats_across_attempts():
    """The same item asked three times is ONE entry in the list — otherwise a
    heavily-repeated question crowds out everything else it should be
    competing with."""
    with _table(_attempts([_q(1)], [_q(1)], [_q(2)])):
        out = recent_question_identities("u1", "n1")
    assert [r.stem for r in out] == ["Question 1?", "Question 2?"]


def test_uses_the_stored_hash_when_present():
    """Rows written after E5 carry their own identity; trust it."""
    q = _q(1)
    q["question_hash"] = "storedhash000000"
    with _table(_attempts([q])):
        out = recent_question_identities("u1", "n1")
    assert out[0].question_hash == "storedhash000000"


def test_reads_pre_e5_rows_that_carry_no_hash():
    """Retroactive coverage on day one — every historical attempt is usable
    because identity is recomputable from the stored stem and options."""
    with _table(_attempts([_q(1)])):
        out = recent_question_identities("u1", "n1")
    assert out[0].question_hash and len(out[0].question_hash) == 16


# ── Query shape ─────────────────────────────────────────────────────────────


def test_query_is_owner_and_concept_scoped_newest_first():
    captured = {}

    def factory(name):
        m = MagicMock()

        def _select(cols, **kw):
            captured["table"] = name
            captured["cols"] = cols
            captured.update(kw)
            return []

        m.select.side_effect = _select
        return m

    with patch("services.quiz_repetition.table", side_effect=factory):
        recent_question_identities("u1", "n1")

    assert captured["table"] == "quiz_attempts"
    assert captured["filters"]["user_id"] == "eq.u1"
    assert captured["filters"]["concept_node_id"] == "eq.n1"
    assert captured["order"].startswith("created_at.desc")
    assert captured["limit"] >= 1


def test_incomplete_attempts_count_as_asked():
    """Deliberately NOT filtered to completed attempts, unlike the history
    tool: a student who generated a quiz and walked away still SAW those
    questions, so re-serving them is still a repeat."""
    captured = {}

    def factory(name):
        m = MagicMock()

        def _select(cols, **kw):
            captured.update(kw)
            return []

        m.select.side_effect = _select
        return m

    with patch("services.quiz_repetition.table", side_effect=factory):
        recent_question_identities("u1", "n1")
    assert "completed_at" not in captured["filters"]


# ── Degradation: this must never break generation ───────────────────────────


def test_read_failure_degrades_to_empty():
    with _table([], raises=True):
        assert recent_question_identities("u1", "n1") == []


def test_undecryptable_blob_is_skipped_not_fatal():
    rows = [
        {"id": "a0", "questions_json": "not-decryptable-ciphertext"},
        {"id": "a1", "questions_json": encrypt_json([_q(2)])},
    ]
    with _table(rows):
        out = recent_question_identities("u1", "n1")
    assert [r.stem for r in out] == ["Question 2?"]


def test_plaintext_jsonb_rows_still_work():
    """Pre-#521 rows stored plaintext JSONB rather than a ciphertext string."""
    with _table(_attempts([_q(3)], encrypted=False)):
        out = recent_question_identities("u1", "n1")
    assert [r.stem for r in out] == ["Question 3?"]


@pytest.mark.parametrize(
    "payload",
    [None, [], {}, "junk", [None], ["not a dict"], [{"no": "shape"}]],
)
def test_unusable_question_payloads_are_skipped(payload):
    with _table([{"id": "a0", "questions_json": encrypt_json(payload)}]):
        assert recent_question_identities("u1", "n1") == []


def test_legacy_seed_shape_is_skipped_not_crashed():
    """The rich seed stores {"q":..., "a":...} — no stem, no options."""
    with _table([{"id": "a0", "questions_json": encrypt_json([{"q": "x", "a": "y"}])}]):
        assert recent_question_identities("u1", "n1") == []


def test_missing_identifiers_short_circuit():
    with _table(_attempts([_q(1)])) as t:
        assert recent_question_identities("", "n1") == []
        assert recent_question_identities("u1", "") == []
    t.assert_not_called()


def test_stems_are_returned_verbatim_for_the_prompt():
    """The prompt needs the readable stem, not the hash — 'do not repeat
    <hash>' is unactionable for a model."""
    with _table(_attempts([_q(1)])):
        out = recent_question_identities("u1", "n1")
    assert out[0].stem == "Question 1?"
    assert json.dumps(out[0].stem)  # plain serialisable text
