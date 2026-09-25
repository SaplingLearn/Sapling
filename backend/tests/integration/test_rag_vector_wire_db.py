"""#628 — the pgvector wire format, real-PostgREST half.

The bug: `_index_document_chunks`' relevance gate read a catalog row's
`embedding` through `table()` and multiplied it, float by float, against a
fresh embedding. PostgREST serialises a `VECTOR` column as its TEXT form — a
JSON *string* — so that raised TypeError on every course with a catalog row,
the catch-all swallowed it, and no upload to a catalog course was ever indexed.
Verified live on 2026-09-20: prod held 8,721 catalog chunks, 0 document chunks,
and 5 indexable documents that never indexed.

Why this file has to exist: every hermetic test handed the code a Python list
for that column, a shape the database never produces. The fixed hermetic tests
now hand it a string — but that is still a shape someone typed. These
assertions read a real `VECTOR(768)` back through the real PostgREST.

The write side goes in over raw psycopg (the lane's rule, inverted: the layer
under test here is the PostgREST READ, so the write must not share it).
"""
from unittest.mock import patch

import pytest

pytestmark = pytest.mark.integration

COURSE_CODE = "ITEST CS 628"
DIM = 768


def _unit(axis: int) -> list[float]:
    vec = [0.0] * DIM
    vec[axis] = 1.0
    return vec


def _literal(vec) -> str:
    return "[" + ",".join(str(v) for v in vec) + "]"


def _insert_catalog(db_conn, row_id, embedding, created_at):
    db_conn.execute(
        """
        INSERT INTO course_chunks
            (id, course_id, chunk_index, chunk_text, chunk_hash, embedding,
             category, semester, school, created_at)
        VALUES (%s, %s, 0, %s, %s, %s::vector, 'catalog', 'fall_2026', 'CAS', %s)
        """,
        (row_id, COURSE_CODE, f"Course: {COURSE_CODE}", row_id,
         _literal(embedding) if embedding is not None else None, created_at),
    )


def test_postgrest_returns_a_vector_column_as_a_string(db_conn):
    """The premise. If PostgREST ever starts returning a JSON array here,
    `parse_vector` still copes — but every comment claiming otherwise is then
    wrong, and this is where that gets noticed."""
    from db.connection import table

    _insert_catalog(db_conn, "itest-628-a", _unit(0), "2026-01-01T00:00:00Z")
    rows = table("course_chunks").select("embedding", filters={"id": "eq.itest-628-a"})

    assert isinstance(rows[0]["embedding"], str)


def test_course_relevance_scores_a_real_stored_vector(db_conn):
    """The #628 line itself, against the real wire: same direction -> 1.0,
    orthogonal -> 0.0. Before the fix this raised TypeError."""
    from services.rag_service import course_relevance

    _insert_catalog(db_conn, "itest-628-a", _unit(0), "2026-01-01T00:00:00Z")

    with patch("services.rag_service.embed_document_text", return_value=_unit(0)):
        assert course_relevance(COURSE_CODE, "on topic") == pytest.approx(1.0)
    with patch("services.rag_service.embed_document_text", return_value=_unit(1)):
        assert course_relevance(COURSE_CODE, "off topic") == pytest.approx(0.0)


def test_course_relevance_skips_null_embeddings_and_prefers_the_newest_row(db_conn):
    """ingest_catalog.py never deletes a superseded blurb and inserts
    NULL-embedding rows on a double embed failure. `a-null` sorts first by id
    and `b-old` is a stale blurb; the score must come from `c-new`."""
    from services.rag_service import course_relevance

    _insert_catalog(db_conn, "itest-628-a-null", None, "2026-03-01T00:00:00Z")
    _insert_catalog(db_conn, "itest-628-b-old", _unit(0), "2026-01-01T00:00:00Z")
    _insert_catalog(db_conn, "itest-628-c-new", _unit(1), "2026-02-01T00:00:00Z")

    with patch("services.rag_service.embed_document_text", return_value=_unit(1)):
        assert course_relevance(COURSE_CODE, "sample") == pytest.approx(1.0)


def test_course_relevance_is_none_for_a_course_with_no_catalog_row():
    from services.rag_service import course_relevance

    with patch("services.rag_service.embed_document_text") as mock_embed:
        assert course_relevance("ITEST NO SUCH 000", "sample") is None
    mock_embed.assert_not_called()
