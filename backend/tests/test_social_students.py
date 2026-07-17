"""
Tests for GET /api/social/students (routes/social.py::get_students) and the
school-scoping helper that backs it (services/academics.py::school_peer_user_ids).

#342 turned this endpoint from "return a profile for every user in the DB" into
a school-scoped, visibility-respecting directory with a mastery-free payload.
These tests pin all three:

  - scope:      only users sharing the viewer's school are returned;
  - visibility: users with profile_visibility == 'private' are dropped;
  - payload:    rows carry name/streak/courses only — no mastery data.

The route mocks are deliberately filter-aware: the `users`/`enrollments` mocks
return only rows matching the `in.(...)` filter the route builds, so a route
that forgot to scope its reads would fail these tests rather than pass on a mock
that ignores filters.
"""
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

import routes.social as social
from main import app
from services import academics

client = TestClient(app)


# ── helpers ───────────────────────────────────────────────────────────────────


def _parse_in(filters: dict | None, col: str) -> set[str]:
    """Parse a PostgREST ``{col: 'in.(a,b,c)'}`` filter into a set of ids."""
    if not filters or col not in filters:
        return set()
    raw = filters[col]
    assert raw.startswith("in.("), f"expected an in.() filter, got {raw!r}"
    inner = raw[len("in.(") : -1]
    return set(p for p in inner.split(",") if p)


def _route_tables(settings_rows, all_users, all_enrollments):
    """Factory + captured per-table mocks for the route's `table()` calls.

    `users` and `enrollments` are filter-aware — they return only rows whose id
    matches the route's `in.(...)` filter, so the scoping the route applies is
    reflected in the output (and any missing filter would raise in _parse_in).
    """
    mocks: dict = {}

    def factory(name):
        if name in mocks:
            return mocks[name]
        m = MagicMock(name=f"table:{name}")
        if name == "user_settings":
            m.select.return_value = settings_rows
        elif name == "users":
            def _users_select(cols=None, filters=None, **kw):
                ids = _parse_in(filters, "id")
                return [u for u in all_users if u["id"] in ids]
            m.select.side_effect = _users_select
        elif name == "enrollments":
            def _enr_select(cols=None, filters=None, **kw):
                ids = _parse_in(filters, "user_id")
                return [e for e in all_enrollments if e["user_id"] in ids]
            m.select.side_effect = _enr_select
        else:
            m.select.return_value = []
        mocks[name] = m
        return m

    return factory, mocks


def _enrollment(user_id: str, course_name: str) -> dict:
    """An enrollments row with the PostgREST embedded course-offering → course join."""
    return {
        "user_id": user_id,
        "course_offerings": {"courses": {"course_name": course_name}},
    }


# ── route: scope ────────────────────────────────────────────────────────────


class TestSchoolScope:
    def test_only_school_peers_are_returned(self):
        peers = {"user_andres", "user_maya", "user_sam"}
        all_users = [
            {"id": "user_andres", "streak_count": 3},
            {"id": "user_maya", "streak_count": 9},
            {"id": "user_sam", "streak_count": 5},
            # A user outside the viewer's school — must NOT appear even though the
            # `users` table physically contains them.
            {"id": "user_outsider", "streak_count": 99},
        ]
        factory, mocks = _route_tables(
            settings_rows=[],
            all_users=all_users,
            all_enrollments=[
                _enrollment("user_maya", "Calculus II"),
                _enrollment("user_sam", "Algorithms"),
            ],
        )
        with patch.object(social.academics, "school_peer_user_ids", return_value=peers), \
             patch.object(social, "table", factory), \
             patch.object(social, "get_display_names", return_value={
                 "user_andres": "Andres", "user_maya": "Maya", "user_sam": "Sam",
             }):
            r = client.get("/api/social/students")

        assert r.status_code == 200
        ids = {s["user_id"] for s in r.json()["students"]}
        assert ids == peers
        assert "user_outsider" not in ids
        # The users read was scoped to exactly the school peers.
        assert _parse_in(mocks["users"].select.call_args.kwargs["filters"], "id") == peers

    def test_empty_scope_returns_empty_and_reads_nothing_else(self):
        factory, _ = _route_tables([], [], [])
        tbl = MagicMock(side_effect=factory)  # wrap so we can assert it isn't called
        with patch.object(social.academics, "school_peer_user_ids", return_value=set()), \
             patch.object(social, "table", tbl), \
             patch.object(social, "get_display_names") as names:
            r = client.get("/api/social/students")

        assert r.status_code == 200
        assert r.json() == {"students": []}
        # Fail closed: no user_settings/users/enrollments reads, no name decrypt.
        tbl.assert_not_called()
        names.assert_not_called()


# ── route: visibility ──────────────────────────────────────────────────────


class TestProfileVisibility:
    def test_private_users_are_excluded(self):
        peers = {"user_andres", "user_maya", "user_priya"}
        all_users = [
            {"id": "user_andres", "streak_count": 3},
            {"id": "user_maya", "streak_count": 9},
            {"id": "user_priya", "streak_count": 14},
        ]
        factory, mocks = _route_tables(
            settings_rows=[{"user_id": "user_priya", "profile_visibility": "private"}],
            all_users=all_users,
            all_enrollments=[],
        )
        with patch.object(social.academics, "school_peer_user_ids", return_value=peers), \
             patch.object(social, "table", factory), \
             patch.object(social, "get_display_names", return_value={
                 "user_andres": "Andres", "user_maya": "Maya", "user_priya": "Priya",
             }):
            r = client.get("/api/social/students")

        ids = {s["user_id"] for s in r.json()["students"]}
        assert ids == {"user_andres", "user_maya"}
        assert "user_priya" not in ids
        # The users read excluded the private user up front.
        assert "user_priya" not in _parse_in(
            mocks["users"].select.call_args.kwargs["filters"], "id"
        )

    def test_public_and_school_tiers_are_both_listed(self):
        peers = {"user_pub", "user_sch"}
        factory, _ = _route_tables(
            settings_rows=[
                {"user_id": "user_pub", "profile_visibility": "public"},
                {"user_id": "user_sch", "profile_visibility": "school"},
            ],
            all_users=[
                {"id": "user_pub", "streak_count": 1},
                {"id": "user_sch", "streak_count": 2},
            ],
            all_enrollments=[],
        )
        with patch.object(social.academics, "school_peer_user_ids", return_value=peers), \
             patch.object(social, "table", factory), \
             patch.object(social, "get_display_names", return_value={
                 "user_pub": "Pub", "user_sch": "Sch",
             }):
            r = client.get("/api/social/students")

        assert {s["user_id"] for s in r.json()["students"]} == peers

    def test_missing_settings_row_defaults_to_listed(self):
        # A peer with no user_settings row keeps the column default ('public').
        peers = {"user_nosettings"}
        factory, _ = _route_tables(
            settings_rows=[],
            all_users=[{"id": "user_nosettings", "streak_count": 0}],
            all_enrollments=[],
        )
        with patch.object(social.academics, "school_peer_user_ids", return_value=peers), \
             patch.object(social, "table", factory), \
             patch.object(social, "get_display_names", return_value={"user_nosettings": "Nemo"}):
            r = client.get("/api/social/students")

        assert {s["user_id"] for s in r.json()["students"]} == peers

    def test_all_peers_private_returns_empty(self):
        peers = {"user_a", "user_b"}
        factory, _ = _route_tables(
            settings_rows=[
                {"user_id": "user_a", "profile_visibility": "private"},
                {"user_id": "user_b", "profile_visibility": "private"},
            ],
            all_users=[{"id": "user_a", "streak_count": 0}, {"id": "user_b", "streak_count": 0}],
            all_enrollments=[],
        )
        with patch.object(social.academics, "school_peer_user_ids", return_value=peers), \
             patch.object(social, "table", factory), \
             patch.object(social, "get_display_names") as names:
            r = client.get("/api/social/students")

        assert r.json() == {"students": []}
        names.assert_not_called()


# ── route: payload ─────────────────────────────────────────────────────────


class TestPayloadShape:
    def test_no_mastery_fields_and_courses_deduped(self):
        peers = {"user_maya"}
        factory, _ = _route_tables(
            settings_rows=[],
            all_users=[{"id": "user_maya", "streak_count": 9}],
            # Same abstract course via two offerings → one deduped entry.
            all_enrollments=[
                _enrollment("user_maya", "Calculus II"),
                _enrollment("user_maya", "Calculus II"),
                _enrollment("user_maya", "Linear Algebra"),
            ],
        )
        with patch.object(social.academics, "school_peer_user_ids", return_value=peers), \
             patch.object(social, "table", factory), \
             patch.object(social, "get_display_names", return_value={"user_maya": "Maya"}):
            r = client.get("/api/social/students")

        row = r.json()["students"][0]
        assert set(row.keys()) == {"user_id", "name", "streak", "courses"}
        assert "stats" not in row and "top_concepts" not in row
        assert row["courses"] == ["Calculus II", "Linear Algebra"]
        assert row["streak"] == 9
        assert row["name"] == "Maya"

    def test_never_reads_graph_nodes(self):
        # Mastery is gone entirely — the route must not touch graph_nodes.
        peers = {"user_maya"}
        factory, mocks = _route_tables(
            settings_rows=[], all_users=[{"id": "user_maya", "streak_count": 0}], all_enrollments=[]
        )
        with patch.object(social.academics, "school_peer_user_ids", return_value=peers), \
             patch.object(social, "table", factory), \
             patch.object(social, "get_display_names", return_value={"user_maya": "Maya"}):
            client.get("/api/social/students")
        assert "graph_nodes" not in mocks


# ── helper: academics.school_peer_user_ids ─────────────────────────────────


def _chain_tables(responses: dict):
    """`table()` factory whose select() dispatches on (table_name, filter_col).

    Distinguishes the two reads that hit the same table with different filters
    (course_offerings by id vs by course_id; enrollments by user_id vs by
    offering_id).
    """
    def factory(name):
        m = MagicMock(name=f"table:{name}")
        def _select(cols=None, filters=None, **kw):
            fcol = next(iter(filters.keys())) if filters else None
            return responses.get((name, fcol), [])
        m.select.side_effect = _select
        return m
    return factory


class TestSchoolPeerUserIds:
    def test_traverses_enrollment_chain_to_school_peers(self):
        responses = {
            ("enrollments", "user_id"): [{"id": "e1", "offering_id": "off1"}],   # viewer's enrollments
            ("course_offerings", "id"): [{"course_id": "c1"}],                    # off1 → course c1
            ("courses", "id"): [{"school_id": "s1"}],                             # c1 → school s1
            ("courses", "school_id"): [{"id": "c1"}, {"id": "c2"}],               # all courses at s1
            ("course_offerings", "course_id"): [{"id": "off1"}, {"id": "off2"}],  # their offerings
            ("enrollments", "offering_id"): [                                     # everyone enrolled
                {"user_id": "user_v"}, {"user_id": "user_peer"}, {"user_id": "user_peer"},
            ],
        }
        with patch.object(academics, "table", _chain_tables(responses)):
            assert academics.school_peer_user_ids("user_v") == {"user_v", "user_peer"}

    def test_no_enrollments_returns_empty(self):
        with patch.object(academics, "table", _chain_tables({("enrollments", "user_id"): []})):
            assert academics.school_peer_user_ids("user_v") == set()

    def test_course_without_school_fails_closed(self):
        responses = {
            ("enrollments", "user_id"): [{"id": "e1", "offering_id": "off1"}],
            ("course_offerings", "id"): [{"course_id": "c1"}],
            ("courses", "id"): [{"school_id": None}],  # no school → empty scope
        }
        with patch.object(academics, "table", _chain_tables(responses)):
            assert academics.school_peer_user_ids("user_v") == set()

    def test_empty_user_id_returns_empty(self):
        with patch.object(academics, "table", _chain_tables({})):
            assert academics.school_peer_user_ids("") == set()
