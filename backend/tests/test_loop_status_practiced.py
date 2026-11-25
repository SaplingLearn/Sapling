"""W3.2 resume: GET /status carries the ids of the concepts graded this session
(`practiced_node_ids`), so the session map's practiced outlines survive a
reload. Read-only and ids only; a node the student holds no measurement on
(§13 A150, #866 K52) is never one, and the key is absent when there is none.
"""

from __future__ import annotations

import json

import pytest

from tests import test_learn_loop_routes as _routes
from tests.test_learn_loop_routes import NOW, _graded, _state, _step, client

gate_on, no_rate_limit, seams = _routes.gate_on, _routes.no_rate_limit, _routes.seams

URL = "/api/learn/loop/status?user_id=u1&session_id=s1"
KEY = "practiced_node_ids"


def _doc() -> dict:
    """Two concepts graded (one twice), one posed and not answered."""
    doc = _state()
    doc["steps"].update(
        {
            "qh-b": _step(node_id="node-b", graded_at=NOW - 40, last_verdict="not_yet", last_correct=False),
            "qh-a": _step(node_id="node-a", graded_at=NOW - 30, last_verdict="correct", last_correct=True),
            "qh-a2": _step(node_id="node-a", graded_at=NOW - 20, last_verdict="idk", last_correct=False),
        }
    )
    return doc


def _status() -> dict:
    r = client.get(URL)
    assert r.status_code == 200, r.text
    return r.json()


def test_status_names_the_concepts_graded_this_session(gate_on, seams):
    seams.p_known.update({"node-a": 0.6, "node-b": 0.2})
    seams.store["doc"] = _doc()
    body = _status()
    # once each; the posed-only node-1 (measured by an earlier session) is not one
    assert body[KEY] == ["node-a", "node-b"]
    assert all(isinstance(n, str) for n in body[KEY])  # ids only: no belief rides along
    seams.save.assert_not_called()
    seams.flush.assert_not_called()
    # one batched read, on the student's own rows
    assert [c.args for c in seams.read_states.call_args_list if "node-a" in c.args[1]] == [
        ("u1", {"node-a", "node-b"})
    ]


def test_an_unmeasured_concept_is_never_practiced(gate_on, seams):
    """A grade voided since (its row back at opps 0) or a node with no row."""
    seams.p_known["node-a"] = 0.35
    seams.opps["node-a"] = 0
    seams.store["doc"] = _doc()  # node-b: no learner_state row at all
    assert KEY not in _status()
    seams.p_known["node-b"] = 0.2
    assert _status()[KEY] == ["node-b"]


@pytest.mark.parametrize("doc", [{}, {"phase": "teach"}, _state()])
def test_a_session_with_no_graded_step_has_no_key_and_no_extra_read(gate_on, seams, doc):
    seams.store["doc"] = doc
    assert KEY not in _status()
    assert all(list(c.args[1]) == ["node-1"] for c in seams.read_states.call_args_list)


def test_a_graded_item_waiting_for_its_feedback_counts(gate_on, seams):
    seams.store["doc"] = _graded("not_yet")
    body = _status()
    assert body["phase"] == "feedback" and body[KEY] == ["node-1"]


def test_a_failed_read_draws_no_outline_and_still_resumes(gate_on, seams):
    real = seams.read_states.side_effect

    def flaky(user_id, node_ids, **kw):
        if "node-a" in node_ids:
            raise RuntimeError("down")
        return real(user_id, node_ids, **kw)

    seams.read_states.side_effect = flaky
    seams.store["doc"] = _doc()
    body = _status()
    assert KEY not in body and body["phase"] == "check"


def test_another_students_pending_session_names_nothing(gate_on, seams):
    from services.tutor_sessions import PENDING_SESSIONS

    seams.p_known.update({"node-a": 0.6, "node-b": 0.2})
    PENDING_SESSIONS["s1"] = {"user_id": "someone-else", "loop_state": _doc()}
    try:
        body = _status()
    finally:
        PENDING_SESSIONS.pop("s1", None)
    assert KEY not in body and "node-a" not in json.dumps(body)
