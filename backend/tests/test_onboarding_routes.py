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


class TestSaveOnboardingProfile:
    def test_success_enrolls_in_courses(self):
        tables = {}

        def factory(name):
            if name not in tables:
                m = MagicMock()
                if name == "users":
                    m.select.return_value = [{"id": "user_123"}]
                elif name == "courses":
                    m.select.return_value = [{"id": "some-id"}]
                elif name == "user_courses":
                    m.select.return_value = []  # not enrolled
                tables[name] = m
            return tables[name]

        with patch("routes.onboarding.table", side_effect=factory):
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

        # Two enrollments were created
        assert tables["user_courses"].insert.call_count == 2

    def test_skips_nonexistent_course(self):
        tables = {}

        def factory(name):
            if name not in tables:
                m = MagicMock()
                if name == "users":
                    m.select.return_value = [{"id": "user_123"}]
                elif name == "courses":
                    m.select.return_value = []  # course not found
                elif name == "user_courses":
                    m.select.return_value = []
                tables[name] = m
            return tables[name]

        with patch("routes.onboarding.table", side_effect=factory):
            res = client.post("/api/onboarding/profile", json=VALID_PAYLOAD)

        assert res.status_code == 200
        # No enrollments since courses don't exist
        assert "user_courses" not in tables or tables.get("user_courses", MagicMock()).insert.call_count == 0

    def test_skips_enrollment_if_already_enrolled(self):
        tables = {}

        def factory(name):
            if name not in tables:
                m = MagicMock()
                if name == "users":
                    m.select.return_value = [{"id": "user_123"}]
                elif name == "courses":
                    m.select.return_value = [{"id": "some-id"}]
                elif name == "user_courses":
                    m.select.return_value = [{"id": "uc-already"}]
                tables[name] = m
            return tables[name]

        with patch("routes.onboarding.table", side_effect=factory):
            res = client.post("/api/onboarding/profile", json=VALID_PAYLOAD)

        assert res.status_code == 200
        tables["user_courses"].insert.assert_not_called()

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

        def factory(name):
            if name not in tables:
                m = MagicMock()
                if name == "users":
                    m.select.return_value = [{"id": "user_123"}]
                elif name == "courses":
                    m.select.return_value = [{"id": "some-id"}]
                elif name == "user_courses":
                    m.select.return_value = []
                tables[name] = m
            return tables[name]

        with patch("routes.onboarding.table", side_effect=factory):
            res = client.post("/api/onboarding/profile", json=payload)

        assert res.status_code == 200
        update_data = tables["users"].update.call_args[0][0]
        assert update_data["minors"] == []
