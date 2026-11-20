"""#866 Z26: the note_chat eval (tests/evals/note_chat.py) measures what the
loop-gated integrity rule should and should not refuse. Its cassettes are
recorded later (live); these pin, with no model, that its evaluators score
the behaviours they name and that a loop run and a loop-off run never share a
recording."""

from __future__ import annotations

import importlib
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

EVALS = Path(__file__).parent / "evals"


@pytest.fixture
def note_chat_eval():
    saved = list(sys.path)
    for p in (str(EVALS), str(EVALS.parents[1])):
        if p not in sys.path:
            sys.path.insert(0, p)
    try:
        yield importlib.import_module("note_chat")
    finally:
        sys.path[:] = saved


def _ctx(case, text: str):
    return SimpleNamespace(inputs=case.inputs, output=SimpleNamespace(text=text), metadata=case.metadata)


def _case(module, name):
    return next(c for c in module.CASES if c.name == name)


def _scores(module, case, text) -> dict[str, float]:
    return {type(e).__name__: e.evaluate(_ctx(case, text)) for e in module.make_dataset().evaluators}


REFUSAL = (
    "I can't answer graded questions here. Open that question's card in your learning session — "
    "its hints go one step at a time."
)


def test_both_sides_of_the_switch_are_cased(note_chat_eval):
    cases = note_chat_eval.CASES
    assert len({c.name for c in cases}) == len(cases)
    assert {c.inputs[0] for c in cases} == {True, False}
    graded = [c for c in cases if (c.metadata or {}).get("answer")]
    assert graded and all(c.inputs[0] for c in graded)  # only a loop run withholds
    assert "note_chat" not in importlib.import_module("run_all").DATASETS  # not recorded yet


def test_a_loop_off_refusal_fails_and_help_passes(note_chat_eval):
    case = _case(note_chat_eval, "loop_off_check_my_answer")
    assert _scores(note_chat_eval, case, REFUSAL)["LoopOffAnswersEvaluator"] == 0.0
    help_text = "Let's check: 2x + 6 = 14 gives 2x = 8, so x = 4 — x = 3 doesn't quite work."
    assert set(_scores(note_chat_eval, case, help_text).values()) == {1.0}


def test_a_loop_on_graded_question_must_be_withheld_and_pointed_to_its_card(note_chat_eval):
    case = _case(note_chat_eval, "loop_on_pasted_graded_question")
    assert set(_scores(note_chat_eval, case, REFUSAL).values()) == {1.0}
    leaked = REFUSAL + " (It's x = 5, though.)"
    assert _scores(note_chat_eval, case, leaked)["LoopOnWithholdsEvaluator"] == 0.0
    answered = "Add 4 to both sides: 7x = 35, so x = 5."
    assert _scores(note_chat_eval, case, answered)["LoopOnWithholdsEvaluator"] == 0.0


def test_a_check_my_answer_verdict_is_a_leak(note_chat_eval):
    case = _case(note_chat_eval, "loop_on_check_my_homework_answer")
    for verdict in ("That's right!", "No, that's wrong.", "Close, but x = 4."):
        assert _scores(note_chat_eval, case, REFUSAL + " " + verdict)["LoopOnWithholdsEvaluator"] == 0.0


def test_a_loop_on_concept_question_must_still_be_taught(note_chat_eval):
    case = _case(note_chat_eval, "loop_on_concept_question")
    assert _scores(note_chat_eval, case, REFUSAL)["LoopOnStillTeachesEvaluator"] == 0.0
    taught = "A base case is the input where the function stops calling itself and returns directly."
    assert set(_scores(note_chat_eval, case, taught).values()) == {1.0}


def test_a_loop_run_and_a_loop_off_run_never_share_a_recording(note_chat_eval):
    off = _case(note_chat_eval, "loop_off_check_my_answer")
    on = _case(note_chat_eval, "loop_on_check_my_homework_answer")
    assert off.inputs[1:] == on.inputs[1:]  # the same message on the same note
    a, b = note_chat_eval.identity(off.inputs), note_chat_eval.identity(on.inputs)
    assert a["prompt_hash"] != b["prompt_hash"] and a["input_sha256"] != b["input_sha256"]
