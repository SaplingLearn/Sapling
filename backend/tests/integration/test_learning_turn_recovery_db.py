"""Real PostgREST timing writes, independent SQL reads and a cold Python worker."""

import json
import subprocess
import sys

import pytest

from tests.integration.conftest import USER_ACTIVE
from tests.integration.test_learning_goals_db import _session

pytestmark = pytest.mark.integration


def test_interrupted_tutor_timing_survives_a_cold_worker(authed_client, db_conn, monkeypatch):
    import config
    from learning import turn_activity
    from routes import learn_loop
    from services.agent_events import SaplingEvent

    monkeypatch.setattr(config, "LEARNING_LOOP_ENABLED", True)
    session = _session(state={"phase": "teach", "served_at": 1})
    monkeypatch.setattr(learn_loop, "_context_blocks", lambda **kwargs: [])

    async def interrupted(**kwargs):
        row = db_conn.execute("SELECT loop_state FROM sessions WHERE id=%s", (session,)).fetchone()
        assert row["loop_state"][turn_activity.KEY]["state"] == "pending"
        yield SaplingEvent(type="error", step="reply", message="Synthetic provider interruption", data={"retryable": True})

    monkeypatch.setattr(learn_loop, "stream_structured_turn", interrupted)
    response = authed_client.post("/api/learn/loop/chat/stream", json={"user_id": USER_ACTIVE, "session_id": session, "message": "Explain this concept"})
    assert response.status_code == 200 and '"error"' in response.text and '"done"' not in response.text
    row = db_conn.execute("SELECT loop_state FROM sessions WHERE id=%s", (session,)).fetchone()
    activity = row["loop_state"][turn_activity.KEY]
    assert activity["state"] == "interrupted" and activity["at"] > 1
    assert row["loop_state"]["served_at"] == 1
    learn_loop._FAILED_TURN_ANCHORS.clear()
    # A separately imported process has no route cache and does its own real
    # adapter read. Only prose-free operational metadata is printed by it.
    code = "from learning.loop_state_store import load_loop_state; import json,sys; print(json.dumps(load_loop_state(sys.argv[1]).state.to_json()['turn_activity']))"
    cold = subprocess.run([sys.executable, "-c", code, session], capture_output=True, text=True, check=True, timeout=30)
    assert json.loads(cold.stdout.strip().splitlines()[-1]) == activity
    assert db_conn.execute("SELECT count(*) AS n FROM messages WHERE session_id=%s", (session,)).fetchone()["n"] == 0
    assert db_conn.execute("SELECT count(*) AS n FROM node_mastery_events WHERE session_id=%s", (session,)).fetchone()["n"] == 0


def test_new_worker_operation_fences_an_old_completion_in_the_real_cas(db_conn):
    from learning import turn_activity
    from learning.loop_state_store import update_loop_state

    session = _session(state={"phase": "teach"})

    def change(action, identity, at):
        def mutate(state):
            doc = state.to_json()
            action(doc, identity, at)
            return type(state).from_json(doc)
        return update_loop_state(session, mutate, require_open=True)

    change(turn_activity.begin, "first-worker", 100)
    change(turn_activity.begin, "second-worker", 101)
    before = db_conn.execute("SELECT loop_state,loop_state_rev FROM sessions WHERE id=%s", (session,)).fetchone()
    with pytest.raises(turn_activity.StaleTurnActivity):
        change(turn_activity.complete, "first-worker", 102)
    after = db_conn.execute("SELECT loop_state,loop_state_rev FROM sessions WHERE id=%s", (session,)).fetchone()
    assert after == before
    change(turn_activity.interrupt, "first-worker", 103)
    current = db_conn.execute("SELECT loop_state FROM sessions WHERE id=%s", (session,)).fetchone()["loop_state"]
    assert current[turn_activity.KEY] == before["loop_state"][turn_activity.KEY]
    change(turn_activity.complete, "second-worker", 104)
    current = db_conn.execute("SELECT loop_state FROM sessions WHERE id=%s", (session,)).fetchone()["loop_state"]
    assert current[turn_activity.KEY]["state"] == "complete"
