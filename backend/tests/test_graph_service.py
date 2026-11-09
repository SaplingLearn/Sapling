"""
Unit tests for services/graph_service.py

All Supabase calls are mocked so no live DB connection is needed.
"""
from datetime import datetime, timedelta, timezone

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

import services.graph_service as gs
from services.graph_service import (
    get_graph,
    get_courses,
    add_course,
    delete_course,
    apply_graph_update,
    get_recommendations,
    ensure_user_exists,
)


# #117: a sync PostgREST call reached on the event loop raises here.
pytestmark = pytest.mark.usefixtures("no_sync_db_on_loop")


# ── helpers ───────────────────────────────────────────────────────────────────

def _mock_table(data: dict):
    """
    Return a factory function that, given a table name, returns a MagicMock
    whose .select() returns the matching list from `data`.
    """
    def _factory(name):
        mock = MagicMock()
        mock.select.return_value = data.get(name, [])
        mock.insert.return_value = []
        mock.update.return_value = []
        mock.delete.return_value = []
        mock.upsert.return_value = []
        return mock
    return _factory


def _simple_mock(select_returns=None):
    """Return a single MagicMock SupabaseTable for tests that only use one table."""
    mock = MagicMock()
    mock.select.return_value = select_returns if select_returns is not None else []
    mock.insert.return_value = []
    mock.update.return_value = []
    mock.delete.return_value = []
    return mock


def _cached_mock_table(data: dict):
    """Like `_mock_table` but caches one mock per table name so a test can assert
    on a specific table's `.insert`/`.delete`/`.update` calls (the factory is
    shared between `services.graph_service.table` and `services.academics.table`)."""
    mocks: dict = {}

    def factory(name):
        if name not in mocks:
            m = MagicMock()
            m.select.return_value = data.get(name, [])
            m.insert.return_value = []
            m.update.return_value = []
            m.delete.return_value = []
            m.upsert.return_value = []
            mocks[name] = m
        return mocks[name]
    return factory, mocks


def _enrollment_row(course_id: str, code: str = "", name: str = "Course",
                    term: str = "Spring 2026", offering_id: str | None = None):
    """A row in the enrollments→course_offerings→courses/terms join shape that
    graph_service._reshape_enrollment expects. `course_id` is the ABSTRACT id."""
    return {
        "id": f"e-{course_id}",
        "offering_id": offering_id or f"off-{course_id}",
        "color": None,
        "nickname": None,
        "enrolled_at": "2026-01-01",
        "course_offerings": {
            "course_id": course_id,
            "courses": {"course_code": code, "course_name": name, "department": ""},
            "terms": {"label": term},
        },
    }


# ── ensure_user_exists ────────────────────────────────────────────────────────

class TestEnsureUserExists:
    def test_insert_payload_omits_name_after_identity_split(self):
        """`name` moved to user_profiles (migration 0024); the users insert must
        not reference it or the real-DB write raises."""
        factory, mocks = _cached_mock_table({"users": []})  # no existing row
        with patch("services.graph_service.table", side_effect=factory):
            ensure_user_exists("u1")

        users = mocks["users"]
        users.insert.assert_called_once()
        payload = users.insert.call_args[0][0]
        assert "name" not in payload
        assert payload == {"id": "u1", "streak_count": 0}

    def test_does_not_create_profile_row(self):
        """A stub user has no display name yet; onboarding/oauth own user_profiles."""
        factory, mocks = _cached_mock_table({"users": []})
        with patch("services.graph_service.table", side_effect=factory):
            ensure_user_exists("u1")
        assert "user_profiles" not in mocks

    def test_skips_insert_when_user_exists(self):
        factory, mocks = _cached_mock_table({"users": [{"id": "u1"}]})
        with patch("services.graph_service.table", side_effect=factory):
            ensure_user_exists("u1")
        mocks["users"].insert.assert_not_called()


# ── get_graph ─────────────────────────────────────────────────────────────────

class TestGetGraph:
    def test_empty_graph_returns_zero_stats(self):
        today = datetime.now(timezone.utc).date().isoformat()
        factory = _mock_table({
            "users": [{"streak_count": 5, "last_active_date": today}],
            "graph_nodes": [],
            "graph_edges": [],
            "enrollments": [],
        })
        with patch("services.graph_service.table", side_effect=factory):
            result = get_graph("u1")

        assert result["stats"]["total_nodes"] == 0
        assert result["stats"]["streak"] == 5
        assert result["nodes"] == []
        assert result["edges"] == []

    def test_lapsed_streak_reads_zero(self):
        # #767: the stored count is only reset on next activity; a student last
        # active three days ago has no streak, whatever streak_count says.
        stale = (datetime.now(timezone.utc).date() - timedelta(days=3)).isoformat()
        factory = _mock_table({
            "users": [{"streak_count": 12, "last_active_date": stale}],
            "graph_nodes": [],
            "graph_edges": [],
            "enrollments": [],
        })
        with patch("services.graph_service.table", side_effect=factory):
            result = get_graph("u1")
        assert result["stats"]["streak"] == 0

    def test_counts_each_mastery_tier(self):
        nodes = [
            {"id": "n1", "concept_name": "A", "mastery_tier": "mastered",   "mastery_score": 0.9,  "subject": "Math", "times_studied": 1, "user_id": "u1", "course_id": "c1"},
            {"id": "n2", "concept_name": "B", "mastery_tier": "learning",   "mastery_score": 0.5,  "subject": "Math", "times_studied": 1, "user_id": "u1", "course_id": "c1"},
            {"id": "n3", "concept_name": "C", "mastery_tier": "struggling", "mastery_score": 0.2,  "subject": "Math", "times_studied": 1, "user_id": "u1", "course_id": "c1"},
            {"id": "n4", "concept_name": "D", "mastery_tier": "unexplored", "mastery_score": 0.0,  "subject": "Math", "times_studied": 0, "user_id": "u1", "course_id": "c1"},
        ]
        factory = _mock_table({
            "users": [{"streak_count": 0}],
            "graph_nodes": nodes,
            "graph_edges": [],
            "enrollments": [_enrollment_row("c1", "M", "Math")],
        })
        with patch("services.graph_service.table", side_effect=factory):
            stats = get_graph("u1")["stats"]

        assert stats["mastered"]   == 1
        assert stats["learning"]   == 1
        assert stats["struggling"] == 1
        assert stats["unexplored"] == 1
        assert stats["total_nodes"] == 4

    def test_adds_subject_root_node_per_subject(self):
        nodes = [
            {"id": "n1", "concept_name": "Loops",     "mastery_tier": "learning", "mastery_score": 0.5,
             "subject": "CS101", "course_id": "c1", "times_studied": 2, "user_id": "u1"},
            {"id": "n2", "concept_name": "Functions", "mastery_tier": "mastered", "mastery_score": 0.8,
             "subject": "CS101", "course_id": "c1", "times_studied": 3, "user_id": "u1"},
        ]
        enrollment = [_enrollment_row("c1", "CS101", "Intro CS")]
        factory = _mock_table({
            "users": [{"streak_count": 0}],
            "enrollments": enrollment,
            "graph_nodes": nodes,
            "graph_edges": [],
        })
        with patch("services.graph_service.table", side_effect=factory):
            result = get_graph("u1")

        roots = [n for n in result["nodes"] if n.get("is_subject_root")]
        assert len(roots) == 1
        assert "CS101" in roots[0]["concept_name"]
        assert roots[0]["mastery_tier"] == "subject_root"

    def test_legacy_seed_same_as_course_title_shows_only_subject_hub(self):
        """Course enrolled but no concept nodes — only the subject hub appears."""
        enrollment = [_enrollment_row("c1", "", "EK 103: LINEAR ALGEBRA")]
        factory = _mock_table({
            "users": [{"streak_count": 0}],
            "enrollments": enrollment,
            "graph_nodes": [],
            "graph_edges": [],
        })
        with patch("services.graph_service.table", side_effect=factory):
            result = get_graph("u1")

        roots = [n for n in result["nodes"] if n.get("is_subject_root")]
        assert len(roots) == 1
        assert roots[0]["concept_name"] == "EK 103: LINEAR ALGEBRA"
        assert roots[0]["mastery_score"] == 0.0

    def test_course_with_no_graph_nodes_still_shows_subject_hub(self):
        enrollment = [_enrollment_row("c1", "", "Philosophy")]
        factory = _mock_table({
            "users": [{"streak_count": 0}],
            "enrollments": enrollment,
            "graph_nodes": [],
            "graph_edges": [],
        })
        with patch("services.graph_service.table", side_effect=factory):
            result = get_graph("u1")

        roots = [n for n in result["nodes"] if n.get("is_subject_root")]
        assert len(roots) == 1
        assert roots[0]["concept_name"] == "Philosophy"
        assert roots[0]["mastery_score"] == 0.0

    def test_edges_are_remapped(self):
        nodes = [{"id": "n1", "concept_name": "A", "mastery_tier": "learning", "mastery_score": 0.5, "subject": "X", "times_studied": 0, "user_id": "u1", "course_id": "c-x"}]
        edges = [{"id": "e1", "source_node_id": "n1", "target_node_id": "n1", "strength": 0.9}]
        factory = _mock_table({
            "users": [{"streak_count": 0}],
            "graph_nodes": nodes,
            "graph_edges": edges,
            "enrollments": [_enrollment_row("c-x", "", "X")],
        })
        with patch("services.graph_service.table", side_effect=factory):
            result = get_graph("u1")

        graph_edges = [e for e in result["edges"] if not e["id"].startswith("subject_edge")]
        assert len(graph_edges) == 1
        assert graph_edges[0]["source"] == "n1"
        assert graph_edges[0]["strength"] == 0.9

    def test_streak_defaults_to_zero_when_no_user_row(self):
        factory = _mock_table({"users": [], "graph_nodes": [], "graph_edges": [], "enrollments": []})
        with patch("services.graph_service.table", side_effect=factory):
            result = get_graph("u1")
        assert result["stats"]["streak"] == 0

    def test_learning_velocity_computed_from_event_rows(self):
        """learning_velocity + trimmed mastery_events come from node_mastery_events
        (the JSON column was dropped in 0023), not from a node column."""
        now = datetime.now(timezone.utc).isoformat()
        nodes = [
            {"id": "n1", "concept_name": "Loops", "mastery_tier": "learning",
             "mastery_score": 0.5, "subject": "CS", "times_studied": 3,
             "user_id": "u1", "course_id": "c1"},
        ]
        events = [
            {"node_id": "n1", "delta": 0.2, "reason": "r1", "created_at": now},
            {"node_id": "n1", "delta": 0.1, "reason": "r2", "created_at": now},
        ]
        factory = _mock_table({
            "users": [{"streak_count": 1}],
            "graph_nodes": nodes,
            "graph_edges": [],
            "node_mastery_events": events,
            "enrollments": [_enrollment_row("c1", "CS", "Intro CS")],
        })
        with patch("services.graph_service.table", side_effect=factory):
            result = get_graph("u1")

        node = next(n for n in result["nodes"] if n["id"] == "n1")
        assert node["learning_velocity"] > 0
        # API contract preserved: trimmed event tail (<=5) still surfaced per node.
        assert len(node["mastery_events"]) == 2
        assert result["stats"]["avg_learning_velocity"] > 0

    def test_dedupes_subject_root_for_two_offerings_of_same_course(self):
        """#355: a user enrolled in TWO offerings of the same abstract course
        (e.g. re-taking it, or two sections) must get exactly ONE subject-root
        node — synthesis dedupes by abstract course_id, not per-enrollment."""
        nodes = [
            {"id": "n1", "concept_name": "Loops", "mastery_tier": "learning",
             "mastery_score": 0.5, "subject": "CS101", "course_id": "c1",
             "times_studied": 2, "user_id": "u1"},
        ]
        enrollments = [
            _enrollment_row("c1", "CS101", "Intro CS", offering_id="off-1"),
            _enrollment_row("c1", "CS101", "Intro CS", offering_id="off-2"),
        ]
        factory = _mock_table({
            "users": [{"streak_count": 0}],
            "enrollments": enrollments,
            "graph_nodes": nodes,
            "graph_edges": [],
        })
        with patch("services.graph_service.table", side_effect=factory):
            result = get_graph("u1")

        node_ids = [n["id"] for n in result["nodes"]]
        assert len(node_ids) == len(set(node_ids)), f"duplicate node ids: {node_ids}"

        roots = [n for n in result["nodes"] if n.get("is_subject_root")]
        assert len(roots) == 1
        assert roots[0]["id"] == "subject_root__c1"

        # No surplus hub-spoke edges either: exactly one subject_edge per
        # concept node under the course, not one per enrollment.
        subject_edges = [e for e in result["edges"] if e["id"].startswith("subject_edge__")]
        assert len(subject_edges) == len(nodes)

    def test_velocity_zero_when_no_events(self):
        nodes = [
            {"id": "n1", "concept_name": "Loops", "mastery_tier": "learning",
             "mastery_score": 0.5, "subject": "CS", "times_studied": 0,
             "user_id": "u1", "course_id": "c1"},
        ]
        factory = _mock_table({
            "users": [{"streak_count": 0}],
            "graph_nodes": nodes,
            "graph_edges": [],
            "node_mastery_events": [],
            "enrollments": [_enrollment_row("c1", "CS", "Intro CS")],
        })
        with patch("services.graph_service.table", side_effect=factory):
            result = get_graph("u1")

        node = next(n for n in result["nodes"] if n["id"] == "n1")
        assert node["learning_velocity"] == 0.0
        assert node["mastery_events"] == []


# ── get_courses ───────────────────────────────────────────────────────────────

class TestGetCourses:
    def test_returns_courses_with_node_count(self):
        def factory(name):
            mock = MagicMock()
            if name == "enrollments":
                mock.select.return_value = [_enrollment_row(
                    "c1", "MATH101", "Math", term="Spring 2026", offering_id="off-1")]
            elif name == "graph_nodes":
                mock.select.return_value = [{"id": "n1"}, {"id": "n2"}]
            else:
                mock.select.return_value = []
            return mock

        with patch("services.graph_service.table", side_effect=factory):
            result = get_courses("u1")

        assert len(result) == 1
        assert result[0]["course_id"] == "c1"          # abstract course id
        assert result[0]["course_name"] == "Math"
        assert result[0]["term"] == "Spring 2026"      # term surfaced
        assert result[0]["node_count"] == 2

    def test_collapses_duplicate_course_across_terms(self):
        """#449 (findings F1/F3): a user enrolled in the SAME abstract course in
        two terms (CS101 Fall 2025 + CS101 Spring 2026) has two enrollments/
        offerings sharing one abstract course_id. get_courses must collapse them
        to ONE row per course_id — not fan out one row per enrollment."""
        fall = _enrollment_row("cs101", "CS101", "Intro CS",
                               term="Fall 2025", offering_id="off-fall")
        fall["id"] = "enr-fall"
        fall["enrolled_at"] = "2025-09-01"
        spring = _enrollment_row("cs101", "CS101", "Intro CS",
                                 term="Spring 2026", offering_id="off-spring")
        spring["id"] = "enr-spring"
        spring["enrolled_at"] = "2026-01-15"

        def factory(name):
            mock = MagicMock()
            if name == "enrollments":
                # _user_enrolled_courses orders enrolled_at.asc
                mock.select.return_value = [fall, spring]
            elif name == "graph_nodes":
                mock.select.return_value = [{"id": "n1"}, {"id": "n2"}, {"id": "n3"}]
            else:
                mock.select.return_value = []
            return mock

        with patch("services.graph_service.table", side_effect=factory):
            result = get_courses("u1")

        # exactly one row per DISTINCT abstract course_id
        assert len(result) == 1
        course_ids = [c["course_id"] for c in result]
        assert course_ids == ["cs101"]
        row = result[0]
        # representative = most recent enrollment (latest enrolled_at = Spring 2026)
        assert row["term"] == "Spring 2026"
        assert row["enrollment_id"] == "enr-spring"
        # node_count is the abstract course's count, counted ONCE — not doubled
        # across the two offerings.
        assert row["node_count"] == 3
        # per-enrollment detail is preserved (not silently dropped) for any
        # enrollment-keyed consumer.
        assert set(row["enrollment_ids"]) == {"enr-fall", "enr-spring"}
        assert set(row["terms"]) == {"Fall 2025", "Spring 2026"}

    def test_returns_empty_on_exception(self):
        def factory(name):
            mock = MagicMock()
            mock.select.side_effect = Exception("DB error")
            return mock

        with patch("services.graph_service.table", side_effect=factory):
            result = get_courses("u1")
        assert result == []


# ── add_course ────────────────────────────────────────────────────────────────

class TestAddCourse:
    def test_inserts_new_course(self):
        # `courses` (abstract) exists; resolve_offering finds an existing offering
        # in the current term; no existing enrollment → insert against offering_id.
        factory, mocks = _cached_mock_table({
            "courses": [{"id": "c1"}],
            "enrollments": [],                       # existing-enrollment check → none
            "terms": [{"id": "t1", "sort_key": 1}],
            "course_offerings": [{"id": "off-1"}],   # resolve_offering → existing
        })
        with patch("services.graph_service.table", side_effect=factory), \
             patch("services.academics.table", side_effect=factory), \
             patch("services.course_context_service.update_course_context"):
            result = add_course("u1", "c1")

        assert result["course_id"] == "c1"
        assert result["already_existed"] is False
        inserted = mocks["enrollments"].insert.call_args[0][0]
        assert inserted["offering_id"] == "off-1"
        assert "course_id" not in inserted             # enrollments key on the offering

    def test_skips_insert_for_existing_course(self):
        # The up-front no-retake check is the single already-existed path (the
        # redundant per-offering enrollment check was removed): an enrollment in
        # any offering of the course short-circuits before any term resolution.
        factory, mocks = _cached_mock_table({
            "courses": [{"id": "c1"}],
            "enrollments": [{"id": "existing", "offering_id": "off-1"}],
            "terms": [{"id": "t1", "sort_key": 1}],
            "course_offerings": [{"id": "off-1"}],
        })
        with patch("services.graph_service.table", side_effect=factory), \
             patch("services.academics.table", side_effect=factory):
            result = add_course("u1", "c1")

        assert result["already_existed"] is True
        assert "term" in result  # single return contract: duplicate carries term
        mocks["enrollments"].insert.assert_not_called()


# ── delete_course ─────────────────────────────────────────────────────────────

class TestDeleteCourse:
    """#766: a drop removes ONE term's enrollment, never every term's — an
    enrollment cascades to that term's assignments/grades/checklists."""

    _TERMS = {"off-fall": {"id": "fall-2025"}, "off-spring": {"id": "spring-2026"}}

    def _run(self, *, held, term=None, current="spring-2026", label_map=None):
        factory, mocks = _cached_mock_table({})
        label_map = label_map if label_map is not None else {
            "Fall 2025": "fall-2025", "Spring 2026": "spring-2026",
        }
        with patch("services.graph_service.table", side_effect=factory), \
             patch("services.academics.user_offering_ids_for_course", return_value=held), \
             patch("services.academics.term_for_offering", side_effect=self._TERMS.get), \
             patch("services.academics.term_id_for_label", side_effect=label_map.get), \
             patch("services.academics.current_term",
                   return_value={"id": current} if current else None), \
             patch("services.course_context_service.update_course_context") as ucc:
            result = delete_course("u1", "cs101", term)
        deleted = [
            c.args[0]["offering_id"] for c in mocks["enrollments"].delete.call_args_list
        ] if "enrollments" in mocks else []
        return result, deleted, ucc

    def test_default_drops_only_the_current_terms_enrollment(self):
        result, deleted, ucc = self._run(held=["off-fall", "off-spring"])
        assert result == {"deleted": True}
        # The past term's enrollment (and its gradebook) survives.
        assert deleted == ["eq.off-spring"]
        ucc.assert_called_once_with("off-spring")

    def test_explicit_term_drops_only_that_term(self):
        result, deleted, _ = self._run(held=["off-fall", "off-spring"], term="Fall 2025")
        assert result == {"deleted": True}
        assert deleted == ["eq.off-fall"]

    def test_unknown_term_label_is_an_error_and_deletes_nothing(self):
        result, deleted, _ = self._run(held=["off-fall"], term="Winter 1999")
        assert result["deleted"] is False and "error" in result
        assert deleted == []

    def test_no_term_and_only_past_enrollment_refuses(self):
        # Without a term the caller means "this term"; silently dropping the
        # student's Fall gradebook instead is exactly the bug.
        result, deleted, _ = self._run(held=["off-fall"])
        assert result["deleted"] is False and "error" in result
        assert deleted == []

    def test_not_enrolled_is_an_idempotent_noop(self):
        result, deleted, _ = self._run(held=[])
        assert result == {"deleted": False}
        assert deleted == []

    def test_graph_nodes_are_never_touched(self):
        factory, mocks = _cached_mock_table({})
        with patch("services.graph_service.table", side_effect=factory), \
             patch("services.academics.user_offering_ids_for_course", return_value=["off-spring"]), \
             patch("services.academics.term_for_offering", side_effect=self._TERMS.get), \
             patch("services.academics.current_term", return_value={"id": "spring-2026"}), \
             patch("services.course_context_service.update_course_context"):
            delete_course("u1", "cs101")
        assert "graph_nodes" not in mocks and "graph_edges" not in mocks


# ── apply_graph_update ────────────────────────────────────────────────────────

#: Stand-in for graph_nodes as the ``apply_mastery_delta`` SQL function sees it
#: (#766): id → stored row copy. ``_bulk_factory`` seeds it with the existing
#: nodes and every upserted node; ``_fake_mastery_rpc`` applies deltas to it
#: exactly as the migration's function does (clamp, tier, times_studied + 1).
_FAKE_NODE_STORE: dict = {}


def _fake_mastery_rpc(name, params):
    assert name == "apply_mastery_delta"
    node = _FAKE_NODE_STORE.get(params["p_node_id"])
    if node is None:
        return []
    before = float(node.get("mastery_score") or 0.0)
    after = max(0.0, min(1.0, before + params["p_delta"]))
    tier = (
        "mastered" if after >= params["p_mastered_min"]
        else "learning" if after >= params["p_learning_min"]
        else "struggling" if after >= params["p_struggling_min"]
        else "unexplored"
    )
    node.update(mastery_score=after, mastery_tier=tier,
                times_studied=(node.get("times_studied") or 0) + 1)
    return [{"before_score": before, "after_score": after, "new_tier": tier}]


@pytest.fixture(autouse=True)
def _mastery_rpc():
    _FAKE_NODE_STORE.clear()
    with patch("services.graph_service.rpc", side_effect=_fake_mastery_rpc) as m:
        yield m
    _FAKE_NODE_STORE.clear()


def _bulk_factory(existing_nodes=None, existing_edges=None):
    """Factory that returns a fresh mock per table; bulk-fetch returns the given rows.

    ``graph_nodes.upsert`` echoes back the inserted payload (PostgREST
    ``return=representation``) so apply_graph_update can read the canonical node
    id from the response, matching live Supabase behaviour.
    """
    nodes = list(existing_nodes or [])
    edges = list(existing_edges or [])
    mocks = {}
    for n in nodes:
        _FAKE_NODE_STORE[n["id"]] = dict(n)

    def _upsert(data, **kw):
        for d in [data] if isinstance(data, dict) else list(data):
            _FAKE_NODE_STORE.setdefault(d["id"], dict(d))
        return [data] if isinstance(data, dict) else list(data)

    def factory(name):
        if name not in mocks:
            m = MagicMock()
            if name == "graph_nodes":
                m.select.return_value = nodes
                m.upsert.side_effect = _upsert
            elif name == "graph_edges":
                m.select.return_value = edges
                m.upsert.return_value = []
            elif name == "users":
                m.select.return_value = [{"streak_count": 0, "last_active_date": None}]
                m.upsert.return_value = []
            else:
                m.select.return_value = []
                m.upsert.return_value = []
            m.insert.return_value = []
            m.update.return_value = []
            m.delete.return_value = []
            mocks[name] = m
        return mocks[name]

    return factory, mocks


class TestApplyGraphUpdate:
    def test_inserts_new_node(self):
        factory, mocks = _bulk_factory(existing_nodes=[])
        graph_update = {
            "new_nodes": [{"concept_name": "Recursion", "initial_mastery": 0.0}],
            "updated_nodes": [],
            "new_edges": [],
        }
        with patch("services.graph_service.table", side_effect=factory):
            result = apply_graph_update("u1", graph_update)

        assert result == []
        # UNIQUE-backed upsert replaces the old select-then-insert (0023).
        mocks["graph_nodes"].insert.assert_not_called()
        mocks["graph_nodes"].upsert.assert_called_once()
        inserted, kwargs = mocks["graph_nodes"].upsert.call_args
        payload = inserted[0]
        assert payload["concept_name"] == "Recursion"
        assert payload["mastery_score"] == 0.0
        assert payload["mastery_tier"] == "unexplored"
        # mastery_events column is gone (replaced by node_mastery_events).
        assert "mastery_events" not in payload
        assert kwargs["on_conflict"] == "user_id,course_id,concept_name"

    def test_skips_insert_for_existing_node_case_insensitive(self):
        existing = [
            {"id": "n1", "concept_name": "Linear Regression", "mastery_score": 0.3,
             "times_studied": 1, "course_id": "c1"}
        ]
        factory, mocks = _bulk_factory(existing_nodes=existing)
        # The LLM emits the same concept with different casing/whitespace
        graph_update = {
            "new_nodes": [{"concept_name": "  linear   regression ", "initial_mastery": 0.0}],
            "updated_nodes": [],
            "new_edges": [],
        }
        with patch("services.graph_service.table", side_effect=factory):
            apply_graph_update("u1", graph_update, course_id="c1")

        mocks["graph_nodes"].upsert.assert_not_called()
        mocks["graph_nodes"].insert.assert_not_called()

    def test_dedups_within_a_single_batch(self):
        factory, mocks = _bulk_factory(existing_nodes=[])
        graph_update = {
            "new_nodes": [
                {"concept_name": "Gradient Descent", "initial_mastery": 0.0},
                {"concept_name": "gradient descent", "initial_mastery": 0.0},
                {"concept_name": "Gradient  Descent", "initial_mastery": 0.0},
            ],
            "updated_nodes": [],
            "new_edges": [],
        }
        with patch("services.graph_service.table", side_effect=factory):
            apply_graph_update("u1", graph_update, course_id="c1")

        assert mocks["graph_nodes"].upsert.call_count == 1

    def test_skips_blank_concept_names(self):
        factory, mocks = _bulk_factory(existing_nodes=[])
        graph_update = {
            "new_nodes": [
                {"concept_name": "", "initial_mastery": 0.0},
                {"concept_name": "   ", "initial_mastery": 0.0},
                {"concept_name": None, "initial_mastery": 0.0},
            ],
            "updated_nodes": [],
            "new_edges": [],
        }
        with patch("services.graph_service.table", side_effect=factory):
            apply_graph_update("u1", graph_update, course_id="c1")

        mocks["graph_nodes"].upsert.assert_not_called()

    def test_coerces_null_initial_mastery(self):
        factory, mocks = _bulk_factory(existing_nodes=[])
        graph_update = {
            "new_nodes": [{"concept_name": "X", "initial_mastery": None}],
            "updated_nodes": [],
            "new_edges": [],
        }
        with patch("services.graph_service.table", side_effect=factory):
            apply_graph_update("u1", graph_update, course_id="c1")

        payload = mocks["graph_nodes"].upsert.call_args[0][0]
        assert payload["mastery_score"] == 0.0

    def test_clamps_initial_mastery_above_one(self):
        factory, mocks = _bulk_factory(existing_nodes=[])
        graph_update = {
            "new_nodes": [{"concept_name": "X", "initial_mastery": 5.0}],
            "updated_nodes": [],
            "new_edges": [],
        }
        with patch("services.graph_service.table", side_effect=factory):
            apply_graph_update("u1", graph_update, course_id="c1")

        payload = mocks["graph_nodes"].upsert.call_args[0][0]
        assert payload["mastery_score"] == 1.0

    def test_updates_mastery_score(self):
        existing = [
            {"id": "n1", "concept_name": "Algebra", "mastery_score": 0.4,
             "times_studied": 2, "course_id": "c1"}
        ]
        factory, mocks = _bulk_factory(existing_nodes=existing)
        graph_update = {
            "new_nodes": [],
            "updated_nodes": [{"concept_name": "Algebra", "mastery_delta": 0.2,
                               "reason": "solved a problem"}],
            "new_edges": [],
        }
        with patch("services.graph_service.table", side_effect=factory):
            with patch("services.course_context_service.update_course_context"):
                result = apply_graph_update("u1", graph_update, course_id="c1")

        assert len(result) == 1
        assert result[0]["before"] == pytest.approx(0.4)
        assert result[0]["after"] == pytest.approx(0.6)
        # Mastery change should reference the canonical stored name, not the LLM's
        assert result[0]["concept"] == "Algebra"
        # #766: the score is no longer written back by a Python
        # read-modify-write; the atomic SQL function applies the DELTA.
        mocks["graph_nodes"].update.assert_not_called()
        assert _FAKE_NODE_STORE["n1"]["mastery_score"] == pytest.approx(0.6)
        assert _FAKE_NODE_STORE["n1"]["mastery_tier"] == "learning"
        assert _FAKE_NODE_STORE["n1"]["times_studied"] == 3

    # ── #766: the mastery update is atomic ────────────────────────────────

    def _update(self, existing, delta=0.2, user="u1"):
        factory, mocks = _bulk_factory(existing_nodes=existing)
        graph_update = {
            "new_nodes": [],
            "updated_nodes": [{"concept_name": "Algebra", "mastery_delta": delta}],
            "new_edges": [],
        }
        with patch("services.graph_service.table", side_effect=factory), \
             patch("services.course_context_service.update_course_context"):
            return apply_graph_update(user, graph_update, course_id="c1"), mocks

    def test_rpc_gets_the_delta_and_configs_thresholds(self, _mastery_rpc):
        from config import (
            MASTERY_LEARNING_MIN, MASTERY_MASTERED_MIN, MASTERY_STRUGGLING_MIN,
        )
        self._update([{"id": "n1", "concept_name": "Algebra", "mastery_score": 0.4,
                       "times_studied": 2, "course_id": "c1"}])
        _mastery_rpc.assert_called_once_with("apply_mastery_delta", {
            "p_node_id": "n1",
            "p_user_id": "u1",
            "p_delta": pytest.approx(0.2),
            "p_mastered_min": MASTERY_MASTERED_MIN,
            "p_learning_min": MASTERY_LEARNING_MIN,
            "p_struggling_min": MASTERY_STRUGGLING_MIN,
        })

    def test_concurrent_writers_compose_instead_of_losing_an_update(self):
        # Two writers (a quiz submit and a tutor turn) both bulk-read the node
        # at 0.4. The old Python read-modify-write had each write back
        # 0.4 + 0.2, so the store ended at 0.6 with times_studied 3; deltas
        # applied in SQL compose to 0.8 / 4.
        stale = {"id": "n1", "concept_name": "Algebra", "mastery_score": 0.4,
                 "times_studied": 2, "course_id": "c1"}
        first, _ = self._update([dict(stale)])
        # The second writer's bulk read predates the first commit: it still
        # sees 0.4. (_bulk_factory would re-seed the store from that stale
        # row, so restore the committed state the database actually holds.)
        committed = dict(_FAKE_NODE_STORE["n1"])
        factory2, _ = _bulk_factory(existing_nodes=[dict(stale)])
        _FAKE_NODE_STORE["n1"] = committed
        graph_update = {"new_nodes": [], "new_edges": [],
                        "updated_nodes": [{"concept_name": "Algebra", "mastery_delta": 0.2}]}
        with patch("services.graph_service.table", side_effect=factory2), \
             patch("services.course_context_service.update_course_context"):
            second = apply_graph_update("u1", graph_update, course_id="c1")

        assert first[0]["after"] == pytest.approx(0.6)
        # The second writer's before/after are what was actually applied.
        assert second[0]["before"] == pytest.approx(0.6)
        assert second[0]["after"] == pytest.approx(0.8)
        assert _FAKE_NODE_STORE["n1"]["mastery_score"] == pytest.approx(0.8)
        assert _FAKE_NODE_STORE["n1"]["times_studied"] == 4

    def test_a_node_deleted_under_us_is_skipped(self, _mastery_rpc):
        _mastery_rpc.side_effect = lambda *_a, **_k: []
        result, mocks = self._update([{"id": "n1", "concept_name": "Algebra",
                                       "mastery_score": 0.4, "course_id": "c1"}])
        assert result == []
        assert "node_mastery_events" not in mocks

    def test_missing_function_falls_back_to_the_legacy_write(self, _mastery_rpc):
        import httpx
        req = httpx.Request("POST", "http://test/rpc/apply_mastery_delta")
        _mastery_rpc.side_effect = httpx.HTTPStatusError(
            "404", request=req, response=httpx.Response(404, request=req))
        result, mocks = self._update([{"id": "n1", "concept_name": "Algebra",
                                       "mastery_score": 0.4, "times_studied": 2,
                                       "course_id": "c1"}])
        assert result[0]["after"] == pytest.approx(0.6)
        payload = mocks["graph_nodes"].update.call_args[0][0]
        assert payload["mastery_score"] == pytest.approx(0.6)
        assert payload["mastery_tier"] == "learning"
        assert payload["times_studied"] == 3
        assert mocks["graph_nodes"].update.call_args.kwargs["filters"] == {
            "id": "eq.n1", "user_id": "eq.u1",
        }

    def test_other_rpc_errors_propagate(self, _mastery_rpc):
        import httpx
        req = httpx.Request("POST", "http://test/rpc/apply_mastery_delta")
        _mastery_rpc.side_effect = httpx.HTTPStatusError(
            "500", request=req, response=httpx.Response(500, request=req))
        with pytest.raises(httpx.HTTPStatusError):
            self._update([{"id": "n1", "concept_name": "Algebra",
                           "mastery_score": 0.4, "course_id": "c1"}])

    def test_mastery_change_appends_event_row(self):
        """A mastery change appends exactly one append-only node_mastery_events row
        (fixes the non-atomic JSON read-modify-write, #247)."""
        existing = [
            {"id": "n1", "concept_name": "Algebra", "mastery_score": 0.4,
             "times_studied": 2, "course_id": "c1"}
        ]
        factory, mocks = _bulk_factory(existing_nodes=existing)
        graph_update = {
            "new_nodes": [],
            "updated_nodes": [{"concept_name": "Algebra", "mastery_delta": 0.2,
                               "reason": "aced the quiz"}],
            "new_edges": [],
        }
        with patch("services.graph_service.table", side_effect=factory):
            with patch("services.course_context_service.update_course_context"):
                apply_graph_update("u1", graph_update, course_id="c1")

        mocks["node_mastery_events"].insert.assert_called_once()
        event = mocks["node_mastery_events"].insert.call_args[0][0]
        assert event["node_id"] == "n1"
        assert event["delta"] == pytest.approx(0.2)
        assert event["reason"] == "aced the quiz"
        # This caller classified nothing, so the (E7-added) event_type column
        # stays absent rather than carrying an explicit null.
        assert "event_type" not in event

    def test_updates_existing_node_via_case_insensitive_name(self):
        existing = [
            {"id": "n1", "concept_name": "Linear Regression", "mastery_score": 0.3,
             "times_studied": 1, "course_id": "c1"}
        ]
        factory, mocks = _bulk_factory(existing_nodes=existing)
        graph_update = {
            "new_nodes": [],
            "updated_nodes": [{"concept_name": "linear regression", "mastery_delta": 0.1}],
            "new_edges": [],
        }
        with patch("services.graph_service.table", side_effect=factory):
            with patch("services.course_context_service.update_course_context"):
                result = apply_graph_update("u1", graph_update, course_id="c1")

        assert len(result) == 1
        assert result[0]["concept"] == "Linear Regression"

    def test_can_update_node_just_inserted_in_same_call(self):
        factory, mocks = _bulk_factory(existing_nodes=[])
        graph_update = {
            "new_nodes": [{"concept_name": "Eigenvectors", "initial_mastery": 0.0}],
            "updated_nodes": [{"concept_name": "Eigenvectors", "mastery_delta": 0.1}],
            "new_edges": [],
        }
        with patch("services.graph_service.table", side_effect=factory):
            with patch("services.course_context_service.update_course_context"):
                result = apply_graph_update("u1", graph_update, course_id="c1")

        assert len(result) == 1
        assert result[0]["before"] == 0.0
        assert result[0]["after"] == pytest.approx(0.1)

    def test_mastery_clamped_at_1(self):
        existing = [
            {"id": "n1", "concept_name": "X", "mastery_score": 0.95,
             "times_studied": 5, "course_id": "c1"}
        ]
        factory, _ = _bulk_factory(existing_nodes=existing)
        graph_update = {"new_nodes": [], "updated_nodes": [{"concept_name": "X", "mastery_delta": 0.5}], "new_edges": []}
        with patch("services.graph_service.table", side_effect=factory):
            with patch("services.course_context_service.update_course_context"):
                result = apply_graph_update("u1", graph_update, course_id="c1")
        assert result[0]["after"] == 1.0

    def test_mastery_clamped_at_0(self):
        existing = [
            {"id": "n1", "concept_name": "X", "mastery_score": 0.05,
             "times_studied": 0, "course_id": "c1"}
        ]
        factory, _ = _bulk_factory(existing_nodes=existing)
        graph_update = {"new_nodes": [], "updated_nodes": [{"concept_name": "X", "mastery_delta": -0.5}], "new_edges": []}
        with patch("services.graph_service.table", side_effect=factory):
            with patch("services.course_context_service.update_course_context"):
                result = apply_graph_update("u1", graph_update, course_id="c1")
        assert result[0]["after"] == 0.0

    def test_empty_update_returns_empty_list(self):
        factory, _ = _bulk_factory(existing_nodes=[])
        with patch("services.graph_service.table", side_effect=factory):
            result = apply_graph_update("u1", {"new_nodes": [], "updated_nodes": [], "new_edges": []})
        assert result == []

    # ── E7: event_type reaches the event row ──────────────────────────────

    def _apply_with_event_type(self, upd_extra):
        existing = [
            {"id": "n1", "concept_name": "X", "mastery_score": 0.5,
             "times_studied": 0, "course_id": "c1"}
        ]
        factory, mocks = _bulk_factory(existing_nodes=existing)
        graph_update = {
            "new_nodes": [],
            "updated_nodes": [{"concept_name": "X", "mastery_delta": 0.1,
                               "reason": "Quiz: 1/3 correct", **upd_extra}],
            "new_edges": [],
        }
        with patch("services.graph_service.table", side_effect=factory):
            with patch("services.course_context_service.update_course_context"):
                apply_graph_update("u1", graph_update, course_id="c1")
        mocks["node_mastery_events"].insert.assert_called_once()
        return mocks["node_mastery_events"].insert.call_args[0][0]

    def test_event_type_is_persisted_on_the_mastery_event(self):
        """E7: submit computes a categorical reading from the score ratio and
        used to DROP it at the write. It reaches the row now, namespaced."""
        row = self._apply_with_event_type({"event_type": "quiz_confusion"})
        assert row["event_type"] == "quiz_confusion"
        # The rest of the append-only shape is untouched.
        assert row["delta"] == pytest.approx(0.1)
        assert row["reason"] == "Quiz: 1/3 correct"

    def test_event_type_omitted_when_caller_supplies_none(self):
        """The callers that classify NOTHING (the document pipeline, notes
        extraction, manual adds via add_node) pass no event_type, and the key
        must be ABSENT rather than an explicit null.

        Note this is NOT "every non-quiz caller": the chat tutor's
        `update_mastery_tool` has always supplied a category of its own, and
        is in fact the highest-volume writer here. Its field is nullable, so
        it lands in this branch only for a turn the model did not classify.

        Absent, not null, on purpose: it keeps the non-classifying callers
        working against a database where E7's migration hasn't been applied
        yet — PostgREST rejects an insert naming a column the schema cache
        doesn't have, so writing the key unconditionally would break those
        paths on any environment that took the code before the DDL.
        """
        row = self._apply_with_event_type({})
        assert "event_type" not in row

    def test_explicit_none_event_type_is_treated_as_absent(self):
        """A caller that passes the key with None is a DIFFERENT branch from
        one that omits it — the implementation guards with `isinstance(...,
        str)`, and a dict built unconditionally (which is what the tutor tool
        used to do) hits exactly this. It must not write the key, or the
        pre-migration 400 comes back for the unclassified turns too."""
        row = self._apply_with_event_type({"event_type": None})
        assert "event_type" not in row

    def test_blank_event_type_is_treated_as_absent(self):
        """An empty string is not a category — don't persist one."""
        row = self._apply_with_event_type({"event_type": "  "})
        assert "event_type" not in row

    def _apply_with_failing_events(self, fail_times):
        """Run one mastery update whose node_mastery_events insert fails
        `fail_times` times. Returns the payloads it attempted."""
        existing = [
            {"id": "n1", "concept_name": "X", "mastery_score": 0.5,
             "times_studied": 0, "course_id": "c1"}
        ]
        factory, mocks = _bulk_factory(existing_nodes=existing)
        attempts = []

        def _insert(payload):
            attempts.append(payload)
            if len(attempts) <= fail_times:
                raise RuntimeError("PGRST204 column event_type does not exist")
            return []

        mocks_holder = {}

        def wrapped(name):
            m = factory(name)
            if name == "node_mastery_events" and name not in mocks_holder:
                m.insert.side_effect = _insert
                mocks_holder[name] = m
            return m

        graph_update = {
            "new_nodes": [],
            "updated_nodes": [{"concept_name": "X", "mastery_delta": 0.1,
                               "reason": "Quiz: 1/3",
                               "event_type": "quiz_partial"}],
            "new_edges": [],
        }
        with patch("services.graph_service.table", side_effect=wrapped):
            with patch("services.course_context_service.update_course_context"):
                result = apply_graph_update("u1", graph_update, course_id="c1")
        return attempts, result

    def test_event_type_rejection_retries_without_it(self):
        """The E7 ordering hazard: a deploy that takes this code before the
        migration lands gets a 400 for the unknown column. Degrade to the
        pre-E7 row rather than costing the student their graded quiz."""
        attempts, result = self._apply_with_failing_events(fail_times=1)
        assert len(attempts) == 2
        assert attempts[0]["event_type"] == "quiz_partial"
        assert "event_type" not in attempts[1]
        # The mastery change is still reported, so submit writes its score.
        assert result and result[0]["after"] == pytest.approx(0.6)

    def test_a_dead_event_table_never_takes_the_caller_down(self):
        """quiz submit calls this AFTER its atomic completed_at claim and
        BEFORE writing score/answers_json, and does not wrap it — so raising
        here permanently loses a graded attempt, and the retry 409s. The
        journal is not worth the quiz."""
        attempts, result = self._apply_with_failing_events(fail_times=2)
        assert len(attempts) == 2
        assert result and result[0]["after"] == pytest.approx(0.6)

    # ── The tutor path: the OTHER producer of this column ─────────────────

    def test_tutor_mastery_tool_persists_a_namespaced_event_type(self):
        """The chat tutor's `update_mastery_tool` has ALWAYS supplied an
        event_type (it used to default to "interaction"), so this column has
        two producers from the day it exists — not "quiz only".

        Both vocabularies therefore land in one unconstrained TEXT column, and
        the tutor's bare `quiz` ("I quizzed the student mid-conversation")
        would be unreadable beside submit_quiz's own labels. This drives the
        real tool -> apply_graph_update path and pins the namespaced value
        that reaches the row.
        """
        import asyncio
        from types import SimpleNamespace

        from agents.tools.graph import (
            ConceptMasteryUpdate,
            MasteryUpdateInput,
            update_mastery_tool,
        )

        existing = [
            {"id": "n1", "concept_name": "Recursion", "mastery_score": 0.5,
             "times_studied": 0, "course_id": "c1"}
        ]
        factory, mocks = _bulk_factory(existing_nodes=existing)
        ctx = SimpleNamespace(deps=SimpleNamespace(
            user_id="u1", course_id="c1", graph_updates=[], mastery_changes=[],
        ))
        update = MasteryUpdateInput(updates=[
            ConceptMasteryUpdate(
                concept_name="Recursion", mastery_delta=0.1,
                reason="answered correctly", event_type="quiz",
            )
        ])

        with patch("services.graph_service.table", side_effect=factory):
            with patch("services.course_context_service.update_course_context"):
                asyncio.run(update_mastery_tool(ctx, update))

        mocks["node_mastery_events"].insert.assert_called_once()
        row = mocks["node_mastery_events"].insert.call_args[0][0]
        # `tutor_quiz`, not `quiz`: the value names its producer, so it can
        # never be read as one of submit_quiz's quiz_* labels.
        assert row["event_type"] == "tutor_quiz"
        assert row["node_id"] == "n1"

    def test_tutor_mastery_tool_omits_an_unclassified_event_type(self):
        """The tool's field is nullable and defaults to None now, so a turn
        the model didn't classify writes NO key — an un-categorised event must
        stay distinguishable from a confident one, which a default of
        "interaction" made impossible."""
        import asyncio
        from types import SimpleNamespace

        from agents.tools.graph import (
            ConceptMasteryUpdate,
            MasteryUpdateInput,
            update_mastery_tool,
        )

        existing = [
            {"id": "n1", "concept_name": "Recursion", "mastery_score": 0.5,
             "times_studied": 0, "course_id": "c1"}
        ]
        factory, mocks = _bulk_factory(existing_nodes=existing)
        ctx = SimpleNamespace(deps=SimpleNamespace(
            user_id="u1", course_id="c1", graph_updates=[], mastery_changes=[],
        ))
        update = MasteryUpdateInput(updates=[
            ConceptMasteryUpdate(concept_name="Recursion", mastery_delta=0.1)
        ])

        with patch("services.graph_service.table", side_effect=factory):
            with patch("services.course_context_service.update_course_context"):
                asyncio.run(update_mastery_tool(ctx, update))

        row = mocks["node_mastery_events"].insert.call_args[0][0]
        assert "event_type" not in row

    def test_edge_upsert_uses_unique_conflict(self):
        """A new edge is written via UNIQUE-backed upsert (no select-then-insert);
        the DB dedups on (user_id, source, target, relationship_type) — 0023."""
        existing_nodes = [
            {"id": "n1", "concept_name": "A", "mastery_score": 0.0,
             "times_studied": 0, "course_id": "c1"},
            {"id": "n2", "concept_name": "B", "mastery_score": 0.0,
             "times_studied": 0, "course_id": "c1"},
        ]
        factory, mocks = _bulk_factory(existing_nodes=existing_nodes)
        graph_update = {
            "new_nodes": [],
            "updated_nodes": [],
            "new_edges": [{"source": "A", "target": "B", "strength": 0.7,
                           "relationship_type": "prerequisite"}],
        }
        with patch("services.graph_service.table", side_effect=factory):
            apply_graph_update("u1", graph_update, course_id="c1")

        mocks["graph_edges"].insert.assert_not_called()
        mocks["graph_edges"].upsert.assert_called_once()
        payload, kwargs = mocks["graph_edges"].upsert.call_args
        edge = payload[0]
        assert edge["source_node_id"] == "n1"
        assert edge["target_node_id"] == "n2"
        assert edge["relationship_type"] == "prerequisite"
        assert edge["strength"] == pytest.approx(0.7)
        assert kwargs["on_conflict"] == "user_id,source_node_id,target_node_id,relationship_type"

    def test_duplicate_edge_is_idempotent_via_upsert(self):
        """Re-emitting an existing edge re-upserts it; the DB UNIQUE constraint keeps
        it idempotent (no pre-check select needed)."""
        existing_nodes = [
            {"id": "n1", "concept_name": "A", "mastery_score": 0.0,
             "times_studied": 0, "course_id": "c1"},
            {"id": "n2", "concept_name": "B", "mastery_score": 0.0,
             "times_studied": 0, "course_id": "c1"},
        ]
        factory, mocks = _bulk_factory(
            existing_nodes=existing_nodes,
            existing_edges=[{"id": "e1", "user_id": "u1", "source_node_id": "n1",
                             "target_node_id": "n2", "relationship_type": "related"}],
        )
        graph_update = {
            "new_nodes": [],
            "updated_nodes": [],
            "new_edges": [{"source": "A", "target": "B", "strength": 0.7}],
        }
        with patch("services.graph_service.table", side_effect=factory):
            apply_graph_update("u1", graph_update, course_id="c1")

        # No legacy select-then-insert; the upsert is the single write path.
        mocks["graph_edges"].insert.assert_not_called()
        mocks["graph_edges"].upsert.assert_called_once()

    def test_skips_self_edges(self):
        existing_nodes = [
            {"id": "n1", "concept_name": "A", "mastery_score": 0.0,
             "times_studied": 0, "course_id": "c1"},
        ]
        factory, mocks = _bulk_factory(existing_nodes=existing_nodes)
        graph_update = {
            "new_nodes": [],
            "updated_nodes": [],
            "new_edges": [{"source": "A", "target": "a", "strength": 0.7}],
        }
        with patch("services.graph_service.table", side_effect=factory):
            apply_graph_update("u1", graph_update, course_id="c1")

        # The only edge (A -> a) is a self-edge after case-folding, so it must be
        # skipped — no edge write of any kind.
        if "graph_edges" in mocks:
            mocks["graph_edges"].upsert.assert_not_called()
            mocks["graph_edges"].insert.assert_not_called()

    def test_mastery_change_advances_streak_via_streak_service(self):
        """apply_graph_update's mastery-change path (graph_service.py:750-751)
        now delegates to services.streak_service.touch_streak_safe — the sole
        writer of streak_count/longest_streak — instead of a duplicate local
        implementation. This pins the delegation and its UTC calendar-day
        semantics (matching services.streak_service._today(), not local
        date.today())."""
        existing = [
            {"id": "n1", "concept_name": "Algebra", "mastery_score": 0.4,
             "times_studied": 2, "course_id": "c1"}
        ]
        factory, mocks = _bulk_factory(existing_nodes=existing)
        factory("users")  # seed the lazily-cached mock so it can be configured below
        yesterday_utc = (datetime.now(timezone.utc).date() - timedelta(days=1)).isoformat()
        mocks["users"].select.return_value = [
            {"last_active_date": yesterday_utc, "streak_count": 4, "longest_streak": 4}
        ]
        graph_update = {
            "new_nodes": [],
            "updated_nodes": [{"concept_name": "Algebra", "mastery_delta": 0.2,
                               "reason": "practice"}],
            "new_edges": [],
        }
        with patch("services.graph_service.table", side_effect=factory), \
             patch("services.streak_service.table", side_effect=factory), \
             patch("services.course_context_service.update_course_context"):
            apply_graph_update("u1", graph_update, course_id="c1")

        mocks["users"].update.assert_called_once()
        payload = mocks["users"].update.call_args[0][0]
        assert payload["streak_count"] == 5
        assert payload["longest_streak"] == 5


# ── streak reconciliation (mastery path vs. session-end path) ─────────────────

class _StatefulUsersTable:
    """A `table("users")` stand-in whose row persists across select/update
    calls, unlike a MagicMock's static `select.return_value`. Needed because
    proving two sequential touch_streak calls agree requires the second call
    to see the first call's write (same-day idempotency), not a frozen
    fixture row."""

    def __init__(self, row: dict):
        self.row = dict(row)
        self.update_calls = 0

    def select(self, *_args, **_kwargs):
        return [dict(self.row)]

    def update(self, data, **_kwargs):
        self.update_calls += 1
        self.row.update(data)
        return []


class TestStreakReconciliation:
    def test_mastery_touch_then_session_touch_same_utc_day_increments_once(self):
        """graph_service.apply_graph_update's mastery-driven touch and
        routes/learn.py::end_session's post-session touch both now funnel
        through the same services.streak_service.touch_streak. Firing both
        for the same user on the same UTC day (the ordinary shape of a real
        study session: mastery updates during chat, then session end) must
        advance the streak exactly once, not twice — this was the review
        finding that motivated deleting graph_service's duplicate writer."""
        existing = [
            {"id": "n1", "concept_name": "Algebra", "mastery_score": 0.4,
             "times_studied": 2, "course_id": "c1"}
        ]
        node_factory, mocks = _bulk_factory(existing_nodes=existing)
        yesterday_utc = (datetime.now(timezone.utc).date() - timedelta(days=1)).isoformat()
        users_table = _StatefulUsersTable(
            {"last_active_date": yesterday_utc, "streak_count": 4, "longest_streak": 4}
        )

        def factory(name):
            return users_table if name == "users" else node_factory(name)

        graph_update = {
            "new_nodes": [],
            "updated_nodes": [{"concept_name": "Algebra", "mastery_delta": 0.2,
                               "reason": "practice"}],
            "new_edges": [],
        }

        with patch("services.graph_service.table", side_effect=factory), \
             patch("services.streak_service.table", side_effect=factory), \
             patch("services.course_context_service.update_course_context"):
            apply_graph_update("u1", graph_update, course_id="c1")   # mastery-driven touch

            from services.streak_service import touch_streak_safe
            touch_streak_safe("u1")                                  # session-end touch, same day

        assert users_table.row["streak_count"] == 5
        assert users_table.row["longest_streak"] == 5
        assert users_table.update_calls == 1


# ── get_recommendations ───────────────────────────────────────────────────────

class TestGetRecommendations:
    def test_returns_recommendations(self):
        rows = [
            {"concept_name": "Pointers",   "mastery_score": 0.05, "mastery_tier": "struggling"},
            {"concept_name": "References", "mastery_score": 0.0,  "mastery_tier": "unexplored"},
        ]
        with patch("services.graph_service.table", return_value=_simple_mock(rows)):
            result = get_recommendations("u1")

        assert len(result) == 2
        assert result[0]["concept_name"] == "Pointers"
        assert "struggling" in result[0]["reason"].lower()
        assert "haven't studied" in result[1]["reason"].lower()

    def test_learning_tier_reason(self):
        rows = [{"concept_name": "Loops", "mastery_score": 0.5, "mastery_tier": "learning"}]
        with patch("services.graph_service.table", return_value=_simple_mock(rows)):
            result = get_recommendations("u1")
        assert "progress" in result[0]["reason"].lower()

    def test_empty_when_no_rows(self):
        with patch("services.graph_service.table", return_value=_simple_mock([])):
            result = get_recommendations("u1")
        assert result == []


# ── get_graph semester scoping ─────────────────────────────────────────────────

def test_get_graph_semester_filters_nodes_and_stats():
    """With a semester, only that term's course nodes survive and stats recount."""
    enrolled = [
        {"id": "e1", "offering_id": "o1", "course_id": "bio-101",
         "color": None, "nickname": None, "enrolled_at": "2026-01-01", "term": "Spring 2026",
         "courses": {"course_code": "BIO-101", "course_name": "Biology", "department": "", "school": ""}},
        {"id": "e2", "offering_id": "o2", "course_id": "psy-110",
         "color": None, "nickname": None, "enrolled_at": "2025-09-01", "term": "Fall 2025",
         "courses": {"course_code": "PSY-110", "course_name": "Psych", "department": "", "school": ""}},
    ]
    nodes = [
        {"id": "n1", "course_id": "bio-101", "concept_name": "Cells",
         "mastery_score": 0.4, "mastery_tier": "learning", "times_studied": 1},
        {"id": "n2", "course_id": "psy-110", "concept_name": "Freud",
         "mastery_score": 0.9, "mastery_tier": "mastered", "times_studied": 2},
    ]

    def fake_table(name):
        from unittest.mock import MagicMock
        m = MagicMock(name=f"table({name})")
        m.select.return_value = {"graph_nodes": nodes, "graph_edges": [],
                                 "node_mastery_events": [], "users": [{"streak_count": 3}]}.get(name, [])
        return m

    with patch.object(gs, "_user_enrolled_courses", return_value=enrolled), \
         patch.object(gs, "ensure_user_exists", return_value=None), \
         patch.object(gs, "table", side_effect=fake_table), \
         patch("services.academics.term_id_for_label", return_value="t-spring"), \
         patch("services.academics.user_course_ids_for_term", return_value={"bio-101"}):
        out = gs.get_graph("user_andres", semester="Spring 2026")

    concept_nodes = [n for n in out["nodes"] if not n.get("is_subject_root")]
    assert {n["course_id"] for n in concept_nodes} == {"bio-101"}
    assert out["stats"]["total_nodes"] == 1
    assert out["stats"]["mastered"] == 0
    # Only the Spring subject-root hub is built.
    roots = [n for n in out["nodes"] if n.get("is_subject_root")]
    assert {r["course_id"] for r in roots} == {"bio-101"}


def test_get_graph_no_semester_returns_all():
    enrolled = []
    nodes = [
        {"id": "n1", "course_id": "bio-101", "concept_name": "Cells",
         "mastery_score": 0.4, "mastery_tier": "learning", "times_studied": 1},
        {"id": "n2", "course_id": "psy-110", "concept_name": "Freud",
         "mastery_score": 0.9, "mastery_tier": "mastered", "times_studied": 2},
    ]

    def fake_table(name):
        from unittest.mock import MagicMock
        m = MagicMock(name=f"table({name})")
        m.select.return_value = {"graph_nodes": nodes, "graph_edges": [],
                                 "node_mastery_events": [], "users": []}.get(name, [])
        return m

    with patch.object(gs, "_user_enrolled_courses", return_value=enrolled), \
         patch.object(gs, "ensure_user_exists", return_value=None), \
         patch.object(gs, "table", side_effect=fake_table):
        out = gs.get_graph("user_andres")

    assert out["stats"]["total_nodes"] == 2


def test_get_recommendations_semester_builds_course_filter():
    """When scoped, the DB query carries a course_id in.(...) filter and limit 5."""
    captured = {}

    def fake_table(name):
        from unittest.mock import MagicMock
        m = MagicMock(name=f"table({name})")
        def _select(cols, filters=None, order=None, limit=None):
            captured["filters"] = filters
            captured["limit"] = limit
            return [{"concept_name": "Cells", "mastery_score": 0.2,
                     "mastery_tier": "struggling", "course_id": "bio-101"}]
        m.select.side_effect = _select
        return m

    with patch.object(gs, "table", side_effect=fake_table), \
         patch("services.academics.term_id_for_label", return_value="t-spring"), \
         patch("services.academics.user_course_ids_for_term", return_value={"bio-101"}):
        recs = gs.get_recommendations("user_andres", semester="Spring 2026")

    assert captured["filters"]["course_id"] == "in.(bio-101)"
    assert captured["limit"] == 5
    assert [r["concept_name"] for r in recs] == ["Cells"]


def test_get_recommendations_semester_empty_allowed_returns_empty():
    """Unresolved term / no enrollment → [] without querying graph_nodes."""
    def fake_table(name):
        from unittest.mock import MagicMock
        m = MagicMock(name=f"table({name})")
        m.select.side_effect = AssertionError("must not query when no courses in term")
        return m

    with patch.object(gs, "table", side_effect=fake_table), \
         patch("services.academics.term_id_for_label", return_value=None), \
         patch("services.academics.user_course_ids_for_term", return_value=set()):
        assert gs.get_recommendations("user_andres", semester="Nope 1999") == []


def test_add_course_rejects_course_taken_in_any_term():
    """A course the user already has in a *different* term can't be re-added."""
    def fake_table(name):
        from unittest.mock import MagicMock
        m = MagicMock(name=f"table({name})")
        m.select.return_value = [{"id": "bio-101"}] if name == "courses" else []
        m.insert.side_effect = AssertionError("must not insert a duplicate enrollment")
        return m

    with patch.object(gs, "table", side_effect=fake_table), \
         patch("services.academics.user_offering_ids_for_course", return_value=["off-old"]), \
         patch("services.academics.term_for_offering", return_value={"label": "Fall 2025"}):
        result = gs.add_course("user_andres", "bio-101")

    assert result["already_existed"] is True
    assert result["term"] == "Fall 2025"


def test_add_course_enrolls_when_never_taken():
    inserted = []

    def fake_table(name):
        from unittest.mock import MagicMock
        m = MagicMock(name=f"table({name})")
        m.select.return_value = [{"id": "bio-101"}] if name == "courses" else []
        def _insert(data):
            inserted.append((name, data))
            return [data]
        m.insert.side_effect = _insert
        return m

    with patch.object(gs, "table", side_effect=fake_table), \
         patch("services.academics.user_offering_ids_for_course", return_value=[]), \
         patch("services.academics.resolve_offering", return_value="off-new"), \
         patch("services.course_context_service.update_course_context", return_value=None):
        result = gs.add_course("user_andres", "bio-101")

    assert result["already_existed"] is False
    assert any(name == "enrollments" for name, _ in inserted)


def test_graph_route_passes_semester_through():
    from fastapi.testclient import TestClient
    import routes.graph as graph_route
    from main import app

    captured = {}

    async def fake_get_graph(user_id, semester=None):
        captured["user_id"] = user_id
        captured["semester"] = semester
        return {"nodes": [], "edges": [], "stats": {}}

    with patch.object(graph_route, "aget_graph", side_effect=fake_get_graph):
        client = TestClient(app)
        resp = client.get("/api/graph/user_andres?semester=Spring%202026")

    assert resp.status_code == 200
    assert captured == {"user_id": "user_andres", "semester": "Spring 2026"}


def test_add_course_enrolls_into_requested_term():
    """A term label picks THAT term's offering, not the date-derived current term.

    Regression: the Courses & Semesters hub adds while a semester tab is active;
    without threading the term through, every add landed in current_term and was
    filtered out of the tab the user was viewing.
    """
    from unittest.mock import MagicMock

    def fake_table(name):
        m = MagicMock(name=f"table({name})")
        m.select.return_value = [{"id": "bio-101"}] if name == "courses" else []
        m.insert.side_effect = lambda data: [data]
        return m

    captured = {}

    def fake_resolve(course_id, term_id=None, *, create=False):
        captured["term_id"] = term_id
        captured["create"] = create
        return "off-fall"

    with patch.object(gs, "table", side_effect=fake_table), \
         patch("services.academics.user_offering_ids_for_course", return_value=[]), \
         patch("services.academics.term_id_for_label", return_value="fall-2026"), \
         patch("services.academics.resolve_offering", side_effect=fake_resolve), \
         patch("services.course_context_service.update_course_context", return_value=None):
        result = gs.add_course("user_andres", "bio-101", term="Fall 2026")

    assert result["already_existed"] is False
    assert captured["term_id"] == "fall-2026"
    assert captured["create"] is True


def test_add_course_no_term_falls_back_to_current_term():
    """No term label → resolve_offering gets term_id=None (its current-term default)."""
    from unittest.mock import MagicMock

    def fake_table(name):
        m = MagicMock(name=f"table({name})")
        m.select.return_value = [{"id": "bio-101"}] if name == "courses" else []
        m.insert.side_effect = lambda data: [data]
        return m

    captured = {}

    def fake_resolve(course_id, term_id=None, *, create=False):
        captured["term_id"] = term_id
        return "off-current"

    with patch.object(gs, "table", side_effect=fake_table), \
         patch("services.academics.user_offering_ids_for_course", return_value=[]), \
         patch("services.academics.resolve_offering", side_effect=fake_resolve), \
         patch("services.course_context_service.update_course_context", return_value=None):
        result = gs.add_course("user_andres", "bio-101")

    assert result["already_existed"] is False
    assert captured["term_id"] is None


def test_create_course_route_passes_term_through():
    from fastapi.testclient import TestClient
    import routes.graph as graph_route
    from main import app

    captured = {}

    def fake_add_course(user_id, course_id, color=None, nickname=None, term=None):
        captured.update(user_id=user_id, course_id=course_id, term=term)
        return {"course_id": course_id, "already_existed": False}

    with patch.object(graph_route, "add_course", side_effect=fake_add_course), \
         patch.object(graph_route, "require_self", return_value=None):
        client = TestClient(app)
        resp = client.post(
            "/api/graph/user_andres/courses",
            json={"course_id": "bio-101", "term": "Fall 2026"},
        )

    assert resp.status_code == 200
    assert captured["term"] == "Fall 2026"


# ── DELETE /api/graph/{user_id}/courses/{course_id} (#766) ───────────────────

class TestRemoveCourseRoute:
    def _client(self):
        from fastapi.testclient import TestClient
        from main import app
        return TestClient(app)

    def test_forwards_term_query_param(self):
        with patch("routes.graph.delete_course", return_value={"deleted": True}) as dc:
            r = self._client().delete("/api/graph/u1/courses/cs101?term=Fall%202025")
        assert r.status_code == 200
        dc.assert_called_once_with("u1", "cs101", "Fall 2025")

    def test_error_is_a_404(self):
        with patch("routes.graph.delete_course",
                   return_value={"deleted": False, "error": "Unknown term: X"}):
            r = self._client().delete("/api/graph/u1/courses/cs101?term=X")
        assert r.status_code == 404


# ── async read twins (#117, docs/design/async-db-client.md §4.1 wave 1) ──────

def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


_PARITY_GRAPHS = {
    "empty": {"users": [{"streak_count": 5, "last_active_date": None}],
              "graph_nodes": [], "graph_edges": [], "enrollments": []},
    "full": {
        "users": [{"streak_count": 2,
                   "last_active_date": datetime.now(timezone.utc).date().isoformat()}],
        "enrollments": [
            _enrollment_row("c1", "CS101", "Intro CS", offering_id="off-1"),
            _enrollment_row("c1", "CS101", "Intro CS", offering_id="off-2"),
            _enrollment_row("c2", "MA", "Math", term="Fall 2025"),
        ],
        "graph_nodes": [
            {"id": "n1", "concept_name": "Loops", "mastery_tier": "learning",
             "mastery_score": 0.5, "course_id": "c1", "times_studied": 2, "user_id": "u1"},
            {"id": "n2", "concept_name": "Sets", "mastery_tier": "mastered",
             "mastery_score": 0.9, "course_id": "c2", "times_studied": 1, "user_id": "u1"},
        ],
        "graph_edges": [
            {"id": "e1", "source_node_id": "n1", "target_node_id": "n2", "strength": 0.4},
            {"id": "e2", "source_node_id": "n1", "target_node_id": "gone", "strength": 0.4},
        ],
        "node_mastery_events": [
            {"node_id": "n1", "delta": 0.2, "reason": "r", "created_at": _now_iso()},
        ],
    },
}


class TestAsyncReadTwins:
    """Each `a*` twin returns exactly what its sync sibling returns over the
    same rows (the routes' behaviour must not depend on which one ran)."""

    @staticmethod
    def _both(fn, afn, data, *args, extra_patches=()):
        import asyncio
        import copy
        from contextlib import ExitStack

        from tests.db_fakes import with_async_twins

        out = []
        for run in (lambda: fn(*args), lambda: asyncio.run(afn(*args))):
            factory, mocks = _cached_mock_table(copy.deepcopy(data))
            with ExitStack() as stack:
                stack.enter_context(patch(
                    "services.graph_service.table", side_effect=with_async_twins(factory)))
                for p in extra_patches:
                    stack.enter_context(p())
                out.append((run(), {n: m.method_calls for n, m in mocks.items()}))
        return out

    @pytest.mark.parametrize("scenario", sorted(_PARITY_GRAPHS))
    def test_aget_graph_matches_get_graph(self, scenario):
        (sync, _), (asynced, _) = self._both(
            gs.get_graph, gs.aget_graph, _PARITY_GRAPHS[scenario], "u1")
        assert asynced == sync

    def test_aget_graph_semester_scope_matches(self):
        patches = (
            lambda: patch("services.academics.term_id_for_label", return_value="t-fall"),
            lambda: patch("services.academics.user_course_ids_for_term", return_value={"c2"}),
        )
        (sync, _), (asynced, _) = self._both(
            gs.get_graph, gs.aget_graph, _PARITY_GRAPHS["full"], "u1", "Fall 2025",
            extra_patches=patches)
        assert asynced == sync
        assert {n["id"] for n in asynced["nodes"]} == {"n2", "subject_root__c2"}

    def test_aget_graph_inserts_a_missing_user_like_the_sync_one(self):
        data = {"users": [], "graph_nodes": [], "graph_edges": [], "enrollments": []}
        (_, sync_calls), (_, async_calls) = self._both(gs.get_graph, gs.aget_graph, data, "u1")
        inserts = [c for c in async_calls["users"] if c[0] == "insert"]
        assert inserts == [c for c in sync_calls["users"] if c[0] == "insert"]
        assert inserts and inserts[0].args[0] == {"id": "u1", "streak_count": 0}

    def test_aget_courses_matches_get_courses(self):
        data = {**_PARITY_GRAPHS["full"], "graph_nodes": [{"id": "n1"}, {"id": "n2"}]}
        (sync, _), (asynced, _) = self._both(gs.get_courses, gs.aget_courses, data, "u1")
        assert asynced == sync
        assert [c["course_id"] for c in asynced] == ["c1", "c2"]

    def test_aget_graph_runs_its_independent_reads_concurrently(self):
        """#117 review: the enrollments, nodes, edges and streak reads used to
        be awaited one after another. Each waits here until all four have
        started, so a sequential run never gets past the first."""
        import asyncio

        rows = _PARITY_GRAPHS["full"]

        async def go():
            barrier = asyncio.Barrier(4)

            def factory(name):
                mock = MagicMock()

                async def aselect(cols="*", filters=None, **_k):
                    if name == "users" and cols == "id":  # aensure_user_exists: first, alone
                        return [{"id": "u1"}]
                    if name in ("enrollments", "graph_nodes", "graph_edges", "users"):
                        await asyncio.wait_for(barrier.wait(), 2)
                    return rows.get(name, [])
                mock.aselect = AsyncMock(side_effect=aselect)
                return mock

            with patch("services.graph_service.table", side_effect=factory):
                return await gs.aget_graph("u1")

        graph = asyncio.run(go())
        assert {"n1", "n2"} <= {n["id"] for n in graph["nodes"]}

    def test_aget_courses_counts_concurrently_and_keeps_order(self):
        import asyncio

        enrollments = [_enrollment_row(f"c{i}", f"C{i}", f"Course {i}") for i in range(20)]
        live, peak = [0], [0]

        def factory(name):
            mock = MagicMock()

            async def aselect(cols="*", filters=None, **_k):
                if name == "enrollments":
                    return enrollments
                live[0] += 1
                peak[0] = max(peak[0], live[0])
                await asyncio.sleep(0.01)
                live[0] -= 1
                return [{"id": f"n{j}"} for j in range(int(filters["course_id"][len("eq.c"):]))]
            mock.aselect = AsyncMock(side_effect=aselect)
            return mock

        with patch("services.graph_service.table", side_effect=factory):
            courses = asyncio.run(gs.aget_courses("u1"))
        assert [c["course_id"] for c in courses] == [f"c{i}" for i in range(20)]
        assert [c["node_count"] for c in courses] == list(range(20))
        assert peak[0] == gs._COURSE_COUNT_CONCURRENCY

    def test_aget_courses_empty_on_enrollment_read_failure(self):
        import asyncio

        from tests.db_fakes import with_async_twins

        def factory(name):
            mock = MagicMock()
            mock.select.side_effect = Exception("DB error")
            return mock

        with patch("services.graph_service.table", side_effect=with_async_twins(factory)):
            assert asyncio.run(gs.aget_courses("u1")) == []

    @pytest.mark.parametrize("semester,allowed", [
        (None, None), ("Fall 2025", {"c1"}), ("Fall 2025", set()), ("Nope", None),
    ])
    def test_aget_recommendations_matches(self, semester, allowed):
        data = {"graph_nodes": [
            {"concept_name": "A", "mastery_score": 0.1, "mastery_tier": "struggling"},
            {"concept_name": "B", "mastery_score": 0.0, "mastery_tier": "unexplored"},
            {"concept_name": "C", "mastery_score": 0.6, "mastery_tier": "learning"},
        ]}
        term = None if semester == "Nope" else "t-fall"
        patches = (
            lambda: patch("services.academics.term_id_for_label", return_value=term),
            lambda: patch("services.academics.user_course_ids_for_term",
                          return_value=allowed or set()),
        )
        (sync, sync_calls), (asynced, async_calls) = self._both(
            gs.get_recommendations, gs.aget_recommendations, data, "u1", semester,
            extra_patches=patches)
        assert asynced == sync
        sync_reads = [c for c in sync_calls.get("graph_nodes", []) if c[0] == "select"]
        async_reads = [c for c in async_calls.get("graph_nodes", []) if c[0] == "select"]
        assert async_reads == sync_reads
        assert bool(sync) == (semester is None or bool(allowed))
