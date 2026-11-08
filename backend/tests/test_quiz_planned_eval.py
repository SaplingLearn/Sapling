"""The quiz flags' eval datasets, offline: the planned writer's (spec §13
A144) and the item gates' live smoke (A145). Their cases are the route's own
messages, their evaluators score the contract, and each stays out of
run_all.py until it is recorded live."""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent / "evals"))

import quiz_generation_planned as ds  # noqa: E402
import run_all  # noqa: E402

from agents.quiz_planned import PlannedQuestion, PlannedQuiz  # noqa: E402


def _ctx(case, questions):
    return SimpleNamespace(metadata=case.metadata, output=PlannedQuiz(questions=questions))


def _mc(slot, *, tags=("", "", "", ""), options=("alpha one", "beta two", "gamma six", "delta ten"), key=1):
    return PlannedQuestion(
        slot=slot, question="Which one holds here?", type="multiple_choice",
        options=list(options), option_misconceptions=list(tags), correct_answer=options[key],
        explanation="Because.",
    )


def test_every_case_is_the_routes_message_for_its_plan():
    names = [c.name for c in ds.CASES]
    assert len(names) == len(set(names))
    for case in ds.CASES:
        for slot in case.metadata["slots"]:
            assert f"QUESTION {slot}: difficulty " in case.inputs
        for slot, key in case.metadata["targets"].items():
            assert f"QUESTION {slot}: difficulty " in case.inputs and f"TARGET: {key}" in case.inputs
        assert f"FORMAT: {case.metadata['format']}" in case.inputs


def test_it_joins_run_all_only_once_recorded():
    assert ds.DATASET not in run_all.DATASETS
    cassettes = Path(__file__).resolve().parent / "evals" / "cassettes" / ds.DATASET
    assert not cassettes.exists(), "recorded: add it to run_all.DATASETS and drop this pin"


def test_the_evaluators_score_the_plans_contract():
    case = next(c for c in ds.CASES if c.name == "developing_mc_three_targets")
    targets = case.metadata["targets"]
    good = [
        _mc(1, tags=(targets[1], "", "", "")),
        _mc(2, tags=(targets[2], "", "", "")),
        _mc(3, tags=(targets[3], "", "", "")),
        _mc(4),
    ]
    for evaluator in (
        ds.SlotCoverageEvaluator(), ds.FormatEvaluator(), ds.McShapeEvaluator(),
        ds.TagValidityEvaluator(), ds.TargetEvaluator(), ds.EvidenceYieldEvaluator(),
    ):
        assert evaluator.evaluate(_ctx(case, good)) == 1.0, type(evaluator).__name__

    missing_slot = good[:3]
    assert ds.SlotCoverageEvaluator().evaluate(_ctx(case, missing_slot)) == 0.0
    key_tagged = [_mc(1, tags=("", targets[1], "", "")), *good[1:]]  # the key carries the tag
    assert ds.TagValidityEvaluator().evaluate(_ctx(case, key_tagged)) == 0.75
    assert ds.TargetEvaluator().evaluate(_ctx(case, key_tagged)) < 1.0
    longest_key = [
        _mc(n, options=("no", "the much longer correct answer here", "nah", "nope"), key=1) for n in (1, 2, 3, 4)
    ]
    assert ds.EvidenceYieldEvaluator().evaluate(_ctx(case, longest_key)) == 0.0


# ── the item gates' live smoke (A145) ───────────────────────────────────────

import quiz_item_gates as gates_ds  # noqa: E402

from agents.check_items_solve import Solution, Solutions  # noqa: E402
from agents.check_items_verify import AlignmentChecks, ConceptCheck  # noqa: E402


def test_the_gate_smoke_joins_run_all_only_once_recorded():
    assert gates_ds.DATASET not in run_all.DATASETS
    cassettes = Path(__file__).resolve().parent / "evals" / "cassettes" / gates_ds.DATASET
    assert not cassettes.exists(), "recorded: add it to run_all.DATASETS and drop this pin"
    assert {c.metadata["kind"] for c in gates_ds.CASES} == {"verify", "solve"}
    for case in gates_ds.CASES:
        assert "ITEM q1" in case.inputs
        if case.metadata["kind"] == "solve":
            assert "> A hash table's load factor" in case.inputs


def test_the_gate_smoke_evaluators_score_a_correct_check():
    by_name = {c.name: c for c in gates_ds.CASES}
    concept, solve = gates_ds.ConceptEvaluator(), gates_ds.SolveEvaluator()

    def verify_out(name):
        return AlignmentChecks(criteria=[], concepts=[ConceptCheck(item="q1", asks="x", concept=name)])

    def solve_out(solvable, answer):
        return Solutions(solutions=[Solution(item="q1", basis="x", solvable=solvable, answer=answer)])

    def score(evaluator, name, output):
        return evaluator.evaluate(SimpleNamespace(metadata=by_name[name].metadata, output=output))

    assert score(concept, "verify_aligned_load_factor", verify_out("Load Factor")) == 1.0
    assert score(concept, "verify_aligned_load_factor", verify_out("none")) == 0.0
    assert score(solve, "solve_agrees_mc", solve_out(True, "C")) == 1.0
    assert score(solve, "solve_agrees_mc", solve_out(True, "B")) == 0.0
    assert score(solve, "solve_numeric", solve_out(True, "0.750")) == 1.0
    assert score(solve, "solve_not_settled_by_the_passage", solve_out(False, "")) == 1.0
    assert score(solve, "solve_not_settled_by_the_passage", solve_out(True, "1953")) == 0.0
