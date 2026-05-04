"""
Unit tests for routes/documents.py

Tests cover:
  - GET  /api/documents/user/{user_id}   → list_documents
  - DELETE /api/documents/doc/{doc_id}   → delete_document
  - PATCH /api/documents/doc/{doc_id}    → update_document
  - POST /api/documents/upload           → upload_document

All Gemini calls, DB access, and file-extraction are mocked.
"""
import io
import json
from types import SimpleNamespace
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from fastapi.testclient import TestClient

from main import app
from routes.documents import _process_document

client = TestClient(app)


def _mock_validate_user():
    """Patch _validate_user to always succeed."""
    return patch("routes.documents._validate_user", return_value=None)


# ── GET /api/documents/user/{user_id} ────────────────────────────────────────

class TestListDocuments:
    def test_returns_documents_for_user(self):
        docs = [
            {"id": "d1", "user_id": "u1", "file_name": "notes.pdf", "category": "lecture_notes"},
            {"id": "d2", "user_id": "u1", "file_name": "syllabus.pdf", "category": "syllabus"},
        ]
        with _mock_validate_user(), patch("routes.documents.table") as t:
            t.return_value.select.return_value = docs
            r = client.get("/api/documents/user/u1")

        assert r.status_code == 200
        assert r.json()["documents"] == docs

    def test_returns_empty_list_when_no_documents(self):
        with _mock_validate_user(), patch("routes.documents.table") as t:
            t.return_value.select.return_value = []
            r = client.get("/api/documents/user/u1")

        assert r.status_code == 200
        assert r.json()["documents"] == []

    def test_queries_correct_user(self):
        with _mock_validate_user(), patch("routes.documents.table") as t:
            t.return_value.select.return_value = []
            client.get("/api/documents/user/user_andres")
            t.assert_called_with("documents")
            t.return_value.select.assert_called_once()
            call_kwargs = t.return_value.select.call_args
            # filters should contain the user_id
            assert "user_andres" in str(call_kwargs)


# ── DELETE /api/documents/doc/{document_id} ──────────────────────────────────

class TestDeleteDocument:
    def test_returns_deleted_true(self):
        with patch("routes.documents.table") as t:
            t.return_value.delete.return_value = None
            r = client.delete("/api/documents/doc/d1")

        assert r.status_code == 200
        assert r.json() == {"deleted": True}

    def test_calls_delete_with_correct_id(self):
        with patch("routes.documents.table") as t:
            t.return_value.delete.return_value = None
            client.delete("/api/documents/doc/my-doc-uuid")
            t.assert_called_with("documents")
            call_kwargs = t.return_value.delete.call_args
            assert "my-doc-uuid" in str(call_kwargs)

    def test_delete_with_user_validation(self):
        with _mock_validate_user(), patch("routes.documents.table") as t:
            t.return_value.select.return_value = [{"id": "d1"}]
            t.return_value.delete.return_value = None
            r = client.delete("/api/documents/doc/d1?user_id=u1")

        assert r.status_code == 200
        assert r.json() == {"deleted": True}

    def test_delete_returns_404_when_doc_not_owned(self):
        with _mock_validate_user(), patch("routes.documents.table") as t:
            t.return_value.select.return_value = []
            r = client.delete("/api/documents/doc/d1?user_id=u1")

        assert r.status_code == 404


# ── PATCH /api/documents/doc/{document_id} ───────────────────────────────────

class TestUpdateDocument:
    def test_updates_category(self):
        with patch("routes.documents.table") as t:
            t.return_value.update.return_value = [{"id": "d1", "category": "slides"}]
            r = client.patch("/api/documents/doc/d1", json={"category": "slides"})

        assert r.status_code == 200
        assert r.json()["category"] == "slides"

    def test_rejects_invalid_category(self):
        r = client.patch("/api/documents/doc/d1", json={"category": "bogus"})
        assert r.status_code == 400

    def test_rejects_empty_update(self):
        r = client.patch("/api/documents/doc/d1", json={})
        assert r.status_code == 400

    def test_update_with_user_validation(self):
        with _mock_validate_user(), patch("routes.documents.table") as t:
            t.return_value.select.return_value = [{"id": "d1"}]
            t.return_value.update.return_value = [{"id": "d1", "category": "reading"}]
            r = client.patch("/api/documents/doc/d1", json={"category": "reading", "user_id": "u1"})

        assert r.status_code == 200


# ── POST /api/documents/upload ───────────────────────────────────────────────

def _make_upload(
    filename="notes.pdf",
    content_type="application/pdf",
    content=b"%PDF-1.4 sample content for testing",
    course_id="course-1",
    user_id="u1",
):
    """Helper: build a multipart upload request.

    Targets /upload/sync so the response is a single JSON dict (the
    legacy contract). The streaming /upload route is exercised
    separately in stream-specific tests.
    """
    return client.post(
        "/api/documents/upload/sync",
        files={"file": (filename, io.BytesIO(content), content_type)},
        data={"course_id": course_id, "user_id": user_id},
    )


class TestProcessDocumentHelper:
    """Direct unit tests for _process_document.

    These bypass the FastAPI route entirely (they call the helper
    directly), so they must NOT be inside TestUploadDocument or they
    needlessly trip the orchestrator-fallback autouse fixture.
    """

    def test_coerces_garbage_into_safe_shape(self):
        """When the LLM emits the wrong types, _process_document normalizes them."""
        garbage = {
            "category": "not-a-real-category",
            "summary": 12345,
            "key_takeaways": "should be a list, not a string",
            "assignments": "not a list either",
            "concept_notes": "Linear Regression, Big-O",  # string instead of list
        }
        with patch("routes.documents.call_gemini_json", return_value=garbage):
            result = _process_document("file.pdf", "text")

        assert result["category"] == "other"
        assert result["summary"] == ""  # int coerced to ""
        assert result["assignments"] == []
        assert result["concept_notes"] == []
        assert result["concepts"] == []

    def test_strips_invalid_concept_notes(self):
        ai_result = {
            "category": "syllabus",
            "summary": "S",
            "key_takeaways": [],
            "assignments": [],
            "concept_notes": [
                {"name": "  Linear Regression  ", "description": "Fits a line."},
                {"name": "Big-O", "description": ""},  # empty desc dropped
                {"name": "", "description": "no name"},  # empty name dropped
                {"description": "no name field"},  # missing name dropped
                "not a dict",  # wrong type dropped
                {"name": "Cross-Entropy", "description": "Loss for classification."},
            ],
        }
        with patch("routes.documents.call_gemini_json", return_value=ai_result):
            result = _process_document("file.pdf", "text")

        assert result["concept_notes"] == [
            {"name": "Linear Regression", "description": "Fits a line."},
            {"name": "Cross-Entropy", "description": "Loss for classification."},
        ]
        assert result["concepts"] == ["Linear Regression", "Cross-Entropy"]

    def test_handles_non_dict_response(self):
        with patch("routes.documents.call_gemini_json", return_value=["not", "a", "dict"]):
            result = _process_document("file.pdf", "text")

        assert result["category"] == "other"
        assert result["concepts"] == []
        assert result["concept_notes"] == []
        assert result["assignments"] == []


class TestUploadDocument:
    @pytest.fixture(autouse=True)
    def _force_legacy_pipeline(self):
        """Route every upload-test through _legacy_upload_pipeline.

        These tests assert against the legacy AI shape (call_gemini_json
        return value, apply_graph_update calls keyed off concept_notes).
        Forcing process_document to raise sends the route into its
        documented fallback, which is exactly the legacy code path the
        existing mocks were written for.
        """
        with patch(
            "routes.documents.process_document",
            side_effect=RuntimeError("force legacy fallback for tests"),
        ):
            yield
    # ── File-type validation ───────────────────────────────────────────────────

    def test_rejects_unsupported_extension(self):
        with _mock_validate_user():
            r = _make_upload(filename="notes.txt", content_type="text/plain", content=b"hello")
        assert r.status_code == 400
        assert "Unsupported file type" in r.json()["detail"]

    def test_rejects_file_over_100mb(self):
        # Cap was raised from 15 MB → 100 MB in commit 9912a25.
        big = b"x" * (100 * 1024 * 1024 + 1)
        with _mock_validate_user(), patch("routes.documents.extract_text_from_file", return_value=""):
            r = _make_upload(content=big)
        assert r.status_code == 400
        assert "100 MB" in r.json()["detail"]

    def test_accepts_pdf_by_extension(self):
        ai_result = {
            "category": "lecture_notes",
            "summary": "Test summary",
            "key_takeaways": ["point 1"],
            "flashcards": [{"question": "Q?", "answer": "A"}],
        }
        row = {"id": "d1", "file_name": "notes.pdf"}
        with (
            _mock_validate_user(),
            patch("routes.documents.extract_text_from_file", return_value="pdf text"),
            patch("routes.documents.call_gemini_json", return_value=ai_result),
            patch("routes.documents.table") as t,
        ):
            t.return_value.insert.return_value = [row]
            r = _make_upload(filename="notes.pdf", content_type="application/pdf")

        assert r.status_code == 200
        assert r.json()["file_name"] == "notes.pdf"

    def test_accepts_docx_by_extension(self):
        ai_result = {
            "category": "reading",
            "summary": "A reading",
            "key_takeaways": [],
            "flashcards": [],
        }
        row = {"id": "d2", "file_name": "chapter.docx"}
        with (
            _mock_validate_user(),
            patch("routes.documents.extract_text_from_file", return_value="docx text"),
            patch("routes.documents.call_gemini_json", return_value=ai_result),
            patch("routes.documents.table") as t,
        ):
            t.return_value.insert.return_value = [row]
            ct = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
            r = _make_upload(filename="chapter.docx", content_type=ct)

        assert r.status_code == 200

    def test_accepts_pptx_by_extension(self):
        ai_result = {
            "category": "slides",
            "summary": "Slides summary",
            "key_takeaways": [],
            "flashcards": [],
        }
        row = {"id": "d3", "file_name": "lecture.pptx"}
        with (
            _mock_validate_user(),
            patch("routes.documents.extract_text_from_file", return_value="pptx text"),
            patch("routes.documents.call_gemini_json", return_value=ai_result),
            patch("routes.documents.table") as t,
        ):
            t.return_value.insert.return_value = [row]
            ct = "application/vnd.openxmlformats-officedocument.presentationml.presentation"
            r = _make_upload(filename="lecture.pptx", content_type=ct)

        assert r.status_code == 200

    # ── AI classification ─────────────────────────────────────────────────────

    def test_stores_ai_category_summary_takeaways_flashcards(self):
        ai_result = {
            "category": "study_guide",
            "summary": "A comprehensive study guide",
            "key_takeaways": ["concept A", "concept B"],
            "flashcards": [{"question": "What is X?", "answer": "X is Y"}],
        }
        inserted_row = {"id": "d4", "category": "study_guide", "summary": "A comprehensive study guide"}
        with (
            _mock_validate_user(),
            patch("routes.documents.extract_text_from_file", return_value="some text"),
            patch("routes.documents.call_gemini_json", return_value=ai_result),
            patch("routes.documents.table") as t,
        ):
            t.return_value.insert.return_value = [inserted_row]
            r = _make_upload()

        assert r.status_code == 200
        assert r.json()["category"] == "study_guide"

    def test_unknown_ai_category_falls_back_to_other(self):
        ai_result = {
            "category": "invalid_category_xyz",
            "summary": "Something",
            "key_takeaways": [],
            "flashcards": [],
        }
        with (
            _mock_validate_user(),
            patch("routes.documents.extract_text_from_file", return_value="text"),
            patch("routes.documents.call_gemini_json", return_value=ai_result),
            patch("routes.documents.table") as t,
        ):
            t.return_value.insert.return_value = [{"id": "d5", "category": "other"}]
            r = _make_upload()

        assert r.status_code == 200
        # The insert call should have received category="other"
        insert_call = t.return_value.insert.call_args[0][0]
        assert insert_call["category"] == "other"

    # ── Syllabus auto-extraction ───────────────────────────────────────────────

    def test_syllabus_triggers_assignment_extraction(self):
        assignments = [{"title": "HW 1", "due_date": "2026-04-01"}]
        ai_result = {
            "category": "syllabus",
            "summary": "Course syllabus",
            "key_takeaways": [],
            "flashcards": [],
            "assignments": assignments,
        }
        with (
            _mock_validate_user(),
            patch("routes.documents.extract_text_from_file", return_value="syllabus text"),
            patch("routes.documents.call_gemini_json", return_value=ai_result),
            patch("routes.documents.save_assignments_to_db") as mock_save,
            patch("routes.documents.table") as t,
        ):
            t.return_value.insert.return_value = [{"id": "d6"}]
            r = _make_upload(filename="syllabus.pdf")

        assert r.status_code == 200
        mock_save.assert_called_once_with("u1", assignments)

    def test_non_syllabus_skips_assignment_extraction(self):
        ai_result = {
            "category": "lecture_notes",
            "summary": "Lecture notes",
            "key_takeaways": [],
            "flashcards": [],
        }
        with (
            _mock_validate_user(),
            patch("routes.documents.extract_text_from_file", return_value="notes text"),
            patch("routes.documents.call_gemini_json", return_value=ai_result),
            patch("routes.documents.save_assignments_to_db") as mock_save,
            patch("routes.documents.table") as t,
        ):
            t.return_value.insert.return_value = [{"id": "d7"}]
            r = _make_upload()

        assert r.status_code == 200
        mock_save.assert_not_called()

    def test_syllabus_populates_graph_concepts(self):
        ai_result = {
            "category": "syllabus",
            "summary": "Course syllabus",
            "key_takeaways": [],
            "assignments": [],
            "concept_notes": [
                {"name": "Linear Regression", "description": "Fits a line."},
                {"name": "Big-O Analysis", "description": "Asymptotic growth."},
            ],
        }
        with (
            _mock_validate_user(),
            patch("routes.documents.extract_text_from_file", return_value="syllabus text"),
            patch("routes.documents.call_gemini_json", return_value=ai_result),
            patch("routes.documents.save_assignments_to_db"),
            patch("routes.documents.apply_graph_update") as mock_apply,
            patch("routes.documents.table") as t,
        ):
            t.return_value.insert.return_value = [{"id": "d_concept"}]
            r = _make_upload(filename="syllabus.pdf", course_id="course-42", user_id="u1")

        assert r.status_code == 200
        mock_apply.assert_called_once()
        args, kwargs = mock_apply.call_args
        assert args[0] == "u1"
        assert kwargs["course_id"] == "course-42"
        new_nodes = args[1]["new_nodes"]
        assert [n["concept_name"] for n in new_nodes] == ["Linear Regression", "Big-O Analysis"]
        assert all(n["initial_mastery"] == 0.0 for n in new_nodes)

    def test_assignment_populates_graph_concepts(self):
        ai_result = {
            "category": "assignment",
            "summary": "Problem set 3",
            "key_takeaways": [],
            "assignments": [],
            "concept_notes": [
                {"name": "Gradient Descent", "description": "Iterative minimization."},
                {"name": "Cross-Entropy Loss", "description": "Classification loss."},
            ],
        }
        with (
            _mock_validate_user(),
            patch("routes.documents.extract_text_from_file", return_value="pset text"),
            patch("routes.documents.call_gemini_json", return_value=ai_result),
            patch("routes.documents.save_assignments_to_db") as mock_save,
            patch("routes.documents.apply_graph_update") as mock_apply,
            patch("routes.documents.table") as t,
        ):
            t.return_value.insert.return_value = [{"id": "d_assign_concept"}]
            r = _make_upload(filename="pset3.pdf", course_id="course-7", user_id="u1")

        assert r.status_code == 200
        mock_save.assert_not_called()
        mock_apply.assert_called_once()
        args, kwargs = mock_apply.call_args
        assert args[0] == "u1"
        assert kwargs["course_id"] == "course-7"
        assert [n["concept_name"] for n in args[1]["new_nodes"]] == ["Gradient Descent", "Cross-Entropy Loss"]

    def test_non_syllabus_non_assignment_skips_concept_population(self):
        ai_result = {
            "category": "lecture_notes",
            "summary": "Notes",
            "key_takeaways": [],
            "concept_notes": [
                {"name": "Should be ignored", "description": "..."},
            ],
        }
        with (
            _mock_validate_user(),
            patch("routes.documents.extract_text_from_file", return_value="notes"),
            patch("routes.documents.call_gemini_json", return_value=ai_result),
            patch("routes.documents.apply_graph_update") as mock_apply,
            patch("routes.documents.table") as t,
        ):
            t.return_value.insert.return_value = [{"id": "d_no_concept"}]
            r = _make_upload()

        assert r.status_code == 200
        mock_apply.assert_not_called()

    def test_concept_population_failure_does_not_fail_upload(self):
        ai_result = {
            "category": "syllabus",
            "summary": "Syllabus",
            "key_takeaways": [],
            "assignments": [],
            "concept_notes": [{"name": "Concept A", "description": "Body."}],
        }
        with (
            _mock_validate_user(),
            patch("routes.documents.extract_text_from_file", return_value="text"),
            patch("routes.documents.call_gemini_json", return_value=ai_result),
            patch("routes.documents.save_assignments_to_db"),
            patch("routes.documents.apply_graph_update", side_effect=RuntimeError("oops")),
            patch("routes.documents.table") as t,
        ):
            t.return_value.insert.return_value = [{"id": "d_concept_fail"}]
            r = _make_upload(filename="syllabus.pdf")

        assert r.status_code == 200

    def test_syllabus_extraction_failure_does_not_fail_upload(self):
        """Assignment save errors must be swallowed so the upload succeeds."""
        ai_result = {
            "category": "syllabus",
            "summary": "Syllabus",
            "key_takeaways": [],
            "flashcards": [],
            "assignments": [{"title": "HW 1", "due_date": "2026-04-01"}],
        }
        with (
            _mock_validate_user(),
            patch("routes.documents.extract_text_from_file", return_value="text"),
            patch("routes.documents.call_gemini_json", return_value=ai_result),
            patch("routes.documents.save_assignments_to_db", side_effect=RuntimeError("oops")),
            patch("routes.documents.table") as t,
        ):
            t.return_value.insert.return_value = [{"id": "d8"}]
            r = _make_upload(filename="syllabus.pdf")

        assert r.status_code == 200

    # ── Row persistence ───────────────────────────────────────────────────────

    def test_persisted_row_contains_user_and_course(self):
        ai_result = {
            "category": "other",
            "summary": "s",
            "key_takeaways": [],
            "flashcards": [],
        }
        with (
            _mock_validate_user(),
            patch("routes.documents.extract_text_from_file", return_value="t"),
            patch("routes.documents.call_gemini_json", return_value=ai_result),
            patch("routes.documents.table") as t,
        ):
            t.return_value.insert.return_value = []
            _make_upload(course_id="c-99", user_id="user_andres")
            insert_call = t.return_value.insert.call_args[0][0]

        assert insert_call["user_id"] == "user_andres"
        assert insert_call["course_id"] == "c-99"

    def test_falls_back_to_row_dict_when_insert_returns_empty(self):
        """If table.insert returns [], the endpoint should return the constructed row dict."""
        ai_result = {
            "category": "other",
            "summary": None,
            "key_takeaways": None,
            "flashcards": None,
        }
        with (
            _mock_validate_user(),
            patch("routes.documents.extract_text_from_file", return_value="t"),
            patch("routes.documents.call_gemini_json", return_value=ai_result),
            patch("routes.documents.table") as t,
        ):
            t.return_value.insert.return_value = []
            r = _make_upload(filename="notes.pdf")

        assert r.status_code == 200
        assert r.json()["file_name"] == "notes.pdf"

    def test_sync_ocr_failure_returns_422_not_500(self):
        """An extractor exception must surface as a clean 4xx with a friendly
        detail, not a 500 with stack trace leaked through the body."""
        with (
            _mock_validate_user(),
            patch(
                "routes.documents.extract_text_from_file",
                side_effect=RuntimeError("scanned PDF too noisy"),
            ),
        ):
            r = _make_upload(filename="bad-scan.pdf")
        assert r.status_code == 422
        detail = r.json().get("detail", "")
        assert "different file" in detail.lower()
        # The global handler attaches request_id to error bodies.
        assert "request_id" in r.json()


# ── POST /api/documents/upload/sync — orchestrator success path ─────────────

def _make_orchestrator_result(
    *,
    category="lecture_notes",
    is_syllabus=False,
    summary_abstract="A concise overview.",
    concept_names=None,
    syllabus_assignments=None,
    grading_categories=None,
    course_title=None,
    graph_updated=False,
):
    """Build a DocumentProcessingResult with sensible defaults for tests."""
    from agents.classifier import DocumentClassification
    from agents.summary import Summary
    from agents.concept_extraction import Concept, ConceptList
    from agents.syllabus_extraction import (
        SyllabusAssignment, SyllabusAssignments, GradingCategory,
    )
    from agents.document import DocumentProcessingResult

    classification = DocumentClassification(
        category=category, is_syllabus=is_syllabus,
        confidence=0.9, rationale="test",
    )
    summary = Summary(
        headline="Test doc",
        abstract=summary_abstract,
        key_points=["a", "b", "c"],
    )
    concepts = ConceptList(concepts=[
        Concept(name=n, description="d", importance=0.5)
        for n in (concept_names or ["Concept A"])
    ])
    syllabus = None
    if is_syllabus:
        syllabus = SyllabusAssignments(
            course_title=course_title,
            instructor=None,
            assignments=[
                SyllabusAssignment(**a) for a in (syllabus_assignments or [])
            ],
            grading_categories=[
                GradingCategory(**c) for c in (grading_categories or [])
            ],
        )
    return DocumentProcessingResult(
        classification=classification,
        summary=summary,
        concepts=concepts,
        syllabus=syllabus,
        graph_updated=graph_updated,
    )


class TestUploadDocumentOrchestrator:
    """Coverage for the orchestrator success path of /upload/sync.

    Mocks process_document to RETURN a DocumentProcessingResult (vs the
    legacy-fallback class above which raises). This exercises
    _persist_document, _save_orchestrator_syllabus, _graph_backstop,
    and _grading_categories_from in routes/documents.py.
    """

    def test_returns_persisted_row_for_lecture_notes(self):
        result = _make_orchestrator_result(
            category="lecture_notes",
            concept_names=["Backpropagation", "Chain Rule"],
        )
        row = {"id": "doc-1", "file_name": "notes.pdf", "category": "lecture_notes"}
        with (
            _mock_validate_user(),
            patch("routes.documents.extract_text_from_file", return_value="text"),
            patch("routes.documents.process_document", return_value=result),
            patch("routes.documents.table") as t,
        ):
            t.return_value.insert.return_value = [row]
            r = _make_upload(filename="notes.pdf")
        assert r.status_code == 200
        body = r.json()
        assert body["category"] == "lecture_notes"
        assert body["file_name"] == "notes.pdf"
        assert body["categories"] == []  # non-syllabus → empty grading buckets

    def test_persists_summary_plaintext_in_response(self):
        """Response carries plaintext summary even though insert encrypts."""
        result = _make_orchestrator_result(
            summary_abstract="Plain English summary.",
        )
        with (
            _mock_validate_user(),
            patch("routes.documents.extract_text_from_file", return_value="text"),
            patch("routes.documents.process_document", return_value=result),
            patch("routes.documents.table") as t,
        ):
            t.return_value.insert.return_value = []
            r = _make_upload()
        assert r.status_code == 200
        assert r.json()["summary"] == "Plain English summary."

    def test_syllabus_grading_categories_pass_through_to_response(self):
        result = _make_orchestrator_result(
            category="syllabus",
            is_syllabus=True,
            grading_categories=[
                {"name": "Exams", "weight": 40},
                {"name": "Homework", "weight": 30},
                {"name": "Final", "weight": 30},
            ],
        )
        with (
            _mock_validate_user(),
            patch("routes.documents.extract_text_from_file", return_value="text"),
            patch("routes.documents.process_document", return_value=result),
            patch("routes.documents.save_assignments_to_db"),
            patch("routes.documents.apply_graph_update"),
            patch("routes.documents.table") as t,
        ):
            t.return_value.insert.return_value = [{"id": "s1"}]
            r = _make_upload(filename="syllabus.pdf")
        assert r.status_code == 200
        cats = r.json()["categories"]
        assert [c["name"] for c in cats] == ["Exams", "Homework", "Final"]
        assert [c["weight"] for c in cats] == [40.0, 30.0, 30.0]

    def test_syllabus_grading_categories_pass_through_points_based(self):
        """Weights > 100 (points-based grading) flow through unchanged.

        The contract is "stated weight verbatim — do not normalize", so a
        rubric like 'Final 200 points, Midterm 150 points' must reach the
        frontend as 200.0 and 150.0, not normalized to percent.
        """
        result = _make_orchestrator_result(
            category="syllabus",
            is_syllabus=True,
            grading_categories=[
                {"name": "Final", "weight": 200},
                {"name": "Midterm", "weight": 150},
                {"name": "Quizzes", "weight": 50},
            ],
        )
        with (
            _mock_validate_user(),
            patch("routes.documents.extract_text_from_file", return_value="text"),
            patch("routes.documents.process_document", return_value=result),
            patch("routes.documents.save_assignments_to_db"),
            patch("routes.documents.apply_graph_update"),
            patch("routes.documents.table") as t,
        ):
            t.return_value.insert.return_value = [{"id": "s_pts"}]
            r = _make_upload(filename="syllabus.pdf")
        assert r.status_code == 200
        cats = r.json()["categories"]
        assert [c["weight"] for c in cats] == [200.0, 150.0, 50.0]

    def test_syllabus_assignments_with_due_dates_persist(self):
        from datetime import date
        result = _make_orchestrator_result(
            category="syllabus",
            is_syllabus=True,
            course_title="CS 188",
            syllabus_assignments=[
                {"title": "PS1", "due_date": date(2026, 4, 1), "description": None},
                {"title": "Midterm", "due_date": None, "description": None},  # dropped
            ],
        )
        with (
            _mock_validate_user(),
            patch("routes.documents.extract_text_from_file", return_value="text"),
            patch("routes.documents.process_document", return_value=result),
            patch("routes.documents.save_assignments_to_db") as mock_save,
            patch("routes.documents.apply_graph_update"),
            patch("routes.documents.table") as t,
        ):
            t.return_value.insert.return_value = [{"id": "s2"}]
            r = _make_upload(filename="syllabus.pdf", course_id="c-7")
        assert r.status_code == 200
        # Only the dated assignment survives the no-invent contract.
        mock_save.assert_called_once()
        saved_user, saved_assignments = mock_save.call_args.args
        assert saved_user == "u1"
        assert len(saved_assignments) == 1
        assert saved_assignments[0]["title"] == "PS1"
        assert saved_assignments[0]["due_date"] == "2026-04-01"
        assert saved_assignments[0]["course_id"] == "c-7"

    def test_graph_backstop_fires_when_orchestrator_skipped_tool(self):
        """If graph_updated=False and category is syllabus/assignment, the
        route applies the graph update procedurally."""
        result = _make_orchestrator_result(
            category="assignment",
            concept_names=["Linear Regression", "Gradient Descent"],
            graph_updated=False,
        )
        with (
            _mock_validate_user(),
            patch("routes.documents.extract_text_from_file", return_value="text"),
            patch("routes.documents.process_document", return_value=result),
            patch("routes.documents.apply_graph_update") as mock_apply,
            patch("routes.documents.table") as t,
        ):
            t.return_value.insert.return_value = [{"id": "a1"}]
            r = _make_upload(filename="pset.pdf", course_id="c-9")
        assert r.status_code == 200
        mock_apply.assert_called_once()
        args, kwargs = mock_apply.call_args
        assert args[0] == "u1"
        assert kwargs["course_id"] == "c-9"
        assert [n["concept_name"] for n in args[1]["new_nodes"]] == [
            "Linear Regression", "Gradient Descent"
        ]

    def test_graph_backstop_skipped_when_orchestrator_already_updated(self):
        result = _make_orchestrator_result(
            category="assignment",
            concept_names=["Stuff"],
            graph_updated=True,
        )
        with (
            _mock_validate_user(),
            patch("routes.documents.extract_text_from_file", return_value="text"),
            patch("routes.documents.process_document", return_value=result),
            patch("routes.documents.apply_graph_update") as mock_apply,
            patch("routes.documents.table") as t,
        ):
            t.return_value.insert.return_value = [{"id": "a2"}]
            r = _make_upload(filename="pset.pdf")
        assert r.status_code == 200
        mock_apply.assert_not_called()

    def test_lecture_notes_skip_graph_backstop(self):
        """Backstop only fires for syllabus/assignment categories."""
        result = _make_orchestrator_result(
            category="lecture_notes", concept_names=["X"], graph_updated=False,
        )
        with (
            _mock_validate_user(),
            patch("routes.documents.extract_text_from_file", return_value="text"),
            patch("routes.documents.process_document", return_value=result),
            patch("routes.documents.apply_graph_update") as mock_apply,
            patch("routes.documents.table") as t,
        ):
            t.return_value.insert.return_value = [{"id": "l1"}]
            r = _make_upload()
        assert r.status_code == 200
        mock_apply.assert_not_called()


# ── POST /api/documents/upload — streaming SSE route ────────────────────────

def _parse_sse_stream(raw: bytes) -> list[dict]:
    """Parse an EventSourceResponse byte stream into a list of {event, data} dicts.

    SSE wire format: blank-line separated blocks; each block has lines like
    `event: <name>` and `data: <json>`. Comments and empty lines are skipped.
    """
    text = raw.decode("utf-8")
    events: list[dict] = []
    cur: dict = {}
    for line in text.splitlines():
        if not line.strip():
            if cur:
                events.append(cur)
                cur = {}
            continue
        if line.startswith(":"):
            continue
        if ":" not in line:
            continue
        field, _, value = line.partition(":")
        cur[field.strip()] = value.lstrip()
    if cur:
        events.append(cur)
    return events


class TestUploadDocumentStreaming:
    """Coverage for the SSE streaming /upload route.

    Mocks each agent's .run / .run_stream_events at the routes.documents
    seam so the test stays deterministic without hitting Gemini.
    """

    def _mock_agent_runs(self, *, is_syllabus: bool = False):
        """Build a context-manager stack patching every agent the route calls."""
        from agents.classifier import DocumentClassification
        from agents.summary import Summary
        from agents.concept_extraction import Concept, ConceptList
        from agents.syllabus_extraction import SyllabusAssignments

        cls = DocumentClassification(
            category="lecture_notes" if not is_syllabus else "syllabus",
            is_syllabus=is_syllabus, confidence=0.9, rationale="test",
        )
        summary = Summary(
            headline="h", abstract="abstract.",
            key_points=["a", "b", "c"],
        )
        concepts = ConceptList(concepts=[
            Concept(name="Backprop", description="d", importance=0.9),
        ])
        syllabus = SyllabusAssignments(
            course_title=None, instructor=None,
            assignments=[], grading_categories=[],
        ) if is_syllabus else None

        cls_run = AsyncMock(return_value=SimpleNamespace(output=cls))
        sum_run = AsyncMock(return_value=SimpleNamespace(output=summary))
        cpt_run = AsyncMock(return_value=SimpleNamespace(output=concepts))
        syl_run = AsyncMock(return_value=SimpleNamespace(output=syllabus))

        return (
            patch("routes.documents.classifier_agent.run", cls_run),
            patch("routes.documents.summary_agent.run", sum_run),
            patch("routes.documents.concept_extraction_agent.run", cpt_run),
            patch("routes.documents.syllabus_extraction_agent.run", syl_run),
            patch("routes.documents.apply_concepts_to_graph", AsyncMock(return_value=0)),
        )

    def test_emits_full_event_sequence_on_happy_path(self):
        """status:start → progress:classify → progress:classified →
        progress:extract → progress:extracted → progress:graph_update →
        progress:graph_updated → result:finalize → status:done with document_id."""
        cls_p, sum_p, cpt_p, syl_p, doc_p = self._mock_agent_runs()
        with (
            _mock_validate_user(),
            patch("routes.documents.extract_text_from_file", return_value="text"),
            cls_p, sum_p, cpt_p, syl_p, doc_p,
            patch("routes.documents.table") as t,
            patch("routes.documents._spawn_post_roll"),  # avoid stray asyncio.create_task in tests
        ):
            t.return_value.insert.return_value = [{"id": "stream-1"}]
            with client.stream(
                "POST", "/api/documents/upload",
                files={"file": ("notes.pdf", io.BytesIO(b"%PDF-1.4 x"), "application/pdf")},
                data={"course_id": "c-1", "user_id": "u1"},
            ) as r:
                assert r.status_code == 200
                body = r.read()

        events = _parse_sse_stream(body)
        types_steps = [(e["event"], json.loads(e["data"])["step"]) for e in events]
        assert types_steps == [
            ("status", "start"),
            ("progress", "classify"),
            ("progress", "classified"),
            ("progress", "extract"),
            ("progress", "extracted"),
            ("progress", "graph_update"),
            ("progress", "graph_updated"),
            ("result", "finalize"),
            ("status", "done"),
        ]
        # Final 'done' carries the persisted document_id.
        done = json.loads(events[-1]["data"])
        assert done["data"]["document_id"] == "stream-1"

    def test_includes_syllabus_event_when_is_syllabus(self):
        """progress:extract message mentions syllabus when classifier flags it."""
        cls_p, sum_p, cpt_p, syl_p, doc_p = self._mock_agent_runs(is_syllabus=True)
        with (
            _mock_validate_user(),
            patch("routes.documents.extract_text_from_file", return_value="text"),
            cls_p, sum_p, cpt_p, syl_p, doc_p,
            patch("routes.documents.save_assignments_to_db"),
            patch("routes.documents.apply_graph_update"),
            patch("routes.documents.table") as t,
            patch("routes.documents._spawn_post_roll"),
        ):
            t.return_value.insert.return_value = [{"id": "stream-syl"}]
            with client.stream(
                "POST", "/api/documents/upload",
                files={"file": ("syllabus.pdf", io.BytesIO(b"%PDF-1.4 s"), "application/pdf")},
                data={"course_id": "c-1", "user_id": "u1"},
            ) as r:
                assert r.status_code == 200
                body = r.read()

        events = _parse_sse_stream(body)
        extract_events = [
            json.loads(e["data"]) for e in events
            if e.get("event") == "progress" and json.loads(e["data"])["step"] == "extract"
        ]
        assert len(extract_events) == 1
        assert "syllabus" in extract_events[0]["message"]

    def test_validation_error_returns_4xx_before_stream_opens(self):
        """File-type rejection should fail with HTTP 400, not enter the SSE loop."""
        with _mock_validate_user():
            r = client.post(
                "/api/documents/upload",
                files={"file": ("notes.txt", io.BytesIO(b"hi"), "text/plain")},
                data={"course_id": "c-1", "user_id": "u1"},
            )
        assert r.status_code == 400
        assert "Unsupported file type" in r.json()["detail"]

    def test_async_ocr_failure_emits_terminal_error_no_legacy_fallthrough(self):
        """OCR_ASYNC_ENABLED=true: a failing extractor must NOT cascade into
        the legacy fallback (which would crash on extracted_text=None).
        It should yield a clean error+done pair and stop.
        """
        cls_p, sum_p, cpt_p, syl_p, doc_p = self._mock_agent_runs()
        with (
            _mock_validate_user(),
            patch("routes.documents.OCR_ASYNC_ENABLED", True),
            patch(
                "routes.documents.extract_text_from_file",
                side_effect=RuntimeError("scanned PDF too noisy"),
            ),
            cls_p, sum_p, cpt_p, syl_p, doc_p,
            patch("routes.documents.table") as t,
        ):
            t.return_value.select.return_value = []  # no idempotency cache hit
            with client.stream(
                "POST", "/api/documents/upload",
                files={"file": ("notes.pdf", io.BytesIO(b"%PDF-1.4 x"), "application/pdf")},
                data={"course_id": "c-1", "user_id": "u1"},
            ) as r:
                assert r.status_code == 200
                body = r.read()

        events = _parse_sse_stream(body)
        types_steps = [(e["event"], json.loads(e["data"])["step"]) for e in events]
        # status:start → progress:extracting_text → error:failed → status:done
        assert ("status", "start") in types_steps
        assert ("progress", "extracting_text") in types_steps
        assert ("error", "failed") in types_steps
        assert types_steps[-1] == ("status", "done")
        # Critically: we never reached classify or extract — no fallback fired.
        assert ("progress", "classify") not in types_steps
        # The failure event carries the request_id for support.
        failed_data = next(
            json.loads(e["data"]) for e in events
            if e["event"] == "error" and json.loads(e["data"])["step"] == "failed"
        )
        assert failed_data.get("data", {}).get("request_id")

    def test_sync_ocr_failure_in_streaming_route_returns_422_before_stream(self):
        """When OCR_ASYNC_ENABLED is the default (false), an extractor failure
        on the streaming /upload route also surfaces as a clean 422 — the
        EventSourceResponse never opens. (Async-OCR error path is covered by
        test_async_ocr_failure_emits_terminal_error_no_legacy_fallthrough.)"""
        with (
            _mock_validate_user(),
            patch(
                "routes.documents.extract_text_from_file",
                side_effect=RuntimeError("docling crashed"),
            ),
        ):
            r = client.post(
                "/api/documents/upload",
                files={"file": ("notes.pdf", io.BytesIO(b"%PDF-1.4 x"), "application/pdf")},
                data={"course_id": "c-1", "user_id": "u1"},
            )
        assert r.status_code == 422
        assert "different file" in r.json().get("detail", "").lower()


# ── X-Request-ID middleware + error-handler propagation ─────────────────────

class TestRequestIDPropagation:
    def test_x_request_id_header_on_response(self):
        with _mock_validate_user(), patch("routes.documents.table") as t:
            t.return_value.select.return_value = []
            r = client.get("/api/documents/user/u1")
        assert r.status_code == 200
        # Middleware always sets X-Request-ID.
        assert "x-request-id" in {k.lower() for k in r.headers.keys()}

    def test_caller_supplied_x_request_id_passes_through(self):
        with _mock_validate_user(), patch("routes.documents.table") as t:
            t.return_value.select.return_value = []
            r = client.get(
                "/api/documents/user/u1",
                headers={"X-Request-ID": "custom-trace-1234"},
            )
        assert r.headers.get("X-Request-ID") == "custom-trace-1234"

    def test_invalid_caller_supplied_id_replaced(self):
        with _mock_validate_user(), patch("routes.documents.table") as t:
            t.return_value.select.return_value = []
            r = client.get(
                "/api/documents/user/u1",
                headers={"X-Request-ID": "bad id with spaces"},
            )
        # Bad input → middleware replaced with a generated one.
        assert r.headers.get("X-Request-ID") != "bad id with spaces"
        assert len(r.headers.get("X-Request-ID", "")) >= 8

    def test_http_error_carries_request_id_in_body(self):
        with _mock_validate_user(), patch("routes.documents.table") as t:
            t.return_value.select.return_value = []  # 404 path
            r = client.delete("/api/documents/doc/missing?user_id=u1")
        assert r.status_code == 404
        body = r.json()
        assert "request_id" in body
        # Same ID in header and body.
        assert body["request_id"] == r.headers.get("X-Request-ID")


# ── Idempotency: X-Request-ID dedupe across upload retries ──────────────────

class TestUploadIdempotency:
    """A double-clicked upload (same X-Request-ID, two POSTs) must not run
    the orchestrator twice. The route looks up documents.request_id and
    short-circuits with the previously persisted row.

    These tests live as a sibling of TestUploadDocument so the legacy-
    fallback autouse fixture there doesn't shadow process_document here.
    """

    def test_sync_replay_returns_same_doc_without_reprocessing(self):
        existing = {
            "id": "doc-existing",
            "user_id": "u1",
            "course_id": "c-1",
            "file_name": "notes.pdf",
            "category": "lecture_notes",
            "summary": None,
            "concept_notes": [],
            "created_at": "2026-01-01T00:00:00Z",
            "processed_at": "2026-01-01T00:00:00Z",
        }
        with (
            _mock_validate_user(),
            patch("routes.documents.extract_text_from_file", return_value="text"),
            patch("routes.documents.process_document") as proc,
            patch("routes.documents.table") as t,
        ):
            t.return_value.select.return_value = [existing]
            r = client.post(
                "/api/documents/upload/sync",
                files={"file": ("notes.pdf", io.BytesIO(b"%PDF-1.4 x"), "application/pdf")},
                data={"course_id": "c-1", "user_id": "u1"},
                headers={"X-Request-ID": "trace-replay-1"},
            )
        assert r.status_code == 200
        body = r.json()
        assert body["id"] == "doc-existing"
        assert body["categories"] == []
        # Orchestrator must not have been called on the replay.
        proc.assert_not_called()

    def test_streaming_replay_emits_done_without_reprocessing(self):
        existing = {
            "id": "doc-existing-stream",
            "user_id": "u1",
            "course_id": "c-1",
            "file_name": "notes.pdf",
            "category": "lecture_notes",
            "summary": None,
            "concept_notes": [],
            "created_at": "2026-01-01T00:00:00Z",
            "processed_at": "2026-01-01T00:00:00Z",
        }
        cls_run = AsyncMock()
        with (
            _mock_validate_user(),
            patch("routes.documents.extract_text_from_file", return_value="text"),
            patch("routes.documents.classifier_agent.run", cls_run),
            patch("routes.documents.table") as t,
            patch("routes.documents._spawn_post_roll"),
        ):
            t.return_value.select.return_value = [existing]
            with client.stream(
                "POST", "/api/documents/upload",
                files={"file": ("notes.pdf", io.BytesIO(b"%PDF-1.4 x"), "application/pdf")},
                data={"course_id": "c-1", "user_id": "u1"},
                headers={"X-Request-ID": "trace-replay-stream-1"},
            ) as r:
                assert r.status_code == 200
                body = r.read()
        # Orchestrator's classifier must not have been called on the replay.
        cls_run.assert_not_called()
        events = _parse_sse_stream(body)
        types_steps = [(e["event"], json.loads(e["data"])["step"]) for e in events]
        assert types_steps == [
            ("status", "start"),
            ("result", "finalize"),
            ("status", "done"),
        ]
        result_evt = json.loads(events[1]["data"])
        assert result_evt["data"]["id"] == "doc-existing-stream"
        done_evt = json.loads(events[-1]["data"])
        assert done_evt["data"]["document_id"] == "doc-existing-stream"
        assert done_evt["data"]["request_id"] == "trace-replay-stream-1"
