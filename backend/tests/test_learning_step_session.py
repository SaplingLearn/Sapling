"""PKG-14 (owner decision 2026-09-29, spec §13 A82): zpd.step carries the loop
session's id, so the nightly cost report can attribute cost per session."""

from __future__ import annotations

from unittest.mock import patch

from learning.ladder import Rung
from tests import test_learn_loop_routes as _routes
from tests.test_learn_loop_routes import _answer, _feedback_agent, client

gate_on, no_rate_limit, seams = _routes.gate_on, _routes.no_rate_limit, _routes.seams

_STEP = dict(
    user_id="u1",
    request_id="r1",
    concept_id="n1",
    question_hash="q1",
    phase="check",
    channel="free_response",
    band="develop",
    ceiling=Rung.H3,
    ceiling_reason="develop",
    first_attempt_correct=True,
    n_attempts=1,
    max_rung_used=Rung.H0,
    rungs=[],
    time_to_first_attempt_ms=None,
    time_to_correct_ms=None,
    independent_time_ms=None,
    assisted=False,
    confidence=None,
    fsrs_rating=3,
    p_known_before=0.3,
    p_known_after=0.5,
    r_before=None,
    item_difficulty=2,
)


def _payloads(**extra):
    from learning import zpd_events

    captured = []
    with patch.object(zpd_events, "log_event", lambda et, **kw: captured.append(kw["payload"])):
        zpd_events.emit_zpd_step(**_STEP, **extra)
    return captured


def test_zpd_step_payload_carries_the_session_id_when_given():
    (p,) = _payloads(session_id="3f2c9a1e-5b7d-4e0a-9c8b-1d2e3f4a5b6c")
    assert p["session_id"] == "3f2c9a1e-5b7d-4e0a-9c8b-1d2e3f4a5b6c"


def test_zpd_step_without_a_session_omits_the_key():
    (p,) = _payloads()
    assert "session_id" not in p  # the post-test has no session: omitted, never blank


def test_the_check_answer_step_carries_its_session(gate_on, seams):
    agent_p, usage_p, _ = _feedback_agent()
    with agent_p, usage_p:
        r = client.post("/api/learn/loop/check/answer", json=_answer(answer="n == 0 returns 1"))
    assert r.status_code == 200
    assert seams.zpd.emit_zpd_step.call_args.kwargs["session_id"] == "s1"
