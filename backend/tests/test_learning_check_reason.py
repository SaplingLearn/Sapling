"""W2.3 reason-before-submit: sealed on the step, never evidence / never mastery."""

from __future__ import annotations

import pathlib

import pytest

from learning import check_reason
from services.encryption import decrypt_if_present, nested_bind

BACKEND = pathlib.Path(__file__).resolve().parents[1]


@pytest.mark.parametrize(
    "fmt, reasoning, expect",
    [
        ("free", "  because n==0  ", "because n==0"),
        ("teachback", "in my words", "in my words"),
        ("mc_reason", "should be ignored", ""),
        ("free", "   ", ""),
        ("free", None, ""),
        (None, "x", ""),
    ],
)
def test_normalize_keeps_only_free_and_teachback(fmt, reasoning, expect):
    assert check_reason.normalize(fmt, reasoning) == expect


def test_seal_is_bound_ciphertext_not_plaintext():
    plain = "I thought about the base case first"
    sealed = check_reason.seal("sess-1", plain)
    assert sealed and plain not in sealed
    opened = decrypt_if_present(
        sealed,
        bind=nested_bind("sessions", "loop_state", check_reason.KEY, "sess-1"),
    )
    assert opened == plain
    assert check_reason.open("sess-1", sealed) == plain
    # Wrong session binding must not open (AAD).
    assert (
        decrypt_if_present(
            sealed,
            bind=nested_bind("sessions", "loop_state", check_reason.KEY, "other"),
        )
        is None
    )
    assert check_reason.open("other", sealed) is None
    assert check_reason.open("sess-1", None) is None
    assert check_reason.open("sess-1", "") is None


def test_latest_plaintext_picks_most_recent_graded_step():
    older = check_reason.seal("s1", "older recursion base case prose")
    newer = check_reason.seal("s1", "newer inductive step confusion")
    assert older and newer
    state = {
        "steps": {
            "qh-old": {check_reason.KEY: older, "graded_at": 10.0},
            "qh-new": {check_reason.KEY: newer, "graded_at": 20.0},
        }
    }
    assert check_reason.latest_plaintext(state, "s1") == "newer inductive step confusion"
    assert check_reason.latest_plaintext(state, "wrong") is None
    assert check_reason.latest_plaintext({}, "s1") is None
    assert check_reason.latest_plaintext(state, None) is None


@pytest.mark.parametrize("empty", [None, "", 7])
def test_latest_plaintext_none_when_the_latest_graded_step_has_no_reasoning(empty):
    """w2-next-probe-hint.md: the most recently graded step is picked first, so
    prose on an older step never speaks for a newer grade without any."""
    older = check_reason.seal("s1", "older recursion base case prose")
    latest = {"graded_at": 30.0}
    if empty is not None:
        latest[check_reason.KEY] = empty
    state = {"steps": {"qh-old": {check_reason.KEY: older, "graded_at": 10.0}, "qh-new": latest}}
    assert check_reason.latest_plaintext(state, "s1") is None
    latest["graded_at"] = 5.0  # graded BEFORE the step with reasoning: no longer the latest
    assert check_reason.latest_plaintext(state, "s1") == "older recursion base case prose"


@pytest.mark.parametrize("at", [None, True, "30", float("nan"), float("inf")])
def test_latest_plaintext_never_picks_an_ungraded_step(at):
    """Reasoning is sealed under the grading claim, before the grade: a step
    without a finite graded_at is not graded, whatever it carries."""
    sealed = check_reason.seal("s1", "open answer recursion base case")
    state = {"steps": {"qh-open": {check_reason.KEY: sealed, "graded_at": at}}}
    assert check_reason.latest_plaintext(state, "s1") is None
    state["steps"]["qh-graded"] = {"graded_at": 1.0}
    assert check_reason.latest_plaintext(state, "s1") is None


def test_stash_on_step_writes_only_when_allowed():
    step: dict = {}
    check_reason.stash_on_step(step, "s1", format="mc_reason", reasoning="nope")
    assert check_reason.KEY not in step
    check_reason.stash_on_step(step, "s1", format="free", reasoning="yes")
    assert step[check_reason.KEY]
    assert "yes" not in step[check_reason.KEY]


def test_module_never_touches_mastery_or_grader():
    """Hard invariant: this store has no path to apply_graph_update / p_known /
    grade_answer. The check route grades answer + rubric only."""
    src = (BACKEND / "learning" / "check_reason.py").read_text()
    for banned in (
        "apply_graph_update",
        "flush_pending",
        "grade_answer",
        "p_known",
        "pending_evidence",
        "CheckAnswer",
        "graph_service",
        "node_mastery",
    ):
        assert banned not in src, f"check_reason.py must not mention {banned}"
