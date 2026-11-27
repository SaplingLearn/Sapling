"""Tutor redesign ("Just ask a question", owner decision 2026-11-26): an
ungraded chat session (services/just_ask.py).

A `just_ask` session starts in `teach` on no planned concept, with a template
opener (no model run; the student asks first), poses no check of its own,
refuses "Check me" and an answer with a 409, and never ends a teach turn on an
open question whose reply would get a verdict. The origin is refused while the
student's `just_ask` flag is off.
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from services.just_ask import JUST_ASK_ORIGIN, UNGRADED_DETAIL, is_just_ask, just_ask_state
from tests import test_learn_loop_routes as _routes
from tests.test_learn_loop_routes import client
from tests.split_patches import patch_loop

gate_on, no_rate_limit, seams = _routes.gate_on, _routes.no_rate_limit, _routes.seams


def _start(*, flag: bool, extra=None, agent=None):
    topic_p, offering_p, graph_p = _routes._opener_patches()
    if agent is None:
        agent = MagicMock()
        agent.run = AsyncMock(side_effect=AssertionError("a just-ask opener runs no model"))
    with topic_p, offering_p, graph_p, patch("services.loop.opener.flag_on", return_value=flag), \
            patch_loop("loop_tutor_agent", agent), patch_loop("record_agent_usage", side_effect=lambda r, **k: r):
        return client.post("/api/learn/loop/start-session", json={
            "user_id": "u1", "topic": "Ask anything", "origin": JUST_ASK_ORIGIN, **(extra or {})})


def test_a_just_ask_session_teaches_on_no_planned_concept_with_a_template_opener(gate_on, seams):
    from learning.turn_shape import LOOP_JUST_ASK_OPENER, LOOP_PROBE_OPENER
    from services.tutor_sessions import PENDING_SESSIONS

    r = _start(flag=True)
    assert r.status_code == 200, r.text
    assert r.json()["initial_message"] == LOOP_JUST_ASK_OPENER != LOOP_PROBE_OPENER
    assert "graded" in LOOP_JUST_ASK_OPENER and "?" not in LOOP_JUST_ASK_OPENER  # it asks nothing
    state = PENDING_SESSIONS.pop(r.json()["session_id"])["loop_state"]
    assert state == just_ask_state()
    assert state["phase"] == "teach" and state["plan"] == {"approved": [], "cursor": 0}
    assert "open_question" not in state  # the student's first message is their own question


def test_the_origin_is_refused_while_the_flag_is_off(gate_on, seams):
    assert _start(flag=False).status_code == 422


def test_a_just_ask_session_takes_no_goal(gate_on, seams):
    assert _start(flag=True, extra={"goal": {"text": "x", "target_node_ids": ["n1"]}}).status_code == 422


def test_check_me_is_refused_in_a_just_ask_session(gate_on, seams):
    seams.store["doc"] = just_ask_state()
    seams.list_items.return_value = [_routes.ITEM]
    r = client.post("/api/learn/loop/check/next", json={"session_id": "s1", "user_id": "u1"})
    assert r.status_code == 409 and r.json()["detail"] == UNGRADED_DETAIL
    seams.select_item.assert_not_called()
    assert seams.store["doc"] == just_ask_state()  # nothing activated


def test_an_answer_is_refused_in_a_just_ask_session(gate_on, seams):
    seams.store["doc"] = just_ask_state()
    r = client.post("/api/learn/loop/check/answer", json={
        "session_id": "s1", "user_id": "u1", "question_hash": _routes.ITEM.question_hash, "answer": "anything"})
    assert r.status_code == 409 and r.json()["detail"] == UNGRADED_DETAIL


def test_no_teach_turn_poses_a_check_or_asks_a_question_to_grade():
    from services.loop.cursor import _auto_poses_checks
    from services.loop.turn import _asks_open_question

    assert _auto_poses_checks(just_ask_state()) is False
    assert _auto_poses_checks({"phase": "teach"}) is True
    turn = SimpleNamespace(state=just_ask_state(), tier="model", phase="teach", poses_check=False, pq_follows=False, se_prompt=None)
    assert _asks_open_question(turn) is False
    turn.state = {"phase": "teach"}
    assert _asks_open_question(turn) is True  # any other teach turn, as before


def test_is_just_ask():
    assert is_just_ask(just_ask_state()) and not is_just_ask({"origin": "guide_ask"}) and not is_just_ask(None)


def test_a_resumed_just_ask_session_says_it_is_ungraded(gate_on, seams):
    seams.store["doc"] = just_ask_state()
    body = client.get("/api/learn/loop/status", params={"session_id": "s1", "user_id": "u1"}).json()
    assert body["ungraded"] is True and body["loop_phase"] == "teach"
    seams.store["doc"] = _routes._plan_state()
    assert "ungraded" not in client.get("/api/learn/loop/status", params={"session_id": "s1", "user_id": "u1"}).json()

