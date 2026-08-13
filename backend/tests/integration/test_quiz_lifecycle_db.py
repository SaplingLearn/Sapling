"""#542 real-DB half: attempt lifecycle columns against local Supabase.

The mastery snapshot and abandonment sweep are pure DB behaviour — a
mocked table() would happily accept columns the migration never added
(the #265 schema/code-drift class). #397 seam: writes through the app
layer, raw reads via psycopg.
"""
from datetime import datetime, timedelta, timezone

import pytest

pytestmark = pytest.mark.integration

USER = "rich-user-active"


def _node_id(db_conn) -> str:
    row = db_conn.execute(
        "SELECT id FROM graph_nodes WHERE user_id = %s ORDER BY id LIMIT 1",
        (USER,),
    ).fetchone()
    assert row is not None
    return row["id"]


def test_lifecycle_columns_exist_and_round_trip(db_conn):
    """mastery_before/after/abandoned_at must be real columns the app can
    write — the exact drift a MagicMock suite cannot see."""
    import uuid

    from db.connection import table

    attempt_id = str(uuid.uuid4())
    table("quiz_attempts").insert({
        "id": attempt_id,
        "user_id": USER,
        "concept_node_id": _node_id(db_conn),
        "difficulty": "medium",
        "questions_json": [],
    })
    table("quiz_attempts").update(
        {"mastery_before": 0.25, "mastery_after": 0.34},
        filters={"id": f"eq.{attempt_id}"},
    )
    row = db_conn.execute(
        "SELECT mastery_before, mastery_after, abandoned_at "
        "FROM quiz_attempts WHERE id = %s",
        (attempt_id,),
    ).fetchone()
    assert row["mastery_before"] == pytest.approx(0.25)
    assert row["mastery_after"] == pytest.approx(0.34)
    assert row["abandoned_at"] is None


def test_sweep_marks_only_stale_unfinished_attempts(db_conn):
    """The conditional update must touch the stale in-progress row and
    leave the fresh one and the completed one alone."""
    import uuid

    from db.connection import table
    from routes.quiz import _sweep_abandoned
    from services.quiz_config import QUIZ_ATTEMPT_ABANDON_TTL_HOURS

    node_id = _node_id(db_conn)
    stale_id, fresh_id, done_id = (str(uuid.uuid4()) for _ in range(3))
    now = datetime.now(timezone.utc)
    long_ago = (now - timedelta(hours=QUIZ_ATTEMPT_ABANDON_TTL_HOURS + 2)).isoformat()

    for attempt_id, created_at, completed_at in (
        (stale_id, long_ago, None),
        (fresh_id, now.isoformat(), None),
        (done_id, long_ago, now.isoformat()),
    ):
        payload = {
            "id": attempt_id,
            "user_id": USER,
            "concept_node_id": node_id,
            "difficulty": "easy",
            "questions_json": [],
            "created_at": created_at,
        }
        if completed_at:
            payload["completed_at"] = completed_at
        table("quiz_attempts").insert(payload)

    _sweep_abandoned(USER)

    rows = {
        r["id"]: r
        for r in db_conn.execute(
            "SELECT id, abandoned_at FROM quiz_attempts WHERE id = ANY(%s)",
            ([stale_id, fresh_id, done_id],),
        ).fetchall()
    }
    assert rows[stale_id]["abandoned_at"] is not None, "stale in-progress attempt not swept"
    assert rows[fresh_id]["abandoned_at"] is None, "a fresh attempt must stay resumable"
    assert rows[done_id]["abandoned_at"] is None, "a completed attempt is never abandoned"
