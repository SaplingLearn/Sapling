"""#828: 20261109023732_study_guides_unique_key.sql against real Postgres.

The migration creates the (user_id, offering_id, exam_id) unique index only on
a table with no duplicate keys, and otherwise skips WITHOUT touching a row.
Both branches are replayed here inside a transaction that is always rolled
back, so the local stack keeps whatever state its own migration run left.
"""
from pathlib import Path

import psycopg
import pytest

pytestmark = pytest.mark.integration

_MIGRATION = (Path(__file__).resolve().parents[2] / "db" / "migrations"
              / "20261109023732_study_guides_unique_key.sql")
_INDEX = "study_guides_user_offering_exam_key"


class _Rollback(Exception):
    pass


def _key(conn):
    row = conn.execute(
        "SELECT u.id AS user_id, o.id AS offering_id FROM public.users u, "
        "public.course_offerings o ORDER BY u.id, o.id LIMIT 1").fetchone()
    if row is None:
        pytest.skip("no user/offering on this stack")
    return row["user_id"], row["offering_id"]


def _index_exists(conn) -> bool:
    return conn.execute("SELECT to_regclass(%s) IS NOT NULL AS ok",
                        (f"public.{_INDEX}",)).fetchone()["ok"]


def _replay(conn, *, duplicate: bool):
    user_id, offering_id = _key(conn)
    conn.execute(f"DROP INDEX IF EXISTS public.{_INDEX}")
    conn.execute("DELETE FROM public.study_guides WHERE exam_id LIKE 'w3t-%'")
    rows = 2 if duplicate else 1
    for i in range(rows):
        conn.execute(
            "INSERT INTO public.study_guides (id, user_id, offering_id, exam_id, content) "
            "VALUES (%s, %s, %s, 'w3t-exam', '{}'::jsonb)", (f"w3t-g{i}", user_id, offering_id))
    notices: list[str] = []

    def handler(diag):
        notices.append(diag.message_primary or "")

    conn.add_notice_handler(handler)  # the session-scoped conn outlives this test
    try:
        conn.execute(_MIGRATION.read_text())
    finally:
        conn.remove_notice_handler(handler)
    kept = conn.execute("SELECT count(*) AS n FROM public.study_guides "
                        "WHERE exam_id = 'w3t-exam'").fetchone()["n"]
    return _index_exists(conn), kept, notices, (user_id, offering_id)


def test_duplicates_skip_the_index_and_keep_every_row(db_conn):
    with pytest.raises(_Rollback):
        with db_conn.transaction():
            exists, kept, notices, _ = _replay(db_conn, duplicate=True)
            assert exists is False
            assert kept == 2  # nothing deleted
            assert any("NOT creating" in n for n in notices)
            raise _Rollback


def test_a_clean_table_gets_the_unique_index(db_conn):
    with pytest.raises(_Rollback):
        with db_conn.transaction():
            exists, kept, _notices, (user_id, offering_id) = _replay(db_conn, duplicate=False)
            assert exists is True and kept == 1
            with pytest.raises(psycopg.errors.UniqueViolation):
                with db_conn.transaction():
                    db_conn.execute(
                        "INSERT INTO public.study_guides (user_id, offering_id, exam_id, content) "
                        "VALUES (%s, %s, 'w3t-exam', '{}'::jsonb)", (user_id, offering_id))
            # Idempotent: a second run is a no-op.
            db_conn.execute(_MIGRATION.read_text())
            raise _Rollback
