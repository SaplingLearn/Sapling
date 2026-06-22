"""
Regression tests for GET /api/social/students (#158).

Post-#12, `courses` is a shared catalog with no `user_id`; enrollment lives in
`user_courses`. The old code selected `courses.user_id`, which PostgREST rejects
with HTTP 400, breaking the whole students / class-intel surface. These tests
exercise the endpoint against the post-#12 schema shape.
"""
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from main import app

client = TestClient(app)


def _factory(recorder=None):
    def factory(name):
        if recorder is not None:
            recorder.append(name)
        m = MagicMock()
        if name == "users":
            m.select.return_value = [
                {"id": "u1", "name": "Alice", "streak_count": 3},
                {"id": "u2", "name": "Bob", "streak_count": 0},
            ]
        elif name == "user_courses":
            m.select.return_value = [
                {"user_id": "u1", "courses": {"course_name": "Calculus"}},
                {"user_id": "u1", "courses": {"course_name": "Physics"}},
                {"user_id": "u2", "courses": {"course_name": "Biology"}},
            ]
        elif name == "graph_nodes":
            m.select.return_value = [
                {"user_id": "u1", "mastery_tier": "mastered",
                 "concept_name": "Limits", "mastery_score": 0.9},
            ]
        else:
            m.select.return_value = []
        return m

    return factory


class TestGetStudents:
    def test_returns_200_with_per_course_grouping(self):
        with patch("routes.social.table", side_effect=_factory()):
            r = client.get("/api/social/students")

        assert r.status_code == 200
        students = {s["user_id"]: s for s in r.json()["students"]}
        assert sorted(students) == ["u1", "u2"]
        assert students["u1"]["courses"] == ["Calculus", "Physics"]  # sorted
        assert students["u2"]["courses"] == ["Biology"]
        assert students["u1"]["stats"]["mastered"] == 1
        assert students["u1"]["stats"]["total"] == 1
        assert students["u1"]["top_concepts"] == ["Limits"]

    def test_students_sorted_by_name(self):
        with patch("routes.social.table", side_effect=_factory()):
            r = client.get("/api/social/students")
        names = [s["name"] for s in r.json()["students"]]
        assert names == ["Alice", "Bob"]

    def test_queries_user_courses_and_never_selects_courses_user_id(self):
        recorder: list[str] = []
        factory = _factory(recorder)
        with patch("routes.social.table", side_effect=factory) as mocked:
            r = client.get("/api/social/students")

        assert r.status_code == 200
        # Enrollment must be read from user_courses, not the catalog table.
        assert "user_courses" in recorder
        # The embedded select pulls the course name through the join.
        uc_calls = [c for c in mocked.mock_calls if c.args == ("user_courses",)]
        assert uc_calls, "user_courses table was never queried"
        # And nothing selects the column that no longer exists.
        for call in mocked.mock_calls:
            for arg in call.args:
                if isinstance(arg, str):
                    assert "user_id,course_name" not in arg
