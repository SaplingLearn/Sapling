"""The check-item pipeline's model steps have eval datasets (#866 Z24, Z25).

Every learning-loop drafting call runs the A119 alignment check, the A124
blind solve and key match, and (below the mc_reason floor) the A37 top-up.
None had a dataset, and the check_items
dataset drafted one concept per call where production drafts
CHECK_ITEM_CONCEPTS_PER_CALL. `tests/evals/check_item_gates.py` adds one
dataset per step and check_items.py the three-concept call; they are recorded
in the A111 pass. These tests pin the wiring and prove each evaluator scores a
correct answer 1.0 and a wrong one below it, with no model call.
"""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from agents.check_items_key_match import KeyMatch, KeyMatches
from agents.check_items_solve import Solution, Solutions
from agents.check_items_verify import AlignmentChecks, ConceptCheck, CriterionCheck
from learning.params import CHECK_ITEM_CONCEPTS_PER_CALL

EVALS = Path(__file__).parent / "evals"


@pytest.fixture(scope="module")
def mods():
    sys.path.insert(0, str(EVALS))
    try:
        import check_item_gates
        import check_items
        import run_all

        yield SimpleNamespace(gates=check_item_gates, plain=check_items, run_all=run_all)
    finally:
        sys.path.remove(str(EVALS))


def _case(mod, dataset: str, name: str):
    make, _ = mod.VARIANTS[dataset]
    return next(c for c in make().cases if c.name == name)


def _ctx(case, output):
    return SimpleNamespace(inputs=case.inputs, output=output, metadata=case.metadata)


def _alignment(rows: dict[str, tuple[dict[str, bool], str]]) -> AlignmentChecks:
    return AlignmentChecks(
        criteria=[
            CriterionCheck(item=item, criterion=cid, why="w", asked=asked)
            for item, (crit, _) in rows.items()
            for cid, asked in crit.items()
        ],
        concepts=[ConceptCheck(item=item, asks="a", concept=c) for item, (_, c) in rows.items()],
    )


def test_the_pipeline_steps_are_replayed_from_the_start(mods):
    g = mods.gates
    assert "check_item_gates" in mods.run_all.DATASETS
    assert set(g.VARIANTS) == {"check_items_verify", "check_items_solve", "check_items_topup"}
    for name, (make, run) in g.VARIANTS.items():
        for case in make().cases:
            identity = run.identity(case)  # recorded under the step's own slot model
            assert identity["model"] and identity["prompt_hash"] and identity["input_sha256"]


def test_the_alignment_check_is_scored_as_production_applies_it(mods):
    g = mods.gates
    case = _case(g, "check_items_verify", "verify_live_load_factor")
    right = _alignment({"1": ({"c1": True, "c2": False}, "Load Factor")})
    for ev in (g.CriteriaKept(), g.ConceptTested(), g.EveryItemAnswered()):
        assert ev.evaluate(_ctx(case, right)) == 1.0, type(ev).__name__
    # the live miss: the unasked threshold criterion kept, filed under Open Addressing
    wrong = _alignment({"1": ({"c1": True, "c2": True}, "Open Addressing")})
    assert g.CriteriaKept().evaluate(_ctx(case, wrong)) == 0.0
    assert g.ConceptTested().evaluate(_ctx(case, wrong)) == 0.0
    half = AlignmentChecks(criteria=right.criteria, concepts=[])
    assert g.EveryItemAnswered().evaluate(_ctx(case, half)) == 0.0

    five = _case(g, "check_items_verify", "verify_live_five_item_call")
    rows = {
        "1": ({"c1": True}, "Hash Function"),
        "2": ({"c1": True, "c2": False}, "Separate Chaining"),
        "3": ({"c1": True, "c2": False}, "Tombstone Deletion"),
        "4": ({"c1": True}, "none"),
        "5": ({"c1": True, "c2": True}, "Load Factor"),
    }
    assert g.ConceptTested().evaluate(_ctx(five, _alignment(rows))) == 1.0
    assert g.CriteriaKept().evaluate(_ctx(five, _alignment(rows))) == 1.0
    rows["4"] = ({"c1": True}, "Hash Table")  # binary search is no listed concept
    assert g.ConceptTested().evaluate(_ctx(five, _alignment(rows))) == 0.8


def test_the_blind_solve_and_key_match_are_scored_through_item_keys(mods):
    g = mods.gates
    case = _case(g, "check_items_solve", "solve_five_item_call")
    answers = [("A", True), ("C", True), ("0.75", True), ("", False), ("a linked list", True)]

    def solutions(rows):
        return Solutions(solutions=[
            Solution(item=str(n), basis="b", solvable=ok, answer=a) for n, (a, ok) in enumerate(rows, 1)
        ])

    assert g.SolveAgreement().evaluate(_ctx(case, solutions(answers))) == 1.0
    assert g.EveryItemAnswered().evaluate(_ctx(case, solutions(answers))) == 1.0
    agrees_with_wrong_key = [answers[0], ("B", True), *answers[2:]]
    assert g.SolveAgreement().evaluate(_ctx(case, solutions(agrees_with_wrong_key))) == 0.8

    match = _case(g, "check_items_solve", "key_match_five_pairs")
    want = [True, False, True, False, True]

    def judged(rows):
        return KeyMatches(matches=[KeyMatch(item=str(n), why="w", same=s) for n, s in enumerate(rows, 1)])

    assert g.MatchAgreement().evaluate(_ctx(match, judged(want))) == 1.0
    assert g.MatchAgreement().evaluate(_ctx(match, judged([True] * 5))) == 0.6
    # each kind's evaluator is vacuous on the other kind
    assert g.SolveAgreement().evaluate(_ctx(match, judged(want))) == 1.0


def _draft(concept: str, *, difficulty=2, fmt="mc_reason", surface=("numeric", "a table")):
    return SimpleNamespace(
        concept=concept, difficulty=difficulty, format=fmt,
        surface_representation=surface[0], surface_context=surface[1],
    )


def test_the_topup_contract(mods):
    g = mods.gates
    topup = _case(g, "check_items_topup", "topup_limits_after_dropped_drafts")
    ok = SimpleNamespace(items=[_draft("Limits", difficulty=2), _draft("Limits", difficulty=3)])
    assert g.TopupShape().evaluate(_ctx(topup, ok)) == 1.0
    one_short = SimpleNamespace(items=[_draft("Limits", difficulty=2)])
    assert g.TopupShape().evaluate(_ctx(topup, one_short)) == 0.0
    free = SimpleNamespace(items=[_draft("Limits", difficulty=2), _draft("Limits", difficulty=3, fmt="free")])
    assert g.TopupShape().evaluate(_ctx(topup, free)) == 0.0



def test_check_items_drafts_production_three_concept_call(mods):
    ci = mods.plain
    multi = [c for c in ci.CASES if not isinstance(c.inputs[0], str)]
    assert len(multi) == 2 and len(ci.CASES) <= ci._MAX_CASES
    for case in multi:
        assert len(case.inputs[0]) == CHECK_ITEM_CONCEPTS_PER_CALL
        message = ci._message(case.inputs)
        assert all(f"- {name}" in message for name in case.inputs[0])
    for case in ci.CASES:  # a one-concept case's message is the one it was recorded with
        if isinstance(case.inputs[0], str):
            assert ci._message(case.inputs) == ci.build_prompt(
                [case.inputs[0]], [{"id": i, "text": t} for i, t in case.inputs[1]]
            )


def test_concepts_covered_scores_every_concept_of_the_call(mods, monkeypatch):
    ci = mods.plain
    case = next(c for c in ci.CASES if not isinstance(c.inputs[0], str))
    names = list(case.inputs[0])
    monkeypatch.setattr(ci, "_stored", lambda draft: True)
    ev = ci.ConceptsCoveredEvaluator()
    every = SimpleNamespace(items=[SimpleNamespace(concept=n) for n in names])
    assert ev.evaluate(SimpleNamespace(inputs=case.inputs, output=every)) == 1.0
    two = SimpleNamespace(items=[SimpleNamespace(concept=n) for n in names[:2]])
    assert ev.evaluate(SimpleNamespace(inputs=case.inputs, output=two)) == pytest.approx(2 / 3)
    stray = SimpleNamespace(items=[*every.items, SimpleNamespace(concept="Photosynthesis")])
    assert ev.evaluate(SimpleNamespace(inputs=case.inputs, output=stray)) == 0.0
