"""The novice worked-example-first path is in the loop evals (#866 Z23, spec §13 A122).

`phase_prefix` sends NOVICE_WORKED_FIRST_FORMAT whenever `policy.attempt_first`
says no — every novice whose prerequisites are not all known proficient, which
includes every concept with no prerequisite edge (all of an upload-built graph
while `upload_prereq_edges` is off) — and that item's first hint is the H4
worked example. No loop_tutor or misconception_confront case sent it, so the
leak, ceiling and one-question gates had never scored the path the loop serves
by default. Each dataset now carries worked-first cases, built by production's
own helpers at the policy's ceilings; they are recorded in the A111 pass.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

from agents.loop_tutor import NOVICE_WORKED_FIRST_FORMAT
from learning.ladder import Rung

EVALS = Path(__file__).parent / "evals"


@pytest.fixture(scope="module")
def evals():
    sys.path.insert(0, str(EVALS))
    try:
        import loop_tutor
        import misconception_confront

        yield loop_tutor, misconception_confront
    finally:
        sys.path.remove(str(EVALS))


def _worked_first(cases):
    return [c for c in cases if (c.metadata or {}).get("attempt_first") is False]


def test_the_loop_tutor_dataset_scores_a_worked_first_teach_turn_and_its_h4_hint(evals):
    lt, _ = evals
    cases = {c.inputs[0]: c for c in _worked_first(lt.CASES)}
    assert set(cases) == {"teach", "hint"}
    for case in cases.values():
        assert case.inputs[1] == "novice"
        assert NOVICE_WORKED_FIRST_FORMAT in lt._assembled(case.inputs)
        assert NOVICE_WORKED_FIRST_FORMAT in lt._assembled(case.inputs, v2=True)
        assert case.metadata["final_answer"] and case.metadata["reference"]  # scored for leaks
    assert cases["hint"].inputs[2] == int(Rung.H4)  # the first hint is the worked example
    assert cases["teach"].inputs[2] == int(lt._WORKED_FIRST_TEACH_CEILING)
    # every other case stays attempt-first: its recorded message is unchanged
    for case in lt.CASES:
        if case not in cases.values():
            assert NOVICE_WORKED_FIRST_FORMAT not in lt._assembled(case.inputs)
    # in every tier's dataset, so the routing gates score it
    for _slot, (make, _run) in lt.VARIANTS.items():
        assert {c.name for c in cases.values()} <= {c.name for c in make().cases}


def test_the_confront_dataset_scores_a_worked_first_confronting_hint(evals):
    _, mc = evals
    [case] = _worked_first(mc.CASES)
    assert case.inputs[:3] == ("hint", "novice", int(Rung.H4))
    assert NOVICE_WORKED_FIRST_FORMAT in mc.assembled(case.inputs)
    assert len(mc.CASES) <= 8


def test_the_worked_first_hint_sends_the_routes_own_action_text(evals):
    from services.loop.flags import _ACTION_PROMPTS

    lt, mc = evals
    want = f"[ACTION: {_ACTION_PROMPTS['hint']}]"
    for case in _worked_first(lt.CASES) + _worked_first(mc.CASES):
        if case.inputs[0] == "hint":
            assert case.inputs[3] == want
