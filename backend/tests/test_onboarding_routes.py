"""
Unit tests for routes/onboarding.py

Tests the POST /api/onboarding/profile and GET /api/onboarding/courses
endpoints with DB mocked.
"""
import pytest
from unittest.mock import MagicMock, patch
from fastapi.testclient import TestClient

from main import app

client = TestClient(app)

VALID_PAYLOAD = {
    "user_id": "user_123",
    "first_name": "Jose",
    "last_name": "Cruz",
    "year": "junior",
    "majors": ["Computer Science"],
    "minors": ["Mathematics"],
    "course_ids": ["cid-cs111", "cid-ma225"],
    "learning_style": "visual",
}


class TestSearchCourses:
    def test_returns_matching_courses(self):
        mock = MagicMock()
        mock.select.return_value = [
            {"id": "cid-1", "course_code": "CS 111", "course_name": "Intro to CS"},
        ]
        with patch("routes.onboarding.table", return_value=mock):
            res = client.get("/api/onboarding/courses?q=CS")

        assert res.status_code == 200
        assert len(res.json()["courses"]) == 1
        assert res.json()["courses"][0]["course_code"] == "CS 111"

    def test_empty_query_returns_all(self):
        mock = MagicMock()
        mock.select.return_value = [
            {"id": "cid-1", "course_code": "CS 111", "course_name": "Intro to CS"},
            {"id": "cid-2", "course_code": "MA 225", "course_name": "Calculus"},
        ]
        with patch("routes.onboarding.table", return_value=mock):
            res = client.get("/api/onboarding/courses")

        assert res.status_code == 200
        assert len(res.json()["courses"]) == 2


def _make_factory(tables, *, course_rows, enrollment_rows, offering_rows=None):
    """Build a shared table() mock factory across onboarding + academics.

    Seeds a current ``terms`` row and a matching ``course_offerings`` row so
    ``resolve_offering(create=True)`` resolves to an EXISTING offering without
    inserting (keeps tests deterministic). ``enrollment_rows`` controls the
    "already enrolled?" check on ``enrollments``.
    """
    if offering_rows is None:
        offering_rows = [{"id": "off-1"}]

    def factory(name):
        if name not in tables:
            m = MagicMock()
            if name == "users":
                m.select.return_value = [{"id": "user_123"}]
            elif name == "courses":
                m.select.return_value = course_rows
            elif name == "terms":
                m.select.return_value = [
                    {
                        "id": "term-current",
                        "term": "Summer",
                        "year": 2026,
                        "label": "Summer 2026",
                        "start_date": "2026-05-01",
                        "end_date": "2026-08-31",
                        "sort_key": 20262,
                    }
                ]
            elif name == "course_offerings":
                m.select.return_value = offering_rows
            elif name == "enrollments":
                m.select.return_value = enrollment_rows
            tables[name] = m
        return tables[name]

    return factory


class TestSaveOnboardingProfile:
    def test_success_enrolls_in_courses(self):
        tables = {}
        factory = _make_factory(
            tables,
            course_rows=[{"id": "some-id"}],
            enrollment_rows=[],  # not enrolled
        )

        with patch("routes.onboarding.table", side_effect=factory), \
             patch("services.academics.table", side_effect=factory):
            res = client.post("/api/onboarding/profile", json=VALID_PAYLOAD)

        assert res.status_code == 200
        data = res.json()
        assert data["user_id"] == "user_123"
        assert len(data["courses_linked"]) == 2

        # User profile was updated
        from services.encryption import decrypt
        tables["users"].update.assert_called_once()
        update_data = tables["users"].update.call_args[0][0]
        assert decrypt(update_data["first_name"]) == "Jose"
        assert decrypt(update_data["last_name"]) == "Cruz"
        assert decrypt(update_data["name"]) == "Jose Cruz"
        assert update_data["year"] == "junior"
        assert update_data["majors"] == ["Computer Science"]
        assert update_data["minors"] == ["Mathematics"]
        assert update_data["learning_style"] == "visual"

        # Two enrollments were created, keyed on offering_id (not course_id)
        assert tables["enrollments"].insert.call_count == 2
        insert_row = tables["enrollments"].insert.call_args[0][0]
        assert insert_row["offering_id"] == "off-1"
        assert insert_row["user_id"] == "user_123"
        assert "course_id" not in insert_row
        # The legacy user_courses table is no longer touched
        assert "user_courses" not in tables

    def test_skips_nonexistent_course(self):
        tables = {}
        factory = _make_factory(
            tables,
            course_rows=[],  # course not found
            enrollment_rows=[],
        )

        with patch("routes.onboarding.table", side_effect=factory), \
             patch("services.academics.table", side_effect=factory):
            res = client.post("/api/onboarding/profile", json=VALID_PAYLOAD)

        assert res.status_code == 200
        # No enrollments since courses don't exist
        assert "enrollments" not in tables or tables["enrollments"].insert.call_count == 0

    def test_skips_enrollment_if_already_enrolled(self):
        tables = {}
        factory = _make_factory(
            tables,
            course_rows=[{"id": "some-id"}],
            enrollment_rows=[{"id": "enr-already"}],  # already enrolled
        )

        with patch("routes.onboarding.table", side_effect=factory), \
             patch("services.academics.table", side_effect=factory):
            res = client.post("/api/onboarding/profile", json=VALID_PAYLOAD)

        assert res.status_code == 200
        tables["enrollments"].insert.assert_not_called()

    def test_user_not_found_returns_404(self):
        mock = MagicMock()
        mock.select.return_value = []
        with patch("routes.onboarding.table", return_value=mock):
            res = client.post("/api/onboarding/profile", json=VALID_PAYLOAD)

        assert res.status_code == 404
        assert res.json()["detail"] == "User not found"

    def test_missing_required_field_returns_422(self):
        payload = {
            "user_id": "user_123",
            "first_name": "Jose",
            # last_name missing
            "year": "junior",
            "majors": ["Computer Science"],
            "course_ids": ["cid-1"],
            "learning_style": "visual",
        }
        with patch("routes.onboarding.table"):
            res = client.post("/api/onboarding/profile", json=payload)

        assert res.status_code == 422

    def test_empty_course_ids_returns_422(self):
        payload = {**VALID_PAYLOAD, "course_ids": []}
        with patch("routes.onboarding.table"):
            res = client.post("/api/onboarding/profile", json=payload)

        assert res.status_code == 422

    def test_minors_optional_defaults_empty(self):
        payload = {**VALID_PAYLOAD}
        del payload["minors"]

        tables = {}
        factory = _make_factory(
            tables,
            course_rows=[{"id": "some-id"}],
            enrollment_rows=[],
        )

        with patch("routes.onboarding.table", side_effect=factory), \
             patch("services.academics.table", side_effect=factory):
            res = client.post("/api/onboarding/profile", json=payload)

        assert res.status_code == 200
        update_data = tables["users"].update.call_args[0][0]
        assert update_data["minors"] == []
