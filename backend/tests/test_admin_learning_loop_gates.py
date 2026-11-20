"""#866 K56: the ceiling-compliance gate is inconclusive, never a fail, when no
step in the range carries the signal.

Spec §10's gate is "≥ 95% ceiling compliance" over the zpd.step rows that
carry both `max_rung_used` and `ceiling`. With none there is nothing to judge:
`ceiling_compliance_ok` is None (the panel's "inconclusive"), as the
earnest-revise gate is with no graded step (spec §13 A109), never False — a
red "fail" for every range before the loop has served anyone. With rows it is
the rate against GATE_CEILING_COMPLIANCE_MIN, as before.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from learning import params
from main import app
from services.admin.analytics import learning_loop as analytics
from tests.test_admin_learning_loop_kpis import RANGE, URL, _serve, _step

client = TestClient(app)


def _gates(monkeypatch, events):
    _serve(monkeypatch, {"events": events, "node_mastery_events": []})
    r = client.get(URL, params=RANGE)
    assert r.status_code == 200, r.text
    return r.json()


def test_an_empty_range_leaves_the_ceiling_gate_inconclusive(monkeypatch):
    b = _gates(monkeypatch, [])
    assert b["ceiling_compliance"] == {"steps": 0, "compliant": 0, "rate": None}
    assert b["gates"]["ceiling_compliance_ok"] is None


def test_steps_without_the_signal_leave_it_inconclusive(monkeypatch):
    unsignalled = [_step(i) for i in range(3)]
    for row in unsignalled:
        del row["payload"]["ceiling"]
    b = _gates(monkeypatch, unsignalled)
    assert b["steps_total"] == 3 and b["ceiling_compliance"]["steps"] == 0
    assert b["gates"]["ceiling_compliance_ok"] is None


def test_measured_steps_pass_or_fail_against_the_threshold(monkeypatch):
    assert _gates(monkeypatch, [_step(1, max_rung=2, ceiling="H3")])["gates"]["ceiling_compliance_ok"] is True
    breach = _gates(monkeypatch, [_step(1, max_rung=5, ceiling="H3")])
    assert breach["ceiling_compliance"]["rate"] == 0.0
    assert breach["gates"]["ceiling_compliance_ok"] is False


def test_the_gate_and_the_threshold_agree_at_the_edge():
    """The gate reads the same rate the KPI reports."""
    rows = [_step(i, max_rung=2, ceiling="H3") for i in range(19)] + [_step(19, max_rung=5, ceiling="H3")]
    compliance = analytics._ceiling_compliance(rows)
    assert compliance.rate == 19 / 20
    assert (compliance.rate >= params.GATE_CEILING_COMPLIANCE_MIN) is True
