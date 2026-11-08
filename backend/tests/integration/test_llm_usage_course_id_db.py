"""Spec §13 A137, real-DB half: `llm_usage.course_id` (migration
20261108163653_learning_llm_usage_course_id.sql) on the local stack.

- the column has the declared shape (text, nullable, no default), and the
  migration's SQL runs again, in a rolled-back transaction, unchanged;
- a session-less loop run's course round-trips through the app's own writer
  (events_service over PostgREST), read back via psycopg (#397), beside a row
  that names none and a session row.

Run inside the flock'd local-stack cycle with RUN_INTEGRATION=1."""

from __future__ import annotations

import os
import uuid
from pathlib import Path

import pytest

from tests.integration.conftest import _require_local_db_url

pytestmark = pytest.mark.integration

MIGRATION = next((Path(__file__).resolve().parents[2] / "db" / "migrations").glob(
    "*_learning_llm_usage_course_id.sql"
))


def _column(conn):
    return conn.execute(
        "SELECT data_type, is_nullable, column_default FROM information_schema.columns "
        "WHERE table_schema = 'public' AND table_name = 'llm_usage' AND column_name = 'course_id'"
    ).fetchone()


def test_the_column_has_the_declared_shape_and_the_migration_is_idempotent(db_conn):
    import psycopg
    from psycopg.rows import dict_row

    before = _column(db_conn)
    assert before == {"data_type": "text", "is_nullable": "YES", "column_default": None}
    url = (os.getenv("SUPABASE_DB_URL") or "").strip()
    _require_local_db_url(url)
    with psycopg.connect(url, row_factory=dict_row) as conn:
        try:
            conn.execute(MIGRATION.read_text(encoding="utf-8"))
            assert _column(conn) == before
        finally:
            conn.rollback()


def test_a_session_less_runs_course_round_trips_through_the_app_writer(db_conn):
    from services import events_service

    rid = f"it-req-{uuid.uuid4().hex[:10]}"
    usage = {"input_tokens": 10, "output_tokens": 5, "total_tokens": 15}
    events_service.log_llm_usage(  # drafting: no session, its course
        feature="check_items", task="check_items", model="claude-haiku-5-5", usage=usage,
        request_id=rid, course_id="rich-course-cs101",
    )
    events_service.log_llm_usage(  # a tutor turn: its session names the course
        feature="loop_tutor", task="loop_tutor", model="claude-haiku-5-5", usage=usage,
        user_id="rich-user-active", request_id=rid, session_id="it-session-1",
    )
    events_service.flush_now()
    rows = db_conn.execute(
        "SELECT task, session_id, course_id, cost_usd FROM llm_usage WHERE request_id = %s ORDER BY task",
        (rid,),
    ).fetchall()
    assert [(r["task"], r["session_id"], r["course_id"]) for r in rows] == [
        ("check_items", None, "rich-course-cs101"),
        ("loop_tutor", "it-session-1", None),
    ]
    assert all(r["cost_usd"] is not None for r in rows)  # priced as before
