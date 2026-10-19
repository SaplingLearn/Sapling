"""PKG-14: perceived-difficulty prompt every ZPD_RATING_EVERY_N_CHECKS checks
(spec §3.4, §6 zpd.rating). The counter lives in sessions.loop_state
(`checks_since_rating`, PKG-06's typed field) and moves ONLY in the
check-answer handler, once per flushed grade (A16, invariant 26)."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from learning import params
from tests import test_learn_loop_routes as _routes
from tests.test_learn_loop_routes import (
    REFUSED,
    UNAVAILABLE,
    _answer,
    _fake_stream,
    _feedback_agent,
    _sse_events,
    _state,
    client,
)

# the route suite's fixtures (no_rate_limit is autouse there, so here too)
gate_on, no_rate_limit, seams = _routes.gate_on, _routes.no_rate_limit, _routes.seams

N = params.ZPD_RATING_EVERY_N_CHECKS
RATING = "/api/learn/loop/rating"


@pytest.fixture
def gate_off():
    with patch("routes.learn_loop.learning_loop_for_request", return_value=False) as g:
        yield g


@pytest.fixture
def session_row(seams):
    """The loop document of session s1 (the seams' in-memory store)."""
    seams.store["doc"] = _state()
    return seams.store


def _doc(session_row) -> dict:
    return session_row["doc"]


@pytest.fixture
def run_check_answer(gate_on, seams):
    """One genuine answer to /check/answer/stream; returns the done event's data."""

    def _run(**answer):
        with patch("routes.learn_loop.stream_structured_turn", _fake_stream("Right. Next?")):
            r = client.post(
                "/api/learn/loop/check/answer/stream",
                json=_answer(**(answer or {"answer": "n == 0 returns 1"})),
            )
        assert r.status_code == 200, r.text
        (done,) = [e for e in _sse_events(r.text) if e["type"] == "done"]
        return done["data"]

    return _run


@pytest.fixture
def run_chat_turn(gate_on, seams):
    def _run(message):
        with patch("routes.learn_loop.stream_structured_turn", _fake_stream("Try again?")):
            r = client.post(
                "/api/learn/loop/chat/stream",
                json={"session_id": "s1", "user_id": "u1", "message": message},
            )
        assert r.status_code == 200, r.text
        (done,) = [e for e in _sse_events(r.text) if e["type"] == "done"]
        return done["data"]

    return _run


# ── POST /rating ────────────────────────────────────────────────────────────


def test_rating_404_when_gate_false(gate_off, seams):
    r = client.post(RATING, json={"session_id": "s1", "rating": "too_easy"})
    assert r.status_code == 404 and r.json()["detail"] == "learning loop not enabled"
    seams.zpd.emit_zpd_rating.assert_not_called()
    seams.save.assert_not_called()


def test_rating_emits_event_and_resets_counter(gate_on, session_row, seams):
    _doc(session_row)["checks_since_rating"] = N
    r = client.post(RATING, json={"session_id": "s1", "user_id": "u1", "rating": "too_hard"})
    assert r.status_code == 200 and r.json() == {"ok": True}
    seams.zpd.emit_zpd_rating.assert_called_once()
    kw = seams.zpd.emit_zpd_rating.call_args.kwargs
    assert kw["rating"] == "too_hard" and kw["checks_since_last"] == N
    assert kw["user_id"] == "u1"
    assert _doc(session_row)["checks_since_rating"] == 0
    # nothing else in the document moved
    assert _doc(session_row)["steps"] == _state()["steps"]


def test_rating_user_comes_from_the_session_when_absent(gate_on, session_row, seams):
    _doc(session_row)["checks_since_rating"] = N
    r = client.post(RATING, json={"session_id": "s1", "rating": "appropriate"})
    assert r.status_code == 200
    gate_on.assert_called_once_with("user_andres")  # tests/conftest.py's session stub
    assert seams.zpd.emit_zpd_rating.call_args.kwargs["user_id"] == "user_andres"


def test_rating_checks_the_session_owner(gate_on, session_row, seams):
    from fastapi import HTTPException

    seams.scope.side_effect = HTTPException(status_code=403, detail="Session user mismatch")
    r = client.post(RATING, json={"session_id": "s1", "user_id": "u1", "rating": "too_easy"})
    assert r.status_code == 403
    seams.zpd.emit_zpd_rating.assert_not_called()
    seams.save.assert_not_called()


def test_rating_rejects_unknown_value(gate_on, session_row, seams):
    r = client.post(RATING, json={"session_id": "s1", "user_id": "u1", "rating": "meh"})
    assert r.status_code == 422
    seams.zpd.emit_zpd_rating.assert_not_called()


def test_rating_is_rate_limited():
    """Review fix round: /rating writes loop_state and an event, so it carries
    the A20 limit (it still runs no model)."""
    from routes import learn_loop
    from services import ai_budget

    (route,) = [r for r in learn_loop.router.routes if r.path == "/rating"]
    assert ai_budget.enforce_rate_limit in {d.call for d in route.dependant.dependencies}


@pytest.mark.parametrize("count", [None, 0, N - 1])
def test_a_rating_nobody_asked_for_is_409_and_records_nothing(gate_on, session_row, seams, count):
    if count is None:
        _doc(session_row).pop("checks_since_rating", None)
    else:
        _doc(session_row)["checks_since_rating"] = count
    r = client.post(RATING, json={"session_id": "s1", "user_id": "u1", "rating": "too_easy"})
    assert r.status_code == 409 and r.json()["detail"] == "no rating was asked for"
    seams.zpd.emit_zpd_rating.assert_not_called()
    assert _doc(session_row).get("checks_since_rating") == count


def test_a_rating_on_a_closed_session_is_409(gate_on, session_row, seams):
    _doc(session_row)["checks_since_rating"] = N
    _doc(session_row)["close_claim"] = "someone"
    _doc(session_row)["close_claim_at"] = _routes.NOW
    r = client.post(RATING, json={"session_id": "s1", "user_id": "u1", "rating": "too_easy"})
    assert r.status_code == 409
    seams.zpd.emit_zpd_rating.assert_not_called()


def test_rating_event_payload_is_the_spec_shape():
    """zpd.rating (spec §6): {rating, checks_since_last}, emitted through log_event."""
    from learning import zpd_events

    captured = []
    with patch.object(zpd_events, "log_event", lambda et, **kw: captured.append((et, kw))):
        zpd_events.emit_zpd_rating(
            user_id="u1", request_id="r1", rating="too_easy", checks_since_last=N
        )
    ((et, kw),) = captured
    assert et == "zpd.rating" and kw["payload"] == {"rating": "too_easy", "checks_since_last": N}


# ── the counter and ask_rating on the check-answer turn ──────────────────────


def test_done_carries_ask_rating_at_threshold(session_row, run_check_answer):
    _doc(session_row)["checks_since_rating"] = N - 1
    done = run_check_answer()
    assert done["ask_rating"] is True
    assert _doc(session_row)["checks_since_rating"] == N


def test_done_omits_ask_rating_below_threshold(session_row, run_check_answer):
    _doc(session_row)["checks_since_rating"] = 0
    done = run_check_answer()
    assert "ask_rating" not in done
    assert _doc(session_row)["checks_since_rating"] == 1


def test_counter_absent_starts_at_zero(session_row, run_check_answer):
    _doc(session_row).pop("checks_since_rating", None)
    assert "ask_rating" not in run_check_answer()
    assert _doc(session_row)["checks_since_rating"] == 1


def test_json_check_answer_carries_ask_rating(gate_on, session_row, seams):
    _doc(session_row)["checks_since_rating"] = N - 1
    agent_p, usage_p, _ = _feedback_agent()
    with agent_p, usage_p:
        r = client.post("/api/learn/loop/check/answer", json=_answer(answer="n == 0 returns 1"))
    assert r.status_code == 200 and r.json()["ask_rating"] is True


def test_json_check_answer_below_threshold_has_no_key(gate_on, session_row, seams):
    agent_p, usage_p, _ = _feedback_agent()
    with agent_p, usage_p:
        r = client.post("/api/learn/loop/check/answer", json=_answer(answer="n == 0 returns 1"))
    assert r.status_code == 200 and "ask_rating" not in r.json()


def test_an_idk_submission_is_a_check(session_row, run_check_answer):
    """idk is graded evidence (A1) — the counter counts every flushed grade."""
    _doc(session_row)["checks_since_rating"] = 2
    run_check_answer(idk=True)
    assert _doc(session_row)["checks_since_rating"] == 3


@pytest.mark.parametrize("outcome", [UNAVAILABLE, REFUSED], ids=["unavailable", "refused"])
def test_an_ungraded_submission_does_not_count(session_row, seams, run_check_answer, outcome):
    _doc(session_row)["checks_since_rating"] = N - 1
    seams.grade.return_value = outcome
    done = run_check_answer()
    assert "ask_rating" not in done
    assert _doc(session_row)["checks_since_rating"] == N - 1
    seams.flush.assert_not_called()


def test_a_hint_request_submission_does_not_count(session_row, seams, run_check_answer):
    _doc(session_row)["checks_since_rating"] = 4
    run_check_answer(answer="just tell me")
    assert _doc(session_row)["checks_since_rating"] == 4
    seams.grade.assert_not_called()


def test_plain_chat_turn_never_counts_as_a_check(session_row, run_chat_turn):
    _doc(session_row)["checks_since_rating"] = 3
    done = run_chat_turn("is it the lexical scope?")  # typed in the check phase: not graded (A16)
    assert "ask_rating" not in done
    assert _doc(session_row)["checks_since_rating"] == 3


def test_the_counter_rides_the_grade_write(session_row, seams, run_check_answer):
    """One compare-and-set write records the grade AND the counter (A11 / A38 06(q)):
    no extra save for the counter."""
    run_check_answer()
    with_grade = [
        c
        for c in seams.save.call_args_list
        if (c.args[1].to_json().get("steps") or {}).get("qh-1", {}).get("graded_at") is not None
    ]
    first = with_grade[0].args[1].to_json()
    assert first["checks_since_rating"] == 1
