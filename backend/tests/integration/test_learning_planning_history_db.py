"""Real tagged writer/migration/readiness roundtrip; no model calls."""

import hashlib
import uuid

import pytest

from tests.integration.conftest import COURSE_CS, USER_ACTIVE
from tests.integration.test_learning_goals_db import _node, _session

pytestmark = pytest.mark.integration


def _write(node, key, *, correct, rung=0, recheck=False, tagged=True):
    from services.graph_service import apply_graph_update

    check_id = f"planning-db-{key}"
    value = {
        "node_id": node,
        "channel": "free_response",
        "correct": correct,
        "max_rung": rung,
        "same_session_recheck": recheck,
        "confidence": 0.9,
        "check_item_id": check_id,
        "question_hash": hashlib.sha256(key.encode()).hexdigest(),
    }
    if tagged:
        value["planning_provenance"] = {
            "check_item_id": check_id,
            "difficulty": 3,
            "synthetic_idk": False,
            "previously_seen": False,
        }
    apply_graph_update(USER_ACTIVE, {"evidence": [value]}, COURSE_CS)
    return value["question_hash"]


def _prepare():
    from db.connection import table

    foundation, target = _node("Durable foundation"), _node("Durable target")
    table("graph_edges").insert(
        {
            "user_id": USER_ACTIVE,
            "source_node_id": foundation,
            "target_node_id": target,
            "relationship_type": "prerequisite",
        }
    )
    for index in range(7):
        _write(foundation, f"prior-{index}-{uuid.uuid4()}", correct=True)
    return foundation, target


def test_final_tagged_evidence_survives_new_session_and_real_goal_plan(
    authed_client, db_conn, monkeypatch
):
    import config
    from learning.planning_history import read_planning_history
    from learning import planner

    monkeypatch.setattr(config, "LEARNING_LOOP_ENABLED", True)
    foundation, target = _prepare()
    first = _write(foundation, f"miss-1-{uuid.uuid4()}", correct=False, rung=2)
    second = _write(foundation, f"miss-2-{uuid.uuid4()}", correct=False, rung=2, recheck=True)
    p = db_conn.execute(
        "SELECT p_known FROM learner_state WHERE user_id=%s AND node_id=%s",
        (USER_ACTIVE, foundation),
    ).fetchone()["p_known"]
    assert p >= 0.95  # actual weighted evidence reproduces the high-prior edge
    rows = db_conn.execute(
        "SELECT question_hash,planning_observation FROM node_mastery_events WHERE question_hash IN (%s,%s)",
        (first, second),
    ).fetchall()
    assert len(rows) == 2
    assert all(row["planning_observation"]["independent"] is False for row in rows)
    assert all(row["planning_observation"]["max_rung"] == 2 for row in rows)

    session = _session(state={"phase": "plan", "goal": {"target_node_ids": [target]}})
    result = authed_client.get(
        "/api/learn/loop/plan", params={"user_id": USER_ACTIVE, "session_id": session}
    )
    assert result.status_code == 200, result.text
    assert target not in [item["node_id"] for item in result.json()["concepts"]]
    assert foundation in result.json()["goal_progress"]["unresolved_prerequisite_ids"]

    _write(foundation, f"recovery-{uuid.uuid4()}", correct=True)
    history = read_planning_history(USER_ACTIVE, COURSE_CS, [foundation, target])
    assert planner.planning_states({foundation: p, target: 0.35}, history)[foundation] == p
    fresh = _session(state={"phase": "plan", "goal": {"target_node_ids": [target]}})
    result = authed_client.get(
        "/api/learn/loop/plan", params={"user_id": USER_ACTIVE, "session_id": fresh}
    )
    assert result.status_code == 200, result.text
    assert target in [item["node_id"] for item in result.json()["concepts"]]


def test_legacy_null_event_is_not_upgraded_by_current_saved_independence(
    authed_client, db_conn, monkeypatch
):
    import config

    monkeypatch.setattr(config, "LEARNING_LOOP_ENABLED", True)
    foundation, target = _prepare()
    _write(foundation, f"miss-{uuid.uuid4()}", correct=False, rung=2)
    legacy = _write(foundation, f"legacy-{uuid.uuid4()}", correct=True, tagged=False)
    row = db_conn.execute(
        "SELECT planning_observation FROM node_mastery_events WHERE question_hash=%s", (legacy,)
    ).fetchone()
    assert row["planning_observation"] is None
    snapshot = {
        "node_id": foundation,
        "question_hash": legacy,
        "difficulty": 3,
        "channel": "free_response",
        "correct": True,
        "idk": False,
        "independent": True,
        "max_rung": 0,
    }
    session = _session(
        state={
            "phase": "plan",
            "goal": {"target_node_ids": [target]},
            "probe": {"history": [snapshot]},
            "steps": {legacy: {"graded_at": 1, "goal_observation": snapshot}},
        }
    )
    result = authed_client.get(
        "/api/learn/loop/plan", params={"user_id": USER_ACTIVE, "session_id": session}
    )
    assert result.status_code == 200, result.text
    assert target not in [item["node_id"] for item in result.json()["concepts"]]
