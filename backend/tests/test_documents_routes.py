"""
Unit tests for routes/documents.py

Tests cover:
  - GET  /api/documents/user/{user_id}   → list_documents
  - DELETE /api/documents/doc/{doc_id}   → delete_document
  - PATCH /api/documents/doc/{doc_id}    → update_document
  - POST /api/documents/upload           → upload_document

All agent runs, DB access, and file-extraction are mocked.
"""
import io
import json
from types import SimpleNamespace
import pytest
from unittest.mock import AsyncMock, patch
from fastapi.testclient import TestClient
from pydantic_ai.exceptions import UsageLimitExceeded, UnexpectedModelBehavior

from main import app

client = TestClient(app)


def _mock_validate_user():
    """Patch _validate_user to always succeed."""
    return patch("routes.documents._validate_user", return_value=None)


def _doc_text(label: str = "document") -> str:
    """Extraction output long enough to clear `MIN_EXTRACTED_CHARS`.

    The upload routes reject documents whose extracted text is near-empty (a
    rasterized PDF has no text layer, so extraction returns "" with no
    exception to catch). Happy-path fixtures therefore have to supply as much
    text as a real document would - a bare "text" is now indistinguishable
    from a failed extraction.

    `label` is preserved so each fixture still reads as its own document.
    """
    return (
        f"{label}. This sample body gives the upload fixture enough extracted "
        "text to look like a document that was actually read successfully."
    )


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

    def test_documents_carry_course_id_resolved_from_offering(self):
        """#435: Library filters/labels on d.course_id, but this route only
        ever returned offering_id — uploads never matched a course filter
        and always fell into "Uncategorized". Each row must now carry the
        abstract course_id, resolved via services.academics.offering_course_id."""
        docs = [
            {"id": "d1", "user_id": "u1", "offering_id": "off-1", "file_name": "notes.pdf", "category": "lecture_notes"},
            {"id": "d2", "user_id": "u1", "offering_id": "off-2", "file_name": "syllabus.pdf", "category": "syllabus"},
        ]
        with (
            _mock_validate_user(),
            patch("routes.documents.table") as t,
            patch("routes.documents.offering_course_id") as mock_ocid,
        ):
            t.return_value.select.return_value = docs
            mock_ocid.side_effect = {"off-1": "course-A", "off-2": "course-B"}.get
            r = client.get("/api/documents/user/u1")

        assert r.status_code == 200
        body = r.json()["documents"]
        assert body[0]["course_id"] == "course-A"
        assert body[1]["course_id"] == "course-B"

    def test_course_id_resolved_once_per_unique_offering(self):
        """Batch resolution: repeated offering_ids across rows must only hit
        offering_course_id once each, not once per row (mirrors the
        offering_to_course pattern in routes/learn.py::list_sessions)."""
        docs = [
            {"id": "d1", "user_id": "u1", "offering_id": "off-1", "file_name": "a.pdf", "category": "other"},
            {"id": "d2", "user_id": "u1", "offering_id": "off-1", "file_name": "b.pdf", "category": "other"},
            {"id": "d3", "user_id": "u1", "offering_id": "off-1", "file_name": "c.pdf", "category": "other"},
        ]
        with (
            _mock_validate_user(),
            patch("routes.documents.table") as t,
            patch("routes.documents.offering_course_id", return_value="course-A") as mock_ocid,
        ):
            t.return_value.select.return_value = docs
            r = client.get("/api/documents/user/u1")

        assert r.status_code == 200
        assert all(d["course_id"] == "course-A" for d in r.json()["documents"])
        mock_ocid.assert_called_once_with("off-1")

    def test_missing_offering_id_yields_null_course_id(self):
        """Defensive-code coverage: documents.offering_id is NOT NULL (0025),
        so a real persisted row can never surface offering_id=None here — but
        the route's `if off_id and ...` guard must not raise on a None/falsy
        offering_id (e.g. a partially-mocked row in another test, or future
        schema drift). Confirms it degrades to course_id: null instead of
        KeyError/TypeError."""
        docs = [
            {"id": "d1", "user_id": "u1", "offering_id": None, "file_name": "a.pdf", "category": "other"},
        ]
        with _mock_validate_user(), patch("routes.documents.table") as t:
            t.return_value.select.return_value = docs
            r = client.get("/api/documents/user/u1")

        assert r.status_code == 200
        assert r.json()["documents"][0]["course_id"] is None

    def test_unresolvable_offering_id_yields_null_course_id(self):
        """The actually-reachable null case: offering_id IS present (schema
        requires it) but offering_course_id fails to resolve it to a course
        — e.g. the course_offerings row backing it was deleted/data drift.
        Must surface course_id: null, not raise, so the rest of the list
        still renders (Library.tsx buckets this doc as "Uncategorized")."""
        docs = [
            {"id": "d1", "user_id": "u1", "offering_id": "off-orphaned", "file_name": "a.pdf", "category": "other"},
        ]
        with (
            _mock_validate_user(),
            patch("routes.documents.table") as t,
            patch("routes.documents.offering_course_id", return_value=None),
        ):
            t.return_value.select.return_value = docs
            r = client.get("/api/documents/user/u1")

        assert r.status_code == 200
        assert r.json()["documents"][0]["course_id"] is None

    def test_corrupted_concept_notes_degrades_row_others_still_return(self):
        """PR review follow-up: decrypt_json re-raises when both the decrypt
        AND the plaintext-JSON fallback fail (a genuinely corrupted row).
        The loop this fix touches must degrade THAT row's concept_notes to
        [] instead of letting the exception 500 the whole list — sibling
        rows must still come back intact. Mirrors the established
        try/except pattern at _existing_doc_by_request_id and
        scan_document_concepts."""
        docs = [
            {"id": "d-good", "user_id": "u1", "offering_id": "off-1", "file_name": "a.pdf",
             "category": "other", "concept_notes": "GOOD_CIPHERTEXT"},
            {"id": "d-bad", "user_id": "u1", "offering_id": "off-1", "file_name": "b.pdf",
             "category": "other", "concept_notes": "CORRUPTED_CIPHERTEXT"},
        ]

        def fake_decrypt_json(value):
            if value == "CORRUPTED_CIPHERTEXT":
                raise ValueError("decrypt and plaintext parse both failed")
            return [{"name": "Concept A", "description": "d"}]

        with (
            _mock_validate_user(),
            patch("routes.documents.table") as t,
            patch("routes.documents.decrypt_json", side_effect=fake_decrypt_json),
        ):
            t.return_value.select.return_value = docs
            r = client.get("/api/documents/user/u1")

        assert r.status_code == 200
        body = {d["id"]: d for d in r.json()["documents"]}
        assert body["d-good"]["concept_notes"] == [{"name": "Concept A", "description": "d"}]
        assert body["d-bad"]["concept_notes"] == []

# ── DELETE /api/documents/doc/{document_id} ──────────────────────────────────

class TestDeleteDocument:
    def test_returns_deleted_true(self):
        with patch("routes.documents.table") as t:
            t.return_value.delete.return_value = None
            r = client.delete("/api/documents/doc/d1")

        assert r.status_code == 200
        assert r.json() == {"deleted": True}

    def test_soft_deletes_with_correct_id(self):
        """Delete is a soft delete (0025): it stamps deleted_at via an
        update scoped to the document id, not a hard row removal."""
        with patch("routes.documents.table") as t:
            t.return_value.delete.return_value = None
            client.delete("/api/documents/doc/my-doc-uuid")
            t.assert_called_with("documents")
            # No hard delete fired.
            t.return_value.delete.assert_not_called()
            # A deleted_at stamp went out, scoped to the doc id.
            update_args = t.return_value.update.call_args
            assert "my-doc-uuid" in str(update_args)
            payload = update_args[0][0]
            assert payload.get("deleted_at") is not None

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

    Targets /upload/sync so the response is a single JSON dict. The
    streaming /upload route is exercised separately in stream-specific
    tests.
    """
    return client.post(
        "/api/documents/upload/sync",
        files={"file": (filename, io.BytesIO(content), content_type)},
        data={"course_id": course_id, "user_id": user_id},
    )


class TestUploadValidation:
    """Request validation on /upload/sync — extension/content-type, size cap,
    and OCR-failure mapping. (The legacy-pipeline upload tests that used to
    live here died with the pipeline itself in #151b; the agent path's
    success behavior is TestUploadDocumentOrchestrator below.)"""
    # ── File-type validation ───────────────────────────────────────────────────

    def test_rejects_unsupported_extension(self):
        with _mock_validate_user():
            r = _make_upload(filename="notes.txt", content_type="text/plain", content=b"hello")
        assert r.status_code == 400
        assert "Unsupported file type" in r.json()["detail"]

    def test_rejects_file_over_max_size(self):
        # Cap was raised from 15 MB → 100 MB in commit 9912a25. Don't
        # allocate 100MB here — it makes the test fragile under full-suite
        # memory pressure. Instead, monkeypatch MAX_FILE_SIZE to 1 MB and
        # pin that the rejection copy DERIVES from the constant (#132 item
        # 21): a hardcoded "100 MB" in the detail string would not follow
        # the patched cap. test_default_cap_is_100_mb pins the production
        # value, so together they pin the production message.
        with (
            _mock_validate_user(),
            patch("routes.documents.MAX_FILE_SIZE", 1024 * 1024),
            patch("routes.documents.extract_text_from_file", return_value=""),
        ):
            r = _make_upload(content=b"x" * (1024 * 1024 + 1))
        assert r.status_code == 400
        assert "1 MB" in r.json()["detail"]

    def test_default_cap_is_100_mb(self):
        """The rejection copy derives from MAX_FILE_SIZE (see
        test_rejects_file_over_max_size), so pinning the constant pins the
        production message ("File exceeds the 100 MB limit.")."""
        from routes.documents import MAX_FILE_SIZE

        assert MAX_FILE_SIZE == 100 * 1024 * 1024

    def test_accepts_pdf_by_extension(self):
        result = _make_orchestrator_result(category="lecture_notes")
        row = {"id": "d1", "file_name": "notes.pdf"}
        with (
            _mock_validate_user(),
            patch("routes.documents.extract_text_from_file", return_value=_doc_text("pdf text")),
            patch("routes.documents.process_document", return_value=result),
            patch("routes.documents.table") as t,
        ):
            t.return_value.select.return_value = []
            t.return_value.insert.return_value = [row]
            r = _make_upload(filename="notes.pdf", content_type="application/pdf")

        assert r.status_code == 200
        assert r.json()["file_name"] == "notes.pdf"

    def test_accepts_docx_by_extension(self):
        result = _make_orchestrator_result(category="reading")
        row = {"id": "d2", "file_name": "chapter.docx"}
        with (
            _mock_validate_user(),
            patch("routes.documents.extract_text_from_file", return_value=_doc_text("docx text")),
            patch("routes.documents.process_document", return_value=result),
            patch("routes.documents.table") as t,
        ):
            t.return_value.select.return_value = []
            t.return_value.insert.return_value = [row]
            ct = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
            r = _make_upload(filename="chapter.docx", content_type=ct)

        assert r.status_code == 200

    def test_accepts_pptx_by_extension(self):
        result = _make_orchestrator_result(category="slides")
        row = {"id": "d3", "file_name": "lecture.pptx"}
        with (
            _mock_validate_user(),
            patch("routes.documents.extract_text_from_file", return_value=_doc_text("pptx text")),
            patch("routes.documents.process_document", return_value=result),
            patch("routes.documents.table") as t,
        ):
            t.return_value.select.return_value = []
            t.return_value.insert.return_value = [row]
            ct = "application/vnd.openxmlformats-officedocument.presentationml.presentation"
            r = _make_upload(filename="lecture.pptx", content_type=ct)

        assert r.status_code == 200

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
            patch("routes.documents.extract_text_from_file", return_value=_doc_text("text")),
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
            patch("routes.documents.extract_text_from_file", return_value=_doc_text("text")),
            patch("routes.documents.process_document", return_value=result),
            patch("routes.documents.table") as t,
        ):
            t.return_value.insert.return_value = []
            r = _make_upload()
        assert r.status_code == 200
        assert r.json()["summary"] == "Plain English summary."

    def test_persisted_row_contains_user_and_offering(self):
        """The documents row keys on the OFFERING (0025). The upload form
        sends the abstract course id, which the route resolves to the
        current-term offering before persisting — the row carries
        offering_id, never course_id."""
        result = _make_orchestrator_result()
        with (
            _mock_validate_user(),
            patch("routes.documents.resolve_offering", return_value="off-99") as ro,
            patch("routes.documents.extract_text_from_file", return_value=_doc_text("t")),
            patch("routes.documents.process_document", return_value=result),
            patch("routes.documents.table") as t,
        ):
            t.return_value.select.return_value = []
            t.return_value.insert.return_value = []
            _make_upload(course_id="c-99", user_id="user_andres")
            insert_call = t.return_value.insert.call_args[0][0]

        # The abstract course id was resolved to the offering for the row.
        ro.assert_called_once_with("c-99", create=True)
        assert insert_call["user_id"] == "user_andres"
        assert insert_call["offering_id"] == "off-99"
        assert "course_id" not in insert_call

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
            patch("routes.documents.extract_text_from_file", return_value=_doc_text("text")),
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
            patch("routes.documents.extract_text_from_file", return_value=_doc_text("text")),
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
            patch("routes.documents.extract_text_from_file", return_value=_doc_text("text")),
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
            patch("routes.documents.extract_text_from_file", return_value=_doc_text("text")),
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
            patch("routes.documents.extract_text_from_file", return_value=_doc_text("text")),
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
            patch("routes.documents.extract_text_from_file", return_value=_doc_text("text")),
            patch("routes.documents.process_document", return_value=result),
            patch("routes.documents.apply_graph_update") as mock_apply,
            patch("routes.documents.table") as t,
        ):
            t.return_value.insert.return_value = [{"id": "l1"}]
            r = _make_upload()
        assert r.status_code == 200
        mock_apply.assert_not_called()


# ── POST /api/documents/upload/sync — agent-failure → HTTP status (#151b) ───

class TestUploadSyncAgentFailure:
    """#151b: the agent pipeline is the ONLY upload pipeline — the ADR-0001
    legacy fallback is gone (ADR 0024). Failures map to a 502 with a
    retry-friendly detail: nothing was persisted, and the client mints a
    fresh X-Request-ID per attempt, so retrying re-runs the pipeline."""

    @pytest.mark.parametrize(
        "exc",
        [UsageLimitExceeded("token cap"), UnexpectedModelBehavior("degenerate output")],
    )
    def test_guardrail_failure_maps_to_502(self, exc):
        with (
            _mock_validate_user(),
            patch("routes.documents.extract_text_from_file", return_value=_doc_text("text")),
            patch("routes.documents.process_document", side_effect=exc),
            patch("routes.documents.table") as t,
        ):
            t.return_value.select.return_value = []  # no idempotent replay hit
            r = _make_upload()
        assert r.status_code == 502
        assert "try" in r.json()["detail"].lower()  # retry-friendly copy
        t.return_value.insert.assert_not_called()  # nothing persisted

    def test_unexpected_failure_maps_to_502(self):
        with (
            _mock_validate_user(),
            patch("routes.documents.extract_text_from_file", return_value=_doc_text("text")),
            patch("routes.documents.process_document", side_effect=RuntimeError("boom")),
            patch("routes.documents.table") as t,
        ):
            t.return_value.select.return_value = []
            r = _make_upload()
        assert r.status_code == 502
        assert "try" in r.json()["detail"].lower()
        t.return_value.insert.assert_not_called()


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
            patch("routes.documents.extract_text_from_file", return_value=_doc_text("text")),
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
            patch("routes.documents.extract_text_from_file", return_value=_doc_text("text")),
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

    def test_async_ocr_empty_extraction_emits_terminal_error(self):
        """OCR_ASYNC_ENABLED=true: extraction that *succeeds* but returns no
        usable text must stop the pipeline too.

        The test above covers an extractor that raises. A rasterized PDF raises
        nothing -- it simply returns "" -- so that exception path never fires
        and the model gets asked to summarize an empty document, which it
        answers by inventing one. Streaming counterpart of
        TestEmptyExtractionGuard.
        """
        cls_p, sum_p, cpt_p, syl_p, doc_p = self._mock_agent_runs()
        with (
            _mock_validate_user(),
            patch("routes.documents.OCR_ASYNC_ENABLED", True),
            patch("routes.documents.extract_text_from_file", return_value=""),
            cls_p, sum_p, cpt_p, syl_p, doc_p,
            patch("routes.documents.table") as t,
        ):
            t.return_value.select.return_value = []  # no idempotency cache hit
            with client.stream(
                "POST", "/api/documents/upload",
                files={"file": ("scan.pdf", io.BytesIO(b"%PDF-1.4 x"), "application/pdf")},
                data={"course_id": "c-1", "user_id": "u1"},
            ) as r:
                assert r.status_code == 200
                body = r.read()

        events = _parse_sse_stream(body)
        types_steps = [(e["event"], json.loads(e["data"])["step"]) for e in events]
        assert ("error", "failed") in types_steps
        assert types_steps[-1] == ("status", "done")
        # Never reached the model, and never persisted a fabrication.
        assert ("progress", "classify") not in types_steps
        failed_data = next(
            json.loads(e["data"]) for e in events
            if e["event"] == "error" and json.loads(e["data"])["step"] == "failed"
        )
        assert "no text" in failed_data["message"].lower()
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

    def test_streaming_rejects_file_over_max_size_names_actual_cap(self):
        """#132 item 21: the streaming route's 400 detail drifted to "15 MB"
        while MAX_FILE_SIZE is 100 MB. The copy must derive from the constant
        — patch the cap to 1 MB and the message must follow it. (Sync twin:
        TestUploadDocument.test_rejects_file_over_max_size; the production
        value is pinned by test_default_cap_is_100_mb.)"""
        with (
            _mock_validate_user(),
            patch("routes.documents.MAX_FILE_SIZE", 1024 * 1024),
            patch("routes.documents.extract_text_from_file", return_value=""),
        ):
            r = client.post(
                "/api/documents/upload",
                files={"file": ("notes.pdf", io.BytesIO(b"x" * (1024 * 1024 + 1)), "application/pdf")},
                data={"course_id": "c-1", "user_id": "u1"},
            )
        assert r.status_code == 400
        detail = r.json()["detail"]
        assert "1 MB" in detail
        assert "15 MB" not in detail

    def test_post_result_persistence_failure_is_terminal_not_double_result(self):
        """#132 item 11: a persistence failure AFTER the terminal result event
        emits the terminal error:failed + status:done pair and never a second
        result.

        Before the fix, the post-roll block (syllabus save, graph backstop,
        document insert) shared the pipeline's try/except, so a failed insert
        re-ran the whole pipeline via the (now-deleted, #151b) legacy
        fallback: the client saw result → error → result → done, and a second
        model call was spent on a document that had already been fully
        processed. Contract: exactly ONE result event, then the same terminal
        error+done tail the pre-result failure branches use.
        """
        cls_p, sum_p, cpt_p, syl_p, doc_p = self._mock_agent_runs()
        with (
            _mock_validate_user(),
            patch("routes.documents.extract_text_from_file", return_value=_doc_text("text")),
            cls_p, sum_p, cpt_p, syl_p, doc_p,
            patch(
                "routes.documents._persist_document",
                side_effect=RuntimeError("documents insert blew up"),
            ),
            patch("routes.documents.table") as t,
            patch("routes.documents._spawn_post_roll") as spawn,
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
        # Exactly ONE result event — never a second one.
        assert [ts for ts in types_steps if ts[0] == "result"] == [("result", "finalize")]
        # Terminal tail matches the pre-result failure branches.
        assert types_steps[-2:] == [("error", "failed"), ("status", "done")]
        # Side-effect tasks are never spawned when persistence failed.
        spawn.assert_not_called()
        # The failure event carries the request_id for support.
        failed_data = next(
            json.loads(e["data"]) for e in events
            if e["event"] == "error" and json.loads(e["data"])["step"] == "failed"
        )
        assert failed_data.get("data", {}).get("request_id")


# ── Streaming /upload — agent failure is terminal (#151b) ───────────────────

class TestUploadStreamingAgentFailure:
    """#151b: an agent failure mid-stream is TERMINAL — the exact
    error:failed + status:done tail the deleted legacy fallback emitted on
    double-failure, with request_id for support. `step="fallback"` left the
    SSE vocabulary: no fallback event, no second pipeline, no result."""

    @pytest.mark.parametrize(
        "exc",
        [
            UsageLimitExceeded("token cap"),
            UnexpectedModelBehavior("degenerate output"),
            RuntimeError("boom"),
        ],
    )
    def test_agent_failure_emits_terminal_error_done_pair(self, exc):
        with (
            _mock_validate_user(),
            patch("routes.documents.extract_text_from_file", return_value=_doc_text("text")),
            patch("routes.documents.classifier_agent.run", AsyncMock(side_effect=exc)),
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
        # Terminal tail, nothing after it.
        assert types_steps[-2:] == [("error", "failed"), ("status", "done")]
        # Never a result — the pipeline failed before one existed.
        assert all(ts[0] != "result" for ts in types_steps)
        # The fallback vocabulary is gone from the wire.
        assert ("error", "fallback") not in types_steps
        assert ("progress", "fallback_processing") not in types_steps
        # Nothing was persisted.
        t.return_value.insert.assert_not_called()
        # The failure event carries the request_id for support.
        failed_data = next(
            json.loads(e["data"]) for e in events if e["event"] == "error"
        )
        assert failed_data.get("data", {}).get("request_id")


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
            patch("routes.documents.extract_text_from_file", return_value=_doc_text("text")),
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
            patch("routes.documents.extract_text_from_file", return_value=_doc_text("text")),
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


# -- Empty-extraction guard --------------------------------------------------

class TestEmptyExtractionGuard:
    """Documents whose text extraction yields (almost) nothing must be
    rejected *before* any LLM call is made.

    Regression test for the scanned-PDF fabrication bug: a rasterized practice
    exam had no text layer at all, so extraction returned "" with no exception
    to catch. The classify/summarize prompt was still issued with an empty
    `Content:` block, and because that prompt's JSON schema requires a summary
    and a concept list with no "insufficient content" escape hatch, the model
    invented a document -- yielding a summary about the 1964 Berkeley Free
    Speech Movement and concepts about neural networks for a linear-algebra
    final. Those fabricated concepts were persisted and were bound for the
    course's shared knowledge graph, where they would have misled every
    enrolled student.
    """

    def test_rejects_pdf_with_no_extractable_text(self):
        with (
            _mock_validate_user(),
            patch("routes.documents.extract_text_from_file", return_value=""),
        ):
            r = _make_upload()

        assert r.status_code == 422
        assert "no text" in r.json()["detail"].lower()

    def test_threshold_boundary_is_exact(self):
        """49 stripped chars is rejected; exactly MIN_EXTRACTED_CHARS (50)
        passes — the guard is >= threshold, and the boundary itself is what a
        future off-by-one would silently move."""
        from routes.documents import MIN_EXTRACTED_CHARS

        below = "x" * (MIN_EXTRACTED_CHARS - 1)
        at = "x" * MIN_EXTRACTED_CHARS
        with (
            _mock_validate_user(),
            patch("routes.documents.extract_text_from_file", return_value=below),
        ):
            assert _make_upload().status_code == 422
        with (
            _mock_validate_user(),
            patch("routes.documents.extract_text_from_file", return_value="  " + at + "\n"),
            patch(
                "routes.documents.process_document",
                return_value=_make_orchestrator_result(category="other"),
            ),
            patch("routes.documents.table") as t,
        ):
            t.return_value.select.return_value = []
            t.return_value.insert.return_value = [{"id": "d50", "file_name": "notes.pdf"}]
            r = _make_upload()
        assert r.status_code == 200

    def test_rejects_whitespace_only_extraction(self):
        with (
            _mock_validate_user(),
            patch("routes.documents.extract_text_from_file", return_value="  \n\n\t   \n "),
        ):
            r = _make_upload()

        assert r.status_code == 422

    def test_rejects_extraction_below_minimum(self):
        """A scanned page often yields a few stray characters -- a page number,
        a header, a watermark -- rather than nothing at all. That is still far
        too little to summarize, and still enough to trigger fabrication, so
        testing for emptiness alone would be too weak."""
        with (
            _mock_validate_user(),
            patch("routes.documents.extract_text_from_file", return_value="Page 1 of 13"),
        ):
            r = _make_upload()

        assert r.status_code == 422

    def test_never_calls_the_model_when_extraction_is_empty(self):
        """The defect was not the bad copy -- it was spending an LLM call on an
        empty document and persisting the result. Assert the agent pipeline
        is never reached and nothing is written."""
        with (
            _mock_validate_user(),
            patch("routes.documents.extract_text_from_file", return_value=""),
            patch("routes.documents.process_document") as agent,
            patch("routes.documents.table") as t,
        ):
            r = _make_upload()

        assert r.status_code == 422
        agent.assert_not_called()
        t.return_value.insert.assert_not_called()

    def test_accepts_a_document_with_real_text(self):
        """The guard must not reject genuine documents."""
        real_text = (
            "Practice Final 2 Solutions. Problem 1: compute the eigenvalues of "
            "the matrix A and determine whether A is diagonalizable over R."
        )
        with (
            _mock_validate_user(),
            patch("routes.documents.extract_text_from_file", return_value=real_text),
            patch(
                "routes.documents.process_document",
                return_value=_make_orchestrator_result(category="assignment"),
            ),
            patch("routes.documents.apply_graph_update"),
            patch("routes.documents.table") as t,
        ):
            t.return_value.select.return_value = []
            t.return_value.insert.return_value = [{"id": "d9", "file_name": "notes.pdf"}]
            r = _make_upload()

        assert r.status_code == 200
