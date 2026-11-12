"""
Unit tests for routes/onboarding.py

Tests the POST /api/onboarding/profile and GET /api/onboarding/courses
endpoints with DB mocked.
"""
import json
import re

import httpx
import pytest
from unittest.mock import MagicMock, patch
from fastapi.testclient import TestClient

from main import app
from services.legal import PRIVACY_VERSION, TERMS_VERSION

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
    "accepted_terms_version": TERMS_VERSION,
    "accepted_privacy_version": PRIVACY_VERSION,
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

    def test_every_token_must_match_the_code_or_the_name(self):
        """Students type codes without the school prefix ("FE 223" for
        "QST FE 223"), without spaces ("FE223"), and names out of order
        ("corporate finance intro"). One substring over the whole query missed
        all of those, so each letter/digit run is its own AND-ed clause."""
        clause = self._filters_for("FE223")["and"]

        assert clause == (
            '(or(course_name.ilike."%fe%",course_code.ilike."%fe%"),'
            'or(course_name.ilike."%223%",course_code.ilike."%223%"))'
        )

    def test_punctuation_never_reaches_the_logic_tree(self):
        """#592 review C11: a comma or paren in a bare value split the
        PostgREST `or=(…)` tree, and `_`/`%` became live LIKE wildcards.
        Tokens are letter/digit runs only, so none of those survive."""
        clause = self._filters_for('Ethics, Law (CS_1) 100% "hi"')["and"]

        needles = re.findall(r'ilike\."%([^"]*)%"', clause)
        assert needles == [n for t in ["ethics", "law", "cs", "1", "100", "hi"] for n in (t, t)]
        assert clause.count("or(") == 6

    def test_stopwords_are_dropped_unless_they_are_the_whole_query(self):
        assert '"%and%"' not in self._filters_for("Law and Society")["and"]
        assert '"%the%"' in self._filters_for("the")["and"]

    def test_a_punctuation_only_query_returns_nothing_without_a_query(self):
        mock = MagicMock()
        with patch("routes.onboarding.table", return_value=mock):
            res = client.get("/api/onboarding/courses", params={"q": "%%"})
        assert res.status_code == 200
        assert res.json() == {"courses": []}
        mock.select.assert_not_called()

    def _ranked(self, q: str, rows: list[dict]) -> list[str]:
        mock = MagicMock()
        mock.select.return_value = rows
        with patch("routes.onboarding.table", return_value=mock):
            res = client.get("/api/onboarding/courses", params={"q": q})
        assert res.status_code == 200
        return [c["course_code"] for c in res.json()["courses"]]

    @pytest.mark.parametrize("q", ["fe 223", "FE223", "fe-223", "qst fe 223", "QST FE223"])
    def test_the_typed_code_ranks_first_with_or_without_the_school(self, q):
        # Name-ordered, as the DB returns them: the exact code is not first.
        rows = [
            {"id": "1", "course_code": "QST BA 223", "course_name": "Business Life Analytics"},
            {"id": "2", "course_code": "QST FE 223", "course_name": "Introduction to Corporate Finance"},
        ]
        assert self._ranked(q, rows)[0] == "QST FE 223"

    def test_a_title_match_ranks_above_a_scattered_one(self):
        rows = [
            {"id": "1", "course_code": "LAW JD 985", "course_name": "Finance Law: Corporate Deals"},
            {"id": "2", "course_code": "QST FE 223", "course_name": "Introduction to Corporate Finance"},
        ]
        assert self._ranked("intro to corporate finance", rows)[0] == "QST FE 223"

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


# ── POST /api/onboarding/profile ─────────────────────────────────────────────

TERM = {
    "id": "fall-2026", "label": "Fall 2026",
    "start_date": "2026-09-01", "end_date": "2026-12-20", "sort_key": 20263,
}
WRITES = ("insert", "upsert", "update", "delete")


def _pg_error(status: int, code: str) -> httpx.HTTPStatusError:
    """A PostgREST error the way db/connection.py raises it."""
    request = httpx.Request("POST", "https://example.supabase.co/rest/v1/x")
    response = httpx.Response(status, json={"code": code, "message": "boom"}, request=request)
    return httpx.HTTPStatusError(f"{status}", request=request, response=response)


def _unquote(v: str) -> str:
    return v[1:-1] if len(v) >= 2 and v[0] == v[-1] == '"' else v


def _match(row: dict, col: str, cond: str) -> bool:
    op, _, val = cond.partition(".")
    cur = row.get(col)
    if op == "eq":
        return cur is not None and str(cur) == val
    if op == "is":
        return cur is None if val == "null" else str(cur).lower() == val
    if op == "in":
        return str(cur) in {_unquote(v) for v in val[1:-1].split(",")}
    raise AssertionError(f"filter op {op!r} not modelled")


class FakeDB:
    """Just enough PostgREST for the onboarding route: rows per table, the
    filters it sends, and an ordered log of every write ("table.op").

    ``enrollments`` enforces UNIQUE (user_id, offering_id) the way PostgREST
    reports it (409, SQLSTATE 23505). ``fail[table.op]`` raises instead of
    writing, to drive a failure part-way."""

    def __init__(self, *, onboarded=False, courses=("cid-cs111", "cid-ma225")):
        self.rows: dict[str, list[dict]] = {
            "users": [{"id": "user_123", "onboarding_completed": onboarded}],
            "courses": [{"id": c} for c in courses],
            "course_offerings": [],
            "enrollments": [],
        }
        self.log: list[str] = []
        self.calls: list[tuple[str, str, object, dict]] = []
        self.fail: dict[str, Exception] = {}

    def of(self, name, **match):
        return [r for r in self.rows.get(name, []) if all(r.get(k) == v for k, v in match.items())]

    def writes(self):
        return [entry for entry in self.log if entry.split(".")[1] in WRITES]

    def table(self, name):
        db = self

        def hits(filters):
            return [r for r in db.rows.get(name, [])
                    if all(_match(r, k, v) for k, v in (filters or {}).items())]

        def record(op, data=None, **kw):
            db.log.append(f"{name}.{op}")
            db.calls.append((name, op, data, kw))
            if f"{name}.{op}" in db.fail:
                raise db.fail[f"{name}.{op}"]

        class _T:
            def select(self, columns="*", filters=None, order=None, limit=None, **_):
                record("select", filters=filters)
                out = [dict(r) for r in hits(filters)]
                return out[:limit] if limit else out

            def insert(self, data):
                record("insert", data)
                if name == "enrollments" and db.of(
                    "enrollments", user_id=data["user_id"], offering_id=data["offering_id"],
                ):
                    raise _pg_error(409, "23505")
                db.rows.setdefault(name, []).append(dict(data))
                return [dict(data)]

            def upsert(self, data, on_conflict="id", *, ignore_duplicates=False, columns=None):
                record("upsert", data, on_conflict=on_conflict, ignore_duplicates=ignore_duplicates)
                keys = on_conflict.split(",")
                out = []
                for row in data if isinstance(data, list) else [data]:
                    existing = db.of(name, **{k: row[k] for k in keys})
                    if existing:
                        if not ignore_duplicates:
                            existing[0].update(row)
                            out.append(dict(existing[0]))
                        continue
                    db.rows.setdefault(name, []).append(dict(row))
                    out.append(dict(row))
                return out

            def update(self, data, filters, **_):
                record("update", data, filters=filters)
                rows = hits(filters)
                for r in rows:
                    r.update(data)
                return [dict(r) for r in rows]

        return _T()


@pytest.fixture
def db():
    """The fake DB behind every module the route reaches, the onboarding term
    pinned (academics.onboarding_term has its own tests), and the post-response
    chunk-visibility resync replaced by a spy."""
    fake = FakeDB()
    resync = MagicMock(name="resync_user_chunk_visibility")
    fake.resync = resync
    with patch("routes.onboarding.table", side_effect=fake.table), \
         patch("services.academics.table", side_effect=fake.table), \
         patch("services.legal.table", side_effect=fake.table), \
         patch("routes.onboarding.onboarding_term", return_value=TERM) as term, \
         patch("routes.onboarding.resync_user_chunk_visibility", resync):
        fake.onboarding_term = term
        yield fake


def _post(payload=None, **changes):
    body = {**VALID_PAYLOAD, **(payload or {}), **changes}
    return client.post("/api/onboarding/profile", json=body)


class TestSaveOnboardingProfile:
    def test_success_writes_profile_enrollments_acceptances_then_the_flag(self, db):
        res = _post()

        assert res.status_code == 200, res.text
        assert res.json() == {"ok": True, "user_id": "user_123", "courses_linked": 2}

        from services.encryption import decrypt
        [profile] = db.rows["user_profiles"]
        assert profile["user_id"] == "user_123"
        assert decrypt(profile["first_name"]) == "Jose"
        assert decrypt(profile["last_name"]) == "Cruz"
        assert decrypt(profile["name"]) == "Jose Cruz"
        assert profile["year"] == "junior"
        assert profile["majors"] == ["Computer Science"]
        assert profile["minors"] == ["Mathematics"]
        assert profile["learning_style"] == "visual"

        # One enrollment per course, keyed on an offering of the onboarding
        # term (created on demand), never on the abstract course id.
        offerings = {o["id"]: o for o in db.rows["course_offerings"]}
        enrollments = db.rows["enrollments"]
        assert len(enrollments) == 2
        for e in enrollments:
            assert e["user_id"] == "user_123"
            assert "course_id" not in e
            assert offerings[e["offering_id"]]["term_id"] == TERM["id"]
        assert {offerings[e["offering_id"]]["course_id"] for e in enrollments} == {
            "cid-cs111", "cid-ma225",
        }
        assert "user_courses" not in db.rows  # the legacy table is not touched

        acceptances = {(a["document"], a["version"]) for a in db.rows["legal_acceptances"]}
        assert acceptances == {("terms", TERMS_VERSION), ("privacy", PRIVACY_VERSION)}
        assert all(a["user_id"] == "user_123" for a in db.rows["legal_acceptances"])

        assert db.rows["users"][0]["onboarding_completed"] is True
        # An adult's settings are left alone.
        assert "user_settings" not in db.rows
        db.resync.assert_not_called()

    def test_the_contract_write_order(self, db):
        res = _post(under_18=True)
        assert res.status_code == 200, res.text
        writes = db.writes()
        assert writes[-1] == "users.update"
        assert writes.index("user_profiles.upsert") < writes.index("enrollments.insert")
        assert writes.index("enrollments.insert") < writes.index("user_settings.upsert")
        assert writes.index("user_settings.upsert") < writes.index("legal_acceptances.upsert")
        flag = [c for c in db.calls if c[:2] == ("users", "update")][-1]
        assert flag[2] == {"onboarding_completed": True}
        assert flag[3]["filters"] == {"id": "eq.user_123", "onboarding_completed": "is.false"}

    def test_names_are_trimmed(self, db):
        res = _post(first_name="  Ada ", last_name=" Lovelace  ")
        assert res.status_code == 200, res.text
        from services.encryption import decrypt
        [profile] = db.rows["user_profiles"]
        assert decrypt(profile["first_name"]) == "Ada"
        assert decrypt(profile["last_name"]) == "Lovelace"
        assert decrypt(profile["name"]) == "Ada Lovelace"

    def test_an_empty_last_name_is_allowed(self, db):
        res = _post(last_name="")
        assert res.status_code == 200, res.text
        from services.encryption import decrypt
        assert decrypt(db.rows["user_profiles"][0]["name"]) == "Jose"

    def test_courses_are_resolved_in_one_quoted_read(self, db):
        """The ids are the client's: one `in.(…)` read with each id quoted, so
        a comma or paren in an id can't split the PostgREST list."""
        res = _post(course_ids=["cid-cs111", 'odd,"id)'])
        assert res.status_code == 200, res.text
        reads = [c[3]["filters"] for c in db.calls if c[:2] == ("courses", "select")]
        assert reads == [{"id": 'in.("cid-cs111","odd,\\"id)")'}]
        assert res.json()["courses_linked"] == 1

    def test_empty_course_ids_completes_with_no_enrollments(self, db):
        """ "My courses aren't listed — I'll add them later." """
        res = _post(course_ids=[])
        assert res.status_code == 200, res.text
        assert res.json()["courses_linked"] == 0
        assert db.rows["enrollments"] == []
        assert db.rows["users"][0]["onboarding_completed"] is True
        db.onboarding_term.assert_not_called()

    def test_course_ids_may_be_omitted(self, db):
        payload = {**VALID_PAYLOAD}
        del payload["course_ids"]
        res = client.post("/api/onboarding/profile", json=payload)
        assert res.status_code == 200, res.text
        assert res.json()["courses_linked"] == 0

    def test_unknown_courses_are_skipped_when_one_is_known(self, db):
        res = _post(course_ids=["nope-1", "cid-cs111", "nope-2"])
        assert res.status_code == 200, res.text
        assert res.json()["courses_linked"] == 1
        assert len(db.rows["enrollments"]) == 1

    def test_no_known_courses_is_a_422_and_writes_nothing(self, db):
        res = _post(course_ids=["nope-1", "nope-2"])
        assert res.status_code == 422
        detail = res.json()["detail"]
        assert detail["code"] == "no_known_courses"
        assert detail["message"]
        assert db.writes() == []
        assert db.rows["users"][0]["onboarding_completed"] is False

    @pytest.mark.parametrize("field,value", [
        ("accepted_terms_version", "2026-01-01"),
        ("accepted_privacy_version", "2026-01-01"),
        ("accepted_terms_version", ""),
    ])
    def test_an_outdated_legal_version_is_a_422_and_writes_nothing(self, db, field, value):
        res = _post(**{field: value})
        assert res.status_code == 422
        detail = res.json()["detail"]
        assert detail["code"] == "legal_outdated"
        assert detail["message"]
        assert db.writes() == []
        assert db.rows["users"][0]["onboarding_completed"] is False

    def test_no_term_seeded_is_a_503_and_writes_nothing(self, db):
        db.onboarding_term.return_value = None
        res = _post()
        assert res.status_code == 503
        assert db.writes() == []

    def test_under_18_starts_private_before_completion(self, db):
        res = _post(under_18=True)
        assert res.status_code == 200, res.text
        [settings] = db.rows["user_settings"]
        assert settings["user_id"] == "user_123"
        assert settings["profile_visibility"] == "private"
        assert settings["share_class_context"] is False
        assert settings["updated_at"]
        upsert = [c for c in db.calls if c[:2] == ("user_settings", "upsert")][-1]
        assert upsert[3]["on_conflict"] == "user_id"
        # As the settings PATCH does when sharing goes off (#629).
        db.resync.assert_called_once_with("user_123")

    def test_under_18_overrides_existing_settings(self, db):
        db.rows["user_settings"] = [{
            "user_id": "user_123", "profile_visibility": "public",
            "share_class_context": True, "theme": "dark",
        }]
        res = _post(under_18=True)
        assert res.status_code == 200, res.text
        [settings] = db.rows["user_settings"]
        assert settings["profile_visibility"] == "private"
        assert settings["share_class_context"] is False
        assert settings["theme"] == "dark"

    def test_a_course_already_held_in_any_term_is_linked_not_re_enrolled(self, db):
        db.rows["course_offerings"].append(
            {"id": "off-old", "course_id": "cid-cs111", "term_id": "spring-2026"})
        db.rows["enrollments"].append(
            {"id": "enr-old", "user_id": "user_123", "offering_id": "off-old"})
        res = _post()
        assert res.status_code == 200, res.text
        assert res.json()["courses_linked"] == 2
        assert [e["id"] for e in db.rows["enrollments"]][0] == "enr-old"
        assert len(db.rows["enrollments"]) == 2  # only cid-ma225 was added

    def test_a_concurrent_duplicate_enrollment_reads_as_enrolled(self, db):
        """Two submits race past the "already held?" read; the loser's insert
        hits UNIQUE (user_id, offering_id). That student IS enrolled: 200."""
        db.rows["course_offerings"] = [
            {"id": "off-cs", "course_id": "cid-cs111", "term_id": TERM["id"]},
            {"id": "off-ma", "course_id": "cid-ma225", "term_id": TERM["id"]},
        ]
        with patch("routes.onboarding.user_enrolled_course_ids", return_value=set()):
            db.rows["enrollments"].append(
                {"id": "enr-winner", "user_id": "user_123", "offering_id": "off-cs"})
            res = _post()
        assert res.status_code == 200, res.text
        assert res.json()["courses_linked"] == 2
        assert sorted(e["offering_id"] for e in db.rows["enrollments"]) == ["off-cs", "off-ma"]
        assert db.rows["users"][0]["onboarding_completed"] is True

    def test_a_retry_after_a_failure_completes_without_duplicates(self, db):
        db.fail["legal_acceptances.upsert"] = RuntimeError("postgrest down")
        local = TestClient(app, raise_server_exceptions=False)
        assert local.post("/api/onboarding/profile", json=VALID_PAYLOAD).status_code == 500
        assert db.rows["users"][0]["onboarding_completed"] is False

        del db.fail["legal_acceptances.upsert"]
        res = _post()
        assert res.status_code == 200, res.text
        assert len(db.rows["enrollments"]) == 2
        assert len(db.rows["user_profiles"]) == 1
        assert len(db.rows["legal_acceptances"]) == 2
        assert db.rows["users"][0]["onboarding_completed"] is True

    def test_acceptances_are_inserted_once(self, db):
        res = _post()
        assert res.status_code == 200, res.text
        upsert = [c for c in db.calls if c[:2] == ("legal_acceptances", "upsert")][-1]
        assert upsert[3] == {"on_conflict": "user_id,document,version", "ignore_duplicates": True}

    def test_user_not_found_returns_404(self, db):
        db.rows["users"] = []
        res = _post()
        assert res.status_code == 404
        assert res.json()["detail"] == "User not found"
        assert db.writes() == []


class TestOnboardingBodyValidation:
    """422s from the request model (contract: names, year, courses, versions)."""

    def _status(self, **changes):
        payload = {**VALID_PAYLOAD, **changes}
        for k in [k for k, v in changes.items() if v is _DROP]:
            del payload[k]
        with patch("routes.onboarding.table") as t:
            res = client.post("/api/onboarding/profile", json=payload)
        return res, t

    @pytest.mark.parametrize("changes", [
        {"last_name": None},
        {"first_name": ""},
        {"first_name": "   "},
        {"first_name": "x" * 81},
        {"last_name": "x" * 81},
        {"year": "Junior"},
        {"year": "phd"},
        {"year": ""},
        {"course_ids": ["cid-1", "cid-1"]},
        {"course_ids": [f"cid-{i}" for i in range(21)]},
        {"course_ids": [""]},
        {"course_ids": ["x" * 129]},
        {"under_18": "maybe"},
    ])
    def test_malformed_input_is_a_422(self, changes):
        changes = {k: (_DROP if v is None else v) for k, v in changes.items()}
        res, t = self._status(**changes)
        assert res.status_code == 422, res.text
        t.assert_not_called()

    @pytest.mark.parametrize("field", ["accepted_terms_version", "accepted_privacy_version"])
    def test_the_accepted_versions_are_required(self, field):
        res, _ = self._status(**{field: _DROP})
        assert res.status_code == 422

    @pytest.mark.parametrize("year", ["freshman", "sophomore", "junior", "senior", "graduate", "other"])
    def test_every_onboarding_year_is_accepted(self, year):
        from models import OnboardingBody
        assert OnboardingBody(**{**VALID_PAYLOAD, "year": year}).year == year

    def test_the_bounds_themselves_are_accepted(self):
        from models import OnboardingBody
        body = OnboardingBody(**{
            **VALID_PAYLOAD,
            "first_name": "x" * 80, "last_name": "y" * 80,
            "course_ids": [f"c{i:03d}" + "z" * 124 for i in range(20)],
        })
        assert len(body.course_ids) == 20
        assert body.under_18 is False

    def test_a_422_here_never_carries_the_quiz_message(self):
        """The quiz's friendly 422 sentence is for /api/quiz/* only."""
        res, _ = self._status(year="phd")
        assert res.status_code == 422
        body = res.json()
        assert "error" not in body
        assert isinstance(body["detail"], list)
        assert "quiz" not in json.dumps(body).lower()


_DROP = object()


class TestOnboardingIsAOneWayGate:
    """#757: `onboarding_completed` is written last, and a replay is a 409."""

    def test_a_failure_part_way_leaves_the_account_not_onboarded(self, db):
        db.fail["enrollments.insert"] = RuntimeError("postgrest down")
        local = TestClient(app, raise_server_exceptions=False)
        res = local.post("/api/onboarding/profile", json=VALID_PAYLOAD)
        assert res.status_code == 500
        assert "users.update" not in db.log
        assert "legal_acceptances.upsert" not in db.log

    def test_an_enrollment_conflict_that_is_not_a_duplicate_still_fails(self, db):
        """Only a 23505 means "already enrolled"; a foreign-key 409 (an
        offering deleted under us) is a real failure."""
        db.fail["enrollments.insert"] = _pg_error(409, "23503")
        local = TestClient(app, raise_server_exceptions=False)
        res = local.post("/api/onboarding/profile", json=VALID_PAYLOAD)
        assert res.status_code == 500
        assert "users.update" not in db.log

    def test_a_failure_recording_the_acceptances_leaves_it_not_onboarded(self, db):
        db.fail["legal_acceptances.upsert"] = RuntimeError("postgrest down")
        local = TestClient(app, raise_server_exceptions=False)
        res = local.post("/api/onboarding/profile", json=VALID_PAYLOAD)
        assert res.status_code == 500
        assert "users.update" not in db.log

    def test_a_replay_by_an_onboarded_user_is_a_409_and_writes_nothing(self, db):
        db.rows["users"][0]["onboarding_completed"] = True
        res = _post()
        assert res.status_code == 409
        assert res.json()["detail"] == "Onboarding is already complete."
        assert db.writes() == []

    def test_the_409_comes_before_the_legal_check(self, db):
        """A stale tab of an onboarded student gets "already complete", not a
        request to re-accept documents it will never submit."""
        db.rows["users"][0]["onboarding_completed"] = True
        res = _post(accepted_terms_version="2020-01-01")
        assert res.status_code == 409
