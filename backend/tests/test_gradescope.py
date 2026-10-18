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
        # No resolvable enrollment → 404 (IDOR guard). This used to read a
        # `user_courses` row; 0020 renamed that table to `enrollments`, so the
        # guard now resolves through academics.enrollment_id_for (#265).
        # Patched explicitly: enrollment_id_for reads services.academics.table,
        # NOT routes.gradescope.table, so mocking the latter alone would leave
        # this passing by accident via the suite's global stub.
        with (
            patch("routes.gradescope.table", side_effect=_table_factory({})),
            patch("routes.gradescope.enrollment_id_for", return_value=None),
        ):
            r = client.post("/api/gradescope/sync/c1", params={"user_id": "u1"})
        assert r.status_code == 404


class TestLinkIsEnrollmentKeyed:
    """#265: gradescope_course_links keys on enrollment_id (0027). These pin
    the SHAPE the routes send — a mocked DB can't catch column drift (that's
    what the integration lane is for), but it can catch a regression back to
    the abstract course id, which is what broke here."""

    def test_link_writes_enrollment_id_and_never_the_course_id(self):
        writes = {}

        def factory(name):
            m = MagicMock()
            m.select.return_value = []
            m.delete.return_value = []

            def _insert(d):
                writes[name] = d
                return [d]

            m.insert.side_effect = _insert
            return m

        with (
            patch("routes.gradescope.table", side_effect=factory),
            patch("routes.gradescope.enrollment_id_for", return_value="enr-1"),
        ):
            r = client.post(
                "/api/gradescope/link",
                json={
                    "user_id": "u1",
                    "sapling_course_id": "course-1",
                    "gradescope_course_id": "gs-9",
                },
            )

        assert r.status_code == 200
        row = writes["gradescope_course_links"]
        assert row["enrollment_id"] == "enr-1"
        # The columns the pre-redesign code wrote do not exist on the table.
        assert "sapling_course_id" not in row
        assert "user_id" not in row
        # ...but the API still answers in course-id vocabulary.
        assert r.json()["link"]["sapling_course_id"] == "course-1"

    def test_link_404s_when_the_user_has_no_enrollment(self):
        with (
            patch("routes.gradescope.table", side_effect=_table_factory({})),
            patch("routes.gradescope.enrollment_id_for", return_value=None),
        ):
            r = client.post(
                "/api/gradescope/link",
                json={
                    "user_id": "u1",
                    "sapling_course_id": "course-1",
                    "gradescope_course_id": "gs-9",
                },
            )
        assert r.status_code == 404

    def test_list_links_maps_enrollment_rows_back_to_course_ids(self):
        rows = {
            "gradescope_course_links": [
                {
                    "id": "l1",
                    "enrollment_id": "enr-1",
                    "gradescope_course_id": "gs-9",
                    "last_synced_at": None,
                }
            ]
        }
        with (
            patch("routes.gradescope.table", side_effect=_table_factory(rows)),
            patch(
                "routes.gradescope.user_enrollment_ids",
                return_value=[{"id": "enr-1", "offering_id": "off-1"}],
            ),
            patch("routes.gradescope.offering_course_id", return_value="course-1"),
        ):
            r = client.get("/api/gradescope/links", params={"user_id": "u1"})

        assert r.status_code == 200
        link = r.json()["links"][0]
        assert link["sapling_course_id"] == "course-1"
        assert link["gradescope_course_id"] == "gs-9"


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


class TestPastedCookieCleaning:
    """`_clean_pasted_cookie` strips only unambiguous packaging. It must NOT
    touch percent-encoding — deciding encoded-vs-decoded is login_with_cookies'
    job, which tries both against /account.

    Values below are structurally identical to a real Gradescope cookie (base64
    body, '--', 40 hex chars of HMAC) but are dummies.
    """

    _clean = staticmethod(gs._clean_pasted_cookie)

    DECODED = "YWJjZGVm==--3f9fe2c7fc866986103e247fafc5a5d00cba53a8"
    ENCODED = "YWJjZGVm%3D%3D--3f9fe2c7fc866986103e247fafc5a5d00cba53a8"

    def test_percent_encoding_is_preserved_not_guessed_at(self):
        assert self._clean(self.ENCODED) == self.ENCODED

    def test_decoded_value_is_untouched(self):
        assert self._clean(self.DECODED) == self.DECODED

    def test_name_prefix_is_stripped(self):
        assert self._clean(f"_gradescope_session={self.DECODED}") == self.DECODED
        assert self._clean(f"signed_token={self.DECODED}") == self.DECODED

    def test_surrounding_quotes_and_whitespace_are_stripped(self):
        assert self._clean(f'  "{self.DECODED}"  ') == self.DECODED

    def test_empty_and_none_become_none(self):
        assert self._clean(None) is None
        assert self._clean("   ") is None

    def test_base64_special_characters_survive(self):
        val = "YWJj+ZGVm/Zm9v--3f9fe2c7fc866986103e247fafc5a5d00cba53a8"
        assert self._clean(val) == val


class TestCookieLoginTriesBothEncodings:
    """A percent-encoded cookie that fails must be retried decoded before the
    user is told their session is expired."""

    ENCODED = "YWJjZGVm%3D%3D--3f9fe2c7fc866986103e247fafc5a5d00cba53a8"
    DECODED = "YWJjZGVm==--3f9fe2c7fc866986103e247fafc5a5d00cba53a8"

    def _fake_session(self, results, seen):
        """Session double whose /account result depends on the cookie set."""
        def _make():
            s = MagicMock()
            s.headers = {}
            s.cookies = MagicMock()
            store = {}
            s.cookies.set = lambda name, value, **kw: store.__setitem__(name, value)

            def _get(url, **kw):
                value = store.get("_gradescope_session")
                seen.append(value)
                ok = results.get(value, False)
                return SimpleNamespace(
                    status_code=200 if ok else 302,
                    url="https://www.gradescope.com/account" if ok
                        else "https://www.gradescope.com/login",
                    text="<meta name='csrf-token' content='tok'>",
                )

            s.get = _get
            return s
        return _make

    def test_falls_back_to_decoded_form(self):
        seen: list[str] = []
        with patch.object(gs, "_require_gradescopeapi", lambda: None), \
             patch.object(gs, "requests") as req, \
             patch.object(gs, "GSConnection", MagicMock()), \
             patch.object(gs, "Account", MagicMock()):
            req.Session = self._fake_session({self.DECODED: True}, seen)
            req.RequestException = Exception
            gs.login_with_cookies(signed_token=None, gradescope_session=self.ENCODED)
        assert seen == [self.ENCODED, self.DECODED], (
            "must try the pasted form first, then the decoded one"
        )

    def test_no_second_attempt_when_first_form_works(self):
        seen: list[str] = []
        with patch.object(gs, "_require_gradescopeapi", lambda: None), \
             patch.object(gs, "requests") as req, \
             patch.object(gs, "GSConnection", MagicMock()), \
             patch.object(gs, "Account", MagicMock()):
            req.Session = self._fake_session({self.ENCODED: True}, seen)
            req.RequestException = Exception
            gs.login_with_cookies(signed_token=None, gradescope_session=self.ENCODED)
        assert seen == [self.ENCODED], "must not retry once a form succeeds"

    def test_both_forms_failing_reports_expired(self):
        seen: list[str] = []
        with patch.object(gs, "_require_gradescopeapi", lambda: None), \
             patch.object(gs, "requests") as req, \
             patch.object(gs, "GSConnection", MagicMock()), \
             patch.object(gs, "Account", MagicMock()):
            req.Session = self._fake_session({}, seen)
            req.RequestException = Exception
            with pytest.raises(gs.GradescopeAuthError, match="expired"):
                gs.login_with_cookies(signed_token=None, gradescope_session=self.ENCODED)
        assert len(seen) == 2, "both encodings must be attempted before giving up"
