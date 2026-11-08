"""#115: course-keyed writes refuse a caller who is not enrolled in the course.

Before this, any signed-in student could upload into another class's course
(pushing chunks into its shared RAG pool), file a note under it, or spend
model quota scanning it. Every such write now goes through
`services/academics.py::require_course_enrollment` (enrolled in ANY term's
offering of the abstract course, else the same 404 a missing course gets).

These tests opt OUT of the hermetic `_bypass_course_enrollment` fixture with
the `real_course_enrollment` marker, and model enrollment at the one read the
check makes (`academics.user_offering_ids_for_course`).
"""
from __future__ import annotations

import io
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from main import app
from services import academics

pytestmark = pytest.mark.real_course_enrollment

client = TestClient(app)


def _enrolled(yes: bool):
    """Patch the check's single enrollment read: `yes` → one offering."""
    return patch(
        "services.academics.user_offering_ids_for_course",
        return_value=["off-1"] if yes else [],
    )


def _assert_not_enrolled_404(r):
    assert r.status_code == 404, r.text
    # The route's 404 detail may carry a request-id suffix.
    assert str(r.json()["detail"]).startswith(academics.COURSE_NOT_ENROLLED_DETAIL)


# ── the helper ───────────────────────────────────────────────────────────────


class TestHelper:
    def test_enrolled_in_any_term_counts(self):
        with _enrolled(True) as read:
            assert academics.is_enrolled_in_course("u1", "c1") is True
        read.assert_called_once_with("u1", "c1")

    def test_not_enrolled_raises_404(self):
        with _enrolled(False), pytest.raises(HTTPException) as exc:
            academics.require_course_enrollment("u1", "c-foreign")
        assert exc.value.status_code == 404
        assert exc.value.detail == academics.COURSE_NOT_ENROLLED_DETAIL

    def test_enrolled_passes(self):
        with _enrolled(True):
            assert academics.require_course_enrollment("u1", "c1") is None

    @pytest.mark.parametrize("uid,cid", [("", "c1"), ("u1", ""), (None, None)])
    def test_blank_ids_are_not_enrolled(self, uid, cid):
        with _enrolled(True) as read:
            assert academics.is_enrolled_in_course(uid, cid) is False
        read.assert_not_called()

    def test_reads_the_callers_enrollments_only(self):
        """The real read: offerings of the course ∩ the CALLER's enrollments."""
        calls: list[tuple[str, dict]] = []

        def _table(name):
            t = MagicMock()

            def _select(cols, filters=None, **kw):
                calls.append((name, dict(filters or {})))
                if name == "course_offerings":
                    return [{"id": "off-a"}, {"id": "off-b"}]
                if name == "enrollments":
                    return [{"offering_id": "off-z"}]  # a different course
                return []
            t.select.side_effect = _select
            return t

        with patch("services.academics.table", side_effect=_table):
            assert academics.is_enrolled_in_course("u1", "c1") is False
        assert ("enrollments", {"user_id": "eq.u1"}) in calls


# ── the routes ───────────────────────────────────────────────────────────────


def _upload(path: str, *, filename="notes.txt", content_type="text/plain"):
    # An unsupported file type: a caller who passes the enrollment gate gets
    # the NEXT check's 400, which proves the gate ran first and let them by
    # without needing the OCR/agent pipeline.
    return client.post(
        path,
        files={"file": (filename, io.BytesIO(b"hello"), content_type)},
        data={"course_id": "c-target", "user_id": "u1"},
    )


@pytest.mark.parametrize("path", ["/api/documents/upload/sync", "/api/documents/upload"])
class TestUploadGate:
    def test_not_enrolled_is_404_before_any_work(self, path):
        with _enrolled(False), \
             patch("routes.documents._validate_user", return_value=None), \
             patch("routes.documents.resolve_offering") as ro, \
             patch("routes.documents.extract_text_from_file") as ocr:
            r = _upload(path, filename="notes.pdf", content_type="application/pdf")
        _assert_not_enrolled_404(r)
        ro.assert_not_called()
        ocr.assert_not_called()

    def test_enrolled_reaches_the_next_check(self, path):
        with _enrolled(True), patch("routes.documents._validate_user", return_value=None):
            r = _upload(path)
        assert r.status_code == 400
        assert "Unsupported file type" in r.json()["detail"]


class TestCourseScanGate:
    def test_not_enrolled_is_404_and_no_scan(self):
        with _enrolled(False), \
             patch("routes.documents._validate_user", return_value=None), \
             patch("routes.documents._scan_concepts_for_course") as scan:
            r = client.post("/api/documents/course/c-foreign/scan-concepts",
                            json={"user_id": "u1"})
        _assert_not_enrolled_404(r)
        scan.assert_not_called()

    def test_enrolled_scans(self):
        shape = {"concepts": ["X"], "added": 1, "existing": 0}
        with _enrolled(True), \
             patch("routes.documents._validate_user", return_value=None), \
             patch("routes.documents._scan_concepts_for_course", return_value=shape) as scan:
            r = client.post("/api/documents/course/c1/scan-concepts",
                            json={"user_id": "u1"})
        assert r.status_code == 200
        assert r.json() == shape
        scan.assert_called_once_with("u1", "c1")


class TestNoteCreateGate:
    def test_not_enrolled_is_404_and_nothing_written(self):
        with _enrolled(False), \
             patch("routes.notes.resolve_offering") as ro, \
             patch("routes.notes.create_note") as create:
            r = client.post("/api/notes", json={"user_id": "u1", "course_id": "c-foreign",
                                                "title": "T", "body": "B"})
        _assert_not_enrolled_404(r)
        ro.assert_not_called()  # no offering minted for a course that is not theirs
        create.assert_not_called()

    def test_enrolled_creates(self):
        async def fake_create(user_id, offering_id, title, body, tags):
            return {"id": "n1", "user_id": user_id, "offering_id": offering_id,
                    "title": title, "body": body, "tags": tags,
                    "last_summary": None, "last_summary_at": None,
                    "created_at": "", "updated_at": ""}
        with _enrolled(True), \
             patch("routes.notes.resolve_offering", return_value="off1"), \
             patch("routes.notes.create_note", side_effect=fake_create), \
             patch("routes.notes.award_xp_safe"):
            r = client.post("/api/notes", json={"user_id": "u1", "course_id": "c1",
                                                "title": "T", "body": "B"})
        assert r.status_code == 200
        assert r.json()["id"] == "n1"
