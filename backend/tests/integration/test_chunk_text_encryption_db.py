"""#484 against the real column — the assertion the oracle cannot make yet.

The `ciphertext` oracle now lists `course_chunks.chunk_text`, but the E2E stack
never indexes anything (embedding is disabled below the seam, #439), so that
entry samples zero rows and passes vacuously. This is the non-vacuous version,
and it is the lane's rule exactly: the write goes through the app
(`index_document_chunks`), and the assertion reads the column back over raw
psycopg — never through the same PostgREST layer that made the write, which
would prove only the echo.

What it protects: that a passage is ciphertext AT REST while retrieval still
hands back plaintext, and that the id is the hash of the plaintext so two
uploads of one passage still converge on one row.
"""
from unittest.mock import patch

import pytest

pytestmark = pytest.mark.integration

COURSE_CODE = "ITEST CS 484"
DIM = 768
TEXT = "Gradient descent steps against the gradient of the loss surface."

from tests.integration.conftest import USER_ACTIVE  # noqa: E402


def _vec():
    v = [0.0] * DIM
    v[0] = 1.0
    return v


def _index():
    from services.rag_service import index_document_chunks

    with (
        patch("services.rag_service._embed_documents_batch", return_value=[_vec()]),
        patch("services.chunk_visibility.shares_class_context", return_value=True),
    ):
        return index_document_chunks(
            COURSE_CODE, "itest-484-doc", USER_ACTIVE, [TEXT],
            visibility="shared", category="lecture_notes",
        )


def test_the_stored_column_is_ciphertext(db_conn):
    from services.encryption import decrypt
    from services.rag_service import chunk_id

    assert _index() == 1

    row = db_conn.execute(
        "SELECT id, chunk_text, chunk_hash FROM course_chunks WHERE course_id = %s",
        (COURSE_CODE,),
    ).fetchone()

    assert row["chunk_text"] != TEXT
    assert decrypt(row["chunk_text"]) == TEXT
    # …and the id is still the PLAINTEXT content hash, so a re-upload merges.
    assert row["id"] == chunk_id(COURSE_CODE, TEXT)
    assert row["chunk_hash"] == row["id"]


def test_two_uploads_of_one_passage_stay_one_row(db_conn):
    """Content-addressing survives encryption only because ids are computed
    before it. The two ciphertexts differ (fresh AES-GCM nonce per call); the
    row count must not."""
    assert _index() == 1
    first = db_conn.execute(
        "SELECT chunk_text FROM course_chunks WHERE course_id = %s", (COURSE_CODE,),
    ).fetchone()["chunk_text"]

    assert _index() == 1
    rows = db_conn.execute(
        "SELECT chunk_text FROM course_chunks WHERE course_id = %s", (COURSE_CODE,),
    ).fetchall()

    assert len(rows) == 1
    assert rows[0]["chunk_text"] != first  # re-encrypted, same row


def test_retrieval_returns_plaintext_from_the_encrypted_row(db_conn):
    """End to end over the real RPC: ciphertext at rest, plaintext in hand."""
    from services.rag_service import retrieve_chunks

    assert _index() == 1

    with patch("services.rag_service._embed_query", return_value=_vec()):
        chunks = retrieve_chunks(
            "gradient descent", course_id=COURSE_CODE, user_id=USER_ACTIVE,
        )

    assert [c["chunk_text"] for c in chunks] == [TEXT]
