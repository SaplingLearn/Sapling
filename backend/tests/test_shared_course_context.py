"""
Unit tests for the shared course context system.

Tests: course_context_service (incl. course_summary agent), graph_service
       (apply_graph_update side-effects), learn.py topic/offering helpers.

(The legacy build_system_prompt tests were deleted with the template
pipeline in #151a. Their surviving contracts moved to the agent side:
academic integrity + injection guard per mode in
test_prompt_injection.py::TestAgentPromptHardening, peer-aggregate text
wrapped as untrusted in
test_prompt_injection.py::test_read_misconceptions_tool_neutralizes_peer_text,
and the use_shared_context opt-out constraint in
test_learn_routes.py::test_use_shared_context_false_appends_constraint.)

Run from backend/:
    python -m pytest tests/test_shared_course_context.py -v
"""
import sys
import os
import json
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch, MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# ─────────────────────────────────────────────────────────────────────────────
# 1. course_context_service — get_course_context
# ─────────────────────────────────────────────────────────────────────────────

class TestGetCourseContext(unittest.TestCase):

    def test_empty_course_name_returns_empty_dict(self):
        from services.course_context_service import get_course_context
        result = get_course_context("")
        self.assertEqual(result, {})

    @patch("services.course_context_service.table")
    def test_returns_context_json_when_found(self, mock_table):
        summary_row = {
            "offering_id": "off-1",
            "student_count": 5,
            "avg_class_mastery": 0.6,
            "top_struggling_concepts": ["Pointers"],
            "top_mastered_concepts": ["Variables"],
            "summary_text": "Good progress.",
            "updated_at": "2026-04-01T00:00:00+00:00",
        }
        stat_row = {
            "offering_id": "off-1",
            "concept_name": "Pointers",
            "avg_mastery_score": 0.2,
            "pct_struggling": 0.6,
            "pct_mastered": 0.1,
            "pct_unexplored": 0.3,
            "student_count": 5,
            "common_misconceptions": ["Dangling pointer"],
        }

        def _tbl(name):
            m = MagicMock()
            if name == "offering_summary":
                m.select.return_value = [summary_row]
            elif name == "offering_concept_stats":
                m.select.return_value = [stat_row]
            else:
                m.select.return_value = []
            return m
        mock_table.side_effect = _tbl

        from services.course_context_service import get_course_context
        result = get_course_context("off-1")
        self.assertIn("course_summary", result)
        self.assertIn("concept_stats", result)
        self.assertEqual(result["course_summary"]["offering_id"], "off-1")
        self.assertEqual(result["concept_stats"][0]["concept_name"], "Pointers")

    @patch("services.course_context_service.table")
    def test_returns_empty_dict_when_not_found(self, mock_table):
        mock_table.return_value.select.return_value = []

        from services.course_context_service import get_course_context
        result = get_course_context("CS101")
        self.assertEqual(result, {})

    @patch("services.course_context_service.table")
    def test_returns_empty_dict_on_exception(self, mock_table):
        mock_table.return_value.select.side_effect = RuntimeError("network error")

        from services.course_context_service import get_course_context
        result = get_course_context("CS101")
        self.assertEqual(result, {})


# ─────────────────────────────────────────────────────────────────────────────
# 2. course_context_service — update_course_context
# ─────────────────────────────────────────────────────────────────────────────

class TestUpdateCourseContext(unittest.TestCase):

    def test_no_op_for_empty_course_name(self):
        from services.course_context_service import update_course_context
        # Should return without error and without hitting DB
        with patch("services.course_context_service.table") as mock_table:
            update_course_context("")
            mock_table.assert_not_called()

    @patch("services.course_context_service.table")
    def test_no_op_when_no_nodes(self, mock_table):
        mock_table.return_value.select.return_value = []

        from services.course_context_service import update_course_context
        update_course_context("CS101")
        # upsert should never be called when there are no nodes
        mock_table.return_value.upsert.assert_not_called()

    @patch("services.academics.table")
    @patch("services.course_context_service.table")
    def test_aggregates_mastery_and_upserts(self, mock_table, mock_ac_table):
        # Two students enrolled in offering "off-1", same concept "Loops".
        node_rows = [
            {"id": "n1", "concept_name": "Loops", "mastery_score": 0.2,
             "mastery_tier": "struggling", "user_id": "u1"},
            {"id": "n2", "concept_name": "Loops", "mastery_score": 0.9,
             "mastery_tier": "mastered",   "user_id": "u2"},
        ]
        nodes_tbl = MagicMock()
        nodes_tbl.select.return_value = node_rows

        stats_tbl = MagicMock()
        summary_tbl = MagicMock()
        summary_tbl.select.return_value = []  # no existing summary

        _table, _ = self._table_factory([], nodes_tbl, stats_tbl, summary_tbl)
        mock_table.side_effect = _table
        mock_ac_table.side_effect = _table

        with patch("services.course_context_service._generate_summary_with_gemini", return_value="summary"):
            from services.course_context_service import update_course_context
            update_course_context("off-1")

        # offering_concept_stats should be upserted for "Loops"
        stats_tbl.upsert.assert_called_once()
        upsert_payload = stats_tbl.upsert.call_args[0][0]
        self.assertEqual(upsert_payload["offering_id"], "off-1")
        self.assertEqual(upsert_payload["concept_name"], "Loops")
        self.assertEqual(upsert_payload["student_count"], 2)
        # avg mastery for Loops = (0.2 + 0.9) / 2 = 0.55
        self.assertAlmostEqual(upsert_payload["avg_mastery_score"], 0.55, places=2)

    @patch("services.academics.table")
    @patch("services.course_context_service.table")
    def test_struggling_concepts_threshold(self, mock_table, mock_ac_table):
        """Concepts with pct_struggling > 0 should appear in top_struggling_concepts."""
        node_rows = [
            {"id": "n1", "concept_name": "Recursion", "mastery_score": 0.1,
             "mastery_tier": "struggling", "user_id": "u1"},
            {"id": "n2", "concept_name": "Recursion", "mastery_score": 0.15,
             "mastery_tier": "struggling", "user_id": "u2"},
            {"id": "n3", "concept_name": "Loops", "mastery_score": 0.8,
             "mastery_tier": "mastered", "user_id": "u1"},
        ]
        nodes_tbl = MagicMock()
        nodes_tbl.select.return_value = node_rows

        stats_tbl = MagicMock()
        summary_tbl = MagicMock()
        summary_tbl.select.return_value = []

        _table, _ = self._table_factory([], nodes_tbl, stats_tbl, summary_tbl)
        mock_table.side_effect = _table
        mock_ac_table.side_effect = _table

        with patch("services.course_context_service._generate_summary_with_gemini", return_value="summary"):
            from services.course_context_service import update_course_context
            update_course_context("off-1")

        # offering_summary upsert should have Recursion in top_struggling_concepts
        summary_tbl.upsert.assert_called_once()
        summary_payload = summary_tbl.upsert.call_args[0][0]
        self.assertIn("Recursion", summary_payload["top_struggling_concepts"])
        self.assertNotIn("Loops", summary_payload["top_struggling_concepts"])

    @patch("services.academics.table")
    @patch("services.course_context_service.table")
    def test_deduplicates_misconceptions_case_insensitive(self, mock_table, mock_ac_table):
        node_rows = [
            {"id": "n1", "concept_name": "Loops", "mastery_score": 0.3,
             "mastery_tier": "learning", "user_id": "u1"},
            {"id": "n2", "concept_name": "Loops", "mastery_score": 0.3,
             "mastery_tier": "learning", "user_id": "u2"},
        ]
        nodes_tbl = MagicMock()
        nodes_tbl.select.return_value = node_rows
        quiz_rows = [
            {"concept_node_id": "n1",
             "context_json": {"common_mistakes": ["Off-by-one error", "off-by-one error"], "weak_areas": []}},
            {"concept_node_id": "n2",
             "context_json": {"common_mistakes": ["OFF-BY-ONE ERROR"], "weak_areas": ["boundary conditions"]}},
        ]

        stats_tbl = MagicMock()
        summary_tbl = MagicMock()
        summary_tbl.select.return_value = []

        _table, _ = self._table_factory([], nodes_tbl, stats_tbl, summary_tbl, quiz_rows=quiz_rows)
        mock_table.side_effect = _table
        mock_ac_table.side_effect = _table

        with patch("services.course_context_service._generate_summary_with_gemini", return_value="summary"):
            from services.course_context_service import update_course_context
            update_course_context("off-1")

        # All three "off-by-one" variants are the same after .lower() — only one kept
        stats_tbl.upsert.assert_called_once()
        upsert_payload = stats_tbl.upsert.call_args[0][0]
        self.assertEqual(len(upsert_payload["common_misconceptions"]), 1)
        self.assertEqual(len(upsert_payload["prerequisite_gaps"]), 1)

    @patch("services.academics.table")
    @patch("services.course_context_service.table")
    def test_effective_explanations_never_emitted_even_when_source_has_it(
        self, mock_table, mock_ac_table
    ):
        """#572 — full rationale lives at the canonical comment in
        `_parse_quiz_context_to_arrays` (services/course_context_service.py).
        This plants the key on a source row to prove the read is really gone,
        not just untested; the `model_fields` assertion below additionally
        pins the premise that `QuizContext` never emits the key in the first
        place, so this test goes red (instead of quietly passing) if a future
        change ever adds the field without also adding the rollup half."""
        from agents.quiz_context import QuizContext
        self.assertNotIn("effective_explanations", QuizContext.model_fields)

        node_rows = [
            {"id": "n1", "concept_name": "Loops", "mastery_score": 0.3,
             "mastery_tier": "learning", "user_id": "u1"},
        ]
        nodes_tbl = MagicMock()
        nodes_tbl.select.return_value = node_rows
        quiz_rows = [
            {"concept_node_id": "n1",
             "context_json": {
                 "common_mistakes": ["Off-by-one error"],
                 "weak_areas": ["boundary conditions"],
                 "effective_explanations": ["A worked example with a number line"],
             }},
        ]

        stats_tbl = MagicMock()
        summary_tbl = MagicMock()
        summary_tbl.select.return_value = []

        _table, _ = self._table_factory([], nodes_tbl, stats_tbl, summary_tbl, quiz_rows=quiz_rows)
        mock_table.side_effect = _table
        mock_ac_table.side_effect = _table

        with patch("services.course_context_service._generate_summary_with_gemini", return_value="summary"):
            from services.course_context_service import update_course_context
            update_course_context("off-1")

        stats_tbl.upsert.assert_called_once()
        upsert_payload = stats_tbl.upsert.call_args[0][0]
        self.assertNotIn("effective_explanations", upsert_payload)
        # The legitimate siblings still come through unaffected.
        self.assertEqual(upsert_payload["common_misconceptions"], ["Off-by-one error"])
        self.assertEqual(upsert_payload["prerequisite_gaps"], ["boundary conditions"])

    # ── #72: the persisted Class Intel opt-out gates the WRITE path ──────────

    @staticmethod
    def _table_factory(settings_rows, nodes_tbl, stats_tbl, summary_tbl, quiz_rows=None):
        """Dispatch table() by name — shared across the update_course_context
        tests (the share_class_context ones plus any test that just needs the
        standard 2-student CS101/off-1 fixture around a custom graph_nodes /
        quiz_context payload)."""
        enrollment_rows = [{"user_id": "u1"}, {"user_id": "u2"}]
        course_rows = [{"course_code": "CS101", "course_name": "Intro CS"}]
        offering_rows = [{"course_id": "abstract-cs101"}]
        settings_tbl = MagicMock()
        settings_tbl.select.return_value = settings_rows

        def _table(name):
            m = MagicMock()
            if name == "enrollments":
                m.select.return_value = enrollment_rows
            elif name == "user_settings":
                return settings_tbl
            elif name == "course_offerings":
                m.select.return_value = offering_rows
            elif name == "courses":
                m.select.return_value = course_rows
            elif name == "graph_nodes":
                return nodes_tbl
            elif name == "quiz_context":
                m.select.return_value = quiz_rows or []
            elif name == "offering_concept_stats":
                return stats_tbl
            elif name == "offering_summary":
                return summary_tbl
            else:
                m.select.return_value = []
            return m

        return _table, settings_tbl

    @patch("services.academics.table")
    @patch("services.course_context_service.table")
    def test_opted_out_user_excluded_from_aggregation(self, mock_table, mock_ac_table):
        """A user whose user_settings.share_class_context is false must not
        contribute graph data to the class aggregates (#72)."""
        nodes_tbl = MagicMock()
        nodes_tbl.select.return_value = [
            {"id": "n1", "concept_name": "Loops", "mastery_score": 0.2,
             "mastery_tier": "struggling", "user_id": "u1"},
        ]
        stats_tbl = MagicMock()
        summary_tbl = MagicMock()
        summary_tbl.select.return_value = []

        _table, _ = self._table_factory(
            [{"user_id": "u2", "share_class_context": False}],
            nodes_tbl, stats_tbl, summary_tbl,
        )
        mock_table.side_effect = _table
        mock_ac_table.side_effect = _table

        with patch("services.course_context_service._generate_summary_with_gemini", return_value="summary"):
            from services.course_context_service import update_course_context
            update_course_context("off-1")

        # graph_nodes must be filtered to opted-in users only — u2's graph is
        # never queried.
        nodes_tbl.select.assert_called_once()
        node_filters = nodes_tbl.select.call_args.kwargs["filters"]
        self.assertEqual(node_filters["user_id"], "in.(u1)")
        # And the class summary counts only the opted-in student.
        summary_tbl.upsert.assert_called_once()
        self.assertEqual(summary_tbl.upsert.call_args[0][0]["student_count"], 1)

    @patch("services.academics.table")
    @patch("services.course_context_service.table")
    def test_missing_settings_row_defaults_to_opt_in(self, mock_table, mock_ac_table):
        """A user with NO user_settings row is opted in (matching the column
        default) — only an explicit false excludes them."""
        nodes_tbl = MagicMock()
        nodes_tbl.select.return_value = [
            {"id": "n1", "concept_name": "Loops", "mastery_score": 0.2,
             "mastery_tier": "struggling", "user_id": "u1"},
            {"id": "n2", "concept_name": "Loops", "mastery_score": 0.9,
             "mastery_tier": "mastered", "user_id": "u2"},
        ]
        stats_tbl = MagicMock()
        summary_tbl = MagicMock()
        summary_tbl.select.return_value = []

        # u1 has an explicit opt-in row; u2 has no settings row at all.
        _table, settings_tbl = self._table_factory(
            [{"user_id": "u1", "share_class_context": True}],
            nodes_tbl, stats_tbl, summary_tbl,
        )
        mock_table.side_effect = _table
        mock_ac_table.side_effect = _table

        with patch("services.course_context_service._generate_summary_with_gemini", return_value="summary"):
            from services.course_context_service import update_course_context
            update_course_context("off-1")

        # The settings lookup covers every enrolled user in one select…
        settings_tbl.select.assert_called_once()
        settings_filters = settings_tbl.select.call_args.kwargs["filters"]
        self.assertEqual(settings_filters["user_id"], "in.(u1,u2)")
        # …and both users are aggregated (u2 included despite no row).
        node_filters = nodes_tbl.select.call_args.kwargs["filters"]
        self.assertEqual(node_filters["user_id"], "in.(u1,u2)")
        summary_tbl.upsert.assert_called_once()
        self.assertEqual(summary_tbl.upsert.call_args[0][0]["student_count"], 2)

    @patch("services.academics.table")
    @patch("services.course_context_service.table")
    def test_all_opted_out_purges_aggregates_without_crash(self, mock_table, mock_ac_table):
        """When every enrolled student opted out, the refresh must not crash and
        must not publish anything — stale aggregates are purged instead so
        previously shared data stops being served."""
        nodes_tbl = MagicMock()
        stats_tbl = MagicMock()
        summary_tbl = MagicMock()
        summary_tbl.select.return_value = []

        _table, _ = self._table_factory(
            [{"user_id": "u1", "share_class_context": False},
             {"user_id": "u2", "share_class_context": False}],
            nodes_tbl, stats_tbl, summary_tbl,
        )
        mock_table.side_effect = _table
        mock_ac_table.side_effect = _table

        with patch("services.course_context_service._generate_summary_with_gemini", return_value="summary"):
            from services.course_context_service import update_course_context
            update_course_context("off-1")  # must not raise

        nodes_tbl.select.assert_not_called()
        stats_tbl.upsert.assert_not_called()
        summary_tbl.upsert.assert_not_called()
        stats_tbl.delete.assert_called_once_with({"offering_id": "eq.off-1"})
        summary_tbl.delete.assert_called_once_with({"offering_id": "eq.off-1"})


# ─────────────────────────────────────────────────────────────────────────────
# 3. graph_service — apply_graph_update side-effects on course context
# ─────────────────────────────────────────────────────────────────────────────

class TestApplyGraphUpdateTriggersContext(unittest.TestCase):

    @patch("services.academics.user_offering_ids_for_course", return_value=["off-1"])
    @patch("services.graph_service.table")
    @patch("services.course_context_service.update_course_context")
    def test_update_course_context_called_for_touched_subjects(
        self, mock_update_ctx, mock_table, mock_uoff
    ):
        # touched_courses holds the abstract course_id ("course-1"); the analytics
        # refresh resolves it to the user's offering(s) and refreshes each one.
        node_tbl = MagicMock()
        node_tbl.select.return_value = [
            {"id": "n1", "concept_name": "Loops", "mastery_score": 0.4,
             "times_studied": 2, "course_id": "course-1", "mastery_events": []}
        ]

        def _table(name):
            if name == "graph_nodes": return node_tbl
            return MagicMock()

        mock_table.side_effect = _table

        from services.graph_service import apply_graph_update
        apply_graph_update(
            "user1",
            {"updated_nodes": [{"concept_name": "Loops", "mastery_delta": 0.1}],
             "new_nodes": [],
             "new_edges": []}
        )

        mock_uoff.assert_called_once_with("user1", "course-1")
        mock_update_ctx.assert_called_once_with("off-1")

    @patch("services.academics.user_offering_ids_for_course", return_value=["off-1"])
    @patch("services.graph_service.table")
    @patch("services.course_context_service.update_course_context",
           side_effect=RuntimeError("DB down"))
    def test_update_course_context_exception_does_not_raise(
        self, mock_update_ctx, mock_table, mock_uoff
    ):
        """A failure in update_course_context must never surface to the caller."""
        node_tbl = MagicMock()
        node_tbl.select.return_value = [
            {"id": "n1", "concept_name": "Loops", "mastery_score": 0.4,
             "times_studied": 2, "course_id": "c1", "mastery_events": []}
        ]

        def _table(name):
            if name == "graph_nodes": return node_tbl
            return MagicMock()

        mock_table.side_effect = _table

        from services.graph_service import apply_graph_update
        try:
            apply_graph_update(
                "user1",
                {"updated_nodes": [{"concept_name": "Loops", "mastery_delta": 0.05}],
                 "new_nodes": [], "new_edges": []}
            )
        except RuntimeError:
            self.fail("apply_graph_update raised RuntimeError from update_course_context")

    @patch("services.graph_service.table")
    @patch("services.course_context_service.update_course_context")
    def test_no_context_call_for_node_without_course(self, mock_update_ctx, mock_table):
        """Nodes with no course_id should NOT trigger a context refresh."""
        node_tbl = MagicMock()
        node_tbl.select.return_value = [
            {"id": "n1", "concept_name": "GenericConcept", "mastery_score": 0.4,
             "times_studied": 0, "course_id": None, "mastery_events": []}
        ]

        def _table(name):
            if name == "graph_nodes": return node_tbl
            return MagicMock()

        mock_table.side_effect = _table

        from services.graph_service import apply_graph_update
        apply_graph_update(
            "user1",
            {"updated_nodes": [{"concept_name": "GenericConcept", "mastery_delta": 0.1}],
             "new_nodes": [], "new_edges": []}
        )
        mock_update_ctx.assert_not_called()


# ─────────────────────────────────────────────────────────────────────────────
# 4. learn.py — topic/offering resolution helpers
# ─────────────────────────────────────────────────────────────────────────────

class TestLearnHelpers(unittest.TestCase):

    @patch("routes.learn.table")
    def test_resolve_course_when_topic_matches_course_code(self, mock_table):
        # enrollments → course_offerings → courses; returns the ABSTRACT course_id.
        enrolled_tbl = MagicMock()
        enrolled_tbl.select.return_value = [
            {"offering_id": "off-1",
             "course_offerings": {"course_id": "course-1",
                                  "courses": {"course_code": "CS101", "course_name": "Intro CS"}}}
        ]
        node_tbl = MagicMock()
        node_tbl.select.return_value = []

        def _factory(name):
            if name == "enrollments": return enrolled_tbl
            return node_tbl

        mock_table.side_effect = _factory

        from routes.learn import _get_course_id_for_topic
        result = _get_course_id_for_topic("CS101", "user1")
        self.assertEqual(result, "course-1")

    @patch("routes.learn.table")
    def test_resolve_course_when_topic_is_concept(self, mock_table):
        enrolled_tbl = MagicMock()
        enrolled_tbl.select.return_value = []
        node_tbl = MagicMock()
        # First call (concept_name match) → found with course_id
        node_tbl.select.side_effect = [[{"course_id": "course-1"}], []]

        def _factory(name):
            if name == "enrollments": return enrolled_tbl
            return node_tbl

        mock_table.side_effect = _factory

        from routes.learn import _get_course_id_for_topic
        result = _get_course_id_for_topic("Loops", "user1")
        self.assertEqual(result, "course-1")

    @patch("routes.learn.table")
    def test_resolve_course_unknown_topic_returns_empty(self, mock_table):
        mock_table.return_value.select.return_value = []

        from routes.learn import _get_course_id_for_topic
        result = _get_course_id_for_topic("RandomTopic", "user1")
        self.assertEqual(result, "")

    def test_resolve_course_empty_topic_returns_empty(self):
        from routes.learn import _get_course_id_for_topic
        result = _get_course_id_for_topic("", "user1")
        self.assertEqual(result, "")

    @patch("routes.learn.table")
    def test_get_session_offering_id_found(self, mock_table):
        # Sessions key on the offering (0025); the helper returns it.
        mock_table.return_value.select.return_value = [{"offering_id": "off-1"}]

        from routes.learn import _get_session_offering_id
        result = _get_session_offering_id("session-abc")
        self.assertEqual(result, "off-1")

    @patch("routes.learn.table")
    def test_get_session_offering_id_not_found(self, mock_table):
        mock_table.return_value.select.return_value = []

        from routes.learn import _get_session_offering_id
        result = _get_session_offering_id("session-missing")
        self.assertEqual(result, "")


# ─────────────────────────────────────────────────────────────────────────────
# 5. quiz.py — generate_quiz prompt augmentation
# ─────────────────────────────────────────────────────────────────────────────


class TestCourseSummaryAgent(unittest.TestCase):
    """#145: _generate_summary_with_gemini runs the course_summary agent and
    degrades to a deterministic template string on agent failure."""

    def test_returns_agent_summary_on_success(self):
        from services import course_context_service as ccs
        run = AsyncMock(
            return_value=SimpleNamespace(
                output=SimpleNamespace(summary="Agent class summary.")
            )
        )
        with patch.object(ccs.course_summary_agent, "run", new=run):
            out = ccs._generate_summary_with_gemini(
                "CS101", "Intro", 0.6, ["Loops"], ["Vars"], 12,
            )
        self.assertEqual(out, "Agent class summary.")
        run.assert_called_once()

    def test_falls_back_to_template_on_agent_failure(self):
        from services import course_context_service as ccs
        run = AsyncMock(side_effect=RuntimeError("boom"))
        with patch.object(ccs.course_summary_agent, "run", new=run):
            out = ccs._generate_summary_with_gemini(
                "CS101", "Intro", 0.6, ["Loops"], ["Vars"], 12,
            )
        # Deterministic template fallback — no second LLM call.
        self.assertIn("Class average mastery", out)
        self.assertIn("Loops", out)


if __name__ == "__main__":
    import unittest
    unittest.main(verbosity=2)
