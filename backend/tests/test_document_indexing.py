"""
Unit tests for routes.documents._index_document_chunks.

This helper is normally fired via `_spawn_post_roll` as a background task
after a document upload completes. Every existing upload test patches
`_spawn_post_roll` itself, so `_index_document_chunks` (course-code
resolution, chunking, the relevance gate, and the call into
`services.rag_service.index_document_chunks`) was never actually
exercised. These tests call it directly.

`chunk_for_category` and `index_document_chunks` are imported *inside* the
function body (local imports), so they must be patched at their
definition sites (`services.chunker.chunk_for_category`,
`services.rag_service.index_document_chunks`) rather than on
`routes.documents`.
"""
from unittest.mock import patch

from routes.documents import _index_document_chunks


def _mock_table_for(courses_rows, course_chunks_rows):
    """Build a `table()` stand-in whose `.select()` return value depends on
    which table name it was called for."""
    def _table(name):
        m = type("T", (), {})()
        if name == "courses":
            m.select = lambda *a, **k: courses_rows
        elif name == "course_chunks":
            m.select = lambda *a, **k: course_chunks_rows
        elif name == "documents":
            m.update = lambda *a, **k: None
        else:
            raise AssertionError(f"unexpected table name: {name}")
        return m
    return _table


class TestIndexDocumentChunks:
    def test_happy_path_indexes_chunks_when_no_catalog_embedding(self):
        """No catalog embedding for the course -> relevance gate is skipped
        entirely, and the resolved course_code/doc_id/uploader_id/chunks
        flow straight through to services.rag_service.index_document_chunks."""
        chunks = ["chunk one about photosynthesis", "chunk two about mitosis"]
        with (
            patch(
                "routes.documents.table",
                side_effect=_mock_table_for(
                    courses_rows=[{"course_code": "BIO-101"}],
                    course_chunks_rows=[],  # no catalog embedding -> gate skipped
                ),
            ),
            patch("services.chunker.chunk_for_category", return_value=chunks) as mock_chunk,
            patch(
                "services.rag_service.index_document_chunks", return_value=2
            ) as mock_index,
        ):
            _index_document_chunks(
                doc_id="doc-1",
                course_id="course-uuid-1",
                user_id="user-1",
                extracted_text="some extracted text",
                category="lecture_notes",
            )

        mock_chunk.assert_called_once_with("some extracted text", "lecture_notes")
        mock_index.assert_called_once_with(
            course_code="BIO-101",
            doc_id="doc-1",
            uploader_id="user-1",
            chunks=chunks,
        )

    def test_empty_chunks_short_circuits_before_indexing(self):
        """chunk_for_category() returning [] (e.g. empty/garbage extracted text)
        must bail out before ever calling index_document_chunks."""
        with (
            patch(
                "routes.documents.table",
                side_effect=_mock_table_for(
                    courses_rows=[{"course_code": "BIO-101"}],
                    course_chunks_rows=[],
                ),
            ),
            patch("services.chunker.chunk_for_category", return_value=[]),
            patch("services.rag_service.index_document_chunks") as mock_index,
        ):
            _index_document_chunks(
                doc_id="doc-2",
                course_id="course-uuid-1",
                user_id="user-1",
                extracted_text="",
                category="lecture_notes",
            )

        mock_index.assert_not_called()

    def test_category_is_passed_to_chunker(self):
        """The document's category must reach the chunker so prose docs get
        the prose strategy."""
        with (
            patch(
                "routes.documents.table",
                side_effect=_mock_table_for(
                    courses_rows=[{"course_code": "ENG-201"}],
                    course_chunks_rows=[],
                ),
            ),
            patch(
                "services.chunker.chunk_for_category",
                return_value=["one chunk of prose"],
            ) as mock_chunk,
            patch("services.rag_service.index_document_chunks", return_value=1),
        ):
            _index_document_chunks(
                doc_id="doc-3",
                course_id="course-uuid-1",
                user_id="user-1",
                extracted_text="an essay body",
                category="assignment",
            )

        mock_chunk.assert_called_once_with("an essay body", "assignment")
