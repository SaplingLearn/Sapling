"""Goal HTTP routes against real local PostgREST; assertions use direct SQL.

No tutor/model calls are needed. The normal integration conftest exclusively
owns local-only safety, truncate/reseed isolation, authentication and DB access.
Concurrency hooks delay real writes; they never fake a DB result or CAS outcome.
"""

from __future__ import annotations

import json
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor

import pytest

from tests.integration.conftest import COURSE_CS, USER_ACTIVE, USER_SECOND, _client_for

pytestmark = pytest.mark.integration

LOOP = "/api/learn/loop"
OFFERING = "rich-off-cs101-f25"
COURSE_OTHER = "rich-course-bio110"


@pytest.fixture(autouse=True)
def _exercise_active_loop(monkeypatch):
    import config

    monkeypatch.setattr(config, "LEARNING_LOOP_ENABLED", True)


def _node(name, *, owner=USER_ACTIVE, course=COURSE_CS):
    from db.connection import table

    node_id = str(uuid.uuid4())
    table("graph_nodes").insert(
        {"id": node_id, "user_id": owner, "course_id": course, "concept_name": name}
    )
    return node_id


def _session(*, owner=USER_ACTIVE, state=None):
    from db.connection import table

    session_id = str(uuid.uuid4())
    table("sessions").insert(
        {
            "id": session_id,
            "user_id": owner,
            "offering_id": OFFERING,
            "mode": "socratic",
            "topic": "Integration goal persistence",
            "loop_state": state or {"phase": "probe"},
            "loop_state_rev": 0,
        }
    )
    return session_id


def _body(session_id, *, user=USER_ACTIVE):
    return {"session_id": session_id, "user_id": user}


def _goal(
    client, session_id, target, text="Apply this concept in a private project", *, user=USER_ACTIVE
):
    return client.post(
        f"{LOOP}/goal",
        json={**_body(session_id, user=user), "goal": {"text": text, "target_node_ids": [target]}},
    )


def _raw(db_conn, session_id):
    row = db_conn.execute(
        "SELECT loop_state, loop_state_rev FROM sessions WHERE id = %s", (session_id,)
    ).fetchone()
    assert row is not None
    return row


def _finish_empty_bank(client, session_id):
    response = client.post(f"{LOOP}/probe/next", json=_body(session_id))
    assert response.status_code == 200, response.text
    assert response.json()["done"] is True
    return response.json()


def test_goal_http_write_encrypts_prose_and_roundtrips_from_persisted_json(authed_client, db_conn):
    from learning.goals import public_goal
    from learning.loop_state_store import load_loop_state
    from services.encryption import decrypt_if_present

    target = _node("Private goal roundtrip")
    session_id = _session()
    secret = "Private medical-school application project ✓"
    response = _goal(authed_client, session_id, target, secret)
    assert response.status_code == 200, response.text
    assert response.json()["goal"] == {"text": secret, "target_node_ids": [target]}
    row = _raw(db_conn, session_id)
    persisted = row["loop_state"]
    assert secret not in json.dumps(persisted, ensure_ascii=False)
    assert "text" not in persisted["goal"]
    assert decrypt_if_present(persisted["goal"]["text_encrypted"]) == secret
    assert persisted["goal"]["target_node_ids"] == [target]
    assert row["loop_state_rev"] == 1 and persisted["goal_version"] == 1
    assert public_goal(load_loop_state(session_id).state.to_json()) == response.json()["goal"]
    events = db_conn.execute(
        "SELECT payload FROM events WHERE user_id = %s", (USER_ACTIVE,)
    ).fetchall()
    assert secret not in json.dumps(events, default=str, ensure_ascii=False)


def test_goal_course_ownership_and_prerequisite_closure_use_real_graph(authed_client, db_conn):
    from db.connection import table
    from learning.evidence import PREREQ_RELATIONSHIP_TYPE

    root = _node("Goal integration foundation")
    middle = _node("Goal integration bridge")
    target = _node("Goal integration application")
    unrelated = _node("Goal integration unrelated")
    foreign = _node("Goal integration other student", owner=USER_SECOND)
    wrong_course = _node("Goal integration other course", course=COURSE_OTHER)
    table("graph_edges").insert(
        [
            {
                "user_id": USER_ACTIVE,
                "source_node_id": a,
                "target_node_id": b,
                "relationship_type": PREREQ_RELATIONSHIP_TYPE,
            }
            for a, b in [
                (root, middle),
                (middle, target),
                (foreign, middle),
                (wrong_course, middle),
            ]
        ]
    )
    session_id = _session()
    for invalid in [foreign, wrong_course, "absent-goal-concept"]:
        response = _goal(authed_client, session_id, invalid)
        assert response.status_code == 422, response.text
        assert _raw(db_conn, session_id)["loop_state_rev"] == 0
    response = _goal(authed_client, session_id, target)
    assert response.status_code == 200, response.text
    diagnosis = _finish_empty_bank(authed_client, session_id)["diagnosis"]
    assert {s["node_id"] for s in diagnosis["skills"]} == {root, middle, target}
    assert all(s["status"] == "untested" for s in diagnosis["skills"])
    assert diagnosis["status"] == "not_assessed"
    plan = authed_client.get(f"{LOOP}/plan", params=_body(session_id))
    assert plan.status_code == 200, plan.text
    assert [c["node_id"] for c in plan.json()["concepts"]] == [root]
    assert plan.json()["concepts"][0]["reason"] == "prerequisite"
    assert plan.json()["concepts"][0]["target_node_ids"] == [target]
    raw = _raw(db_conn, session_id)["loop_state"]
    assert set(raw["probe"]["scope"]) == {root, middle, target}
    assert set(raw["probe"]["scope"]).isdisjoint({unrelated, foreign, wrong_course})
    assert (
        db_conn.execute(
            "SELECT count(*) AS n FROM learner_state WHERE node_id = ANY(%s)",
            ([root, middle, target],),
        ).fetchone()["n"]
        == 0
    )  # Goals/plans cannot fabricate mastery evidence.


def test_foreign_authenticated_user_cannot_read_or_mutate_goal(
    authed_client, other_user_client, db_conn
):
    target = _node("Owned goal")
    session_id = _session()
    assert _goal(authed_client, session_id, target).status_code == 200
    before = _raw(db_conn, session_id)
    response = _goal(other_user_client, session_id, target, user=USER_SECOND)
    assert response.status_code == 404, response.text
    response = other_user_client.get(f"{LOOP}/plan", params=_body(session_id, user=USER_SECOND))
    assert response.status_code == 404, response.text
    assert _raw(db_conn, session_id) == before


def test_goal_edit_preserves_fatigue_and_invalidates_old_plan_approval(authed_client, db_conn):
    target = _node("Goal edit application")
    history = [
        {
            "node_id": "old-strand",
            "question_hash": "old-question",
            "difficulty": 2,
            "channel": "free_response",
            "correct": True,
            "idk": False,
            "p_after": 0.6,
        }
    ]
    session_id = _session(
        state={
            "phase": "plan",
            "probe": {
                "history": history,
                "presented": ["old-question"],
                "unavailable": ["old-unavailable"],
            },
            "plan": {"proposed": ["old-strand"]},
        }
    )
    first = _goal(authed_client, session_id, target, "First purpose")
    assert first.status_code == 200, first.text
    _finish_empty_bank(authed_client, session_id)
    first_plan = authed_client.get(f"{LOOP}/plan", params=_body(session_id)).json()
    assert [c["node_id"] for c in first_plan["concepts"]] == [target]
    second = _goal(authed_client, session_id, target, "A new purpose for the same concept")
    assert second.status_code == 200, second.text
    raw = _raw(db_conn, session_id)["loop_state"]
    assert raw["probe"]["history"] == history
    assert raw["probe"]["presented"] == ["old-question"]
    assert raw["probe"]["unavailable"] == ["old-unavailable"]
    assert "plan" not in raw and raw["phase"] == "probe"
    _finish_empty_bank(authed_client, session_id)
    second_plan = authed_client.get(f"{LOOP}/plan", params=_body(session_id)).json()
    assert first_plan["goal_version"] + 1 == second_plan["goal_version"]
    stale = authed_client.post(
        f"{LOOP}/plan/approve",
        json={
            **_body(session_id),
            "concept_ids": [target],
            "goal_version": first_plan["goal_version"],
        },
    )
    assert stale.status_code == 409, stale.text
    assert "Goal changed" in stale.json()["detail"]
    raw = _raw(db_conn, session_id)["loop_state"]
    assert raw["phase"] == "plan" and not raw["plan"].get("approved")
    assert raw["plan"]["goal_version"] == second_plan["goal_version"]


def test_concurrent_http_goal_edits_reapply_against_real_compare_and_set(monkeypatch, db_conn):
    from learning import loop_state_store as store

    target = _node("Concurrent goal application")
    session_id = _session()
    barrier = threading.Barrier(2)
    lock = threading.Lock()
    outcomes = []
    real_save = store.save_loop_state

    def synchronized_save(sid, state, *, expected_rev, **kwargs):
        if sid == session_id and expected_rev == 0:
            barrier.wait(timeout=15)  # Both real HTTP requests loaded revision 0.
        outcome = real_save(sid, state, expected_rev=expected_rev, **kwargs)
        with lock:
            outcomes.append((expected_rev, outcome))
        return outcome

    monkeypatch.setattr(store, "save_loop_state", synchronized_save)

    def edit(text):
        client = _client_for(USER_ACTIVE)
        try:
            response = _goal(client, session_id, target, text)
            assert response.status_code == 200, response.text
            return response.json()
        finally:
            client.close()

    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(edit, ["Concurrent purpose one", "Concurrent purpose two"]))
    assert sorted(r["goal_version"] for r in responses) == [1, 2]
    assert sum(outcome is store.SaveOutcome.CONFLICT for _, outcome in outcomes) == 1
    assert sum(outcome is store.SaveOutcome.SAVED for _, outcome in outcomes) == 2
    raw = _raw(db_conn, session_id)
    assert raw["loop_state_rev"] == 2 and raw["loop_state"]["goal_version"] == 2
    winner = next(r for r in responses if r["goal_version"] == 2)
    from learning.goals import public_goal

    assert public_goal(raw["loop_state"]) == winner["goal"]


def test_selected_goal_reads_more_than_1000_learner_states_without_prior_fallback(db_conn):
    from db.connection import table
    from learning.learner_state import read_states
    from routes.learn_loop import _plan_states

    ids = [str(uuid.uuid4()) for _ in range(1005)]
    for start in range(0, len(ids), 200):
        batch = ids[start : start + 200]
        table("graph_nodes").insert(
            [
                {
                    "id": n,
                    "user_id": USER_ACTIVE,
                    "course_id": COURSE_CS,
                    "concept_name": f"Large goal concept {n}",
                }
                for n in batch
            ]
        )
        table("learner_state").insert(
            [{"user_id": USER_ACTIVE, "node_id": n, "p_known": 0.97} for n in batch]
        )
    table("learner_state").insert({"user_id": USER_SECOND, "node_id": ids[0], "p_known": 0.1})
    stored = db_conn.execute(
        "SELECT node_id, p_known FROM learner_state WHERE user_id = %s AND node_id = ANY(%s)",
        (USER_ACTIVE, ids),
    ).fetchall()
    assert len(stored) == 1005
    states = read_states(USER_ACTIVE, ids)
    assert set(states) == {r["node_id"] for r in stored}
    assert all(states[r["node_id"]].p_known == r["p_known"] for r in stored)
    planned = _plan_states(USER_ACTIVE, COURSE_CS)
    assert all(planned[n] == 0.97 for n in ids)
    foreign_states = read_states(USER_SECOND, ids)
    assert set(foreign_states) == {ids[0]}
    assert foreign_states[ids[0]].p_known == 0.1
