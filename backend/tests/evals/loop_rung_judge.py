"""Calibration for the eval-side rung judge (_rung_judge.py; PKG-07 Task 9).

    cd backend
    SAPLING_EVAL_MODE=record python tests/evals/loop_rung_judge.py   # SAPLING_MODEL_MODE unset
    SAPLING_EVAL_MODE=replay python tests/evals/loop_rung_judge.py

Eight hand-written tutor replies with a gold rung and a gold reveal flag,
spanning H0..H6. Two of them (`h1_plain_pump`, `h2_plain_pointer`) are plain,
unmarked H1/H2 text that `loop_tutor._infer_rung` misreads as H3 — the gap the
judge exists to close — and `h6_unmarked_solution` is a full solution with no
marker phrase, which the old classifier under-counts as H3. Both evaluators are
gated at 1.0: the judge scores the loop tutor's CeilingCompliance only while it
agrees with every calibration case. On a miss fix the JUDGE PROMPT (never the
gold) and re-record.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).parent))

from pydantic import BaseModel  # noqa: E402
from pydantic_evals import Case, Dataset  # noqa: E402
from pydantic_evals.evaluators import Evaluator, EvaluatorContext  # noqa: E402

from _replay import cli_main  # noqa: E402
from _rung_judge import JudgeItem, RungJudgement, ajudge_rung  # noqa: E402
from learning.ladder import Rung  # noqa: E402

DATASET = "loop_rung_judge"


class JudgeCase(BaseModel):
    case_id: str
    served_text: str
    item: JudgeItem


_BASE = {
    "prompt": "What stops factorial(0) from recursing forever?",
    "reference_answer": "The base case returns 1 when n equals 0 so the function stops calling itself.",
    "final_answer": "returns 1",
}
_DERIV = {
    "prompt": "What is the derivative of f(x) = x^3?",
    "reference_answer": "By the power rule, bring the exponent down and subtract one from it: the derivative is 3x^2.",
    "final_answer": "3x^2",
}


def _case(name: str, gold: Rung, reveals: bool, item: dict, served: str, student: str = "") -> Case:
    return Case(
        name=name,
        inputs=JudgeCase(
            case_id=name, served_text=served, item=JudgeItem(**item, student_message=student)
        ),
        metadata={"gold_rung": int(gold), "gold_reveals": reveals},
    )


CASES: list[Case] = [
    _case(
        "h0_verify_step",
        Rung.H0,
        False,
        _DERIV,
        "Yes, that's the right first move — bringing the 3 down in front is correct.",
        student="First I bring the 3 down in front, right?",
    ),
    _case(
        "h1_plain_pump",
        Rung.H1,
        False,
        _BASE,
        "Let's slow down for a second. What is the first thing you need to figure out here?",
        student="I have no idea where to start.",
    ),
    _case(
        "h2_plain_pointer",
        Rung.H2,
        False,
        _BASE,
        "Your lecture notes define a base case as the simple version of a problem that a recursive "
        "function solves directly, without calling itself again. Have another look at that definition.",
        student="Can I get a hint?",
    ),
    _case(
        "h3_next_step_question",
        Rung.H3,
        False,
        _BASE,
        "Look at the line that checks n. What should factorial do when n reaches 0, instead of calling itself again?",
        student="Can I get another hint?",
    ),
    _case(
        "h4_isomorph",
        Rung.H4,
        False,
        _BASE,
        "Let's work through a similar function first: sum_to(n) returns n + sum_to(n - 1), and when n "
        "is 0 it returns 0 directly without another call — that direct return is what ends the chain. "
        "Which line in your factorial plays that role?",
    ),
    _case(
        "h5_completion",
        Rung.H5,
        False,
        _BASE,
        "Here is the function with the last step left for you: def factorial(n): if n == 0: return ____ "
        "else: return n * factorial(n - 1). What value goes in the gap?",
    ),
    _case(
        "h6_marked_solution",
        Rung.H6,
        True,
        _BASE,
        "Here is the solution: when n equals 0, factorial returns 1 directly instead of calling itself, "
        "so the recursion stops there.",
        student="Just tell me.",
    ),
    _case(
        "h6_unmarked_solution",
        Rung.H6,
        True,
        _DERIV,
        "Bring the 3 down in front and lower the exponent by one: f'(x) = 3x^2.",
        student="How do I do this one?",
    ),
]

assert len(CASES) <= 8, "series cap: at most 8 cases per agent dataset"


_Ctx = EvaluatorContext[JudgeCase, RungJudgement]


@dataclass
class RungJudgeAgreement(Evaluator[JudgeCase, RungJudgement]):
    def evaluate(self, ctx: _Ctx) -> float:
        return 1.0 if ctx.output and ctx.output.rung == (ctx.metadata or {})["gold_rung"] else 0.0


@dataclass
class RevealAgreement(Evaluator[JudgeCase, RungJudgement]):
    def evaluate(self, ctx: _Ctx) -> float:
        gold = (ctx.metadata or {})["gold_reveals"]
        return 1.0 if ctx.output and ctx.output.reveals_final_answer is gold else 0.0


async def _judge(case: JudgeCase, *, mode: str | None = None) -> RungJudgement:
    return await ajudge_rung(case.case_id, DATASET, case.served_text, case.item, mode=mode)


async def _run(case: JudgeCase) -> RungJudgement:
    """Honours SAPLING_EVAL_MODE (run_all.py's contract)."""
    return await _judge(case)


async def replay_run(case: JudgeCase) -> RungJudgement:
    """Replay regardless of the environment (the unit test's run)."""
    return await _judge(case, mode="replay")


def make_dataset() -> Dataset[JudgeCase, RungJudgement]:
    return Dataset(name=DATASET, cases=CASES, evaluators=[RungJudgeAgreement(), RevealAgreement()])


if __name__ == "__main__":
    cli_main(make_dataset, _run)
