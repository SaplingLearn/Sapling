"""Tests for Gradescope sync.

Two layers:
  - Service parsing helpers (`_parse_grade`, `list_student_courses`,
    `list_assignments`) — pure logic over a mocked GSConnection.
  - Route authz + rate limiting — exercises require_self/_user_owns_course
    scoping and the per-user sliding-window limiter, mocking only the
    Supabase `table()` boundary.
"""
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from main import app
from services import gradescope_service as gs
from services import request_limits


client = TestClient(app)


# ── _parse_grade ─────────────────────────────────────────────────────────────

class TestParseGrade:
    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("85.0", 85.0),
            ("100", 100.0),
            ("0", 0.0),
            ("  92.5  ", 92.5),
            (90, 90.0),
            (88.5, 88.5),
            (None, None),
            ("", None),
            ("—", None),   # em dash (Gradescope "no grade")
            ("-", None),
            ("/", None),
            ("N/A", None),
            ("abc", None),
            ("--", None),  # non-numeric → ValueError → None
        ],
    )
    def test_parse(self, raw, expected):
        assert gs._parse_grade(raw) == expected


# ── list_student_courses ─────────────────────────────────────────────────────

class TestListStudentCourses:
    def test_drops_instructor_courses(self):
        conn = MagicMock()
        conn.account.get_courses.return_value = {
            "student": {
                "c1": SimpleNamespace(
                    name="CS161", full_name="Intro CS", semester="Fall",
                    year="2025", num_assignments="5",
                ),
            },
            "instructor": {"c9": SimpleNamespace(name="TA Course")},
        }
        out = gs.list_student_courses(conn)
        assert [c["id"] for c in out] == ["c1"]
        assert out[0]["name"] == "CS161"
        assert out[0]["semester"] == "Fall"

    def test_handles_non_dict_payload(self):
        conn = MagicMock()
        conn.account.get_courses.return_value = []  # not a dict
        assert gs.list_student_courses(conn) == []

    def test_fetch_error_wrapped(self):
        conn = MagicMock()
        conn.account.get_courses.side_effect = RuntimeError("network down")
        with pytest.raises(gs.GradescopeFetchError):
            gs.list_student_courses(conn)


# ── list_assignments ─────────────────────────────────────────────────────────

class TestListAssignments:
    def test_parses_grades_and_dates(self):
        conn = MagicMock()
        due = SimpleNamespace(isoformat=lambda: "2025-12-01T23:59:00")
        a = SimpleNamespace(
            assignment_id="a1", name="HW1", release_date=None, due_date=due,
            submissions_status="submitted", grade="9.0", max_grade="10",
        )
        conn.account.get_assignments.return_value = [a]
        out = gs.list_assignments(conn, "c1")
        assert out[0]["id"] == "a1"
        assert out[0]["points_earned"] == 9.0
        assert out[0]["points_possible"] == 10.0
        assert out[0]["due_date"] == "2025-12-01T23:59:00"
        assert out[0]["release_date"] is None

    def test_ungraded_assignment_yields_none_earned(self):
        conn = MagicMock()
        a = SimpleNamespace(
            assignment_id="a2", name="HW2", release_date=None, due_date=None,
            submissions_status=None, grade="—", max_grade="10",
        )
        conn.account.get_assignments.return_value = [a]
        out = gs.list_assignments(conn, "c1")
        assert out[0]["points_earned"] is None
        assert out[0]["points_possible"] == 10.0

    def test_fetch_error_wrapped(self):
        conn = MagicMock()
        conn.account.get_assignments.side_effect = RuntimeError("boom")
        with pytest.raises(gs.GradescopeFetchError):
            gs.list_assignments(conn, "c1")


# ── Route authz + rate limiting ──────────────────────────────────────────────

def _table_factory(rows_by_table):
    """side_effect for routes.gradescope.table returning canned rows."""
    def factory(name):
        m = MagicMock()
        m.select.return_value = rows_by_table.get(name, [])
        m.insert.side_effect = lambda d: [d] if isinstance(d, dict) else d
        m.update.side_effect = lambda d, filters=None: [d]
        m.upsert.side_effect = lambda d, **kw: [d] if isinstance(d, dict) else d
        m.delete.return_value = []
        return m
    return factory


@pytest.fixture(autouse=True)
def _clear_rate_state():
    """The limiter keeps process-local state; isolate each test."""
    request_limits._rate_state.clear()
    yield
    request_limits._rate_state.clear()


class TestSyncAuthz:
    def test_sync_unowned_course_returns_404(self):
        # No user_courses row → _user_owns_course False → 404 (IDOR guard).
        with patch("routes.gradescope.table", side_effect=_table_factory({})):
            r = client.post("/api/gradescope/sync/c1", params={"user_id": "u1"})
        assert r.status_code == 404


class TestRateLimiting:
    def test_courses_limited_after_10(self):
        # /courses caps at 10/5min. No creds → 404 for the allowed calls,
        # then 429 once the window is full.
        with patch("routes.gradescope.table", side_effect=_table_factory({})):
            statuses = [
                client.get("/api/gradescope/courses", params={"user_id": "u1"}).status_code
                for _ in range(11)
            ]
        assert statuses[:10] == [404] * 10
        assert statuses[10] == 429

    def test_sync_limited_after_10(self):
        with patch("routes.gradescope.table", side_effect=_table_factory({})):
            statuses = [
                client.post("/api/gradescope/sync/c1", params={"user_id": "u1"}).status_code
                for _ in range(11)
            ]
        assert statuses[10] == 429

    def test_bu_sso_limited_after_3(self):
        # Strictest cap (3/10min). Playwright isn't installed in the test env,
        # so calls 1-3 fail in the flow — but the 4th must be rejected by the
        # limiter before reaching it.
        body = {"user_id": "u1", "bu_username": "x", "bu_password": "y"}
        with patch("routes.gradescope.table", side_effect=_table_factory({})):
            statuses = [
                client.post("/api/gradescope/credentials/bu-sso", json=body).status_code
                for _ in range(4)
            ]
        assert all(s != 429 for s in statuses[:3]), "first 3 calls must not be rate-limited"
        assert statuses[3] == 429

    def test_limit_is_per_user(self):
        # u1 exhausts its window; u2 is unaffected.
        with patch("routes.gradescope.table", side_effect=_table_factory({})):
            for _ in range(11):
                client.get("/api/gradescope/courses", params={"user_id": "u1"})
            other = client.get("/api/gradescope/courses", params={"user_id": "u2"}).status_code
        assert other == 404
