"""#629: quiz grounding reads the course pool AS the student taking the quiz.

`_course_material` fed `retrieve_chunks_detailed` a course code and nothing
else, so the RPC could not tell one reader from another. Once `visibility`
exists, an un-threaded caller is not merely imprecise — it silently drops the
student's own private uploads out of their own quiz, and (before the RPC
filtered at all) served a classmate's.
"""
from unittest.mock import MagicMock, patch

from services.rag_service import Retrieval


def _material(user_id="user_1", chunks=(), catalog=""):
    from routes.quiz import _course_material

    with (
        patch("routes.quiz._resolve_bu_code") as mock_resolve,
        patch("routes.quiz._get_catalog_chunk", return_value=catalog),
        patch(
            "routes.quiz.retrieve_chunks_detailed",
            return_value=Retrieval(chunks=list(chunks)),
        ) as mock_retrieve,
        patch("routes.quiz.table") as mock_table,
    ):
        from routes.quiz import BuCodeLookup

        mock_resolve.return_value = BuCodeLookup(code="CAS CS 330", failed=False)
        mock_table.return_value.select_with_count.return_value = ([], 0)
        result = _course_material("course-uuid", "dynamic programming", user_id=user_id)
    return result, mock_retrieve, mock_table


def test_course_material_passes_the_student_as_the_retrieval_reader():
    _, mock_retrieve, _ = _material(user_id="user_1")
    assert mock_retrieve.call_args.kwargs["user_id"] == "user_1"


def test_coverage_count_is_scoped_to_what_this_student_could_retrieve():
    """`course_chunks=0` is E8's "this course has nothing indexed" signal. An
    unscoped count would report a course as covered on the strength of rows
    the student is not allowed to see, sending grounding diagnosis the wrong
    way for exactly the students the privacy filter applies to."""
    _, _, mock_table = _material(user_id="user_1")

    filters = mock_table.return_value.select_with_count.call_args.kwargs["filters"]
    assert "or" in filters, filters
    assert "visibility.eq.shared" in filters["or"]
    # Quoted per `pg_quote_value` — a bare operand ends at the first comma or
    # paren inside a logic tree.
    assert 'uploader_id.eq."user_1"' in filters["or"]


def test_coverage_count_without_a_reader_counts_shared_rows_only():
    from routes.quiz import _course_chunk_coverage

    tbl = MagicMock()
    tbl.select_with_count.return_value = ([], 7)
    with patch("routes.quiz.table", return_value=tbl):
        assert _course_chunk_coverage("CAS CS 330", None) == 7

    filters = tbl.select_with_count.call_args.kwargs["filters"]
    assert filters["visibility"] == "eq.shared"
    assert "or" not in filters


def test_generate_threads_the_quiz_taker_through_to_grounding():
    """Through the real route, so a refactor that drops the argument at the
    `asyncio.to_thread` call site is caught and not just at the signature."""
    from unittest.mock import AsyncMock

    from tests.test_quiz_routes import TestQuizGrounding, client

    harness = TestQuizGrounding()
    agent_run = AsyncMock(return_value=harness._valid_quiz_result())
    with (
        patch("routes.quiz.table", side_effect=harness._table_factory()),
        patch("routes.quiz.quiz_agent.run", new=agent_run),
        patch("routes.quiz._get_catalog_chunk", return_value=""),
        patch(
            "routes.quiz.retrieve_chunks_detailed", return_value=Retrieval(chunks=[])
        ) as mock_retrieve,
    ):
        r = client.post("/api/quiz/generate", json={
            "user_id": "user_1", "concept_node_id": "node_x",
            "num_questions": 1, "difficulty": "easy", "use_shared_context": False,
        })

    assert r.status_code == 200
    assert mock_retrieve.call_args.kwargs["user_id"] == "user_1"
