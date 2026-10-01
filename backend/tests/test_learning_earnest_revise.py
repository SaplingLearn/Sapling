"""Spec §10's third gate, earnest-revise ≤ 5 % (spec §13 A109): the rate of
graded check steps whose `/hint` was denied at the ceiling (or the H6 gate)
after a genuine attempt. `learning.earnest_revise` is the one reader the
admin KPI and scripts/derive_zpd_metrics.py share."""

from __future__ import annotations

import pytest

from learning import params
from learning.earnest_revise import earnest_revise


def _step(phase="check", blocked=None, *, payload=True):
    p = {"phase": phase}
    if blocked is not None:
        p["earnest_blocked"] = blocked
    return {"event_type": "zpd.step", "payload": p if payload else None}


def test_the_gate_constant_is_spec_section_10s_five_percent():
    assert params.GATE_EARNEST_REVISE_MAX == 0.05


def test_rate_is_blocked_over_graded_check_steps():
    steps = [_step(blocked=True)] + [_step(blocked=False)] * 19
    out = earnest_revise(steps)
    assert out == {
        "graded_steps": 20,
        "earnest_blocked": 1,
        "unmeasured_steps": 0,
        "rate": pytest.approx(0.05),
        "gate": "pass",
    }


def test_the_gate_fails_above_the_max():
    steps = [_step(blocked=True)] * 2 + [_step(blocked=False)] * 18
    out = earnest_revise(steps)
    assert out["rate"] == pytest.approx(0.1) and out["gate"] == "fail"


def test_no_graded_steps_is_inconclusive_never_a_pass():
    for steps in ([], [_step(phase="posttest", blocked=False)], [_step(blocked=None)]):
        out = earnest_revise(steps)
        assert out["rate"] is None and out["gate"] == "inconclusive", steps
        assert out["graded_steps"] == 0


def test_only_check_steps_count():
    """Probe and post-test steps never reach /hint (it serves the PKG-07 active
    item only), so their default False would dilute the rate."""
    steps = [
        _step(blocked=True),
        _step(phase="probe", blocked=False),
        _step(phase="posttest", blocked=False),
    ]
    out = earnest_revise(steps)
    assert out["graded_steps"] == 1 and out["rate"] == 1.0 and out["gate"] == "fail"


def test_a_step_without_the_key_is_unmeasured_not_a_zero():
    """zpd.step rows written before A109 carry no key: not counted as
    un-blocked (that would flatter the rate), reported as unmeasured."""
    steps = [_step(blocked=True), _step(blocked=None), _step(blocked="yes"), _step(payload=False)]
    out = earnest_revise(steps)
    assert out["graded_steps"] == 1 and out["earnest_blocked"] == 1
    assert out["unmeasured_steps"] == 2  # the non-bool and the missing key; no payload = no phase
