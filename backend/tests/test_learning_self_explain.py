"""Spec §13 A139: self-explanation prompts — the junctures decided in code
(learning/self_explain.py), the per-concept cap, the loop-state record, the
store (the reply encrypted, never read back by a learner path) and the admin
report (learning/self_explain_report.py)."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from learning import self_explain as se
from learning.params import SELF_EXPLAIN_JUNCTURES, SELF_EXPLAIN_MAX_PER_CONCEPT
from learning.self_explain_report import self_explanation_report
from learning.turn_shape import sentences


def test_the_params():
    assert SELF_EXPLAIN_JUNCTURES == ("worked_example", "released_solution", "first_correct")
    assert SELF_EXPLAIN_MAX_PER_CONCEPT == 1


@pytest.mark.parametrize("text", list(se.PROMPTS.values()))
def test_every_prompt_is_one_interrogative_why_question(text):
    """Bisra et al. 2018: interrogative prompts (g = 0.56) over imperative (0.40);
    the turn shape's question rule: one sentence ending in a single '?'."""
    assert text.startswith("Why ") and text.endswith("?") and text.count("?") == 1
    assert len(sentences(text)) == 1


@pytest.mark.parametrize(
    "kw,expected",
    [
        (dict(phase="hint", rung=4, answer_released=False, first_correct=False), ("worked_example", "worked_example")),
        (dict(phase="hint", rung=5, answer_released=False, first_correct=False), ("released_solution", "completion")),
        (dict(phase="hint", rung=6, answer_released=False, first_correct=False), ("released_solution", "released_answer")),
        (dict(phase="feedback", rung=0, answer_released=True, first_correct=False), ("released_solution", "released_answer")),
        (dict(phase="feedback", rung=0, answer_released=False, first_correct=True), ("first_correct", "first_correct")),
        (dict(phase="hint", rung=3, answer_released=False, first_correct=False), None),
        (dict(phase="hint", rung=1, answer_released=False, first_correct=False), None),
        (dict(phase="feedback", rung=0, answer_released=False, first_correct=False), None),
        (dict(phase="teach", rung=0, answer_released=False, first_correct=True), None),
        (dict(phase="check", rung=4, answer_released=False, first_correct=False), None),
    ],
)
def test_the_junctures_are_decided_in_code(kw, expected):
    assert se.juncture(**kw) == expected


def _graded(node="n1", verdict="correct", rung=0, assisted=False, at=10.0):
    return {"node_id": node, "last_verdict": verdict, "max_rung": rung, "assisted": assisted, "graded_at": at}


def test_unhelped_correct_reads_the_graded_step_after_the_help_floor():
    assert se.unhelped_correct(_graded()) is True
    assert se.unhelped_correct(_graded(rung=1)) is False  # a hint, or a reveal floor
    assert se.unhelped_correct(_graded(assisted=True)) is False
    assert se.unhelped_correct(_graded(verdict="not_yet")) is False
    assert se.unhelped_correct({"last_verdict": "correct", "max_rung": True, "assisted": False}) is False
    assert se.unhelped_correct(None) is False


def test_first_correct_is_the_sessions_first_unhelped_correct_on_the_concept():
    steps = {"a": _graded(at=10.0), "b": _graded(at=20.0), "c": _graded(node="n2", at=5.0)}
    assert se.first_unhelped_on_concept(steps, "n1", "a") is True
    assert se.first_unhelped_on_concept(steps, "n1", "b") is False  # a came first
    assert se.first_unhelped_on_concept(steps, "n2", "c") is True
    steps["a"]["max_rung"] = 2  # a was helped: b is the first unhelped one
    assert se.first_unhelped_on_concept(steps, "n1", "b") is True


def test_the_cap_and_the_record():
    st: dict = {}
    assert se.may_prompt(st, "n1") and not se.may_prompt(st, None)
    prompt = {"id": "p1", "node_id": "n1", "juncture": "worked_example", "prompt_key": "worked_example",
              "question_hash": "q1", "rung": 4, "prompted_at": 1.0}
    se.record_prompt(st, prompt)
    assert se.open_prompt(st) == prompt and se.prompted(st) == ["n1"]
    assert not se.may_prompt(st, "n1") and se.may_prompt(st, "n2")
    assert se.prompt_text(prompt) == se.WORKED_EXAMPLE_PROMPT
    assert se.close_open(st) == prompt and se.open_prompt(st) is None
    assert se.prompted(st) == ["n1"], "closing never refunds the concept's prompt"
    assert se.close_open(st) is None
    se.set_ack(st, "p1")
    assert se.ack_due(st) == "p1"
    se.set_ack(st, None)
    assert se.ack_due(st) is None
    with pytest.raises(ValueError):
        se.record_prompt(st, {**prompt, "juncture": "whenever"})
    with pytest.raises(ValueError):
        se.record_prompt(st, {**prompt, "prompt_key": "free text"})


def test_the_loop_state_record_holds_no_text():
    """A38: the open prompt stores a prompt KEY, never its text (nor the reply)."""
    st: dict = {}
    se.record_prompt(st, {"id": "p1", "node_id": "n1", "juncture": "first_correct", "prompt_key": "first_correct",
                          "question_hash": "q1", "rung": 0, "prompted_at": 1.0})
    assert se.FIRST_CORRECT_PROMPT not in str(st)


# ── the store ─────────────────────────────────────────────────────────────


def test_the_reply_is_stored_encrypted_with_its_length_and_a_skip_stores_none():
    from learning import self_explain_store as store
    from services.encryption import decrypt_if_present

    t = MagicMock()
    prompt = {"id": "p1", "node_id": "n1", "juncture": "worked_example", "prompt_key": "worked_example",
              "question_hash": "q1", "rung": 4, "prompted_at": 1_790_000_000.0}
    when = datetime(2026, 11, 8, tzinfo=timezone.utc)
    with patch.object(store, "table", return_value=t):
        store.close_prompt(prompt, user_id="u1", session_id="s1", course_id="c1",
                           reply="  Each step halves the value.  ", closed_at=when)
        store.close_prompt(prompt, user_id="u1", session_id="s1", course_id="c1", reply=None, closed_at=when)
    replied, skipped = (c.args[0] for c in t.upsert.call_args_list)
    assert replied["status"] == "replied" and replied["reply_chars"] == len("Each step halves the value.")
    assert replied["reply_text"] != "Each step halves the value."
    assert decrypt_if_present(replied["reply_text"]) == "Each step halves the value."
    assert skipped["status"] == "skipped" and skipped["reply_text"] is None and skipped["reply_chars"] is None
    assert replied["juncture"] == "worked_example" and replied["rung"] == 4
    assert replied["prompted_at"].startswith("2026-09-")  # UTC from the prompt's unix seconds
    assert "prompt_key" not in replied and "prompt" not in replied


def test_the_served_prompt_row_never_raises():
    from learning import self_explain_store as store

    t = MagicMock()
    t.insert_ignore_duplicates.side_effect = RuntimeError("down")
    with patch.object(store, "table", return_value=t):
        store.record_prompt({"id": "p1", "node_id": "n1", "juncture": "worked_example", "prompted_at": 1.0},
                            user_id="u1", session_id="s1", course_id=None)  # logs, never raises


def test_the_report_never_reads_the_reply():
    from learning.self_explain_store import REPORT_COLUMNS

    assert "reply_text" not in REPORT_COLUMNS.split(",")


# ── the admin report ──────────────────────────────────────────────────────


def _p(pid, status, *, juncture="worked_example", node="n1", qh="q1", at="2026-11-08T10:00:00+00:00", chars=None):
    return {"id": pid, "node_id": node, "question_hash": qh, "juncture": juncture, "prompted_at": at,
            "status": status, "reply_chars": chars}


def _ev(node, qh, at, *, correct=True, assisted=False, rung=0):
    return {"node_id": node, "question_hash": qh, "created_at": at, "correct": correct,
            "assisted": assisted, "max_rung": rung}


def test_the_report_counts_rates_and_the_next_item_with_their_n():
    prompts = [
        _p("a", "replied", chars=40),
        _p("b", "replied", node="n2", chars=10, juncture="first_correct"),
        _p("c", "skipped", node="n3"),
        _p("d", "open", node="n4"),
    ]
    evidence = [
        _ev("n1", "q1", "2026-11-08T10:05:00+00:00", correct=True),  # the prompt's own item: skipped
        _ev("n1", "q2", "2026-11-08T10:06:00+00:00", correct=True),  # next: unassisted
        _ev("n2", "q5", "2026-11-08T10:06:00+00:00", correct=True, rung=2),  # next: helped
        _ev("n3", "q6", "2026-11-08T09:00:00+00:00"),  # before the prompt: not next
        _ev("n3", "q7", "2026-11-08T11:00:00+00:00", correct=False),  # next: wrong
    ]
    r = self_explanation_report(prompts, evidence)
    assert (r["shown"], r["replied"], r["skipped"], r["open"]) == (4, 2, 1, 1)
    assert r["reply_rate"] == 0.5
    assert r["reply_chars"] == {"median": 25.0, "n": 2}
    assert r["next_item"]["replied"] == {"n": 2, "unassisted": 1, "rate": 0.5, "none": 0}
    assert r["next_item"]["not_replied"] == {"n": 1, "unassisted": 0, "rate": 0.0, "none": 1}
    by = {g["juncture"]: g for g in r["by_juncture"]}
    assert set(by) == set(SELF_EXPLAIN_JUNCTURES)
    assert by["first_correct"]["shown"] == 1 and by["first_correct"]["reply_rate"] == 1.0
    assert by["released_solution"] == {
        "juncture": "released_solution", "shown": 0, "replied": 0, "reply_rate": None,
        "next_item": {"replied": {"n": 0, "unassisted": 0, "rate": None, "none": 0},
                      "not_replied": {"n": 0, "unassisted": 0, "rate": None, "none": 0}},
    }


def test_an_empty_range_is_none_never_zero():
    r = self_explanation_report([], [])
    assert r["shown"] == 0 and r["reply_rate"] is None and r["reply_chars"] == {"median": None, "n": 0}
    assert r["next_item"]["replied"]["rate"] is None
