"""Saved grades recover through real PostgREST/RPC/CAS in a cold worker.

The integration conftest owns the isolated local database. Test assets are
explicitly synthetic and inserted before activity; actual IDK grading needs no
provider. Fault hooks interrupt a boundary, never fabricate a DB acknowledgment.
Independent SQL reads check journal/scalar/receipt/session state.
"""

from __future__ import annotations

from copy import deepcopy
import json
import subprocess
import sys
import textwrap
import uuid
from unittest.mock import AsyncMock

from fastapi import HTTPException
import pytest

from tests.integration.conftest import COURSE_CS, USER_ACTIVE
from tests.integration.test_learning_goals_db import LOOP, _body, _goal, _node, _session

pytestmark = pytest.mark.integration


@pytest.fixture(autouse=True)
def _active_loop(monkeypatch):
    import config

    monkeypatch.setattr(config, "LEARNING_LOOP_ENABLED", True)


def _scenario(client):
    """Create assets, confirm an actual goal, then obtain an actual probe pose."""
    from db.connection import table
    from learning.checks import question_hash
    from services.check_item_service import concept_key
    from services.encryption import encrypt_if_present, encrypt_json

    name = f"Synthetic checkpoint integration {uuid.uuid4().hex}"
    node = _node(name)
    # Keep multiple fresh items besides the posttest and practice reserves.
    for variant in range(6):
        prompt = f"Synthetic checkpoint fixture {variant}: identify the stable response."
        table("check_items").insert({
            "id": str(uuid.uuid4()), "course_id": COURSE_CS,
            "concept_key": concept_key(name), "format": "free", "difficulty": 1,
            "prompt": encrypt_if_present(prompt), "question_hash": question_hash(prompt),
            "reference_answer": encrypt_if_present("The synthetic fixture response is stable."),
            "final_answer": encrypt_if_present("stable"),
            "rubric_json": encrypt_json([
                {"id": "r1", "text": "Identify the synthetic response"},
                {"id": "r2", "text": "Explain the synthetic fixture"},
            ]),
            "common_wrong_json": encrypt_json([
                {"key": "fixture", "text": "A synthetic mismatch"},
            ]),
        })
    session = _session()
    confirmed = _goal(client, session, node, "Recover my explicitly confirmed synthetic goal")
    assert confirmed.status_code == 200, confirmed.text
    posed = client.post(f"{LOOP}/probe/next", json=_body(session))
    assert posed.status_code == 200, posed.text
    assert posed.json().get("done") is False and posed.json()["node_id"] == node
    body = {**_body(session), "question_hash": posed.json()["question_hash"], "idk": True}
    return node, session, body


def _session_row(db_conn, session):
    return db_conn.execute(
        "SELECT loop_state,loop_state_rev,ended_at,close_json FROM sessions WHERE id=%s",
        (session,),
    ).fetchone()


def _learning_rows(db_conn, node):
    return {
        "state": db_conn.execute(
            "SELECT * FROM learner_state WHERE user_id=%s AND node_id=%s", (USER_ACTIVE, node)
        ).fetchone(),
        "mirror": db_conn.execute(
            "SELECT mastery_score,times_studied,evidence_version FROM graph_nodes WHERE id=%s",
            (node,),
        ).fetchone(),
        "events": db_conn.execute(
            "SELECT * FROM node_mastery_events WHERE node_id=%s ORDER BY created_at,evidence_seq,id",
            (node,),
        ).fetchall(),
    }


def _hold_grade(monkeypatch, *, after_commit):
    """Leave the real encrypted checkpoint at either side of Evidence commit."""
    from learning.evidence import PlanningPersistenceUnavailable
    from routes import learn_loop

    grade = AsyncMock(wraps=learn_loop.grade_answer)
    monkeypatch.setattr(learn_loop, "grade_answer", grade)
    if after_commit:
        real_update = learn_loop._update_loop_state

        def stop_before_session_finalization(session, mutate, **kwargs):
            if mutate.__name__ == "record_posed":
                raise HTTPException(status_code=409, detail="Synthetic crash before final CAS")
            return real_update(session, mutate, **kwargs)

        monkeypatch.setattr(learn_loop, "_update_loop_state", stop_before_session_finalization)
    else:
        def stop_before_evidence(*args, **kwargs):
            raise PlanningPersistenceUnavailable("Synthetic interruption before Evidence commit")

        monkeypatch.setattr(learn_loop, "flush_pending", stop_before_evidence)
    return grade


def _cold_answer(body):
    """Fresh process/import/client with no route caches and no possible grader."""
    code = textwrap.dedent("""
        import json, sys
        import config
        config.LEARNING_LOOP_ENABLED = True
        from fastapi.testclient import TestClient
        from main import app
        from routes import learn_loop
        from services.session_tokens import mint_session
        calls = []
        async def forbidden(*args, **kwargs):
            calls.append(1)
            raise AssertionError('Saved grade recovery must never invoke the grader')
        learn_loop.grade_answer = forbidden
        body = json.loads(sys.argv[1])
        # A changed retry body cannot replace the frozen original IDK grade.
        body.update(idk=False, answer='Different retry text must never be graded')
        client = TestClient(app)
        client.cookies.set('sapling_session', mint_session(body['user_id']))
        response = client.post('/api/learn/loop/probe/answer', json=body)
        value = response.json()
        print('RECOVERY_METADATA=' + json.dumps({
            'status': response.status_code, 'graded': value.get('graded'),
            'correct': value.get('correct'), 'p_known': value.get('p_known'),
            'grader_calls': len(calls),
        }))
    """)
    result = subprocess.run(
        [sys.executable, "-c", code, json.dumps(body)],
        capture_output=True, text=True, check=True, timeout=30,
    )
    lines = [line for line in result.stdout.splitlines() if line.startswith("RECOVERY_METADATA=")]
    assert len(lines) == 1
    return json.loads(lines[0].removeprefix("RECOVERY_METADATA="))


@pytest.mark.parametrize("after_commit", [False, True], ids=["saved-before-evidence", "committed-before-session-cas"])
def test_probe_saved_grade_recovers_in_a_cold_worker_without_regrading(
    authed_client, db_conn, monkeypatch, after_commit
):
    from learning import bkt, grade_checkpoint
    from learning.params import BKT_L0

    node, session, body = _scenario(authed_client)
    original_goal = deepcopy(_session_row(db_conn, session)["loop_state"]["goal"])
    grade = _hold_grade(monkeypatch, after_commit=after_commit)
    failed = authed_client.post(f"{LOOP}/probe/answer", json=body)
    assert failed.status_code == (409 if after_commit else 503)
    grade.assert_awaited_once()
    held = _session_row(db_conn, session)
    current = held["loop_state"]["probe"]["current"]
    operation = current["grading_claim"]
    assert isinstance(current[grade_checkpoint.KEY], str)
    assert held["loop_state"]["probe"]["history"] == []
    assert held["ended_at"] is None and held["close_json"] is None
    before = _learning_rows(db_conn, node)
    assert len(before["events"]) == int(after_commit)
    assert (before["state"] is not None) is after_commit
    assert db_conn.execute(
        "SELECT count(*) n FROM learning_evidence_operations WHERE operation_id=%s", (operation,)
    ).fetchone()["n"] == int(after_commit)

    recovered = _cold_answer(body)
    assert recovered["status"] == 200 and recovered["graded"] is True
    assert recovered["correct"] is False and recovered["grader_calls"] == 0
    after = _learning_rows(db_conn, node)
    expected = bkt.update(BKT_L0, "free_response", False, idk=True)
    assert after["state"]["p_known"] == pytest.approx(expected)
    assert recovered["p_known"] == pytest.approx(expected)
    assert after["state"]["opps"] == after["mirror"]["times_studied"] == 1
    assert len(after["events"]) == 1 and after["events"][0]["correct"] is False
    assert after["events"][0]["planning_observation"]["idk"] is True
    if after_commit:
        assert after == before, "Recovery must not rewrite the already committed learning result"
    final = _session_row(db_conn, session)
    probe = final["loop_state"]["probe"]
    assert probe["current"] is None and len(probe["history"]) == 1
    assert probe["history"][0]["grade_operation_id"] == operation
    assert probe["history"][0]["idk"] is True and probe["history"][0]["correct"] is False
    assert final["loop_state"]["goal"] == original_goal and final["loop_state"]["goal_version"] == 1
    assert final["ended_at"] is None and final["close_json"] is None
    duplicate = _cold_answer(body)
    assert duplicate["status"] == 409 and duplicate["grader_calls"] == 0
    assert _learning_rows(db_conn, node) == after
    assert _session_row(db_conn, session) == final
    assert db_conn.execute(
        "SELECT count(*) n FROM learning_evidence_operations WHERE operation_id=%s", (operation,)
    ).fetchone()["n"] == 1


def test_legacy_end_cannot_strand_an_encrypted_uncommitted_grade(
    authed_client, db_conn, monkeypatch
):
    from learning.grade_checkpoint import KEY

    node, session, body = _scenario(authed_client)
    _hold_grade(monkeypatch, after_commit=False)
    failed = authed_client.post(f"{LOOP}/probe/answer", json=body)
    assert failed.status_code == 503
    before = _session_row(db_conn, session)
    assert KEY in before["loop_state"]["probe"]["current"]
    ended = authed_client.post("/api/learn/end-session", json=_body(session))
    assert ended.status_code == 409, ended.text
    assert _session_row(db_conn, session) == before
    assert _learning_rows(db_conn, node)["events"] == []
    recovered = _cold_answer(body)
    assert recovered["status"] == 200 and recovered["grader_calls"] == 0
    assert len(_learning_rows(db_conn, node)["events"]) == 1
