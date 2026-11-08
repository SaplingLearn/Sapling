"""#116: the `document_uploads` staging table (20261108212226_document_uploads.sql)
against real Postgres.

SQL only (no app imports): the hermetic suite (tests/test_document_upload_jobs.py)
pins what services/document_jobs.py sends; this pins what the table does with
it — the (user_id, request_id) idempotency key, the stage/error_code CHECKs,
the compare-and-swap the request and the worker race on (exactly one of
`queued -> inline` and `queued -> extracting` wins), the cascades, and that
only the service role can touch it. Every test runs in one rolled-back
transaction over its own `w6a-*` rows.
"""
import psycopg
import pytest

pytestmark = pytest.mark.integration

U, V = "w6a-user-a", "w6a-user-b"

_SEED = [
    "INSERT INTO schools (id, name, slug) VALUES ('w6a-school', 'w6a', 'w6a-school')",
    "INSERT INTO courses (id, school_id, course_code, course_name) "
    "VALUES ('w6a-course', 'w6a-school', 'W6A101', 'w6a')",
    "INSERT INTO terms (id, term, year, label, start_date, end_date, sort_key) "
    "VALUES ('w6a-term', 'Fall', 2098, 'w6a Fall 2098', '2098-09-01', '2098-12-20', 2098997)",
    "INSERT INTO course_offerings (id, course_id, term_id, section) "
    "VALUES ('w6a-off', 'w6a-course', 'w6a-term', 'w6a')",
    f"INSERT INTO users (id, email) VALUES ('{U}', 'w6a-a@example.com'), "
    f"('{V}', 'w6a-b@example.com')",
]


@pytest.fixture
def conn(db_conn):
    with db_conn.transaction() as tx:
        for stmt in _SEED:
            db_conn.execute(stmt)
        yield db_conn
        raise psycopg.Rollback(tx)


def _stage(conn, user=U, request_id="rid-1", **cols) -> str:
    data = {"user_id": user, "offering_id": "w6a-off", "course_id": "w6a-course",
            "request_id": request_id, "file_name": "a.pdf", "file_size": 3,
            "file_data": "ciphertext", **cols}
    names = ", ".join(data)
    marks = ", ".join(["%s"] * len(data))
    return conn.execute(
        f"INSERT INTO public.document_uploads ({names}) VALUES ({marks}) RETURNING id",
        list(data.values()),
    ).fetchone()["id"]


def _sqlstate(conn, sql, params=None) -> str | None:
    try:
        with conn.transaction():
            conn.execute(sql, params)
    except psycopg.Error as e:
        return e.sqlstate
    return None


def _swap(conn, upload_id, frm, to) -> int:
    """The services/document_jobs.py stage swap: PATCH ... WHERE stage = frm."""
    return conn.execute(
        "UPDATE public.document_uploads SET stage = %s WHERE id = %s AND stage = %s",
        (to, upload_id, frm),
    ).rowcount


def test_defaults_queued_with_empty_progress(conn):
    uid = _stage(conn)
    row = conn.execute("SELECT * FROM public.document_uploads WHERE id = %s", (uid,)).fetchone()
    assert row["stage"] == "queued" and row["progress"] == {}
    assert row["error_code"] is None and row["document_id"] is None


def test_the_request_id_is_unique_per_user_only(conn):
    _stage(conn)
    assert _sqlstate(conn, "INSERT INTO public.document_uploads (user_id, offering_id, "
                     "course_id, request_id, file_name) VALUES (%s, 'w6a-off', "
                     "'w6a-course', 'rid-1', 'b.pdf')", (U,)) == "23505"
    _stage(conn, user=V)  # another student may reuse the same X-Request-ID


@pytest.mark.parametrize("bad", ["bogus", "QUEUED", ""])
def test_unknown_stages_are_refused(conn, bad):
    uid = _stage(conn)
    assert _sqlstate(conn, "UPDATE public.document_uploads SET stage = %s WHERE id = %s",
                     (bad, uid)) == "23514"


@pytest.mark.parametrize("bad", ["Has Spaces", "a" * 41, "TypeError: boom"])
def test_error_codes_must_be_fixed_codes_not_messages(conn, bad):
    uid = _stage(conn)
    assert _sqlstate(conn, "UPDATE public.document_uploads SET error_code = %s WHERE id = %s",
                     (bad, uid)) == "23514"


def test_exactly_one_of_take_back_and_worker_start_wins(conn):
    uid = _stage(conn)
    assert _swap(conn, uid, "queued", "extracting") == 1   # the worker
    assert _swap(conn, uid, "queued", "inline") == 0       # the request, too late
    other = _stage(conn, request_id="rid-2")
    assert _swap(conn, other, "queued", "inline") == 1     # the request first
    assert _swap(conn, other, "queued", "extracting") == 0  # the job is now a no-op


def test_deleting_the_user_removes_their_staged_uploads(conn):
    _stage(conn)
    _stage(conn, user=V)
    conn.execute("DELETE FROM public.users WHERE id = %s", (U,))
    left = conn.execute("SELECT user_id FROM public.document_uploads "
                        "WHERE user_id IN (%s, %s)", (U, V)).fetchall()
    assert [r["user_id"] for r in left] == [V]


def test_deleting_the_document_keeps_the_upload_row(conn):
    conn.execute("INSERT INTO public.documents (id, user_id, offering_id, file_name, category) "
                 "VALUES ('w6a-doc', %s, 'w6a-off', 'a.pdf', 'other')", (U,))
    uid = _stage(conn, stage="done", document_id="w6a-doc", file_data=None)
    conn.execute("DELETE FROM public.documents WHERE id = 'w6a-doc'")
    row = conn.execute("SELECT stage, document_id FROM public.document_uploads WHERE id = %s",
                       (uid,)).fetchone()
    assert row == {"stage": "done", "document_id": None}


@pytest.mark.parametrize("role", ["anon", "authenticated"])
def test_only_the_service_role_can_touch_it(conn, role):
    _stage(conn)
    conn.execute(f"SET LOCAL ROLE {role}")
    try:
        assert _sqlstate(conn, "SELECT 1 FROM public.document_uploads") == "42501"
    finally:
        conn.execute("RESET ROLE")
    conn.execute("SET LOCAL ROLE service_role")
    try:
        assert conn.execute("SELECT count(*) AS n FROM public.document_uploads "
                            "WHERE user_id = %s", (U,)).fetchone()["n"] == 1
    finally:
        conn.execute("RESET ROLE")
