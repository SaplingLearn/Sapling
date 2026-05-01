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
import pytest
from unittest.mock import MagicMock, patch
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
    """Helper: build a multipart upload request."""
    return client.post(
        "/api/documents/upload",
        files={"file": (filename, io.BytesIO(content), content_type)},
        data={"course_id": course_id, "user_id": user_id},
    )


class TestUploadDocument:
    # ── File-type validation ───────────────────────────────────────────────────

    def test_rejects_unsupported_extension(self):
        with _mock_validate_user():
            r = _make_upload(filename="notes.txt", content_type="text/plain", content=b"hello")
        assert r.status_code == 400
        assert "Unsupported file type" in r.json()["detail"]

    def test_rejects_file_over_15mb(self):
        big = b"x" * (15 * 1024 * 1024 + 1)
        with _mock_validate_user(), patch("routes.documents.extract_text_from_file", return_value=""):
            r = _make_upload(content=big)
        assert r.status_code == 400
        assert "15 MB" in r.json()["detail"]

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
            "flashcards": [],
            "assignments": [],
            "concepts": ["Linear Regression", "Big-O Analysis", "  ", ""],
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
            "flashcards": [],
            "assignments": [],
            "concepts": ["Gradient Descent", "Cross-Entropy Loss"],
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
            "flashcards": [],
            "concepts": ["Should be ignored"],
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
            "flashcards": [],
            "assignments": [],
            "concepts": ["Concept A"],
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

    # ── _process_document harness ─────────────────────────────────────────────

    def test_process_document_coerces_garbage_into_safe_shape(self):
        """When the LLM emits the wrong types, _process_document normalizes them."""
        garbage = {
            "category": "not-a-real-category",
            "summary": 12345,
            "key_takeaways": "should be a list, not a string",
            "flashcards": [{"question": "Q", "answer": "A"}, "bad", None],
            "assignments": "not a list either",
            "concepts": "Linear Regression, Big-O",  # string instead of list
        }
        with patch("routes.documents.call_gemini_json", return_value=garbage):
            result = _process_document("file.pdf", "text")

        assert result["category"] == "other"
        assert result["summary"] == ""  # int coerced to ""
        assert result["key_takeaways"] == []
        assert result["flashcards"] == [{"question": "Q", "answer": "A"}]
        assert result["assignments"] == []
        assert result["concepts"] == []  # comma-separated string is rejected

    def test_process_document_strips_blanks_from_concepts(self):
        ai_result = {
            "category": "syllabus",
            "summary": "S",
            "key_takeaways": [],
            "flashcards": [],
            "assignments": [],
            "concepts": ["A", "  B  ", "", "   ", 42, None, "C"],
        }
        with patch("routes.documents.call_gemini_json", return_value=ai_result):
            result = _process_document("file.pdf", "text")

        assert result["concepts"] == ["A", "B", "C"]

    def test_process_document_handles_non_dict_response(self):
        with patch("routes.documents.call_gemini_json", return_value=["not", "a", "dict"]):
            result = _process_document("file.pdf", "text")

        assert result["category"] == "other"
        assert result["concepts"] == []
        assert result["assignments"] == []

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
