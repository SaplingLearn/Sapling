"""#117: learning-loop sessions pending in `tutor_pending_sessions`, through
the real routes and PostgREST, asserted with direct SQL.

Flag `stateless_tutor_sessions` on. Between requests `_other_worker()` wipes
every module-level map the loop and its pending store keep, standing in for
"the next request landed on another worker": nothing a later request needs may
survive only there. No model runs (the probe opener is a template, A121).
"""
from __future__ import annotations

import pytest

from tests.integration.conftest import COURSE_CS, USER_ACTIVE, USER_SECOND, _client_for
import services.loop.history

pytestmark = pytest.mark.integration

LOOP = "/api/learn/loop"


def _other_worker() -> None:
    from routes import learn_loop
    from services import tutor_sessions as ts

    for live in (ts.PENDING_SESSIONS, ts._DISCARDED, services.loop.history._BRIEF_FAILED, learn_loop._DUE_CACHE):
        live.clear()


@pytest.fixture(autouse=True)
def _loop_on_and_stateless(monkeypatch):
    import config

    monkeypatch.setattr(config, "LEARNING_LOOP_ENABLED", True)
    monkeypatch.setenv("SAPLING_FLAG_STATELESS_TUTOR_SESSIONS", "on")
    _other_worker()
    yield
    _other_worker()


def _start(client) -> tuple[str, str]:
    r = client.post(
        f"{LOOP}/start-session",
        json={"user_id": USER_ACTIVE, "topic": "Recursion", "course_id": COURSE_CS},
    )
    assert r.status_code == 200, r.text
    return r.json()["session_id"], r.json()["initial_message"]


def _pending_row(db_conn, sid):
    return db_conn.execute(
        "SELECT state, loop_state, assistant_reply, offering_id FROM tutor_pending_sessions "
        "WHERE session_id = %s",
        (sid,),
    ).fetchone()


def _count(db_conn, table, column, sid) -> int:
    return db_conn.execute(
        f"SELECT count(*) AS n FROM {table} WHERE {column} = %s", (sid,)
    ).fetchone()["n"]


def test_a_loop_session_started_on_one_worker_is_answered_on_another(authed_client, db_conn):
    from services import tutor_sessions as ts
    from services.encryption import decrypt_if_present

    sid, greeting = _start(authed_client)
    assert ts.PENDING_SESSIONS == {}, "flag on: nothing pending in this worker's memory"
    row = _pending_row(db_conn, sid)
    assert row["state"] == "pending" and row["loop_state"] == {}, "a loop session, empty document"
    assert row["assistant_reply"] != greeting and decrypt_if_present(row["assistant_reply"]) == greeting
    assert _count(db_conn, "sessions", "id", sid) == 0, "still lazy"

    _other_worker()
    status = authed_client.get(f"{LOOP}/status", params={"user_id": USER_ACTIVE, "session_id": sid})
    assert status.status_code == 200, status.text
    other = _client_for(USER_SECOND).get(
        f"{LOOP}/status", params={"user_id": USER_SECOND, "session_id": sid}
    )
    assert other.status_code == 404
    assert _count(db_conn, "sessions", "id", sid) == 0, "a read never materialises"

    _other_worker()
    r = authed_client.post(f"{LOOP}/probe/next", json={"session_id": sid, "user_id": USER_ACTIVE})
    assert r.status_code == 200, r.text
    s = db_conn.execute(
        "SELECT user_id, offering_id, ended_at FROM sessions WHERE id = %s", (sid,)
    ).fetchone()
    assert (s["user_id"], s["offering_id"], s["ended_at"]) == (USER_ACTIVE, row["offering_id"], None)
    msgs = db_conn.execute(
        "SELECT role, content FROM messages WHERE session_id = %s ORDER BY created_at", (sid,)
    ).fetchall()
    assert [(m["role"], decrypt_if_present(m["content"])) for m in msgs] == [("assistant", greeting)]
    assert _pending_row(db_conn, sid) is None, "materialised: the pending row is gone"

    _other_worker()
    from services.tutor.pending import _consume_pending

    assert _consume_pending(sid, USER_ACTIVE) is False, "live: nothing left to materialise"
    again = authed_client.get(f"{LOOP}/status", params={"user_id": USER_ACTIVE, "session_id": sid})
    assert again.status_code == 200, again.text
    assert _count(db_conn, "messages", "session_id", sid) == 1, "materialised once"


def test_a_stored_loop_document_reaches_the_row_through_postgrest(db_conn):
    """The app's own stash and materialise calls, by argument name over
    PostgREST, carry a quiz-ask session's document (spec §13 A99) to the row."""
    import uuid

    from routes.learn_loop import quiz_ask_state
    from services import tutor_sessions as ts
    from services.tutor.pending import _consume_pending

    sid = str(uuid.uuid4())
    doc = {**quiz_ask_state("node-1"), "open_question": True}
    ts.stash_pending(sid, {
        "user_id": USER_ACTIVE, "mode": "socratic", "topic": "Recursion", "course_id": COURSE_CS,
        "offering_id": "rich-off-cs101-f25", "use_shared_context": True,
        "assistant_reply": "Key idea: the base case.", "graph_update": {}, "loop": True,
        "loop_state": doc,
    })
    assert _pending_row(db_conn, sid)["loop_state"] == doc
    _other_worker()
    assert ts.get_pending(sid)["loop_state"] == doc
    assert _consume_pending(sid, USER_ACTIVE) is True
    row = db_conn.execute("SELECT loop_state FROM sessions WHERE id = %s", (sid,)).fetchone()
    assert row["loop_state"] == doc


def test_a_never_answered_loop_session_closes_on_another_worker(authed_client, db_conn):
    sid, _ = _start(authed_client)
    _other_worker()
    foreign = _client_for(USER_SECOND).post(
        f"{LOOP}/close", json={"session_id": sid, "user_id": USER_SECOND}
    )
    assert foreign.status_code == 404
    assert _pending_row(db_conn, sid)["state"] == "pending", "left intact"
    r = authed_client.post(f"{LOOP}/close", json={"session_id": sid, "user_id": USER_ACTIVE})
    assert r.status_code == 200, r.text
    assert r.json()["close_phase"] == "close"
    assert _pending_row(db_conn, sid) is None, "claimed"
    s = db_conn.execute(
        "SELECT close_json IS NOT NULL AS closed, loop_state->>'phase' AS phase FROM sessions "
        "WHERE id = %s",
        (sid,),
    ).fetchone()
    assert (s["closed"], s["phase"]) == (True, "close")
    assert _count(db_conn, "messages", "session_id", sid) == 0, "a closed lazy session has no greeting row"


def test_a_loop_session_ended_on_one_worker_answers_409_on_another(authed_client, db_conn):
    sid, _ = _start(authed_client)
    _other_worker()
    r = authed_client.post("/api/learn/end-session", json={"session_id": sid, "user_id": USER_ACTIVE})
    assert r.status_code == 200, r.text
    assert _pending_row(db_conn, sid)["state"] == "ended"
    _other_worker()
    r = authed_client.post(f"{LOOP}/probe/next", json={"session_id": sid, "user_id": USER_ACTIVE})
    assert r.status_code == 409, r.text
    assert _count(db_conn, "sessions", "id", sid) == 0
