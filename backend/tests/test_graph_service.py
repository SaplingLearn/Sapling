"""
Unit tests for services/graph_service.py

All Supabase calls are mocked so no live DB connection is needed.
"""
from datetime import datetime, timedelta, timezone

import pytest
from unittest.mock import MagicMock, patch

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
        factory = _mock_table({
            "users": [{"streak_count": 5}],
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
    def test_unenrolls_user_from_course(self):
        # The user has one offering of the abstract course → delete that enrollment.
        factory, mocks = _cached_mock_table({
            "course_offerings": [{"id": "off-1"}],
            "enrollments": [{"offering_id": "off-1"}],
        })
        with patch("services.graph_service.table", side_effect=factory), \
             patch("services.academics.table", side_effect=factory), \
             patch("services.course_context_service.update_course_context"):
            result = delete_course("u1", "course-id-1")

        assert result == {"deleted": True}
        mocks["enrollments"].delete.assert_called_once()

    def test_unenroll_with_no_prior_nodes(self):
        # No offerings for the course → nothing to delete, still succeeds.
        factory, _ = _cached_mock_table({"course_offerings": [], "enrollments": []})
        with patch("services.graph_service.table", side_effect=factory), \
             patch("services.academics.table", side_effect=factory):
            result = delete_course("u1", "empty-course-id")
        assert result == {"deleted": True}


# ── apply_graph_update ────────────────────────────────────────────────────────

def _bulk_factory(existing_nodes=None, existing_edges=None):
    """Factory that returns a fresh mock per table; bulk-fetch returns the given rows.

    ``graph_nodes.upsert`` echoes back the inserted payload (PostgREST
    ``return=representation``) so apply_graph_update can read the canonical node
    id from the response, matching live Supabase behaviour.
    """
    nodes = list(existing_nodes or [])
    edges = list(existing_edges or [])
    mocks = {}

    def factory(name):
        if name not in mocks:
            m = MagicMock()
            if name == "graph_nodes":
                m.select.return_value = nodes
                m.upsert.side_effect = lambda data, **kw: [data] if isinstance(data, dict) else list(data)
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
        # Scalar columns updated; the dropped JSON blob is no longer written.
        update_payload = mocks["graph_nodes"].update.call_args[0][0]
        assert update_payload["mastery_score"] == pytest.approx(0.6)
        assert "mastery_events" not in update_payload

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
        # Schema has no event_type column.
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

    def fake_get_graph(user_id, semester=None):
        captured["user_id"] = user_id
        captured["semester"] = semester
        return {"nodes": [], "edges": [], "stats": {}}

    with patch.object(graph_route, "get_graph", side_effect=fake_get_graph):
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
