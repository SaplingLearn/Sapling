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
