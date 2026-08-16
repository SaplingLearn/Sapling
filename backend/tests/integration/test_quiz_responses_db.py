"""#541 C2 real-DB half: quiz_responses storage against local Supabase.

Proves the migration's shape actually holds in Postgres — the UNIQUE
arbitrates duplicate answers, the FK cascades with the attempt — the
exact class of constraint behavior MagicMock suites cannot see (#529's
lesson). #397 seam: writes through the app layer, raw reads via psycopg.
"""
import uuid

import pytest

pytestmark = pytest.mark.integration

USER = "rich-user-active"


def _make_attempt(db_conn) -> str:
    from db.connection import table

    node = db_conn.execute(
        "SELECT id FROM graph_nodes WHERE user_id = %s ORDER BY id LIMIT 1",
        (USER,),
    ).fetchone()
    assert node is not None
    attempt_id = str(uuid.uuid4())
    table("quiz_attempts").insert({
        "id": attempt_id,
        "user_id": USER,
        "concept_node_id": node["id"],
        "difficulty": "adaptive",  # also exercises the #540 CHECK widening
        "questions_json": [],
    })
    return attempt_id


def test_unique_arbitrates_duplicate_answers(db_conn):
    from db.connection import table

    attempt_id = _make_attempt(db_conn)
    table("quiz_responses").insert({
        "attempt_id": attempt_id, "question_index": 0,
        "selected_index": 1, "is_correct": True, "time_ms": 1200,
    })
    with pytest.raises(Exception):
        table("quiz_responses").insert({
            "attempt_id": attempt_id, "question_index": 0,
            "selected_index": 0, "is_correct": False,
        })

    rows = db_conn.execute(
        "SELECT selected_index, is_correct, time_ms FROM quiz_responses "
        "WHERE attempt_id = %s",
        (attempt_id,),
    ).fetchall()
    assert len(rows) == 1
    assert rows[0]["selected_index"] == 1     # the first write won
    assert rows[0]["is_correct"] is True
    assert rows[0]["time_ms"] == 1200


def test_responses_cascade_with_their_attempt(db_conn):
    from db.connection import table

    attempt_id = _make_attempt(db_conn)
    table("quiz_responses").insert({
        "attempt_id": attempt_id, "question_index": 0,
        "selected_index": 0, "is_correct": False,
    })
    db_conn.execute("DELETE FROM quiz_attempts WHERE id = %s", (attempt_id,))
    left = db_conn.execute(
        "SELECT count(*) AS n FROM quiz_responses WHERE attempt_id = %s",
        (attempt_id,),
    ).fetchone()
    assert left["n"] == 0
