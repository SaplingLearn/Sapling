"""pydantic-evals cases for the quiz item gates (learning-loop spec §13 A145,
flag `quiz_item_gates`): the A119 concept check and the A124 blind solve,
unchanged agents and prompts, on generated QUIZ questions and on the
`quiz_check` slot's model (`claude-sonnet-5-5` by default) — the live smoke
the flag waits on. Not in run_all.py's DATASETS until recorded:

    cd backend
    SAPLING_EVAL_MODE=record python tests/evals/quiz_item_gates.py
    SAPLING_EVAL_UPDATE_BASELINES=1 SAPLING_EVAL_MODE=replay python tests/evals/quiz_item_gates.py

Each case is one call: a `verify_*` case runs the concept check, a `solve_*`
case the blind solve, both with the model `quiz_check` resolves to. The inputs
are the messages services/quiz_learning.py::gate_questions builds; the expected
answers are the ones a correct check gives (the concept the question tests;
the option or number the passage settles, or "not settled").
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).parent))

from pydantic_evals import Case, Dataset
from pydantic_evals.evaluators import Evaluator, EvaluatorContext

from _replay import cli_main, run_with_cassette
from agents._providers import model_for
from agents.check_items_solve import Solutions, SolveItem, build_solve_prompt, check_items_solve_agent
from agents.check_items_verify import AlignmentChecks, VerifyItem, build_verify_prompt, check_items_verify_agent
from learning import quiz_gates
from learning.item_keys import option_letter

DATASET = "quiz_item_gates"
CONCEPTS = ["Load Factor", "Separate Chaining", "Hash Function", "Open Addressing"]
PASSAGE = [
    {
        "id": "c1",
        "text": (
            "A hash table's load factor is the number of stored entries divided by the number of "
            "buckets. A table with 12 entries in 16 buckets has a load factor of 0.75. Separate "
            "chaining keeps a linked list in each bucket; open addressing probes for the next "
            "free bucket instead."
        ),
    }
]


def _verify(name, prompt, correct, others, expected):
    item = VerifyItem("q1", "mc_reason", prompt, correct, tuple(others), ())
    return Case(
        name=f"verify_{name}",
        inputs=build_verify_prompt(CONCEPTS, [item]),
        metadata={"kind": "verify", "concept": expected},
    )


def _solve(name, prompt, options, expected, *, numeric=False, passages=PASSAGE):
    item = SolveItem(
        "q1", "free" if not options else "mc_reason", prompt, tuple(zip("ABCD", options)),
        "numeric" if numeric else "free",
    )
    return Case(
        name=f"solve_{name}",
        inputs=build_solve_prompt(passages, [item]),
        metadata={"kind": "solve", "answer": expected, "numeric": numeric},
    )


CASES = [
    _verify(
        "aligned_load_factor",
        "A table holds 12 entries in 16 buckets. What is its load factor?",
        "0.75",
        ["1.33", "12", "0.25"],
        "Load Factor",
    ),
    _verify(
        "tests_another_concept",
        "Which collision strategy keeps a linked list in every bucket?",
        "Separate chaining",
        ["Linear probing", "Quadratic probing", "Double hashing"],
        "Separate Chaining",
    ),
    _solve("agrees_mc", "A table holds 12 entries in 16 buckets. What is its load factor?", ["1.33", "12", "0.75", "0.25"], "C"),
    _solve(
        "disputes_a_wrong_key",
        "A table holds 12 entries in 16 buckets. Which value is its load factor?",
        ["0.75", "1.33", "16", "4"],
        "A",  # a wrong key (say B) is disputed by this answer
    ),
    _solve("numeric", "A table holds 12 entries in 16 buckets. Give its load factor as a decimal.", [], "0.75", numeric=True),
    _solve(
        "not_settled_by_the_passage",
        "In what year was the hash table first described?",
        [],
        None,  # the passages say nothing about it: not solvable
    ),
]


@dataclass
class ConceptEvaluator(Evaluator[str, object]):
    def evaluate(self, ctx: EvaluatorContext[str, object]) -> float:
        meta = ctx.metadata or {}
        if meta.get("kind") != "verify":
            return 1.0
        got = quiz_gates.collect_concepts((c.item, c.concept) for c in ctx.output.concepts).get("q1")
        return 1.0 if quiz_gates.alignment_of(got, meta["concept"]) == quiz_gates.ALIGNED else 0.0


@dataclass
class SolveEvaluator(Evaluator[str, object]):
    def evaluate(self, ctx: EvaluatorContext[str, object]) -> float:
        meta = ctx.metadata or {}
        if meta.get("kind") != "solve":
            return 1.0
        rows = [s for s in ctx.output.solutions if s.item == "q1"]
        if len(rows) != 1:
            return 0.0
        row, want = rows[0], meta["answer"]
        if want is None:
            return 1.0 if not row.solvable else 0.0
        if not row.solvable:
            return 0.0
        if meta.get("numeric"):
            try:
                return 1.0 if abs(float(row.answer) - float(want)) < 1e-9 else 0.0
            except ValueError:
                return 0.0
        return 1.0 if option_letter(row.answer) == want else 0.0


_BY_INPUT = {c.inputs: c for c in CASES}


async def _run(case_input: str):
    case = _BY_INPUT[case_input]
    verify = case.metadata["kind"] == "verify"
    agent = check_items_verify_agent if verify else check_items_solve_agent
    with agent.override(model=model_for("quiz_check")):
        return await run_with_cassette(
            dataset=DATASET,
            case_name=case.name,
            agent=agent,
            case_input=case_input,
            output_model=AlignmentChecks if verify else Solutions,
        )


def make_dataset() -> Dataset:
    return Dataset(name=DATASET, cases=CASES, evaluators=[ConceptEvaluator(), SolveEvaluator()])


if __name__ == "__main__":
    cli_main(make_dataset, _run)
