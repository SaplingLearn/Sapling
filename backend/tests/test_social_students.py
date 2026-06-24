"""
Unit tests for GET /api/social/students (routes/social.py::get_students).

After the academics split (migration 0020) the abstract `courses` table no
longer has a `user_id` column or per-enrollment rows. A user's courses are now
resolved through the enrollment chain:

    enrollments(user_id) -> course_offerings(course_id) -> courses(course_name)

These tests pin the new offering-aware resolution and the (unchanged) response
shape of the endpoint.
"""
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from main import app

client = TestClient(app)


def _enrollment(user_id: str, course_name: str) -> dict:
    """An enrollments row with the PostgREST embedded course-offering -> course join."""
    return {
        "user_id": user_id,
        "course_offerings": {"courses": {"course_name": course_name}},
    }


def _table_factory(users, enrollment_rows, node_rows):
    def table_side_effect(name):
        m = MagicMock()
        if name == "users":
            m.select.return_value = users
        elif name == "enrollments":
            m.select.return_value = enrollment_rows
        elif name == "graph_nodes":
            m.select.return_value = node_rows
        else:
            m.select.return_value = []
        return m

    return table_side_effect


class TestGetStudents:
    def test_courses_resolved_via_enrollments(self):
        users = [{"id": "u1", "name": "Alice", "streak_count": 3}]
        enrollments = [
            _enrollment("u1", "Intro CS"),
            _enrollment("u1", "Calculus I"),
        ]
        with patch(
            "routes.social.table",
            side_effect=_table_factory(users, enrollments, []),
        ):
            r = client.get("/api/social/students")

        assert r.status_code == 200
        students = r.json()["students"]
        assert len(students) == 1
        assert students[0]["user_id"] == "u1"
        assert students[0]["courses"] == ["Calculus I", "Intro CS"]  # sorted

    def test_courses_deduped_across_offerings(self):
        # Same abstract course taught in two offerings -> appears once.
        users = [{"id": "u1", "name": "Alice", "streak_count": 0}]
        enrollments = [
            _enrollment("u1", "Intro CS"),
            _enrollment("u1", "Intro CS"),
            _enrollment("u1", "Calculus I"),
        ]
        with patch(
            "routes.social.table",
            side_effect=_table_factory(users, enrollments, []),
        ):
            r = client.get("/api/social/students")

        assert r.status_code == 200
        courses = r.json()["students"][0]["courses"]
        assert courses == ["Calculus I", "Intro CS"]

    def test_courses_grouped_per_user(self):
        users = [
            {"id": "u1", "name": "Alice", "streak_count": 1},
            {"id": "u2", "name": "Bob", "streak_count": 2},
        ]
        enrollments = [
            _enrollment("u1", "Intro CS"),
            _enrollment("u2", "Physics"),
        ]
        with patch(
            "routes.social.table",
            side_effect=_table_factory(users, enrollments, []),
        ):
            r = client.get("/api/social/students")

        assert r.status_code == 200
        by_id = {s["user_id"]: s for s in r.json()["students"]}
        assert by_id["u1"]["courses"] == ["Intro CS"]
        assert by_id["u2"]["courses"] == ["Physics"]

    def test_no_enrollments_yields_empty_courses(self):
        users = [{"id": "u1", "name": "Alice", "streak_count": 0}]
        with patch(
            "routes.social.table",
            side_effect=_table_factory(users, [], []),
        ):
            r = client.get("/api/social/students")

        assert r.status_code == 200
        students = r.json()["students"]
        assert len(students) == 1
        assert students[0]["courses"] == []

    def test_response_shape_preserved(self):
        users = [{"id": "u1", "name": "Alice", "streak_count": 5}]
        enrollments = [_enrollment("u1", "Intro CS")]
        node_rows = [
            {"user_id": "u1", "mastery_tier": "mastered",
             "concept_name": "Loops", "mastery_score": 0.9},
            {"user_id": "u1", "mastery_tier": "struggling",
             "concept_name": "Recursion", "mastery_score": 0.2},
        ]
        with patch(
            "routes.social.table",
            side_effect=_table_factory(users, enrollments, node_rows),
        ):
            r = client.get("/api/social/students")

        assert r.status_code == 200
        student = r.json()["students"][0]
        assert set(student.keys()) == {
            "user_id", "name", "streak", "courses", "stats", "top_concepts"
        }
        assert student["streak"] == 5
        assert student["top_concepts"] == ["Loops"]
        assert student["stats"]["mastered"] == 1
        assert student["stats"]["struggling"] == 1
        assert student["stats"]["total"] == 2
