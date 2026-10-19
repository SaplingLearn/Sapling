"""Spec §10's third gate, earnest-revise ≤ 5% (spec §13 A109). Pure.

The one reader of the feedback zpd.step's `earnest_blocked` bool (written by
`learning.zpd_events.emit_zpd_step`, set by routes/learn_loop.py's /hint when
the ceiling or the H6 gate denied a rung on a step with a genuine attempt).
The admin learning-loop KPI and scripts/derive_zpd_metrics.py share it. It
lives outside the PKG-06 layer on purpose: those two callers must not import
a PKG-06 module (tests/test_learning_zpd_policy.py's inertness scan), and it
needs nothing but params.
"""

from __future__ import annotations

from typing import Any, Iterable, Literal

from learning import params

EarnestGate = Literal["pass", "fail", "inconclusive"]


def earnest_revise(steps: Iterable[dict]) -> dict[str, Any]:
    """Spec §10's earnest-revise gate over zpd.step event rows (spec §13 A109):
    the share of graded CHECK steps whose payload says `earnest_blocked`. Only
    check steps count — /hint serves the active check item alone, so a probe or
    post-test step's default False would dilute the rate. A check step with no
    bool `earnest_blocked` (written before A109) is `unmeasured_steps`, never a
    zero. With no graded step the gate is "inconclusive", never a pass. Pure:
    the admin KPI and scripts/derive_zpd_metrics.py share it."""
    graded = blocked = unmeasured = 0
    for row in steps:
        payload = row.get("payload")
        if not isinstance(payload, dict) or payload.get("phase") != "check":
            continue
        flag = payload.get("earnest_blocked")
        if not isinstance(flag, bool):
            unmeasured += 1
            continue
        graded += 1
        blocked += int(flag)
    rate = blocked / graded if graded else None
    gate: EarnestGate
    if rate is None:
        gate = "inconclusive"
    else:
        gate = "pass" if rate <= params.GATE_EARNEST_REVISE_MAX else "fail"
    return {
        "graded_steps": graded,
        "earnest_blocked": blocked,
        "unmeasured_steps": unmeasured,
        "rate": rate,
        "gate": gate,
    }
