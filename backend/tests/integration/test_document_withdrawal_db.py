"""#758 against the real `match_course_chunks` and PostgREST.

The hermetic suite proves the withdrawal's rules against a model of PostgREST
and pins the SQL's text. This proves the two halves no mock can: that the RPC
really refuses a chunk whose every source document is deleted (and still serves
one a live document holds), and that the withdrawal's filters and cascades do
what they say on the real tables.

Fixtures go in over raw psycopg; the layer under test is the PostgREST read and
the service's writes (#397).
"""
import pytest

from tests.integration.conftest import USER_ACTIVE, USER_SECOND

pytestmark = pytest.mark.integration

COURSE_CODE = "ITEST CS 758"
DIM = 768


def _unit(axis: int) -> str:
    vec = ["0"] * DIM
    vec[axis] = "1"
    return "[" + ",".join(vec) + "]"


def _offering(db_conn) -> str:
    row = db_conn.execute(
        "SELECT id FROM course_offerings WHERE course_id = 'rich-course-cs101' LIMIT 1"
    ).fetchone()
    assert row
    return row["id"]


def _doc(db_conn, doc_id, user, *, deleted=False):
    db_conn.execute(
        "INSERT INTO documents (id, user_id, offering_id, file_name, category, "
        "index_status, deleted_at) VALUES (%s, %s, %s, 'itest.pdf', "
        "'lecture_notes', 'indexed', " + ("now()" if deleted else "NULL") + ")",
        (doc_id, user, _offering(db_conn)),
    )


def _chunk(db_conn, cid, *, doc, uploader, visibility="shared", sources=(),
           contributors=()):
    db_conn.execute(
        """
        INSERT INTO course_chunks
            (id, course_id, doc_id, uploader_id, chunk_index, chunk_text,
             chunk_hash, embedding, category, visibility, semester, school)
        VALUES (%s, %s, %s, %s, 0, 'x', %s, %s::vector, 'lecture_notes', %s,
                'current', '')
        """,
        (cid, COURSE_CODE, doc, uploader, cid, _unit(0), visibility),
    )
    for d in sources:
        db_conn.execute(
            "INSERT INTO course_chunk_sources (chunk_id, doc_id) VALUES (%s, %s)", (cid, d))
    for u in contributors:
        db_conn.execute(
            "INSERT INTO course_chunk_contributors (chunk_id, user_id) VALUES (%s, %s)",
            (cid, u))


def _match(user_id):
    from db.connection import rpc

    rows = rpc("match_course_chunks", {
        "query_embedding": [1.0] + [0.0] * (DIM - 1),
        "match_count": 20,
        "filter_course_id": COURSE_CODE,
        "filter_user_id": user_id,
    })
    return {r["id"] for r in rows}


# ── retrieval: defence in depth ─────────────────────────────────────────────


def test_a_chunk_whose_only_source_is_deleted_is_not_served(db_conn):
    _doc(db_conn, "itest-758-gone", USER_ACTIVE, deleted=True)
    _chunk(db_conn, "itest-758-c", doc="itest-758-gone", uploader=USER_ACTIVE,
           sources=["itest-758-gone"], contributors=[USER_ACTIVE])

    assert "itest-758-c" not in _match(USER_ACTIVE)
    assert "itest-758-c" not in _match(USER_SECOND)


def test_a_chunk_a_live_document_still_holds_is_served(db_conn):
    _doc(db_conn, "itest-758-gone", USER_ACTIVE, deleted=True)
    _doc(db_conn, "itest-758-live", USER_SECOND)
    _chunk(db_conn, "itest-758-c", doc="itest-758-gone", uploader=USER_ACTIVE,
           sources=["itest-758-gone", "itest-758-live"],
           contributors=[USER_ACTIVE, USER_SECOND])

    assert "itest-758-c" in _match(USER_SECOND)


def test_an_unsourced_chunk_is_served_as_before(db_conn):
    """Catalog rows and fixtures have no sources; the new clause must not
    narrow them."""
    _chunk(db_conn, "itest-758-c", doc=None, uploader=USER_ACTIVE)

    assert "itest-758-c" in _match(USER_SECOND)


# ── the withdrawal on real tables ───────────────────────────────────────────


def test_withdrawal_deletes_a_private_chunk_and_its_ledger(db_conn):
    from services.chunk_visibility import withdraw_document_chunks

    _doc(db_conn, "itest-758-gone", USER_ACTIVE, deleted=True)
    _chunk(db_conn, "itest-758-p", doc="itest-758-gone", uploader=USER_ACTIVE,
           visibility="private", sources=["itest-758-gone"])

    out = withdraw_document_chunks("itest-758-gone", USER_ACTIVE)

    assert out["chunks_deleted"] == 1
    assert db_conn.execute(
        "SELECT count(*) AS n FROM course_chunks WHERE id = 'itest-758-p'").fetchone()["n"] == 0
    assert db_conn.execute(
        "SELECT count(*) AS n FROM course_chunk_sources WHERE chunk_id = 'itest-758-p'"
    ).fetchone()["n"] == 0


def test_withdrawal_keeps_a_classmates_shared_chunk(db_conn):
    from services.chunk_visibility import withdraw_document_chunks

    _doc(db_conn, "itest-758-gone", USER_ACTIVE, deleted=True)
    _doc(db_conn, "itest-758-live", USER_SECOND)
    _chunk(db_conn, "itest-758-c", doc="itest-758-gone", uploader=USER_ACTIVE,
           sources=["itest-758-gone", "itest-758-live"],
           contributors=[USER_ACTIVE, USER_SECOND])

    withdraw_document_chunks("itest-758-gone", USER_ACTIVE)

    users = {r["user_id"] for r in db_conn.execute(
        "SELECT user_id FROM course_chunk_contributors WHERE chunk_id = 'itest-758-c'")}
    assert users == {USER_SECOND}
    assert "itest-758-c" in _match(USER_SECOND)
