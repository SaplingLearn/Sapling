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
import logging
from unittest.mock import MagicMock, patch

from routes.documents import _index_document_chunks


def _pgvector_wire(vec):
    """A pgvector column as PostgREST actually returns it: its TEXT form, a
    JSON *string* — never a JSON array. Mocking it as a Python list is the
    fidelity gap that let #628 through."""
    return "[" + ",".join(repr(v) for v in vec) + "]"


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

    def test_function_mode_is_a_designed_skip_not_a_logged_failure(self, monkeypatch, caplog):
        """#439 + #628: outside real mode no embedding is possible, so indexing
        is an explicit, quiet no-op — no client constructed, nothing indexed,
        and NO error/traceback logged.

        It used to `raise` into the outer `except` on purpose, which forced
        e2e_oracles/logscan.py to allowlist "_index_document_chunks failed".
        That allowlist entry then hid #628 — a real TypeError on every catalog
        course — for months. A designed skip needs no allowlist."""
        monkeypatch.setenv("SAPLING_MODEL_MODE", "function")
        ctor = MagicMock(side_effect=AssertionError(
            "genai.Client must not be constructed outside real mode"
        ))
        monkeypatch.setattr("google.genai.Client", ctor)
        fake = _mock_table_for(
            courses_rows=[{"course_code": "BIO-101"}],
            course_chunks_rows=[{"embedding": _pgvector_wire([0.1] * 768)}],
        )

        with (
            patch("routes.documents.table", side_effect=fake),
            patch("services.rag_service.table", side_effect=fake),
            patch("services.chunker.chunk_for_category", return_value=["chunk one"]),
            patch("services.rag_service.index_document_chunks") as mock_index,
            caplog.at_level(logging.INFO, logger="routes.documents"),
        ):
            _index_document_chunks(
                doc_id="doc-gate",
                course_id="course-uuid-1",
                user_id="user-1",
                extracted_text="some extracted text",
                category="lecture_notes",
            )

        ctor.assert_not_called()
        mock_index.assert_not_called()
        assert not [r for r in caplog.records if r.levelno >= logging.WARNING], (
            f"function mode must not log a failure: {[r.getMessage() for r in caplog.records]}"
        )
        assert "_index_document_chunks failed" not in caplog.text
        assert "doc-gate" in caplog.text  # the skip itself is still visible at INFO

    def test_indexes_a_catalog_course_when_the_embedding_arrives_as_a_string(self, monkeypatch):
        """#628 regression. PostgREST returns the catalog row's pgvector
        embedding as a STRING. The old gate zipped floats against that string's
        characters -> TypeError -> swallowed -> the document was never indexed
        while the upload reported success. Confirmed live: prod had 5 indexable
        documents on a catalog course and 0 document chunks."""
        monkeypatch.setenv("SAPLING_MODEL_MODE", "real")
        vec = [1.0] + [0.0] * 767
        fake = _mock_table_for(
            courses_rows=[{"course_code": "CAS CS 132"}],
            course_chunks_rows=[{"embedding": _pgvector_wire(vec)}],
        )

        with (
            patch("routes.documents.table", side_effect=fake),
            patch("services.rag_service.table", side_effect=fake),
            patch("services.chunker.chunk_for_category", return_value=["chunk one"]),
            patch("services.rag_service._embed_document", return_value=vec),
            patch(
                "services.rag_service.index_document_chunks", return_value=1
            ) as mock_index,
            patch("time.sleep"),
        ):
            _index_document_chunks(
                doc_id="doc-628",
                course_id="course-uuid-1",
                user_id="user-1",
                extracted_text="some extracted text",
                category="lecture_notes",
            )

        mock_index.assert_called_once_with(
            course_code="CAS CS 132",
            doc_id="doc-628",
            uploader_id="user-1",
            chunks=["chunk one"],
        )

    def test_low_relevance_is_recorded_but_does_not_block_indexing(self, monkeypatch):
        """The relevance check is OBSERVE-ONLY (#628). It compares a whole
        document against one paragraph of catalog blurb, on a threshold nobody
        calibrated because the gate crashed before ever producing a score.
        Until real scores exist it must never drop a student's upload — it
        records the score so a threshold can be chosen from data."""
        monkeypatch.setenv("SAPLING_MODEL_MODE", "real")
        fake = _mock_table_for(
            courses_rows=[{"course_code": "CAS CS 132"}],
            course_chunks_rows=[{"embedding": _pgvector_wire([1.0, 0.0])}],
        )

        with (
            patch("routes.documents.table", side_effect=fake),
            patch("services.rag_service.table", side_effect=fake),
            patch("services.chunker.chunk_for_category", return_value=["chunk one"]),
            patch("services.rag_service._embed_document", return_value=[0.0, 1.0]),  # orthogonal
            patch(
                "services.rag_service.index_document_chunks", return_value=1
            ) as mock_index,
            patch("routes.documents.events_service.log_event") as mock_event,
            patch("time.sleep"),
        ):
            _index_document_chunks(
                doc_id="doc-offtopic",
                course_id="course-uuid-1",
                user_id="user-1",
                extracted_text="some extracted text",
                category="assignment",
            )

        mock_index.assert_called_once()
        scored = [c for c in mock_event.call_args_list if c.args[0] == "rag.relevance_scored"]
        assert len(scored) == 1
        assert scored[0].kwargs["category"] == "usage"
        payload = scored[0].kwargs["payload"]
        assert payload["doc_id"] == "doc-offtopic"
        assert payload["course_id"] == "CAS CS 132"
        assert payload["category"] == "assignment"
        assert payload["score"] == 0.0

    def test_a_failed_relevance_score_does_not_block_indexing(self, monkeypatch, caplog):
        """An advisory measurement must not be able to lose a document: if the
        scoring embed fails, indexing still runs."""
        monkeypatch.setenv("SAPLING_MODEL_MODE", "real")
        fake = _mock_table_for(
            courses_rows=[{"course_code": "CAS CS 132"}],
            course_chunks_rows=[{"embedding": _pgvector_wire([1.0, 0.0])}],
        )

        with (
            patch("routes.documents.table", side_effect=fake),
            patch("services.rag_service.table", side_effect=fake),
            patch("services.chunker.chunk_for_category", return_value=["chunk one"]),
            patch("services.rag_service._embed_document", side_effect=Exception("embed 429")),
            patch(
                "services.rag_service.index_document_chunks", return_value=1
            ) as mock_index,
            patch("time.sleep"),
            caplog.at_level(logging.WARNING, logger="routes.documents"),
        ):
            _index_document_chunks(
                doc_id="doc-429",
                course_id="course-uuid-1",
                user_id="user-1",
                extracted_text="some extracted text",
                category="lecture_notes",
            )

        mock_index.assert_called_once()
        assert "relevance" in caplog.text and "doc-429" in caplog.text

    def test_relevance_embeds_via_rag_service_not_raw_client(self, monkeypatch):
        """#413: in real mode the relevance embed must go through
        services.rag_service.embed_document_text (shared lazy client:
        dummy-key fallback, request timeout, #439 gate) instead of
        constructing a raw ``genai.Client`` with an empty-string API-key
        fallback, whose keyless construction ValueError the outer ``except`` swallowed
        into a silent no-index degrade that looked like a clean upload."""
        monkeypatch.setenv("SAPLING_MODEL_MODE", "real")
        ctor = MagicMock(side_effect=AssertionError(
            "raw genai.Client constructed below the seam (#413/#439)"
        ))
        monkeypatch.setattr("google.genai.Client", ctor)
        vec = [1.0] + [0.0] * 767
        fake = _mock_table_for(
            courses_rows=[{"course_code": "BIO-101"}],
            course_chunks_rows=[{"embedding": _pgvector_wire(vec)}],
        )

        with (
            patch("routes.documents.table", side_effect=fake),
            patch("services.rag_service.table", side_effect=fake),
            patch("services.chunker.chunk_for_category", return_value=["chunk one"]),
            patch(
                "services.rag_service.embed_document_text", return_value=vec
            ) as mock_embed,
            patch(
                "services.rag_service.index_document_chunks", return_value=1
            ) as mock_index,
            patch("time.sleep"),
        ):
            _index_document_chunks(
                doc_id="doc-real",
                course_id="course-uuid-1",
                user_id="user-1",
                extracted_text="some extracted text",
                category="lecture_notes",
            )

        ctor.assert_not_called()
        mock_embed.assert_called_once_with("chunk one")
        mock_index.assert_called_once()

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
