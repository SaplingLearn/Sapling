"""
Unit tests for services/graph_service.py

All Supabase calls are mocked so no live DB connection is needed.
"""
import pytest
from unittest.mock import MagicMock, patch

from services.graph_service import (
    get_graph,
    get_courses,
    add_course,
    delete_course,
    apply_graph_update,
    get_recommendations,
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


def _enrollment_row(course_id: str, code: str = "", name: str = "Course"):
    return {
        "id": f"e-{course_id}",
        "course_id": course_id,
        "color": None,
        "nickname": None,
        "enrolled_at": "2026-01-01",
        "courses": {"course_code": code, "course_name": name, "school": "", "department": ""},
    }


# ── get_graph ─────────────────────────────────────────────────────────────────

class TestGetGraph:
    def test_empty_graph_returns_zero_stats(self):
        factory = _mock_table({
            "users": [{"streak_count": 5}],
            "graph_nodes": [],
            "graph_edges": [],
            "user_courses": [],
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
            "user_courses": [_enrollment_row("c1", "M", "Math")],
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
        enrollment = [{"course_id": "c1", "courses": {"course_code": "CS101", "course_name": "Intro CS"}}]
        factory = _mock_table({
            "users": [{"streak_count": 0}],
            "user_courses": enrollment,
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
        enrollment = [
            {"course_id": "c1", "courses": {"course_code": "", "course_name": "EK 103: LINEAR ALGEBRA"}}
        ]
        factory = _mock_table({
            "users": [{"streak_count": 0}],
            "user_courses": enrollment,
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
        enrollment = [{"course_id": "c1", "courses": {"course_code": "", "course_name": "Philosophy"}}]
        factory = _mock_table({
            "users": [{"streak_count": 0}],
            "user_courses": enrollment,
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
            "user_courses": [_enrollment_row("c-x", "", "X")],
        })
        with patch("services.graph_service.table", side_effect=factory):
            result = get_graph("u1")

        graph_edges = [e for e in result["edges"] if not e["id"].startswith("subject_edge")]
        assert len(graph_edges) == 1
        assert graph_edges[0]["source"] == "n1"
        assert graph_edges[0]["strength"] == 0.9

    def test_streak_defaults_to_zero_when_no_user_row(self):
        factory = _mock_table({"users": [], "graph_nodes": [], "graph_edges": [], "user_courses": []})
        with patch("services.graph_service.table", side_effect=factory):
            result = get_graph("u1")
        assert result["stats"]["streak"] == 0


# ── get_courses ───────────────────────────────────────────────────────────────

class TestGetCourses:
    def test_returns_courses_with_node_count(self):
        def factory(name):
            mock = MagicMock()
            if name == "user_courses":
                mock.select.return_value = [{
                    "id": "e1", "course_id": "c1", "color": "#fff",
                    "nickname": None, "enrolled_at": "2026-01-01",
                    "courses": {"course_code": "MATH101", "course_name": "Math",
                                "school": "BU", "department": "Math"},
                }]
            elif name == "graph_nodes":
                mock.select.return_value = [{"id": "n1"}, {"id": "n2"}]
            else:
                mock.select.return_value = []
            return mock

        with patch("services.graph_service.table", side_effect=factory):
            result = get_courses("u1")

        assert len(result) == 1
        assert result[0]["course_name"] == "Math"
        assert result[0]["node_count"] == 2

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
        def factory(name):
            mock = MagicMock()
            if name == "user_courses":
                # First call: check existing enrollment → not found
                mock.select.return_value = []
            elif name == "courses":
                # Check canonical course exists → found
                mock.select.return_value = [{"id": "c1"}]
            else:
                mock.select.return_value = []
            mock.insert.return_value = []
            return mock

        with patch("services.graph_service.table", side_effect=factory):
            result = add_course("u1", "c1")

        assert result["course_id"] == "c1"
        assert result["already_existed"] is False

    def test_skips_insert_for_existing_course(self):
        mock = _simple_mock(select_returns=[{"id": "existing"}])
        with patch("services.graph_service.table", return_value=mock):
            result = add_course("u1", "c1")

        assert result["already_existed"] is True


# ── delete_course ─────────────────────────────────────────────────────────────

class TestDeleteCourse:
    def test_unenrolls_user_from_course(self):
        mock = MagicMock()
        mock.delete.return_value = []
        with patch("services.graph_service.table", return_value=mock):
            result = delete_course("u1", "course-id-1")

        assert result == {"deleted": True}
        mock.delete.assert_called_once()

    def test_unenroll_with_no_prior_nodes(self):
        mock = MagicMock()
        mock.delete.return_value = []
        with patch("services.graph_service.table", return_value=mock):
            result = delete_course("u1", "empty-course-id")
        assert result == {"deleted": True}


# ── apply_graph_update ────────────────────────────────────────────────────────

def _bulk_factory(existing_nodes=None, existing_edges=None):
    """Factory that returns a fresh mock per table; bulk-fetch returns the given rows."""
    nodes = list(existing_nodes or [])
    edges = list(existing_edges or [])
    mocks = {}

    def factory(name):
        if name not in mocks:
            m = MagicMock()
            if name == "graph_nodes":
                m.select.return_value = nodes
            elif name == "graph_edges":
                m.select.return_value = edges
            elif name == "users":
                m.select.return_value = [{"streak_count": 0, "last_active_date": None}]
            else:
                m.select.return_value = []
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
        mocks["graph_nodes"].insert.assert_called_once()
        inserted = mocks["graph_nodes"].insert.call_args[0][0]
        assert inserted["concept_name"] == "Recursion"
        assert inserted["mastery_score"] == 0.0
        assert inserted["mastery_tier"] == "unexplored"

    def test_skips_insert_for_existing_node_case_insensitive(self):
        existing = [
            {"id": "n1", "concept_name": "Linear Regression", "mastery_score": 0.3,
             "times_studied": 1, "course_id": "c1", "mastery_events": []}
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

        assert mocks["graph_nodes"].insert.call_count == 1

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

        mocks["graph_nodes"].insert.assert_not_called()

    def test_coerces_null_initial_mastery(self):
        factory, mocks = _bulk_factory(existing_nodes=[])
        graph_update = {
            "new_nodes": [{"concept_name": "X", "initial_mastery": None}],
            "updated_nodes": [],
            "new_edges": [],
        }
        with patch("services.graph_service.table", side_effect=factory):
            apply_graph_update("u1", graph_update, course_id="c1")

        inserted = mocks["graph_nodes"].insert.call_args[0][0]
        assert inserted["mastery_score"] == 0.0

    def test_clamps_initial_mastery_above_one(self):
        factory, mocks = _bulk_factory(existing_nodes=[])
        graph_update = {
            "new_nodes": [{"concept_name": "X", "initial_mastery": 5.0}],
            "updated_nodes": [],
            "new_edges": [],
        }
        with patch("services.graph_service.table", side_effect=factory):
            apply_graph_update("u1", graph_update, course_id="c1")

        inserted = mocks["graph_nodes"].insert.call_args[0][0]
        assert inserted["mastery_score"] == 1.0

    def test_updates_mastery_score(self):
        existing = [
            {"id": "n1", "concept_name": "Algebra", "mastery_score": 0.4,
             "times_studied": 2, "course_id": "c1", "mastery_events": []}
        ]
        factory, mocks = _bulk_factory(existing_nodes=existing)
        graph_update = {
            "new_nodes": [],
            "updated_nodes": [{"concept_name": "Algebra", "mastery_delta": 0.2}],
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

    def test_updates_existing_node_via_case_insensitive_name(self):
        existing = [
            {"id": "n1", "concept_name": "Linear Regression", "mastery_score": 0.3,
             "times_studied": 1, "course_id": "c1", "mastery_events": []}
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
             "times_studied": 5, "course_id": "c1", "mastery_events": []}
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
             "times_studied": 0, "course_id": "c1", "mastery_events": []}
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

    def test_does_not_add_duplicate_edge(self):
        existing_nodes = [
            {"id": "n1", "concept_name": "A", "mastery_score": 0.0,
             "times_studied": 0, "course_id": "c1", "mastery_events": []},
            {"id": "n2", "concept_name": "B", "mastery_score": 0.0,
             "times_studied": 0, "course_id": "c1", "mastery_events": []},
        ]
        factory, mocks = _bulk_factory(
            existing_nodes=existing_nodes,
            existing_edges=[{"id": "e1"}],
        )
        graph_update = {
            "new_nodes": [],
            "updated_nodes": [],
            "new_edges": [{"source": "A", "target": "B", "strength": 0.7}],
        }
        with patch("services.graph_service.table", side_effect=factory):
            apply_graph_update("u1", graph_update, course_id="c1")

        mocks["graph_edges"].insert.assert_not_called()

    def test_skips_self_edges(self):
        existing_nodes = [
            {"id": "n1", "concept_name": "A", "mastery_score": 0.0,
             "times_studied": 0, "course_id": "c1", "mastery_events": []},
        ]
        factory, mocks = _bulk_factory(existing_nodes=existing_nodes)
        graph_update = {
            "new_nodes": [],
            "updated_nodes": [],
            "new_edges": [{"source": "A", "target": "a", "strength": 0.7}],
        }
        with patch("services.graph_service.table", side_effect=factory):
            apply_graph_update("u1", graph_update, course_id="c1")

        mocks["graph_edges"].insert.assert_not_called()


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
