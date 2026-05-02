"""Route tests for /api/gradebook/* — exercise the real Pydantic + service code,
mock only the Supabase `table()` boundary."""
from unittest.mock import patch, MagicMock

import pytest
from fastapi.testclient import TestClient

from main import app


client = TestClient(app)


def _mock_self():
    """Bypass require_self auth in tests."""
    return patch("routes.gradebook.require_self", return_value=None)


def _mock_table_rows(rows_by_table):
    """Return a side_effect for `db.connection.table` that returns canned rows.

    rows_by_table: {"users": [...], "courses": [...], ...}
    Each `select(...)` call returns the rows for that table; `insert`,
    `update`, `delete` echo the data back.
    """
    def factory(name):
        m = MagicMock()
        m.select.return_value = rows_by_table.get(name, [])
        m.insert.side_effect = lambda d: [d] if isinstance(d, dict) else d
        m.update.side_effect = lambda d, filters: [d]
        m.delete.return_value = []
        return m
    return factory


# ── GET /summary ─────────────────────────────────────────────────────────────

class TestSummary:
    def test_returns_courses_with_computed_grades(self):
        enrolled = [
            {"course_id": "cs161", "letter_scale": None, "courses": {
                "id": "cs161", "course_code": "CS 161", "course_name": "Intro CS",
                "semester": "Spring 2026"}},
        ]
        cats = [{"id": "exams", "course_id": "cs161", "name": "Exams", "weight": 100, "sort_order": 0}]
        assigns = [
            {"id": "a1", "course_id": "cs161", "title": "Midterm", "category_id": "exams",
             "points_possible": 100, "points_earned": 90},
        ]
        rows = {
            "user_courses": enrolled,
            "course_categories": cats,
            "assignments": assigns,
        }
        with _mock_self(), patch("routes.gradebook.table", side_effect=_mock_table_rows(rows)):
            r = client.get("/api/gradebook/summary",
                           params={"user_id": "u1", "semester": "Spring 2026"})
        assert r.status_code == 200
        body = r.json()
        assert len(body["courses"]) == 1
        c = body["courses"][0]
        assert c["course_code"] == "CS 161"
        assert c["percent"] == pytest.approx(90.0)
        assert c["letter"] == "A-"
        assert c["graded_count"] == 1
        assert c["total_count"] == 1


# ── GET /courses/{course_id} ─────────────────────────────────────────────────

class TestCourseDetail:
    def test_returns_categories_assignments_and_overall(self):
        enrollment = [{"course_id": "cs161", "letter_scale": None,
                       "courses": {"id": "cs161", "course_code": "CS 161",
                                   "course_name": "Intro CS", "semester": "Spring 2026"}}]
        cats = [
            {"id": "exams", "course_id": "cs161", "user_id": "u1",
             "name": "Exams", "weight": 60, "sort_order": 0},
            {"id": "psets", "course_id": "cs161", "user_id": "u1",
             "name": "P-Sets", "weight": 40, "sort_order": 1},
        ]
        assigns = [
            {"id": "a1", "user_id": "u1", "course_id": "cs161", "title": "Midterm",
             "category_id": "exams", "points_possible": 100, "points_earned": 80,
             "due_date": "2026-03-10", "assignment_type": "exam", "notes": None,
             "source": "manual"},
            {"id": "a2", "user_id": "u1", "course_id": "cs161", "title": "P-Set 1",
             "category_id": "psets", "points_possible": 100, "points_earned": 100,
             "due_date": "2026-02-01", "assignment_type": "homework", "notes": None,
             "source": "manual"},
        ]
        rows = {
            "user_courses": enrollment,
            "course_categories": cats,
            "assignments": assigns,
        }
        with _mock_self(), patch("routes.gradebook.table", side_effect=_mock_table_rows(rows)):
            r = client.get("/api/gradebook/courses/cs161", params={"user_id": "u1"})
        assert r.status_code == 200
        body = r.json()
        assert body["course_code"] == "CS 161"
        # 0.8*60 + 1.0*40 = 88
        assert body["percent"] == pytest.approx(88.0)
        assert body["letter"] == "B+"
        assert {c["name"] for c in body["categories"]} == {"Exams", "P-Sets"}
        assert len(body["assignments"]) == 2

    def test_404_when_user_not_enrolled(self):
        rows = {"user_courses": []}
        with _mock_self(), patch("routes.gradebook.table", side_effect=_mock_table_rows(rows)):
            r = client.get("/api/gradebook/courses/nope", params={"user_id": "u1"})
        assert r.status_code == 404


# ── Categories CRUD ──────────────────────────────────────────────────────────

class TestCategories:
    def test_create_one_category(self):
        rows = {"user_courses": [{"id": "uc1"}]}
        with _mock_self(), patch("routes.gradebook.table", side_effect=_mock_table_rows(rows)):
            r = client.post(
                "/api/gradebook/courses/cs161/categories",
                json={"user_id": "u1", "name": "Exams", "weight": 40},
            )
        assert r.status_code == 200
        assert r.json()["category"]["name"] == "Exams"

    def test_create_rejects_unknown_course(self):
        rows = {"user_courses": []}
        with _mock_self(), patch("routes.gradebook.table", side_effect=_mock_table_rows(rows)):
            r = client.post(
                "/api/gradebook/courses/cs999/categories",
                json={"user_id": "u1", "name": "Exams", "weight": 40},
            )
        assert r.status_code == 404

    def test_bulk_update_validates_weight_total(self):
        rows = {"user_courses": [{"id": "uc1"}]}
        body = {
            "user_id": "u1",
            "categories": [
                {"id": "exams", "name": "Exams", "weight": 60, "sort_order": 0},
                {"id": "psets", "name": "P-Sets", "weight": 30, "sort_order": 1},
            ],
        }
        with _mock_self(), patch("routes.gradebook.table", side_effect=_mock_table_rows(rows)):
            r = client.patch("/api/gradebook/courses/cs161/categories", json=body)
        assert r.status_code == 400
        assert "100" in r.json()["detail"].lower() or "weight" in r.json()["detail"].lower()

    def test_bulk_update_accepts_total_100(self):
        rows = {"user_courses": [{"id": "uc1"}]}
        body = {
            "user_id": "u1",
            "categories": [
                {"id": "exams", "name": "Exams", "weight": 60, "sort_order": 0},
                {"id": "psets", "name": "P-Sets", "weight": 40, "sort_order": 1},
            ],
        }
        with _mock_self(), patch("routes.gradebook.table", side_effect=_mock_table_rows(rows)):
            r = client.patch("/api/gradebook/courses/cs161/categories", json=body)
        assert r.status_code == 200
        assert len(r.json()["categories"]) == 2

    def test_delete_orphans_assignments(self):
        rows = {"course_categories": [{"id": "exams", "user_id": "u1", "course_id": "cs161"}]}
        with _mock_self(), patch("routes.gradebook.table", side_effect=_mock_table_rows(rows)):
            r = client.delete("/api/gradebook/categories/exams", params={"user_id": "u1"})
        assert r.status_code == 200


# ── Assignments CRUD ─────────────────────────────────────────────────────────

class TestAssignments:
    def test_create_assignment_minimal(self):
        rows = {"user_courses": [{"id": "uc1"}]}
        body = {"user_id": "u1", "course_id": "cs161", "title": "Midterm 1"}
        with _mock_self(), patch("routes.gradebook.table", side_effect=_mock_table_rows(rows)):
            r = client.post("/api/gradebook/assignments", json=body)
        assert r.status_code == 200
        a = r.json()["assignment"]
        assert a["title"] == "Midterm 1"
        assert a["source"] == "manual"

    def test_create_rejects_unknown_course(self):
        rows = {"user_courses": []}
        body = {"user_id": "u1", "course_id": "cs999", "title": "X"}
        with _mock_self(), patch("routes.gradebook.table", side_effect=_mock_table_rows(rows)):
            r = client.post("/api/gradebook/assignments", json=body)
        assert r.status_code == 404

    def test_create_rejects_zero_points_possible(self):
        rows = {"user_courses": [{"id": "uc1"}]}
        body = {"user_id": "u1", "course_id": "cs161", "title": "X",
                "points_possible": 0}
        with _mock_self(), patch("routes.gradebook.table", side_effect=_mock_table_rows(rows)):
            r = client.post("/api/gradebook/assignments", json=body)
        assert r.status_code == 422  # Pydantic gt=0 validation

    def test_update_grade_inline(self):
        rows = {"assignments": [{"id": "a1", "user_id": "u1", "course_id": "cs161"}]}
        body = {"user_id": "u1", "points_earned": 87}
        with _mock_self(), patch("routes.gradebook.table", side_effect=_mock_table_rows(rows)):
            r = client.patch("/api/gradebook/assignments/a1", json=body)
        assert r.status_code == 200

    def test_update_404_when_not_owner(self):
        rows = {"assignments": []}
        body = {"user_id": "u1", "points_earned": 87}
        with _mock_self(), patch("routes.gradebook.table", side_effect=_mock_table_rows(rows)):
            r = client.patch("/api/gradebook/assignments/a1", json=body)
        assert r.status_code == 404

    def test_delete_assignment(self):
        rows = {"assignments": [{"id": "a1", "user_id": "u1"}]}
        with _mock_self(), patch("routes.gradebook.table", side_effect=_mock_table_rows(rows)):
            r = client.delete("/api/gradebook/assignments/a1", params={"user_id": "u1"})
        assert r.status_code == 200
