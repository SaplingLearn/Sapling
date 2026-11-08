"""The planned quiz writer's eval dataset (learning-loop spec §13 A144),
offline: its cases are the route's own messages, its evaluators score the
plan's contract, and it stays out of run_all.py until it is recorded live."""

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
