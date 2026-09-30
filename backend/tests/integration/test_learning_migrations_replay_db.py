"""PKG-14 half A + B migrations against real Postgres (spec §13 A87, A89).

1. Replay from EMPTY. The B6 cycle boots the stack on dropped volumes
   (`supabase stop --no-backup` before `make e2e-up`), so e2e-up's
   `db.migrate` replays every migration from an empty database. On that stack:
   the ledger holds the three PKG-14 migrations in filename order, and the
   tables/columns have the declared shape. (A scratch `CREATE DATABASE` is not
   an honest "empty": 0011 writes `storage.buckets`, which only a Supabase
   database has.)
2. Idempotent: each PKG-14 migration's SQL runs again, in a transaction that
   is rolled back, without error and without changing the shape.
3. The running stack's `llm_usage.session_id` round-trips through the app's
   own writer (events_service over PostgREST), read back via psycopg.

Run inside the B6 flock'd cycle with RUN_INTEGRATION=1.
"""

from __future__ import annotations

import os
import uuid
from pathlib import Path

import pytest

from tests.integration.conftest import _require_local_db_url

pytestmark = pytest.mark.integration

MIG_DIR = Path(__file__).resolve().parents[2] / "db" / "migrations"
PKG14_MIGRATIONS = ("learning_loop_arm", "learning_posttest_poses", "learning_llm_usage_session_id")


def _file(suffix: str) -> Path:
    (path,) = sorted(MIG_DIR.glob(f"*_{suffix}.sql"))
    return path


def _column(conn, table: str, column: str):
    return conn.execute(
        "SELECT data_type, is_nullable, column_default FROM information_schema.columns "
        "WHERE table_schema = 'public' AND table_name = %s AND column_name = %s",
        (table, column),
    ).fetchone()


def test_the_pkg14_migrations_are_applied_in_filename_order(db_conn):
    names = [_file(s).name for s in PKG14_MIGRATIONS]
    assert names == sorted(names)
    rows = db_conn.execute(
        "SELECT filename FROM schema_migrations WHERE filename = ANY(%s) ORDER BY applied_at, filename",
        (names,),
    ).fetchall()
    assert [r["filename"] for r in rows] == names


def test_the_pkg14_schema_has_the_declared_shape(db_conn):
    assert _column(db_conn, "user_settings", "loop_arm")["data_type"] == "text"
    rls = db_conn.execute(
        "SELECT relrowsecurity FROM pg_class WHERE oid = 'public.posttest_poses'::regclass"
    ).fetchone()
    assert rls["relrowsecurity"] is True
    col = _column(db_conn, "llm_usage", "session_id")
    assert col is not None, "llm_usage.session_id missing — migration not applied"
    assert (col["data_type"], col["is_nullable"], col["column_default"]) == ("text", "YES", None)


@pytest.mark.parametrize("suffix", PKG14_MIGRATIONS)
def test_each_pkg14_migration_is_idempotent(db_conn, suffix):
    import psycopg
    from psycopg.rows import dict_row

    url = (os.getenv("SUPABASE_DB_URL") or "").strip()
    _require_local_db_url(url)
    before = _column(db_conn, "llm_usage", "session_id")
    with psycopg.connect(url, row_factory=dict_row) as conn:
        try:
            conn.execute(_file(suffix).read_text(encoding="utf-8"))
            assert _column(conn, "llm_usage", "session_id") == before
        finally:
            conn.rollback()


def test_llm_usage_session_id_round_trips_through_the_app_writer(db_conn):
    from services import events_service

    rid = f"it-req-{uuid.uuid4().hex[:10]}"
    usage = {"input_tokens": 10, "output_tokens": 5, "total_tokens": 15}
    events_service.log_llm_usage(
        feature="loop_tutor", task="loop_tutor", model="gemini-2.5-flash", usage=usage,
        user_id="rich-user-active", request_id=rid, session_id="it-session-1",
    )
    events_service.log_llm_usage(
        feature="check_items", task="check_items", model="gemini-2.5-flash-lite", usage=usage,
        request_id=rid,
    )
    events_service.flush_now()
    rows = db_conn.execute(
        "SELECT task, session_id FROM llm_usage WHERE request_id = %s ORDER BY task", (rid,)
    ).fetchall()
    assert [(r["task"], r["session_id"]) for r in rows] == [
        ("check_items", None),
        ("loop_tutor", "it-session-1"),
    ]
