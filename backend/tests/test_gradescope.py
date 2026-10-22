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
            ("NaN", None),
            ("Infinity", None),
            ("-Infinity", None),
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
        with pytest.raises(gs.GradescopeFetchError, match="unexpected course list"):
            gs.list_student_courses(conn)

    def test_fetch_error_wrapped(self):
        conn = MagicMock()
        conn.account.get_courses.side_effect = RuntimeError("network down")
        with pytest.raises(gs.GradescopeFetchError):
            gs.list_student_courses(conn)


# ── list_assignments ─────────────────────────────────────────────────────────

class TestListAssignments:
    @pytest.mark.parametrize("payload", [None, {}, "login page"])
    def test_unexpected_scraper_result_is_reported_as_fetch_failure(self, payload):
        conn = MagicMock()
        conn.account.get_assignments.return_value = payload
        with pytest.raises(gs.GradescopeFetchError, match="unexpected assignment list"):
            gs.list_assignments(conn, "course")

    def test_missing_id_is_not_the_literal_none(self):
        conn = MagicMock()
        conn.account.get_assignments.return_value = [SimpleNamespace(assignment_id=None)]
        assert gs.list_assignments(conn, "c1")[0]["id"] == ""

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
        rows = rows_by_table.get(name, [])
        m.select_with_count.return_value = (rows, len(rows))
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
        # Strictest cap (3/10min). Keep this hermetic even when Chromium is
        # installed: the first three calls reach the mocked flow, and the
        # fourth must be rejected before launching a browser or sending Duo.
        body = {"user_id": "u1", "bu_username": "x", "bu_password": "y"}
        with (
            patch("routes.gradescope.table", side_effect=_table_factory({})),
            patch.object(gs, "login_via_bu_sso", side_effect=gs.GradescopeAuthError("Unavailable")) as login,
        ):
            statuses = [
                client.post("/api/gradescope/credentials/bu-sso", json=body).status_code
                for _ in range(4)
            ]
        assert all(s != 429 for s in statuses[:3]), "first 3 calls must not be rate-limited"
        assert statuses[3] == 429
        assert login.call_count == 3

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


class TestAuthenticationValidation:
    @pytest.mark.parametrize("status", [429, 500, 503])
    def test_cookie_outage_is_retryable_not_an_expired_session(self, status):
        session = MagicMock()
        session.get.return_value = SimpleNamespace(
            status_code=status, url="https://www.gradescope.com/account", text="unavailable",
        )
        with patch.object(gs, "_new_session", return_value=session):
            with pytest.raises(gs.GradescopeFetchError, match="temporarily unavailable"):
                gs.login_with_cookies(None, "encoded%3D")
        session.get.assert_called_once()
        session.close.assert_called_once()

    @pytest.mark.parametrize("step", ["login", "account"])
    def test_password_outage_is_retryable_and_closes_the_session(self, step):
        session = MagicMock()
        session.get.side_effect = [
            SimpleNamespace(text='<form action="/login"><input name="authenticity_token" value="csrf"></form>', raise_for_status=lambda: None),
            SimpleNamespace(status_code=503, url="https://www.gradescope.com/account"),
        ]
        session.post.return_value = SimpleNamespace(
            status_code=503 if step == "login" else 200,
            history=[SimpleNamespace(status_code=302)],
            url="https://www.gradescope.com/", text="",
        )
        with patch.object(gs, "_new_session", return_value=session):
            with pytest.raises(gs.GradescopeFetchError, match="temporarily unavailable"):
                gs.login("student@example.edu", "test-password")
        session.close.assert_called_once()

    def test_missing_login_form_is_a_scraper_failure_and_closes_session(self):
        session = MagicMock()
        session.get.return_value = SimpleNamespace(text="<html>Changed page</html>", raise_for_status=lambda: None)
        with patch.object(gs, "_new_session", return_value=session):
            with pytest.raises(gs.GradescopeFetchError, match="markup may have changed"):
                gs.login("student@example.edu", "test-password")
        session.close.assert_called_once()
        session.post.assert_not_called()

    def test_cookie_network_failure_is_not_reported_as_invalid_credentials(self):
        session = MagicMock()
        session.get.side_effect = gs.requests.ConnectionError("connection refused")
        with patch.object(gs, "_new_session", return_value=session):
            with pytest.raises(gs.GradescopeFetchError, match="Couldn't reach Gradescope"):
                gs.login_with_cookies(None, "encoded%3D")
        session.get.assert_called_once()
        session.close.assert_called_once()

    def test_credential_network_failure_returns_502_without_saving(self):
        saved = MagicMock()
        with (
            patch("routes.gradescope.table", return_value=saved),
            patch.object(gs, "login", side_effect=gs.GradescopeFetchError("Couldn't reach Gradescope")),
        ):
            response = client.post("/api/gradescope/credentials", json={
                "user_id": "u1", "email": "student@example.edu", "password": "test-password",
            })
        assert response.status_code == 502
        saved.upsert.assert_not_called()

    def test_password_login_requires_and_accepts_a_verified_account(self):
        session = MagicMock()
        session.get.side_effect = [
            SimpleNamespace(text='<form action="/login"><input name="authenticity_token" value="csrf"></form>', raise_for_status=lambda: None),
            SimpleNamespace(status_code=200, url="https://www.gradescope.com/account"),
        ]
        session.post.return_value = SimpleNamespace(
            status_code=200, history=[SimpleNamespace(status_code=302)],
            url="https://www.gradescope.com/account", text='<meta name="csrf-token" content="token">',
        )
        with patch.object(gs, "_new_session", return_value=session):
            connection = gs.login("student@example.edu", "test-password")
        assert connection.logged_in is True
        assert connection.session is session
        assert session.headers.update.call_args.args[0] == {"X-CSRF-Token": "token"}

    def test_password_login_landing_on_account_is_not_verified_twice(self):
        session = MagicMock()
        session.get.side_effect = [
            SimpleNamespace(text='<form action="/login"><input name="authenticity_token" value="csrf"></form>', raise_for_status=lambda: None),
        ]
        session.post.return_value = SimpleNamespace(
            status_code=200, history=[SimpleNamespace(status_code=302)],
            url="https://www.gradescope.com/account", text="",
        )
        with patch.object(gs, "_new_session", return_value=session):
            gs.login("student@example.edu", "test-password")
        assert session.get.call_count == 1, "the POST already landed on /account"

    @pytest.mark.parametrize("url", [
        "https://gradescope.com.evil.example/account",
        "https://shib.bu.edu/?next=gradescope.com/account",
        "http://www.gradescope.com/account",
        "https://www.gradescope.com/login",
    ])
    def test_rejects_non_account_redirects(self, url):
        assert not gs._is_gradescope_url(url, account=True)

    @pytest.mark.parametrize("url", [
        "https://www.gradescope.com/",
        "https://www.gradescope.com",
        "https://gradescope.com/",
    ])
    def test_the_gradescope_root_counts_as_landed_off_login(self, url):
        # A successful password POST or SAML callback can land on the root;
        # /account verification (not this check) is what proves the login.
        assert gs._is_gradescope_url(url)

    def test_the_login_page_is_not_landed_off_login(self):
        assert not gs._is_gradescope_url("https://www.gradescope.com/login")
        assert not gs._is_gradescope_url("https://www.gradescope.com/login/")

    def test_password_login_that_lands_on_the_root_is_accepted(self):
        session = MagicMock()
        session.get.side_effect = [
            SimpleNamespace(text='<form action="/login"><input name="authenticity_token" value="csrf"></form>', raise_for_status=lambda: None),
            SimpleNamespace(status_code=200, url="https://www.gradescope.com/account"),
        ]
        session.post.return_value = SimpleNamespace(
            status_code=200, history=[SimpleNamespace(status_code=302)],
            url="https://www.gradescope.com/", text="",
        )
        with patch.object(gs, "_new_session", return_value=session):
            connection = gs.login("student@example.edu", "test-password")
        assert connection.logged_in is True

    def test_password_redirect_to_error_page_is_not_a_login(self):
        session = MagicMock()
        session.get.side_effect = [
            SimpleNamespace(text='<form action="/login"><input name="authenticity_token" value="csrf"></form>', raise_for_status=lambda: None),
            SimpleNamespace(status_code=200, url="https://www.gradescope.com/login"),
        ]
        session.post.return_value = SimpleNamespace(
            status_code=200, history=[SimpleNamespace(status_code=302)],
            url="https://www.gradescope.com/", text="",
        )
        with patch.object(gs, "_new_session", return_value=session):
            with pytest.raises(gs.GradescopeAuthError, match="authenticated session"):
                gs.login("student@example.edu", "test-password")
        assert session.post.call_args.kwargs["data"]["session[password]"] == "test-password"
        assert "params" not in session.post.call_args.kwargs
        session.close.assert_called_once()

    def test_upstream_requests_have_a_default_timeout(self):
        session = gs._new_session()
        try:
            with patch.object(session, "send", return_value=SimpleNamespace()) as send:
                session.get("https://www.gradescope.com/account")
            assert send.call_args.kwargs["timeout"] == 20
        finally:
            session.close()


class TestSyncPersistence:
    def _sync(self, incoming, *, fail_insert=False, links=None, existing_rows=None):
        tables = {name: MagicMock() for name in (
            "assignments", "gradebook_categories", "gradescope_course_links", "gradescope_credentials",
        )}
        tables["assignments"].select.return_value = existing_rows if existing_rows is not None else [{"id": "saved", "gradescope_assignment_id": "existing"}]
        tables["gradebook_categories"].select.return_value = [{"id": "cat", "name": "Homework"}]
        for name in ("assignments", "gradebook_categories"):
            rows = tables[name].select.return_value
            tables[name].select_with_count.return_value = (rows, len(rows))
            if len(rows) > 1000:
                tables[name].select_with_count.side_effect = [
                    (rows[offset:offset + 1000], len(rows)) for offset in range(0, len(rows), 1000)
                ]
        tables["gradescope_course_links"].select.return_value = links if links is not None else [
            {"id": "link", "enrollment_id": "fall-enrollment", "gradescope_course_id": "gs-course"},
        ]
        if fail_insert:
            tables["assignments"].insert.side_effect = RuntimeError("write failed")
        with (
            patch("routes.gradescope.table", side_effect=lambda name: tables[name]),
            patch("routes.gradescope._all_enrollments_for", return_value=["fall-enrollment"]),
            patch("routes.gradescope._load_creds", return_value=MagicMock()),
            patch("routes.gradescope._establish_connection"),
            patch.object(gs, "list_assignments", return_value=incoming),
        ):
            response = client.post("/api/gradescope/sync/c1", params={"user_id": "u1", "semester": "Fall 2025"})
        return response, tables

    def test_import_encrypts_scores_and_preserves_existing_missing_scores(self):
        from services.encryption import decrypt

        response, tables = self._sync([
            {"id": "new", "name": "Homework 1", "points_earned": 0, "points_possible": 10},
            {"id": "existing", "name": "Exam", "points_earned": None, "points_possible": None},
            {"id": "", "name": "Unavailable assignment"},
        ])
        assert response.status_code == 200
        assert response.json() == {"inserted": 1, "updated": 1, "skipped": 1, "failed": 0}
        inserted = tables["assignments"].insert.call_args.args[0]
        assert inserted["enrollment_id"] == "fall-enrollment"
        assert inserted["category_id"] == "cat"
        assert float(decrypt(inserted["points_earned"])) == 0
        assert float(decrypt(inserted["points_possible"])) == 10
        updated = tables["assignments"].update.call_args.args[0]
        assert "points_earned" not in updated and "points_possible" not in updated
        assert "category_id" not in updated

    def test_total_write_failure_is_not_reported_as_success(self):
        response, tables = self._sync([{"id": "new"}], fail_insert=True)
        assert response.status_code == 502
        tables["gradescope_course_links"].update.assert_not_called()
        tables["gradescope_credentials"].update.assert_not_called()

    def test_duplicate_scraped_id_updates_the_same_new_assignment(self):
        response, tables = self._sync([{"id": "new", "name": "Homework"}] * 2)
        assert response.json() == {"inserted": 1, "updated": 1, "skipped": 0, "failed": 0}
        tables["assignments"].insert.assert_called_once()
        inserted_id = tables["assignments"].insert.call_args.args[0]["id"]
        assert tables["assignments"].update.call_args.kwargs["filters"] == {"id": f"eq.{inserted_id}"}

    def test_existing_assignments_beyond_the_postgrest_cap_are_updated(self):
        existing = [{"id": f"saved-{i}", "gradescope_assignment_id": f"gs-{i}"} for i in range(1001)]
        response, tables = self._sync([{"id": "gs-1000", "name": "Homework"}], existing_rows=existing)
        assert response.json()["updated"] == 1
        tables["assignments"].insert.assert_not_called()
        assert tables["assignments"].update.call_args.kwargs["filters"] == {"id": "eq.saved-1000"}

    def test_partial_failure_does_not_advance_success_timestamp(self):
        response, tables = self._sync([{"id": "new"}, {"id": "existing"}], fail_insert=True)
        assert response.status_code == 200
        assert response.json()["failed"] == 1
        assert response.json()["updated"] == 1
        tables["gradescope_course_links"].update.assert_not_called()

    def test_ambiguous_links_are_rejected_before_fetching_grades(self):
        response, tables = self._sync([], links=[
            {"id": "one", "enrollment_id": "fall", "gradescope_course_id": "gs-one"},
            {"id": "two", "enrollment_id": "spring", "gradescope_course_id": "gs-two"},
        ])
        assert response.status_code == 409
        tables["assignments"].insert.assert_not_called()


class TestSemesterScoping:
    def test_selected_semester_filters_enrollments(self):
        from routes.gradescope import _all_enrollments_for

        with (
            patch("routes.gradescope.user_offering_ids_for_course", return_value=["fall", "spring"]),
            patch("routes.gradescope.user_enrollment_ids", return_value=[
                {"id": "fall-enrollment", "offering_id": "fall"},
                {"id": "spring-enrollment", "offering_id": "spring"},
            ]),
            patch("routes.gradescope.term_id_for_label", return_value="fall-term"),
            patch("routes.gradescope.term_for_offering", side_effect=lambda oid: {"id": f"{oid}-term"}),
        ):
            assert _all_enrollments_for("u1", "c1", "Fall 2025") == ["fall-enrollment"]

    def test_invalid_semester_never_falls_back_to_current_term(self):
        from routes.gradescope import _all_enrollments_for

        with (
            patch("routes.gradescope.user_offering_ids_for_course", return_value=["spring"]),
            patch("routes.gradescope.term_id_for_label", return_value=None),
        ):
            assert _all_enrollments_for("u1", "c1", "Missing term") == []

    def test_linking_a_term_preserves_other_terms_links(self):
        writes = MagicMock()
        writes.insert.side_effect = lambda payload: [{"id": "link", **payload}]
        with (
            patch("routes.gradescope.table", return_value=writes),
            patch("routes.gradescope._all_enrollments_for", return_value=["fall-enrollment"]),
        ):
            response = client.post("/api/gradescope/link", json={
                "user_id": "u1", "sapling_course_id": "c1", "gradescope_course_id": "gs-fall", "semester": "Fall 2025",
            })
        assert response.status_code == 200
        assert writes.insert.call_args.args[0]["enrollment_id"] == "fall-enrollment"
        assert writes.delete.call_args.kwargs["filters"]["enrollment_id"] == "in.(fall-enrollment)"


class TestBuSsoCredentials:
    def test_validated_sso_stores_only_encrypted_cookies(self):
        from services.encryption import decrypt
        import json

        saved = MagicMock()
        cookies = {"_gradescope_session": "session-cookie", "signed_token": "remember-cookie"}
        with (
            patch("routes.gradescope.table", return_value=saved),
            patch.object(gs, "login_via_bu_sso", return_value=cookies) as login,
            patch.object(gs, "login_with_cookies") as verify,
        ):
            response = client.post("/api/gradescope/credentials/bu-sso", json={
                "user_id": "u1", "bu_username": "student", "bu_password": "private-password",
            })
        assert response.status_code == 200
        login.assert_called_once_with("student", "private-password", 120)
        verify.assert_called_once_with("remember-cookie", "session-cookie")
        payload = saved.upsert.call_args.args[0]
        assert payload["auth_mode"] == "cookies"
        assert payload["password_encrypted"] is None and payload["email_encrypted"] is None
        assert "private-password" not in str(payload)
        assert json.loads(decrypt(payload["cookies_encrypted"])) == cookies

    def test_unusable_sso_cookie_is_never_saved(self):
        saved = MagicMock()
        with (
            patch("routes.gradescope.table", return_value=saved),
            patch.object(gs, "login_via_bu_sso", return_value={"_gradescope_session": "invalid"}),
            patch.object(gs, "login_with_cookies", side_effect=gs.GradescopeAuthError("Session expired")),
        ):
            response = client.post("/api/gradescope/credentials/bu-sso", json={
                "user_id": "u1", "bu_username": "student", "bu_password": "private-password",
            })
        assert response.status_code == 401
        saved.upsert.assert_not_called()

    def test_unexpected_sso_exception_does_not_expose_internals(self):
        with patch.object(gs, "login_via_bu_sso", side_effect=RuntimeError("private diagnostic")):
            response = client.post("/api/gradescope/credentials/bu-sso", json={
                "user_id": "u1", "bu_username": "student", "bu_password": "private-password",
            })
        assert response.status_code == 500
        assert "private diagnostic" not in response.text


def test_bu_browser_flow_harvests_only_gradescope_cookies_and_closes_browser():
    browser = MagicMock()
    context = browser.new_context.return_value
    page = context.new_page.return_value
    page.url = "https://shib.bu.edu/idp/profile/SAML2/Redirect/SSO"
    context.cookies.return_value = [
        {"name": "_gradescope_session", "value": "session", "domain": ".gradescope.com"},
        {"name": "signed_token", "value": "token", "domain": "www.gradescope.com"},
        {"name": "unrelated", "value": "ignore", "domain": "shib.bu.edu"},
        {"name": "_gradescope_session", "value": "wrong", "domain": "gradescope.com.evil.example"},
    ]
    playwright = MagicMock()
    playwright.return_value.__enter__.return_value.chromium.launch.return_value = browser

    def first_visible(_page, selectors, _timeout):
        field = MagicMock()
        if selectors is gs._SHIB_SUBMIT_SELECTORS:
            field.click.side_effect = lambda: setattr(page, "url", "https://www.gradescope.com/account")
        return field

    with (
        patch.object(gs, "PLAYWRIGHT_AVAILABLE", True),
        # create=True keeps these hermetic in an env without the optional
        # playwright wheel (the module then never binds these names).
        patch.object(gs, "sync_playwright", playwright, create=True),
        patch.object(gs, "PlaywrightTimeoutError", TimeoutError, create=True),
        patch.object(gs, "_first_visible", side_effect=first_visible),
    ):
        result = gs.login_via_bu_sso("student", "private-password")
    assert result == {"_gradescope_session": "session", "signed_token": "token"}
    browser.close.assert_called_once()


@pytest.mark.parametrize("url", [
    "https://shib.bu.edu.evil.example/login",
    "https://evil.example/shib.bu.edu/login",
    "http://shib.bu.edu/login",
])
def test_bu_browser_never_fills_credentials_on_an_untrusted_redirect(url):
    browser = MagicMock()
    page = browser.new_context.return_value.new_page.return_value
    page.url = url
    playwright = MagicMock()
    playwright.return_value.__enter__.return_value.chromium.launch.return_value = browser
    with (
        patch.object(gs, "PLAYWRIGHT_AVAILABLE", True),
        # create=True keeps these hermetic in an env without the optional
        # playwright wheel (the module then never binds these names).
        patch.object(gs, "sync_playwright", playwright, create=True),
        patch.object(gs, "PlaywrightTimeoutError", TimeoutError, create=True),
        patch.object(gs, "_first_visible", return_value=MagicMock()) as find,
    ):
        with pytest.raises(gs.GradescopeAuthError, match="secure WebLogin"):
            gs.login_via_bu_sso("student", "private-password")
    assert find.call_count == 2  # school button and picker only, never credential fields
    browser.close.assert_called_once()
