"""#116: the `gradescope_syncs` staging table (20261108214227_gradescope_syncs.sql)
against real Postgres.

SQL only (no app imports): the hermetic suite (tests/test_gradescope_sync_jobs.py)
pins what services/gradescope_jobs.py sends; this pins what the table does with
it — one ACTIVE (queued/running) sync per (user, enrollment), the stage /
error_code CHECKs, the compare-and-swap the request and the worker race on
(exactly one of `queued -> inline` and `queued -> running` wins), the cascades,
and that only the service role can touch it. Every test runs in one rolled-back
transaction over its own `w6c-*` rows.
"""
import psycopg
import pytest

pytestmark = pytest.mark.integration

U, V = "w6c-user-a", "w6c-user-b"

_SEED = [
    "INSERT INTO schools (id, name, slug) VALUES ('w6c-school', 'w6c', 'w6c-school')",
    "INSERT INTO courses (id, school_id, course_code, course_name) "
    "VALUES ('w6c-course', 'w6c-school', 'W6C101', 'w6c')",
    "INSERT INTO terms (id, term, year, label, start_date, end_date, sort_key) "
    "VALUES ('w6c-term', 'Fall', 2097, 'w6c Fall 2097', '2097-09-01', '2097-12-20', 2097997)",
    "INSERT INTO course_offerings (id, course_id, term_id, section) "
    "VALUES ('w6c-off', 'w6c-course', 'w6c-term', 'w6c')",
    f"INSERT INTO users (id, email) VALUES ('{U}', 'w6c-a@example.com'), "
    f"('{V}', 'w6c-b@example.com')",
    f"INSERT INTO enrollments (id, user_id, offering_id) VALUES "
    f"('w6c-enr-a', '{U}', 'w6c-off'), ('w6c-enr-b', '{V}', 'w6c-off')",
]


@pytest.fixture
def conn(db_conn):
    with db_conn.transaction() as tx:
        for stmt in _SEED:
            db_conn.execute(stmt)
        yield db_conn
        raise psycopg.Rollback(tx)


def _stage(conn, user=U, enrollment="w6c-enr-a", **cols) -> str:
    data = {"user_id": user, "enrollment_id": enrollment, "link_id": "w6c-link",
            "gradescope_course_id": "123456", **cols}
    names = ", ".join(data)
    marks = ", ".join(["%s"] * len(data))
    return conn.execute(
        f"INSERT INTO public.gradescope_syncs ({names}) VALUES ({marks}) RETURNING id",
        list(data.values()),
    ).fetchone()["id"]


def _sqlstate(conn, sql, params=None) -> str | None:
    try:
        with conn.transaction():
            conn.execute(sql, params)
    except psycopg.Error as e:
        return e.sqlstate
    return None


def _swap(conn, sync_id, frm, to) -> int:
    """The services/gradescope_jobs.py stage swap: PATCH ... WHERE stage = frm."""
    return conn.execute(
        "UPDATE public.gradescope_syncs SET stage = %s WHERE id = %s AND stage = %s",
        (to, sync_id, frm),
    ).rowcount


def test_defaults_queued_with_no_outcome(conn):
    sid = _stage(conn)
    row = conn.execute("SELECT * FROM public.gradescope_syncs WHERE id = %s", (sid,)).fetchone()
    assert row["stage"] == "queued"
    assert row["error_code"] is None and row["counts"] is None and row["job_id"] is None


def test_one_active_sync_per_user_and_enrollment(conn):
    sid = _stage(conn)
    insert = ("INSERT INTO public.gradescope_syncs (user_id, enrollment_id, gradescope_course_id) "
              "VALUES (%s, %s, '1')")
    assert _sqlstate(conn, insert, (U, "w6c-enr-a")) == "23505"
    _swap(conn, sid, "queued", "running")
    assert _sqlstate(conn, insert, (U, "w6c-enr-a")) == "23505"   # running is active too
    _stage(conn, user=V, enrollment="w6c-enr-b")                      # another student
    for terminal in ("done", "failed", "inline"):
        conn.execute("UPDATE public.gradescope_syncs SET stage = %s "
                     "WHERE user_id = %s AND stage IN ('queued', 'running')", (terminal, U))
        _stage(conn)  # a finished sync never blocks the next one


@pytest.mark.parametrize("bad", ["bogus", "QUEUED", "", "extracting"])
def test_unknown_stages_are_refused(conn, bad):
    sid = _stage(conn)
    assert _sqlstate(conn, "UPDATE public.gradescope_syncs SET stage = %s WHERE id = %s",
                     (bad, sid)) == "23514"


@pytest.mark.parametrize("bad", ["Has Spaces", "a" * 41, "GradescopeAuthError: expired"])
def test_error_codes_must_be_fixed_codes_not_messages(conn, bad):
    sid = _stage(conn)
    assert _sqlstate(conn, "UPDATE public.gradescope_syncs SET error_code = %s WHERE id = %s",
                     (bad, sid)) == "23514"


def test_exactly_one_of_take_back_and_worker_start_wins(conn):
    sid = _stage(conn)
    assert _swap(conn, sid, "queued", "running") == 1   # the worker
    assert _swap(conn, sid, "queued", "inline") == 0    # the request, too late
    conn.execute("UPDATE public.gradescope_syncs SET stage = 'done' WHERE id = %s", (sid,))
    other = _stage(conn)
    assert _swap(conn, other, "queued", "inline") == 1  # the request first
    assert _swap(conn, other, "queued", "running") == 0  # the job is now a no-op


def test_deleting_the_enrollment_removes_its_syncs_only(conn):
    # The admin wipe deletes enrollments and relies on this cascade
    # (services/account_wipe.py::WIPED_BY_CASCADE).
    _stage(conn)
    _stage(conn, user=V, enrollment="w6c-enr-b")
    conn.execute("DELETE FROM public.enrollments WHERE id = 'w6c-enr-b'")
    left = conn.execute("SELECT user_id FROM public.gradescope_syncs "
                        "WHERE user_id IN (%s, %s)", (U, V)).fetchall()
    assert [r["user_id"] for r in left] == [U]


@pytest.mark.parametrize("role", ["anon", "authenticated"])
def test_only_the_service_role_can_touch_it(conn, role):
    _stage(conn)
    conn.execute(f"SET LOCAL ROLE {role}")
    try:
        assert _sqlstate(conn, "SELECT 1 FROM public.gradescope_syncs") == "42501"
    finally:
        conn.execute("RESET ROLE")
    conn.execute("SET LOCAL ROLE service_role")
    try:
        assert conn.execute("SELECT count(*) AS n FROM public.gradescope_syncs "
                            "WHERE user_id = %s", (U,)).fetchone()["n"] == 1
    finally:
        conn.execute("RESET ROLE")
