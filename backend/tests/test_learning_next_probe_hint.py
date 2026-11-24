"""W2.4 / W2.4b low-trust next-probe hint: selection only, never mastery."""

from __future__ import annotations

import pathlib
from unittest.mock import patch

import pytest

from learning import check_reason, next_probe_hint
from services.loop import next_probe_hint as gated

BACKEND = pathlib.Path(__file__).resolve().parents[1]

BANNED = (
    "apply_graph_update",
    "flush_pending",
    "grade_answer",
    "p_known",
    "pending_evidence",
    "CheckAnswer",
    "graph_service",
    "node_mastery",
    "anthropic",
    "Agent(",
)


def test_module_never_touches_mastery_or_llm():
    """Hard invariant: the pure path cannot mutate mastery or call a model."""
    src = (BACKEND / "learning" / "next_probe_hint.py").read_text()
    for banned in BANNED:
        assert banned not in src, f"next_probe_hint.py must not mention {banned}"
    gate = (BACKEND / "services" / "loop" / "next_probe_hint.py").read_text()
    for banned in BANNED:
        assert banned not in gate, f"services/loop/next_probe_hint.py must not mention {banned}"


def test_prefer_none_on_empty_or_ciphertext():
    cands = [("qh-a", "recursion base case induction"), ("qh-b", "hash table collision")]
    assert next_probe_hint.prefer(None, cands) is None
    assert next_probe_hint.prefer("   ", cands) is None
    assert next_probe_hint.prefer("enc2:0:deadbeef", cands) is None
    assert next_probe_hint.prefer("I thought about recursion base case", []) is None


def test_prefer_picks_highest_overlap_hash():
    cands = [
        ("qh-zz", "linked list pointer traversal"),
        ("qh-aa", "recursion base case and inductive step"),
        ("qh-bb", "sorting comparator stability"),
    ]
    text = "I mixed up the recursion base case with the inductive step"
    assert next_probe_hint.prefer(text, cands) == "qh-aa"


def test_prefer_tie_breaks_on_question_hash():
    cands = [
        ("qh-b", "gradient descent learning rate"),
        ("qh-a", "gradient descent learning rate"),
    ]
    text = "confused about gradient descent and the learning rate"
    assert next_probe_hint.prefer(text, cands) == "qh-a"


def test_prefer_below_overlap_floor_is_none():
    cands = [("qh-1", "completely unrelated topic zeta")]
    assert next_probe_hint.prefer("because the answer is forty two", cands) is None


@pytest.mark.parametrize("on", [False, True])
def test_gated_flag_off_is_noop(on):
    cands = [("qh-aa", "recursion base case inductive step")]
    text = "I mixed up the recursion base case with the inductive step"
    with patch("services.loop.next_probe_hint.flag_on", return_value=on) as flag:
        got = gated.preferred_next_question_hash("user_1", text, cands)
    flag.assert_called_once_with(gated.NEXT_PROBE_HINT_FLAG, "user_1")
    if on:
        assert got == "qh-aa"
    else:
        assert got is None


def test_gated_no_user_is_off_without_flag_read():
    with patch("services.loop.next_probe_hint.flag_on") as flag:
        assert gated.preferred_next_question_hash(None, "recursion base case", []) is None
    flag.assert_not_called()


def test_gated_decrypts_reasoning_when_flag_on():
    """W2.4b: flag on opens step reasoning_encrypted under the session bind."""
    plain = "I mixed up the recursion base case with the inductive step"
    sealed = check_reason.seal("sess-hint", plain)
    assert sealed and plain not in sealed
    state = {"steps": {"qh-prior": {check_reason.KEY: sealed, "graded_at": 1.0}}}
    cands = [
        ("qh-zz", "linked list pointer traversal"),
        ("qh-aa", "recursion base case and inductive step"),
    ]
    with patch("services.loop.next_probe_hint.flag_on", return_value=True):
        assert (
            gated.preferred_next_question_hash(
                "user_1", None, cands, session_id="sess-hint", state=state
            )
            == "qh-aa"
        )
    with patch("services.loop.next_probe_hint.flag_on", return_value=False) as flag:
        assert (
            gated.preferred_next_question_hash(
                "user_1", None, cands, session_id="sess-hint", state=state
            )
            is None
        )
    flag.assert_called_once_with(gated.NEXT_PROBE_HINT_FLAG, "user_1")
    # Wrong session bind → open fails soft → prefer(None) → None even when on.
    with patch("services.loop.next_probe_hint.flag_on", return_value=True):
        assert (
            gated.preferred_next_question_hash(
                "user_1", None, cands, session_id="other-sess", state=state
            )
            is None
        )


def test_gated_flag_off_skips_decrypt():
    """Flag off must not open ciphertext (no scoring, no decrypt side path)."""
    sealed = check_reason.seal("s1", "recursion base case inductive step")
    state = {"steps": {"qh-1": {check_reason.KEY: sealed, "graded_at": 1.0}}}
    cands = [("qh-aa", "recursion base case inductive step")]
    with (
        patch("services.loop.next_probe_hint.flag_on", return_value=False),
        patch("services.loop.next_probe_hint.check_reason.latest_plaintext") as latest,
    ):
        assert gated.preferred_next_question_hash(
            "user_1", None, cands, session_id="s1", state=state
        ) is None
    latest.assert_not_called()
