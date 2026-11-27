"""#866 audit K01 (owner decision 2026-11-19): a study guide's "Ask the tutor".

With the loop on, the guide's Ask opened a session in the check-in, which takes
no teaching before the pretest, so the question the hand-off sends as the first
message was refused and every Ask failed. A `guide_ask` session starts in
`teach` — on the concept the Ask names when the student has it in the course,
else as an open teaching session (the empty plan's shape) — with its own
template opener, no open question and no segment prequestion. The legacy
(loop-off) path accepts the origin and ignores it.
"""
from __future__ import annotations

from contextlib import ExitStack
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from services.guide_ask import GUIDE_ASK_ORIGIN, guide_ask_node, guide_ask_state
from tests import test_learn_loop_routes as _routes
from tests.test_learn_loop_routes import client
from tests.split_patches import patch_loop

gate_on, no_rate_limit, seams = _routes.gate_on, _routes.no_rate_limit, _routes.seams

ASK = {"origin": "guide_ask"}


def _nodes(rows):
    def factory(name):
        m = MagicMock()
        m.select.return_value = rows if name == "graph_nodes" else []
        return m
    return factory


def _start(*, topic: str, nodes, agent=None, extra=None):
    topic_p, offering_p, graph_p = _routes._opener_patches()
    patches = [topic_p, offering_p, graph_p, patch("services.guide_ask.table", side_effect=_nodes(nodes)),
               patch("services.quiz_ask.record_help")]
    if agent is not None:
        patches += [patch_loop("loop_tutor_agent", agent), patch_loop("record_agent_usage", side_effect=lambda r, **k: r)]
    with ExitStack() as stack:
        mocks = [stack.enter_context(p) for p in patches]
        r = client.post("/api/learn/loop/start-session", json={"user_id": "u1", "topic": topic, **ASK, **(extra or {})})
        return r, mocks[4]


def test_a_guide_ask_on_a_known_concept_teaches_it_from_the_first_turn(gate_on, seams):
    from services.tutor_sessions import PENDING_SESSIONS

    agent, _ = _routes._json_agent("Key idea: a loop repeats until its condition fails.")
    r, record_help = _start(topic="Loops", nodes=[{"id": "node-loops"}], agent=agent)
    assert r.status_code == 200, r.text
    pending = PENDING_SESSIONS.pop(r.json()["session_id"])
    assert pending["loop_state"] == guide_ask_state("node-loops")
    assert pending["loop_state"]["phase"] == "teach" and pending["loop_state"]["concept"] == "node-loops"
    # the first message is the student's own question, not a reply (K39's rule)
    assert "open_question" not in pending["loop_state"]
    record_help.assert_not_called()  # a guide Ask is about no one graded question


def test_a_guide_ask_about_the_whole_guide_opens_an_open_teaching_session(gate_on, seams):
    from services.tutor_sessions import PENDING_SESSIONS

    agent, _ = _routes._json_agent("Happy to help with the guide.")
    r, _ = _start(topic="Control flow and functions", nodes=[], agent=agent)
    assert r.status_code == 200, r.text
    state = PENDING_SESSIONS.pop(r.json()["session_id"])["loop_state"]
    assert state == guide_ask_state(None)
    assert state["phase"] == "teach" and state["plan"] == {"approved": [], "cursor": 0}


def test_a_guide_ask_template_opener_promises_no_check_in(gate_on, seams):
    from learning.turn_shape import LOOP_GUIDE_ASK_OPENER, LOOP_PROBE_OPENER
    from services.tutor_sessions import PENDING_SESSIONS

    seams.ai_budget.check.return_value = _routes.HARD
    agent = MagicMock()
    agent.run = AsyncMock(side_effect=AssertionError("no model at the hard level"))
    r, _ = _start(topic="Loops", nodes=[{"id": "node-loops"}], agent=agent)
    assert r.status_code == 200, r.text
    assert r.json()["initial_message"] == LOOP_GUIDE_ASK_OPENER != LOOP_PROBE_OPENER
    assert "check-in" not in LOOP_GUIDE_ASK_OPENER and "?" not in LOOP_GUIDE_ASK_OPENER
    PENDING_SESSIONS.pop(r.json()["session_id"])


def test_a_guide_ask_takes_no_goal(gate_on, seams):
    r, _ = _start(topic="Loops", nodes=[], extra={"goal": {"node_ids": ["n1"]}})
    assert r.status_code == 422


@pytest.mark.parametrize("node", ["node-loops", None])
def test_both_guide_ask_documents_are_open_for_the_first_chat_turn(node):
    """The 409 K01 hit: the follow-up chat read a probe document."""
    from services.loop.state import _require_teaching

    _require_teaching(guide_ask_state(node))  # no 409


def test_a_guide_ask_poses_no_segment_prequestion():
    from learning.prequestion import segment_open

    assert segment_open(guide_ask_state("node-loops")) is None


def test_the_concept_is_read_owner_scoped_by_exact_name():
    seen = {}

    def factory(name):
        m = MagicMock()
        m.select.side_effect = lambda *a, **k: seen.update(k) or [{"id": "node-x"}]
        return m

    with patch("services.guide_ask.table", side_effect=factory):
        assert guide_ask_node("u1", "c1", "  Loops ") == "node-x"
    assert seen["filters"] == {"user_id": "eq.u1", "course_id": "eq.c1", "concept_name": "eq.Loops"}
    assert guide_ask_node("u1", None, "Loops") is None and guide_ask_node("u1", "c1", " ") is None


def test_the_legacy_body_accepts_the_origin():
    from models import StartSessionBody

    assert StartSessionBody(user_id="u1", topic="Loops", origin=GUIDE_ASK_ORIGIN).origin == "guide_ask"
