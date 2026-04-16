"""
Unit tests for routes/onboarding.py

Tests the POST /api/onboarding/profile endpoint with DB mocked.
"""
import pytest
from unittest.mock import MagicMock, patch, call
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
    "courses": ["CS 111", "MA 225"],
    "learning_style": "visual",
}


def _make_table_mock(users_exist=True, courses_exist=False, enrolled=False):
    """Build a table() side_effect that returns mocks per table name."""
    def factory(name):
        m = MagicMock()
        if name == "users":
            m.select.return_value = [{"id": "user_123"}] if users_exist else []
            m.update.return_value = []
        elif name == "courses":
            m.select.return_value = [{"id": "existing-course-id"}] if courses_exist else []
            m.insert.return_value = []
        elif name == "user_courses":
            m.select.return_value = [{"id": "uc-1"}] if enrolled else []
            m.insert.return_value = []
        return m
    return factory


class TestSaveOnboardingProfile:
    def test_success_creates_courses_and_enrolls(self):
        tables = {}

        def factory(name):
            if name not in tables:
                m = MagicMock()
                if name == "users":
                    m.select.return_value = [{"id": "user_123"}]
                elif name == "courses":
                    m.select.return_value = []  # no existing courses
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
        tables["users"].update.assert_called_once()
        update_data = tables["users"].update.call_args[0][0]
        assert update_data["first_name"] == "Jose"
        assert update_data["last_name"] == "Cruz"
        assert update_data["name"] == "Jose Cruz"
        assert update_data["class_year"] == "junior"
        assert update_data["majors"] == ["Computer Science"]
        assert update_data["minors"] == ["Mathematics"]
        assert update_data["learning_style"] == "visual"

        # Two courses were created
        assert tables["courses"].insert.call_count == 2

        # Two enrollments were created
        assert tables["user_courses"].insert.call_count == 2

    def test_reuses_existing_course(self):
        tables = {}

        def factory(name):
            if name not in tables:
                m = MagicMock()
                if name == "users":
                    m.select.return_value = [{"id": "user_123"}]
                elif name == "courses":
                    m.select.return_value = [{"id": "existing-cid"}]
                elif name == "user_courses":
                    m.select.return_value = []
                tables[name] = m
            return tables[name]

        with patch("routes.onboarding.table", side_effect=factory):
            res = client.post("/api/onboarding/profile", json=VALID_PAYLOAD)

        assert res.status_code == 200
        # Existing course reused — no new courses inserted
        tables["courses"].insert.assert_not_called()
        # But enrollments still created
        assert tables["user_courses"].insert.call_count == 2
        # Both course_ids should be the existing one
        assert res.json()["courses_linked"] == ["existing-cid", "existing-cid"]

    def test_skips_enrollment_if_already_enrolled(self):
        tables = {}

        def factory(name):
            if name not in tables:
                m = MagicMock()
                if name == "users":
                    m.select.return_value = [{"id": "user_123"}]
                elif name == "courses":
                    m.select.return_value = [{"id": "existing-cid"}]
                elif name == "user_courses":
                    m.select.return_value = [{"id": "uc-already"}]
                tables[name] = m
            return tables[name]

        with patch("routes.onboarding.table", side_effect=factory):
            res = client.post("/api/onboarding/profile", json=VALID_PAYLOAD)

        assert res.status_code == 200
        tables["user_courses"].insert.assert_not_called()

    def test_user_not_found_returns_404(self):
        with patch("routes.onboarding.table", side_effect=_make_table_mock(users_exist=False)):
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
            "courses": ["CS 111"],
            "learning_style": "visual",
        }
        with patch("routes.onboarding.table", side_effect=_make_table_mock()):
            res = client.post("/api/onboarding/profile", json=payload)

        assert res.status_code == 422

    def test_empty_courses_list_returns_422(self):
        payload = {**VALID_PAYLOAD, "courses": []}
        with patch("routes.onboarding.table", side_effect=_make_table_mock()):
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
                    m.select.return_value = []
                elif name == "user_courses":
                    m.select.return_value = []
                tables[name] = m
            return tables[name]

        with patch("routes.onboarding.table", side_effect=factory):
            res = client.post("/api/onboarding/profile", json=payload)

        assert res.status_code == 200
        update_data = tables["users"].update.call_args[0][0]
        assert update_data["minors"] == []
