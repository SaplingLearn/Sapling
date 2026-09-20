"""E5: stable question identity (#543 addendum Part 2).

`question_hash` is the identity a question keeps across attempts and,
eventually, across students (the prerequisite for item statistics #24 and
the distractor↔misconception tag #25). These tests pin the properties that
make it usable as an identity: stable across processes, insensitive to
presentation noise, sensitive to content.
"""

import pytest

from services.quiz_identity import (
    QUESTION_HASH_LEN,
    normalize_text,
    question_hash,
    wire_question_hash,
)


OPTIONS = ["Base case", "Recursive case", "Tail call", "Stack frame"]


# ── normalize_text ──────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("  What is a base case?  ", "what is a base case?"),
        ("What  is\ta\nbase case?", "what is a base case?"),
        ("WHAT IS A BASE CASE?", "what is a base case?"),
        ("", ""),
        (None, ""),
    ],
)
def test_normalize_text_collapses_presentation_noise(raw, expected):
    assert normalize_text(raw) == expected


# ── question_hash ───────────────────────────────────────────────────────────


def test_question_hash_is_stable_for_identical_input():
    a = question_hash("What is a base case?", OPTIONS)
    b = question_hash("What is a base case?", OPTIONS)
    assert a == b
    assert len(a) == QUESTION_HASH_LEN
    assert all(c in "0123456789abcdef" for c in a)


def test_question_hash_ignores_option_order():
    """A shuffled option list is the SAME item — a quiz that re-serves the
    same question with the options rearranged is a repeat, not a new item."""
    assert question_hash("Stem?", OPTIONS) == question_hash(
        "Stem?", list(reversed(OPTIONS))
    )


def test_question_hash_ignores_whitespace_and_case():
    assert question_hash("  What  is a BASE case? ", ["A one", "b two"]) == (
        question_hash("What is a base case?", ["a  one", "B TWO"])
    )


def test_question_hash_changes_with_stem():
    assert question_hash("Stem A?", OPTIONS) != question_hash("Stem B?", OPTIONS)


def test_question_hash_changes_with_option_content():
    """Same stem, genuinely different answers = a different item."""
    other = ["Base case", "Recursive case", "Tail call", "Heap frame"]
    assert question_hash("Stem?", OPTIONS) != question_hash("Stem?", other)


def test_question_hash_preserves_option_multiplicity():
    """Deduping the option set would collide a 4-option item with a
    malformed 3-distinct-option one; keep multiplicity."""
    assert question_hash("Stem?", ["a", "a", "b"]) != question_hash(
        "Stem?", ["a", "b"]
    )


def test_question_hash_separator_prevents_field_smearing():
    """Concatenating without a separator would make ('ab', ['c']) and
    ('a', ['bc']) collide."""
    assert question_hash("ab", ["c"]) != question_hash("a", ["bc"])


def test_question_hash_survives_surrogates():
    """Never raise on undecodable text — identity is best-effort metadata
    hanging off the generation path, not a gate."""
    assert question_hash("bad \ud800 stem", ["a", "b"])


# ── wire_question_hash ──────────────────────────────────────────────────────


def _wire(stem="What is a base case?", texts=OPTIONS):
    return {
        "id": 1,
        "question": stem,
        "options": [
            {"label": chr(65 + i), "text": t, "correct": i == 0}
            for i, t in enumerate(texts)
        ],
        "explanation": "because",
        "concept_tested": "Recursion",
        "difficulty": "medium",
    }


def test_wire_question_hash_matches_the_raw_form():
    """A stored row (options are dicts) and a fresh agent question (options
    are strings) must hash the same — this is what lets E6 read identity
    off attempts written BEFORE E5 shipped."""
    assert wire_question_hash(_wire()) == question_hash(
        "What is a base case?", OPTIONS
    )


def test_wire_question_hash_prefers_the_stored_hash():
    """Once a row carries its own hash, trust it: recomputing would silently
    re-key every historical item if the normalization ever changes."""
    q = _wire()
    q["question_hash"] = "deadbeefdeadbeef"
    assert wire_question_hash(q) == "deadbeefdeadbeef"


@pytest.mark.parametrize(
    "bad",
    [
        None,
        "not a dict",
        {},
        {"question": "stem only"},
        {"question": "s", "options": "not a list"},
        {"question": "s", "options": [{"no_text": 1}]},
    ],
)
def test_wire_question_hash_returns_none_for_unusable_shapes(bad):
    assert wire_question_hash(bad) is None
