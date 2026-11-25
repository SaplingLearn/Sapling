"""W2.5 at the routes: a confident ("sure") wrong answer carries
`feedback_dwell_ms` on the check and the probe — and a correct answer, an idk (the box or a phrase), a skipped confidence and a lower one
("guessing", "fairly_sure") carry no such key, so Continue / Next is held only
where the hypercorrection dwell applies. The review's response is pinned in
tests/test_learning_review.py; the pure rule
(policy.hypercorrection_feedback_dwell_ms) in tests/test_learning_zpd_policy.py.
"""

from __future__ import annotations

import pytest

import config
from learning import params
from tests import test_learn_loop_routes as _routes
from tests import test_learning_probe_planner as _planner
from tests.test_learn_loop_routes import CORRECT, WRONG, _answer, _feedback_agent, client

# the route suites' fixtures (their rate-limit overrides apply here too)
gate_on, no_rate_limit, seams = _routes.gate_on, _routes.no_rate_limit, _routes.seams
probe, _no_rate_limit = _planner.probe, _planner._no_rate_limit

FULL_MS = params.GATE_HYPERCORRECTION_FEEDBACK_DWELL_S * params.MS_PER_SECOND

#: (the grade, the body beyond the answer, what the response holds Continue for).
CASES = [
    pytest.param(False, {"confidence": "sure"}, FULL_MS, id="sure-wrong"),
    pytest.param(True, {"confidence": "sure"}, None, id="sure-correct"),
    pytest.param(False, {"confidence": "sure", "answer": "idk"}, None, id="idk-phrase"),
    pytest.param(False, {"confidence": "sure", "answer": "", "idk": True}, None, id="idk-box"),
    pytest.param(False, {}, None, id="no-confidence"),
    pytest.param(False, {"confidence": "guessing"}, None, id="guessing-wrong"),
    pytest.param(False, {"confidence": "fairly_sure"}, None, id="fairly-sure-wrong"),
]


@pytest.fixture(autouse=True)
def full_time(monkeypatch):
    """A5's scale at 1, whatever the environment running the suite sets."""
    monkeypatch.setattr(config, "LEARNING_GATE_TIME_SCALE", 1.0)


def _holds(body: dict, ms: int | None) -> None:
    """The key is absent when nothing is held — never 0, never null."""
    if ms is None:
        assert "feedback_dwell_ms" not in body, body
    else:
        assert body["feedback_dwell_ms"] == ms, body


def _check(seams, correct, extra) -> dict:
    seams.grade.return_value = CORRECT if correct else WRONG
    agent_p, usage_p, _ = _feedback_agent()
    with agent_p, usage_p:
        r = client.post(
            "/api/learn/loop/check/answer", json=_answer(**{"answer": "n == 0 returns 1", **extra})
        )
    assert r.status_code == 200, r.text
    assert r.json()["graded"] is True
    return r.json()


@pytest.mark.parametrize("correct,extra,ms", CASES)
def test_the_check_response_holds_continue_after_a_sure_miss_only(gate_on, seams, correct, extra, ms):
    _holds(_check(seams, correct, extra), ms)


def test_the_check_hold_follows_the_gate_time_scale(gate_on, seams, monkeypatch):
    monkeypatch.setattr(config, "LEARNING_GATE_TIME_SCALE", 0.01)
    _holds(_check(seams, False, {"confidence": "sure"}), int(round(FULL_MS * 0.01)))


@pytest.mark.parametrize("correct,extra,ms", CASES)
def test_the_probe_response_holds_next_after_a_sure_miss_only(probe, correct, extra, ms):
    _planner._answer_doc(probe)
    probe.grade.side_effect = _planner._grader(correct=correct)
    r = client.post(
        f"{_planner.LOOP}/probe/answer",
        json={"session_id": "s1", "user_id": _planner.UID, "question_hash": "h-A-3", "answer": "because", **extra},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["graded"] is True and body["correct"] is correct
    assert ("reference_answer" in body) is (not correct)  # what the hold keeps on screen
    _holds(body, ms)
