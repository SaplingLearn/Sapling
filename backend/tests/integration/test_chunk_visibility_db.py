"""#629 against the real `match_course_chunks` — the half no mock can prove.

The guarantee this issue buys is a SQL predicate. Every hermetic test in the
suite asserts that the app *sends* `filter_user_id`; none of them can say what
Postgres does with it, and the predicate is where a leak would actually live —
an `OR` that binds the wrong way, a NULL that widens instead of narrowing, a
stale 3-argument overload of the function still answering without a visibility
clause at all.

So these run the real RPC over real rows, asserting the issue's three
acceptance criteria directly:

  1. an opted-out student's upload is retrievable by that student and no other;
  2. identical text from one opted-in and one opted-out uploader is two rows;
  3. opting out withdraws a sole-contributor chunk from everyone else.

Per the lane's rule (#397) the fixtures are written over raw psycopg, because
the layer under test here is the PostgREST/RPC READ.
"""
import pytest

pytestmark = pytest.mark.integration

COURSE_CODE = "ITEST CS 629"
DIM = 768

# Seeded by db/seed_local_rich; the contributor ledger has an FK to users(id),
# so these have to be real rows.
from tests.integration.conftest import USER_ACTIVE, USER_SECOND  # noqa: E402


def _unit(axis: int) -> list[float]:
    vec = [0.0] * DIM
    vec[axis] = 1.0
    return vec


def _literal(vec) -> str:
    return "[" + ",".join(str(v) for v in vec) + "]"


def _insert_chunk(
    db_conn, row_id, *, text, uploader, visibility, embedding=None, contributors=()
):
    db_conn.execute(
        """
        INSERT INTO course_chunks
            (id, course_id, doc_id, uploader_id, chunk_index, chunk_text,
             chunk_hash, embedding, category, visibility, semester, school)
        VALUES (%s, %s, %s, %s, 0, %s, %s, %s::vector, 'document', %s,
                'current', '')
        """,
        (row_id, COURSE_CODE, f"doc-{row_id}", uploader, text, row_id,
         _literal(embedding if embedding is not None else _unit(0)), visibility),
    )
    for user_id in contributors:
        db_conn.execute(
            "INSERT INTO course_chunk_contributors (chunk_id, user_id) "
            "VALUES (%s, %s) ON CONFLICT DO NOTHING",
            (row_id, user_id),
        )


def _match(user_id, *, k=10):
    """Call the RPC exactly as `retrieve_chunks_detailed` does."""
    from db.connection import rpc

    return rpc("match_course_chunks", {
        "query_embedding": _unit(0),
        "match_count": k,
        "filter_course_id": COURSE_CODE,
        "filter_user_id": user_id,
    })


def _ids(rows):
    return {r["id"] for r in rows}


# ── AC 1: a private chunk reaches its owner and nobody else ─────────────────


def test_a_private_chunk_is_returned_to_its_uploader(db_conn):
    _insert_chunk(db_conn, "itest-629-priv", text="my own notes",
                  uploader=USER_ACTIVE, visibility="private")

    assert "itest-629-priv" in _ids(_match(USER_ACTIVE))


def test_a_private_chunk_is_withheld_from_everyone_else(db_conn):
    """The whole point of the issue. Before the fix this row was `shared` by
    construction and this assertion could not have been written."""
    _insert_chunk(db_conn, "itest-629-priv", text="my own notes",
                  uploader=USER_ACTIVE, visibility="private")

    assert "itest-629-priv" not in _ids(_match(USER_SECOND))


def test_a_private_chunk_is_withheld_from_an_unnamed_reader(db_conn):
    """`filter_user_id => NULL` must NARROW to shared, not widen to everything.
    A predicate written as `filter_user_id IS NULL OR …` would invert exactly
    this case, and the offline scripts are the callers that pass NULL."""
    _insert_chunk(db_conn, "itest-629-priv", text="my own notes",
                  uploader=USER_ACTIVE, visibility="private")

    assert "itest-629-priv" not in _ids(_match(None))


def test_a_shared_chunk_reaches_a_reader_who_never_uploaded_it(db_conn):
    """The corpus is still shared by default — the fix must not quietly turn
    RAG into a private-notes store."""
    _insert_chunk(db_conn, "itest-629-shared", text="lecture 4 notes",
                  uploader=USER_ACTIVE, visibility="shared",
                  contributors=[USER_ACTIVE])

    assert "itest-629-shared" in _ids(_match(USER_SECOND))


# ── AC 2: one opted-in + one opted-out uploader is two rows ─────────────────


def test_identical_text_from_an_opted_in_and_an_opted_out_uploader_is_two_rows(
    db_conn,
):
    """Content-addressed ids mean identical text normally MERGES. If the
    private id namespace were missing, the opted-out upload would merge into the
    shared row — leaving that student's text in the class pool under a row they
    can no longer withdraw. Ids computed here by the real hashing code."""
    from services.rag_service import chunk_id

    text = "Gradient descent follows the negative gradient."
    shared_id = chunk_id(COURSE_CODE, text)
    private_id = chunk_id(
        COURSE_CODE, text, visibility="private", uploader_id=USER_SECOND
    )
    assert shared_id != private_id

    _insert_chunk(db_conn, shared_id, text=text, uploader=USER_ACTIVE,
                  visibility="shared", contributors=[USER_ACTIVE])
    _insert_chunk(db_conn, private_id, text=text, uploader=USER_SECOND,
                  visibility="private")

    rows = db_conn.execute(
        "SELECT id, visibility FROM course_chunks "
        "WHERE course_id = %s AND chunk_text = %s ORDER BY visibility",
        (COURSE_CODE, text),
    ).fetchall()
    assert [r["visibility"] for r in rows] == ["private", "shared"]

    # And each reader sees exactly one of them.
    assert private_id not in _ids(_match(USER_ACTIVE))
    assert shared_id in _ids(_match(USER_ACTIVE))
    assert private_id in _ids(_match(USER_SECOND))


# ── AC 3: the toggle withdraws what is already written ──────────────────────


def test_opting_out_withdraws_a_sole_contributor_chunk_from_other_readers(db_conn):
    from services.chunk_visibility import resync_user_chunk_visibility

    _insert_chunk(db_conn, "itest-629-sole", text="my handout",
                  uploader=USER_ACTIVE, visibility="shared",
                  contributors=[USER_ACTIVE])
    assert "itest-629-sole" in _ids(_match(USER_SECOND))

    db_conn.execute(
        "INSERT INTO user_settings (user_id, share_class_context) VALUES (%s, false) "
        "ON CONFLICT (user_id) DO UPDATE SET share_class_context = false",
        (USER_ACTIVE,),
    )
    assert resync_user_chunk_visibility(USER_ACTIVE)["to_private"] == 1

    assert "itest-629-sole" not in _ids(_match(USER_SECOND))
    # …and the student who uploaded it keeps it, through the ledger clause
    # rather than through `uploader_id`.
    assert "itest-629-sole" in _ids(_match(USER_ACTIVE))


def test_opting_out_keeps_a_chunk_another_student_also_uploaded(db_conn):
    """Deduped rows are jointly contributed. The content is not exclusively the
    opting-out student's, so withdrawing it would delete a classmate's upload
    from their own corpus."""
    from services.chunk_visibility import resync_user_chunk_visibility

    _insert_chunk(db_conn, "itest-629-joint", text="the shared slide deck",
                  uploader=USER_SECOND, visibility="shared",
                  contributors=[USER_ACTIVE, USER_SECOND])

    db_conn.execute(
        "INSERT INTO user_settings (user_id, share_class_context) VALUES (%s, false) "
        "ON CONFLICT (user_id) DO UPDATE SET share_class_context = false",
        (USER_ACTIVE,),
    )
    assert resync_user_chunk_visibility(USER_ACTIVE)["to_private"] == 0

    assert "itest-629-joint" in _ids(_match(USER_SECOND))


def test_opting_back_in_restores_a_flipped_chunk_to_the_pool(db_conn):
    from services.chunk_visibility import resync_user_chunk_visibility

    _insert_chunk(db_conn, "itest-629-back", text="my handout",
                  uploader=USER_ACTIVE, visibility="private",
                  contributors=[USER_ACTIVE])
    db_conn.execute(
        "INSERT INTO user_settings (user_id, share_class_context) VALUES (%s, true) "
        "ON CONFLICT (user_id) DO UPDATE SET share_class_context = true",
        (USER_ACTIVE,),
    )

    assert resync_user_chunk_visibility(USER_ACTIVE)["to_shared"] == 1
    assert "itest-629-back" in _ids(_match(USER_SECOND))


# ── The overload hazard the migration exists to close ───────────────────────


def test_no_unfiltered_three_argument_overload_survives(db_conn):
    """`CREATE OR REPLACE FUNCTION` with a new parameter creates an OVERLOAD
    rather than replacing, so the pre-#629 3-argument function — which has no
    visibility clause whatsoever — would still be live and callable. The
    migration DROPs it; this is what notices if that line is ever lost."""
    rows = db_conn.execute(
        "SELECT pg_get_function_identity_arguments(p.oid) AS args "
        "FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace "
        "WHERE p.proname = 'match_course_chunks' AND n.nspname = 'public'"
    ).fetchall()

    assert len(rows) == 1, [r["args"] for r in rows]
    assert "filter_user_id" in rows[0]["args"]


def test_visibility_is_constrained_to_the_two_known_values(db_conn):
    """A typo'd third value would be neither shared nor matched by the owner
    clause, i.e. permanently unreachable, and nothing would say so."""
    import psycopg

    with pytest.raises(psycopg.errors.CheckViolation):
        _insert_chunk(db_conn, "itest-629-bad", text="x",
                      uploader=USER_ACTIVE, visibility="world-readable")
