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

    def _filters_for(self, q: str) -> dict:
        captured = {}
        mock = MagicMock()

        def select(columns="*", filters=None, **kw):
            captured.update(filters or {})
            return []

        mock.select.side_effect = select
        with patch("routes.onboarding.table", return_value=mock):
            res = client.get("/api/onboarding/courses", params={"q": q})
        assert res.status_code == 200
        return captured

    def test_a_comma_in_the_query_cannot_break_the_logic_tree(self):
        """#592 review C11. The query is user input interpolated into a
        PostgREST `or=(…)` tree, where a bare value ends at the first comma or
        paren — so searching for "Ethics, Law" built two broken operands and
        returned nonsense (or a 400) rather than the course."""
        clause = self._filters_for("Ethics, Law")["or"]

        assert clause == (
            '(course_name.ilike."%Ethics, Law%",'
            'course_code.ilike."%Ethics, Law%")'
        )

    def test_like_metacharacters_in_the_query_are_not_wildcards(self):
        """`_` is LIKE's any-single-character wildcard and `%` is any run of
        them, so typing either turned the search into a pattern over the whole
        catalog. Only the two `%` the route adds are live."""
        clause = self._filters_for("CS_1 100%")["or"]

        # `\\_`, not `\_`: the LIKE escape runs first and the PostgREST quote
        # then doubles its backslashes. The other order emits a bare `\%` that
        # PostgREST unescapes straight back into a live wildcard.
        assert clause == (
            r'(course_name.ilike."%CS\\_1 100\\%%",'
            r'course_code.ilike."%CS\\_1 100\\%%")'
        )

    def test_a_quote_in_the_query_is_escaped_rather_than_closing_the_value(self):
        clause = self._filters_for('say "hi"')["or"]

        assert clause.startswith(r'(course_name.ilike."%say \"hi\"%"')

    def test_a_blank_query_adds_no_filter_at_all(self):
        assert "or" not in self._filters_for("   ")

    def test_collapses_duplicate_course_codes(self):
        # The catalog can hold two DISTINCT abstract courses (different ids,
        # possibly different names) that share a course_code — e.g. the seed-*
        # (Sapling Demo University) and rich-* (Rich Local University) demo
        # schools both define CS101 / BIO110. The picker must not surface them
        # as visually-indistinguishable duplicates (finding F2): collapse by
        # course_code so each code appears once.
        mock = MagicMock()
        mock.select.return_value = [
            {"id": "seed-course-cs101", "course_code": "CS101",
             "course_name": "Intro to Computer Science"},
            {"id": "rich-course-cs101", "course_code": "CS101",
             "course_name": "Introduction to Computer Science"},
            {"id": "seed-course-bio110", "course_code": "BIO110",
             "course_name": "Cell Biology"},
            {"id": "rich-course-bio110", "course_code": "BIO110",
             "course_name": "Cell Biology"},
        ]
        with patch("routes.onboarding.table", return_value=mock):
            res = client.get("/api/onboarding/courses?q=c")

        assert res.status_code == 200
        courses = res.json()["courses"]
        codes = [c["course_code"] for c in courses]
        # No two returned entries share a course_code.
        assert len(codes) == len(set(codes)), f"duplicate course codes leaked: {codes}"
        assert sorted(codes) == ["BIO110", "CS101"]

    def test_distinct_codes_are_all_kept(self):
        # Dedup keys on course_code only; distinct codes (even with blank codes)
        # must all survive so the picker still lists every real course.
        mock = MagicMock()
        mock.select.return_value = [
            {"id": "a", "course_code": "CS101", "course_name": "Intro CS"},
            {"id": "b", "course_code": "MATH210", "course_name": "Linear Algebra"},
            {"id": "c", "course_code": "", "course_name": "Uncoded One"},
            {"id": "d", "course_code": "", "course_name": "Uncoded Two"},
        ]
        with patch("routes.onboarding.table", return_value=mock):
            res = client.get("/api/onboarding/courses")

        assert res.status_code == 200
        ids = [c["id"] for c in res.json()["courses"]]
        # All four survive: two distinct codes + two blank-code rows are not
        # collapsed into each other.
        assert ids == ["a", "b", "c", "d"]


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
            elif name == "user_profiles":
                m.select.return_value = []
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

        # onboarding_completed flag stays on `users`; profile fields moved to
        # user_profiles (migration 0024).
        from services.encryption import decrypt
        tables["users"].update.assert_called_once()
        users_update = tables["users"].update.call_args[0][0]
        assert users_update == {"onboarding_completed": True}

        tables["user_profiles"].upsert.assert_called_once()
        profile_data = tables["user_profiles"].upsert.call_args[0][0]
        assert profile_data["user_id"] == "user_123"
        assert decrypt(profile_data["first_name"]) == "Jose"
        assert decrypt(profile_data["last_name"]) == "Cruz"
        assert decrypt(profile_data["name"]) == "Jose Cruz"
        assert profile_data["year"] == "junior"
        assert profile_data["majors"] == ["Computer Science"]
        assert profile_data["minors"] == ["Mathematics"]
        assert profile_data["learning_style"] == "visual"

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
        profile_data = tables["user_profiles"].upsert.call_args[0][0]
        assert profile_data["minors"] == []
