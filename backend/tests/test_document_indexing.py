"""
Unit tests for routes.documents._index_document_chunks.

This helper is normally fired via `_spawn_post_roll` as a background task
after a document upload completes. Every existing upload test patches
`_spawn_post_roll` itself, so `_index_document_chunks` (course-code
resolution, chunking, the call into
`services.rag_service.index_document_chunks`, and the observe-only relevance
score that follows it) was never actually exercised. These tests call it
directly.

`chunk_for_category` and `index_document_chunks` are imported *inside* the
function body (local imports), so they must be patched at their
definition sites (`services.chunker.chunk_for_category`,
`services.rag_service.index_document_chunks`) rather than on
`routes.documents`.
"""
import logging
from contextlib import contextmanager
from unittest.mock import MagicMock, patch

from routes.documents import _index_document_chunks


def _pgvector_wire(vec):
    """A pgvector column as PostgREST actually returns it: its TEXT form, a
    JSON *string* — never a JSON array. Mocking it as a Python list is the
    fidelity gap that let #628 through. The integration lane pins this shape
    against a real PostgREST (tests/integration/test_rag_vector_wire_db.py)."""
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
            m.upsert = MagicMock(side_effect=AssertionError("unexpected upsert"))
        elif name == "documents":
            m.update = lambda *a, **k: None
        else:
            raise AssertionError(f"unexpected table name: {name}")
        return m
    return _table


@contextmanager
def _tables(courses_rows, course_chunks_rows):
    """Patch BOTH `table` seams the indexer reads through: the route resolves
    `courses` / writes `documents` via `routes.documents.table`, while the
    relevance score reads the catalog row via `services.rag_service.table`.
    Patching only the first leaves the catalog read to whatever the hermetic
    conftest stub happens to return."""
    fake = _mock_table_for(courses_rows, course_chunks_rows)
    with (
        patch("routes.documents.table", side_effect=fake),
        patch("services.rag_service.table", side_effect=fake),
    ):
        yield


def _run(doc_id="doc-1", category="lecture_notes", **kw):
    _index_document_chunks(
        doc_id=doc_id,
        course_id="course-uuid-1",
        user_id="user-1",
        extracted_text="some extracted text",
        category=category,
        **kw,
    )


def _scored(mock_event):
    return [c for c in mock_event.call_args_list if c.args[0] == "rag.relevance_scored"]


class TestIndexDocumentChunks:
    def test_happy_path_indexes_chunks_when_no_catalog_embedding(self):
        """The resolved course_code/doc_id/uploader_id/chunks flow straight
        through to services.rag_service.index_document_chunks; with no catalog
        embedding for the course there is nothing to score against."""
        chunks = ["chunk one about photosynthesis", "chunk two about mitosis"]
        with (
            _tables(courses_rows=[{"course_code": "BIO-101"}], course_chunks_rows=[]),
            patch("services.chunker.chunk_for_category", return_value=chunks) as mock_chunk,
            patch(
                "services.rag_service.index_document_chunks", return_value=2
            ) as mock_index,
            patch("routes.documents.events_service.log_event") as mock_event,
        ):
            _run()

        mock_chunk.assert_called_once_with("some extracted text", "lecture_notes")
        mock_index.assert_called_once_with(
            course_code="BIO-101",
            doc_id="doc-1",
            uploader_id="user-1",
            chunks=chunks,
            # The uploader has no user_settings row, so the 0037 default (opted
            # in) applies — see TestVisibilityAtIndexTime for the other branch.
            visibility="shared",
        )
        assert not _scored(mock_event)

    def test_empty_chunks_short_circuits_before_indexing(self):
        """chunk_for_category() returning [] (e.g. empty/garbage extracted text)
        must bail out before ever calling index_document_chunks."""
        with (
            _tables(courses_rows=[{"course_code": "BIO-101"}], course_chunks_rows=[]),
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
        is a quiet no-op — no client constructed, nothing persisted, nothing
        scored, and NO warning/error/traceback logged.

        The route used to `raise` into its outer `except` on purpose, which
        forced e2e_oracles/logscan.py to allowlist "_index_document_chunks
        failed". That allowlist entry then hid #628 — a real TypeError on every
        catalog course — for months. The seam rule lives in ONE place
        (rag_service's `_require_real_mode`); the route just lets the real
        `index_document_chunks` degrade to 0 the way it already knows how to."""
        monkeypatch.setenv("SAPLING_MODEL_MODE", "function")
        ctor = MagicMock(side_effect=AssertionError(
            "genai.Client must not be constructed outside real mode"
        ))
        monkeypatch.setattr("google.genai.Client", ctor)

        with (
            _tables(
                courses_rows=[{"course_code": "BIO-101"}],
                # catalog row present; the fake's upsert raises if reached
                course_chunks_rows=[{"embedding": _pgvector_wire([0.1] * 768)}],
            ),
            patch("services.chunker.chunk_for_category", return_value=["chunk one"]),
            patch("routes.documents.events_service.log_event") as mock_event,
            caplog.at_level(logging.INFO),
        ):
            _run(doc_id="doc-gate")

        ctor.assert_not_called()
        assert not [r for r in caplog.records if r.levelno >= logging.WARNING], (
            f"function mode must not log a failure: {[r.getMessage() for r in caplog.records]}"
        )
        assert "_index_document_chunks failed" not in caplog.text
        assert "doc-gate" in caplog.text  # the skip itself is still visible at INFO
        assert not _scored(mock_event)

    def test_indexes_a_catalog_course_when_the_embedding_arrives_as_a_string(self, monkeypatch):
        """#628 regression. PostgREST returns the catalog row's pgvector
        embedding as a STRING. The old gate zipped floats against that string's
        characters -> TypeError -> swallowed -> the document was never indexed
        while the upload reported success. Confirmed live: prod had 5 indexable
        documents on a catalog course and 0 document chunks."""
        monkeypatch.setenv("SAPLING_MODEL_MODE", "real")
        vec = [1.0] + [0.0] * 767

        with (
            _tables(
                courses_rows=[{"course_code": "CAS CS 132"}],
                course_chunks_rows=[{"embedding": _pgvector_wire(vec)}],
            ),
            patch("services.chunker.chunk_for_category", return_value=["chunk one"]),
            patch("services.rag_service._embed_document", return_value=vec),
            patch(
                "services.rag_service.index_document_chunks", return_value=1
            ) as mock_index,
            patch("routes.documents.events_service.log_event") as mock_event,
        ):
            _run(doc_id="doc-628")

        mock_index.assert_called_once_with(
            course_code="CAS CS 132",
            doc_id="doc-628",
            uploader_id="user-1",
            chunks=["chunk one"],
            visibility="shared",
        )
        assert _scored(mock_event)[0].kwargs["payload"]["score"] == 1.0

    def test_low_relevance_is_recorded_but_does_not_block_indexing(self, monkeypatch):
        """The relevance check is OBSERVE-ONLY (#628). It compares a whole
        document against one paragraph of catalog blurb, on a threshold nobody
        calibrated because the gate crashed before ever producing a score.
        Until real scores exist it must never drop a student's upload — it
        records the score so a threshold can be chosen from data."""
        monkeypatch.setenv("SAPLING_MODEL_MODE", "real")

        with (
            _tables(
                courses_rows=[{"course_code": "CAS CS 132"}],
                course_chunks_rows=[{"embedding": _pgvector_wire([1.0, 0.0])}],
            ),
            patch("services.chunker.chunk_for_category", return_value=["chunk one"]),
            patch("services.rag_service._embed_document", return_value=[0.0, 1.0]),  # orthogonal
            patch(
                "services.rag_service.index_document_chunks", return_value=1
            ) as mock_index,
            patch("routes.documents.events_service.log_event") as mock_event,
        ):
            _run(doc_id="doc-offtopic", category="assignment")

        mock_index.assert_called_once()
        scored = _scored(mock_event)
        assert len(scored) == 1
        assert scored[0].kwargs["category"] == "usage"
        assert scored[0].kwargs["payload"] == {
            "doc_id": "doc-offtopic",
            "course_id": "CAS CS 132",
            "category": "assignment",
            "sample": "first_chunk",
            "score": 0.0,
        }

    def test_the_score_records_which_sample_produced_it(self, monkeypatch):
        """An LLM-written abstract and a raw first chunk (title page, header)
        score on different distributions. A threshold picked from an unlabelled
        mix of the two is calibrated on neither."""
        monkeypatch.setenv("SAPLING_MODEL_MODE", "real")

        with (
            _tables(
                courses_rows=[{"course_code": "CAS CS 132"}],
                course_chunks_rows=[{"embedding": _pgvector_wire([1.0, 0.0])}],
            ),
            patch("services.chunker.chunk_for_category", return_value=["chunk one"]),
            patch("services.rag_service._embed_document", return_value=[1.0, 0.0]) as mock_embed,
            patch("services.rag_service.index_document_chunks", return_value=1),
            patch("routes.documents.events_service.log_event") as mock_event,
        ):
            _run(doc_id="doc-sum", doc_summary="An abstract of the lecture.")

        mock_embed.assert_called_once_with("An abstract of the lecture.")
        assert _scored(mock_event)[0].kwargs["payload"]["sample"] == "summary"

    def test_scoring_runs_after_indexing_never_before(self, monkeypatch):
        """The score is advisory; the index is the point. Scoring first put an
        extra embed call (and a rate-limit sleep) in front of every upload's
        indexing, and a 429 on it landed the batch embed straight into the same
        exhausted quota. Indexing first means no scoring outcome can touch it."""
        monkeypatch.setenv("SAPLING_MODEL_MODE", "real")
        order: list[str] = []

        with (
            _tables(
                courses_rows=[{"course_code": "CAS CS 132"}],
                course_chunks_rows=[{"embedding": _pgvector_wire([1.0, 0.0])}],
            ),
            patch("services.chunker.chunk_for_category", return_value=["chunk one"]),
            patch(
                "services.rag_service._embed_document",
                side_effect=lambda t: order.append("score") or [1.0, 0.0],
            ),
            patch(
                "services.rag_service.index_document_chunks",
                side_effect=lambda **k: order.append("index") or 1,
            ),
            patch("routes.documents.events_service.log_event"),
            patch("time.sleep", side_effect=AssertionError("no sleep on the indexing path")),
        ):
            _run()

        assert order == ["index", "score"]

    def test_nothing_is_scored_when_nothing_was_indexed(self, monkeypatch):
        """A document with no chunks in retrieval is not a calibration data
        point, and a total embed outage should not also spend a scoring call
        against the same dead quota."""
        monkeypatch.setenv("SAPLING_MODEL_MODE", "real")

        with (
            _tables(
                courses_rows=[{"course_code": "CAS CS 132"}],
                course_chunks_rows=[{"embedding": _pgvector_wire([1.0, 0.0])}],
            ),
            patch("services.chunker.chunk_for_category", return_value=["chunk one"]),
            patch("services.rag_service._embed_document") as mock_embed,
            patch("services.rag_service.index_document_chunks", return_value=0),
        ):
            _run()

        mock_embed.assert_not_called()

    def test_a_failed_relevance_score_is_logged_and_harmless(self, monkeypatch, caplog):
        monkeypatch.setenv("SAPLING_MODEL_MODE", "real")

        with (
            _tables(
                courses_rows=[{"course_code": "CAS CS 132"}],
                course_chunks_rows=[{"embedding": _pgvector_wire([1.0, 0.0])}],
            ),
            patch("services.chunker.chunk_for_category", return_value=["chunk one"]),
            patch("services.rag_service._embed_document", side_effect=Exception("embed 429")),
            patch(
                "services.rag_service.index_document_chunks", return_value=1
            ) as mock_index,
            caplog.at_level(logging.WARNING, logger="routes.documents"),
        ):
            _run(doc_id="doc-429")

        mock_index.assert_called_once()
        assert "relevance" in caplog.text and "doc-429" in caplog.text
        assert "_index_document_chunks failed" not in caplog.text

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

        with (
            _tables(
                courses_rows=[{"course_code": "BIO-101"}],
                course_chunks_rows=[{"embedding": _pgvector_wire(vec)}],
            ),
            patch("services.chunker.chunk_for_category", return_value=["chunk one"]),
            patch(
                "services.rag_service.embed_document_text", return_value=vec
            ) as mock_embed,
            patch(
                "services.rag_service.index_document_chunks", return_value=1
            ) as mock_index,
            patch("routes.documents.events_service.log_event"),
        ):
            _run(doc_id="doc-real")

        ctor.assert_not_called()
        mock_embed.assert_called_once_with("chunk one")
        mock_index.assert_called_once()

    def test_category_is_passed_to_chunker(self):
        """The document's category must reach the chunker so prose docs get
        the prose strategy."""
        with (
            _tables(courses_rows=[{"course_code": "ENG-201"}], course_chunks_rows=[]),
            patch(
                "services.chunker.chunk_for_category",
                return_value=["one chunk of prose"],
            ) as mock_chunk,
            patch("services.rag_service.index_document_chunks", return_value=1),
        ):
            _run(doc_id="doc-3", category="assignment")

        mock_chunk.assert_called_once_with("some extracted text", "assignment")


class TestVisibilityAtIndexTime:
    """#629: the uploader's STORED Class Intel opt-in decides whether the
    chunks join the shared course pool. Before this, every upload did."""

    def test_an_opted_in_upload_is_indexed_shared(self):
        with (
            _tables(courses_rows=[{"course_code": "BIO-101"}], course_chunks_rows=[]),
            patch("services.chunker.chunk_for_category", return_value=["c1"]),
            patch("services.rag_service.index_document_chunks", return_value=1) as mock_index,
            patch("services.chunk_visibility.shares_class_context", return_value=True),
            patch("routes.documents.events_service.log_event"),
        ):
            _run()

        assert mock_index.call_args.kwargs["visibility"] == "shared"

    def test_an_opted_out_upload_is_indexed_private(self):
        with (
            _tables(courses_rows=[{"course_code": "BIO-101"}], course_chunks_rows=[]),
            patch("services.chunker.chunk_for_category", return_value=["c1"]),
            patch("services.rag_service.index_document_chunks", return_value=1) as mock_index,
            patch("services.chunk_visibility.shares_class_context", return_value=False),
            patch("routes.documents.events_service.log_event"),
        ):
            _run()

        assert mock_index.call_args.kwargs["visibility"] == "private"

    def test_the_flag_is_read_for_the_UPLOADER(self):
        """Not for some ambient user: the row being written belongs to whoever
        uploaded it, and that is the consent that matters."""
        with (
            _tables(courses_rows=[{"course_code": "BIO-101"}], course_chunks_rows=[]),
            patch("services.chunker.chunk_for_category", return_value=["c1"]),
            patch("services.rag_service.index_document_chunks", return_value=1),
            patch("services.chunk_visibility.visibility_for", return_value="shared") as mock_vis,
            patch("routes.documents.events_service.log_event"),
        ):
            _run()

        mock_vis.assert_called_once_with("user-1")
