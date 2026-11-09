"""#828: 20261109023732_study_guides_unique_key.sql against real Postgres.

The migration only defines `ensure_study_guides_unique_key()` (a by-hand
release step); applying it builds nothing. The function creates the
(user_id, offering_id, exam_id) unique index on a table with no duplicate
keys ('created'), is a no-op once it exists ('exists'), and otherwise skips
WITHOUT touching a row ('skipped: N duplicate keys'). Every case runs inside a
transaction that is always rolled back, so the local stack keeps its state.
"""
import psycopg
import pytest

pytestmark = pytest.mark.integration

_INDEX = "study_guides_user_offering_exam_key"
_FN = "SELECT public.ensure_study_guides_unique_key() AS r"


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


def _snapshot(conn):
    return conn.execute("SELECT id, user_id, offering_id, exam_id, content, generated_at "
                        "FROM public.study_guides ORDER BY id").fetchall()


def _seed(conn, *, duplicate: bool):
    """No index, no other duplicates, then 1 or 2 rows for one key."""
    user_id, offering_id = _key(conn)
    conn.execute(f"DROP INDEX IF EXISTS public.{_INDEX}")
    conn.execute("DELETE FROM public.study_guides WHERE exam_id LIKE 'w3t-%'")
    for i in range(2 if duplicate else 1):
        conn.execute(
            "INSERT INTO public.study_guides (id, user_id, offering_id, exam_id, content) "
            "VALUES (%s, %s, %s, 'w3t-exam', '{}'::jsonb)", (f"w3t-g{i}", user_id, offering_id))
    return user_id, offering_id


def test_applying_the_migration_builds_nothing(db_conn):
    # The function exists and is service_role-only; the migration never calls it.
    assert db_conn.execute(
        "SELECT to_regprocedure('public.ensure_study_guides_unique_key()') IS NOT NULL AS ok"
    ).fetchone()["ok"]
    for role in ("anon", "authenticated"):
        assert not db_conn.execute(
            "SELECT has_function_privilege(%s, 'public.ensure_study_guides_unique_key()', "
            "'EXECUTE') AS ok", (role,)).fetchone()["ok"]


def test_duplicates_skip_the_index_and_keep_every_row(db_conn):
    with pytest.raises(_Rollback):
        with db_conn.transaction():
            _seed(db_conn, duplicate=True)
            before = _snapshot(db_conn)
            assert db_conn.execute(_FN).fetchone()["r"] == "skipped: 1 duplicate keys"
            assert _index_exists(db_conn) is False
            assert _snapshot(db_conn) == before  # nothing deleted or changed
            raise _Rollback


def test_a_clean_table_gets_the_unique_index_then_exists(db_conn):
    with pytest.raises(_Rollback):
        with db_conn.transaction():
            user_id, offering_id = _seed(db_conn, duplicate=False)
            before = _snapshot(db_conn)
            assert db_conn.execute(_FN).fetchone()["r"] == "created"
            assert _index_exists(db_conn) is True
            assert _snapshot(db_conn) == before
            with pytest.raises(psycopg.errors.UniqueViolation):
                with db_conn.transaction():
                    db_conn.execute(
                        "INSERT INTO public.study_guides (user_id, offering_id, exam_id, content) "
                        "VALUES (%s, %s, 'w3t-exam', '{}'::jsonb)", (user_id, offering_id))
            assert db_conn.execute(_FN).fetchone()["r"] == "exists"  # idempotent
            raise _Rollback
