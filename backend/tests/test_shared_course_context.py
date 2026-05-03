"""
Unit tests for the shared course context system.

Tests: course_context_service, graph_service (apply_graph_update side-effects),
       learn.py (build_system_prompt), quiz.py (generate_quiz prompt augmentation).

Run from backend/:
    python -m pytest tests/test_shared_course_context.py -v
"""
import sys
import os
import json
import unittest
from unittest.mock import patch, MagicMock, call

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _make_table_mock(return_map: dict):
    """Return a mock for `table(name)` that dispatches by table name."""
    def _table(name):
        m = MagicMock()
        rows = return_map.get(name, [])
        m.select.return_value = rows
        m.upsert.return_value = None
        m.insert.return_value = None
        m.update.return_value = None
        m.delete.return_value = None
        return m
    return _table


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
            "course_id": "CS101",
            "semester": "Spring 2026",
            "student_count": 5,
            "avg_class_mastery": 0.6,
            "top_struggling_concepts": ["Pointers"],
            "top_mastered_concepts": ["Variables"],
            "summary_text": "Good progress.",
            "updated_at": "2026-04-01T00:00:00+00:00",
        }
        stat_row = {
            "course_id": "CS101",
            "concept_name": "Pointers",
            "semester": "Spring 2026",
            "avg_mastery_score": 0.2,
            "pct_struggling": 0.6,
            "pct_mastered": 0.1,
            "pct_unexplored": 0.3,
            "student_count": 5,
            "common_misconceptions": ["Dangling pointer"],
        }

        def _tbl(name):
            m = MagicMock()
            if name == "course_summary":
                m.select.return_value = [summary_row]
            elif name == "course_concept_stats":
                m.select.return_value = [stat_row]
            else:
                m.select.return_value = []
            return m
        mock_table.side_effect = _tbl

        from services.course_context_service import get_course_context
        result = get_course_context("CS101")
        self.assertIn("course_summary", result)
        self.assertIn("concept_stats", result)
        self.assertEqual(result["course_summary"]["course_id"], "CS101")
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

    @patch("services.course_context_service.table")
    def test_aggregates_mastery_and_upserts(self, mock_table):
        # Two students enrolled, same concept "Loops" — one struggling, one mastered
        enrollment_rows = [{"user_id": "u1"}, {"user_id": "u2"}]
        course_rows = [{"course_code": "CS101", "course_name": "Intro CS"}]
        node_rows = [
            {"id": "n1", "concept_name": "Loops", "mastery_score": 0.2,
             "mastery_tier": "struggling", "user_id": "u1"},
            {"id": "n2", "concept_name": "Loops", "mastery_score": 0.9,
             "mastery_tier": "mastered",   "user_id": "u2"},
        ]

        stats_tbl = MagicMock()
        stats_tbl.upsert.return_value = None

        summary_tbl = MagicMock()
        summary_tbl.select.return_value = []  # no existing summary
        summary_tbl.upsert.return_value = None

        def _table(name):
            m = MagicMock()
            if name == "user_courses":
                m.select.return_value = enrollment_rows
            elif name == "courses":
                m.select.return_value = course_rows
            elif name == "graph_nodes":
                m.select.return_value = node_rows
            elif name == "quiz_context":
                m.select.return_value = []
            elif name == "course_concept_stats":
                return stats_tbl
            elif name == "course_summary":
                return summary_tbl
            else:
                m.select.return_value = []
            return m

        mock_table.side_effect = _table

        with patch("services.course_context_service._generate_summary_with_gemini", return_value="summary"):
            from services.course_context_service import update_course_context
            update_course_context("c-cs101")

        # course_concept_stats should be upserted for "Loops"
        stats_tbl.upsert.assert_called_once()
        upsert_payload = stats_tbl.upsert.call_args[0][0]
        self.assertEqual(upsert_payload["course_id"], "c-cs101")
        self.assertEqual(upsert_payload["concept_name"], "Loops")
        self.assertEqual(upsert_payload["student_count"], 2)
        # avg mastery for Loops = (0.2 + 0.9) / 2 = 0.55
        self.assertAlmostEqual(upsert_payload["avg_mastery_score"], 0.55, places=2)

    @patch("services.course_context_service.table")
    def test_struggling_concepts_threshold(self, mock_table):
        """Concepts with pct_struggling > 0 should appear in top_struggling_concepts."""
        enrollment_rows = [{"user_id": "u1"}, {"user_id": "u2"}]
        course_rows = [{"course_code": "CS101", "course_name": "Intro CS"}]
        node_rows = [
            {"id": "n1", "concept_name": "Recursion", "mastery_score": 0.1,
             "mastery_tier": "struggling", "user_id": "u1"},
            {"id": "n2", "concept_name": "Recursion", "mastery_score": 0.15,
             "mastery_tier": "struggling", "user_id": "u2"},
            {"id": "n3", "concept_name": "Loops", "mastery_score": 0.8,
             "mastery_tier": "mastered", "user_id": "u1"},
        ]

        stats_tbl = MagicMock()
        summary_tbl = MagicMock()
        summary_tbl.select.return_value = []

        def _table(name):
            m = MagicMock()
            if name == "user_courses":
                m.select.return_value = enrollment_rows
            elif name == "courses":
                m.select.return_value = course_rows
            elif name == "graph_nodes":
                m.select.return_value = node_rows
            elif name == "quiz_context":
                m.select.return_value = []
            elif name == "course_concept_stats":
                return stats_tbl
            elif name == "course_summary":
                return summary_tbl
            else:
                m.select.return_value = []
            return m

        mock_table.side_effect = _table

        with patch("services.course_context_service._generate_summary_with_gemini", return_value="summary"):
            from services.course_context_service import update_course_context
            update_course_context("c-cs101")

        # course_summary upsert should have Recursion in top_struggling_concepts
        summary_tbl.upsert.assert_called_once()
        summary_payload = summary_tbl.upsert.call_args[0][0]
        self.assertIn("Recursion", summary_payload["top_struggling_concepts"])
        self.assertNotIn("Loops", summary_payload["top_struggling_concepts"])

    @patch("services.course_context_service.table")
    def test_deduplicates_misconceptions_case_insensitive(self, mock_table):
        enrollment_rows = [{"user_id": "u1"}, {"user_id": "u2"}]
        course_rows = [{"course_code": "CS101", "course_name": "Intro CS"}]
        node_rows = [
            {"id": "n1", "concept_name": "Loops", "mastery_score": 0.3,
             "mastery_tier": "learning", "user_id": "u1"},
            {"id": "n2", "concept_name": "Loops", "mastery_score": 0.3,
             "mastery_tier": "learning", "user_id": "u2"},
        ]
        quiz_rows = [
            {"concept_node_id": "n1",
             "context_json": {"common_mistakes": ["Off-by-one error", "off-by-one error"], "weak_areas": []}},
            {"concept_node_id": "n2",
             "context_json": {"common_mistakes": ["OFF-BY-ONE ERROR"], "weak_areas": ["boundary conditions"]}},
        ]

        stats_tbl = MagicMock()
        summary_tbl = MagicMock()
        summary_tbl.select.return_value = []

        def _table(name):
            m = MagicMock()
            if name == "user_courses":
                m.select.return_value = enrollment_rows
            elif name == "courses":
                m.select.return_value = course_rows
            elif name == "graph_nodes":
                m.select.return_value = node_rows
            elif name == "quiz_context":
                m.select.return_value = quiz_rows
            elif name == "course_concept_stats":
                return stats_tbl
            elif name == "course_summary":
                return summary_tbl
            else:
                m.select.return_value = []
            return m

        mock_table.side_effect = _table

        with patch("services.course_context_service._generate_summary_with_gemini", return_value="summary"):
            from services.course_context_service import update_course_context
            update_course_context("c-cs101")

        # All three "off-by-one" variants are the same after .lower() — only one kept
        stats_tbl.upsert.assert_called_once()
        upsert_payload = stats_tbl.upsert.call_args[0][0]
        self.assertEqual(len(upsert_payload["common_misconceptions"]), 1)
        self.assertEqual(len(upsert_payload["prerequisite_gaps"]), 1)


# ─────────────────────────────────────────────────────────────────────────────
# 3. graph_service — apply_graph_update side-effects on course context
# ─────────────────────────────────────────────────────────────────────────────

class TestApplyGraphUpdateTriggersContext(unittest.TestCase):

    @patch("services.graph_service.table")
    @patch("services.course_context_service.update_course_context")
    def test_update_course_context_called_for_touched_subjects(
        self, mock_update_ctx, mock_table
    ):
        # update_course_context is lazy-imported inside apply_graph_update;
        # patch it at the source module so the import resolves to our mock.
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

        mock_update_ctx.assert_called_once_with("course-1")

    @patch("services.graph_service.table")
    @patch("services.course_context_service.update_course_context",
           side_effect=RuntimeError("DB down"))
    def test_update_course_context_exception_does_not_raise(
        self, mock_update_ctx, mock_table
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
# 4. learn.py — build_system_prompt
# ─────────────────────────────────────────────────────────────────────────────

class TestLearnHelpers(unittest.TestCase):

    @patch("routes.learn.table")
    def test_resolve_course_when_topic_matches_course_code(self, mock_table):
        enrolled_tbl = MagicMock()
        enrolled_tbl.select.return_value = [
            {"course_id": "course-1", "courses": {"course_code": "CS101", "course_name": "Intro CS"}}
        ]
        node_tbl = MagicMock()
        node_tbl.select.return_value = []

        def _factory(name):
            if name == "user_courses": return enrolled_tbl
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
            if name == "user_courses": return enrolled_tbl
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
    def test_get_session_course_id_found(self, mock_table):
        mock_table.return_value.select.return_value = [{"course_id": "course-1"}]

        from routes.learn import _get_session_course_id
        result = _get_session_course_id("session-abc")
        self.assertEqual(result, "course-1")

    @patch("routes.learn.table")
    def test_get_session_course_id_not_found(self, mock_table):
        mock_table.return_value.select.return_value = []

        from routes.learn import _get_session_course_id
        result = _get_session_course_id("session-missing")
        self.assertEqual(result, "")

    @patch("services.course_context_service.get_course_context", return_value={})
    def test_build_system_prompt_no_course_id(self, mock_ctx):
        from routes.learn import build_system_prompt
        prompt = build_system_prompt("socratic", "Alice", "{}")
        self.assertNotIn("COURSE INTELLIGENCE", prompt)
        mock_ctx.assert_not_called()

    @patch("routes.learn.table")
    @patch("services.course_context_service.get_course_context", return_value={})
    def test_build_system_prompt_course_id_but_empty_ctx(self, mock_ctx, mock_table):
        mock_table.return_value.select.return_value = []
        from routes.learn import build_system_prompt
        prompt = build_system_prompt("socratic", "Alice", "{}", course_id="course-1")
        self.assertNotIn("COURSE INTELLIGENCE", prompt)
        mock_ctx.assert_called_once_with("course-1")

    @patch("routes.learn.table")
    @patch("services.course_context_service.get_course_context")
    def test_build_system_prompt_injects_shared_block(self, mock_ctx, mock_table):
        mock_ctx.return_value = {
            "course_summary": {"avg_class_mastery": 0.6, "top_struggling_concepts": ["Pointers"]},
            "concept_stats": [],
        }
        mock_table.return_value.select.return_value = [
            {"course_code": "CS101", "course_name": "Intro CS"}
        ]

        from routes.learn import build_system_prompt
        prompt = build_system_prompt("socratic", "Alice", "{}", course_id="course-1")
        self.assertIn("COURSE INTELLIGENCE", prompt)
        self.assertIn("CS101", prompt)
        mock_ctx.assert_called_once_with("course-1")

    @patch("routes.learn.table")
    @patch("services.course_context_service.get_course_context")
    def test_build_system_prompt_mode_appended_after_shared_block(self, mock_ctx, mock_table):
        """Mode prompt must always be the last section."""
        mock_ctx.return_value = {
            "course_summary": {"avg_class_mastery": 0.5, "top_struggling_concepts": []},
            "concept_stats": [],
        }
        mock_table.return_value.select.return_value = [
            {"course_code": "CS101", "course_name": "Intro CS"}
        ]

        from routes.learn import build_system_prompt, MODE_PROMPTS
        prompt = build_system_prompt("expository", "Bob", "{}", course_id="course-1")
        expository_text = MODE_PROMPTS["expository"]
        ctx_pos = prompt.find("COURSE INTELLIGENCE")
        mode_pos = prompt.find(expository_text[:40])
        self.assertGreater(mode_pos, ctx_pos)


# ─────────────────────────────────────────────────────────────────────────────
# 5. quiz.py — generate_quiz prompt augmentation
# ─────────────────────────────────────────────────────────────────────────────

class TestQuizPromptAugmentation(unittest.TestCase):

    def _make_generate_body(self):
        from models import GenerateQuizBody
        return GenerateQuizBody(
            user_id="user1",
            concept_node_id="node-abc",
            difficulty="medium",
            num_questions=3,
        )

    # get_course_context is lazily imported inside generate_quiz;
    # patch at the source module so the `from ... import` resolves to our mock.
    @patch("services.course_context_service.get_course_context")
    @patch("routes.quiz.call_gemini_json")
    @patch("routes.quiz.get_quiz_context", return_value=None)
    @patch("routes.quiz.get_graph")
    @patch("routes.quiz.table")
    def test_misconceptions_appended_to_prompt(
        self, mock_table, mock_graph, mock_quiz_ctx, mock_gemini, mock_ctx
    ):
        mock_table.return_value.select.return_value = [{
            "id": "node-abc", "concept_name": "Pointers",
            "mastery_score": 0.3, "course_id": "c1",
        }]
        mock_table.return_value.insert.return_value = None
        mock_graph.return_value = {"nodes": [], "edges": []}
        mock_ctx.return_value = {
            "course_summary": {"avg_class_mastery": 0.4},
            "concept_stats": [
                {
                    "concept_name": "Pointers",
                    "common_misconceptions": ["Dangling pointers", "Memory leaks"],
                    "prerequisite_gaps": ["Pointer arithmetic"],
                }
            ],
        }
        mock_gemini.return_value = {"questions": []}

        from routes.quiz import generate_quiz
        generate_quiz(self._make_generate_body(), MagicMock())

        actual_prompt = mock_gemini.call_args[0][0]
        self.assertIn("Dangling pointers", actual_prompt)
        self.assertIn("Memory leaks", actual_prompt)
        self.assertIn("Pointer arithmetic", actual_prompt)

    @patch("services.course_context_service.get_course_context", return_value={})
    @patch("routes.quiz.call_gemini_json")
    @patch("routes.quiz.get_quiz_context", return_value=None)
    @patch("routes.quiz.get_graph")
    @patch("routes.quiz.table")
    def test_no_augmentation_when_ctx_empty(
        self, mock_table, mock_graph, mock_quiz_ctx, mock_gemini, mock_ctx
    ):
        mock_table.return_value.select.return_value = [{
            "id": "node-abc", "concept_name": "Loops",
            "mastery_score": 0.5, "course_id": "c1",
        }]
        mock_table.return_value.insert.return_value = None
        mock_graph.return_value = {"nodes": [], "edges": []}
        mock_gemini.return_value = {"questions": []}

        from routes.quiz import generate_quiz
        generate_quiz(self._make_generate_body(), MagicMock())

        actual_prompt = mock_gemini.call_args[0][0]
        self.assertNotIn("Common misconceptions seen across the class", actual_prompt)

    @patch("services.course_context_service.get_course_context")
    @patch("routes.quiz.call_gemini_json")
    @patch("routes.quiz.get_quiz_context", return_value=None)
    @patch("routes.quiz.get_graph")
    @patch("routes.quiz.table")
    def test_augmentation_capped_at_10_items(
        self, mock_table, mock_graph, mock_quiz_ctx, mock_gemini, mock_ctx
    ):
        mock_table.return_value.select.return_value = [{
            "id": "node-abc", "concept_name": "Pointers",
            "mastery_score": 0.3, "course_id": "c1",
        }]
        mock_table.return_value.insert.return_value = None
        mock_graph.return_value = {"nodes": [], "edges": []}
        mock_ctx.return_value = {
            "course_summary": {"avg_class_mastery": 0.4},
            "concept_stats": [
                {
                    "concept_name": "Pointers",
                    "common_misconceptions": [f"mistake_{i}" for i in range(20)],
                    "prerequisite_gaps": [],
                }
            ],
        }
        mock_gemini.return_value = {"questions": []}

        from routes.quiz import generate_quiz
        generate_quiz(self._make_generate_body(), MagicMock())

        actual_prompt = mock_gemini.call_args[0][0]
        self.assertIn("mistake_9", actual_prompt)
        self.assertNotIn("mistake_10", actual_prompt)

    @patch("routes.quiz.call_gemini_json")
    @patch("routes.quiz.get_quiz_context", return_value=None)
    @patch("routes.quiz.get_graph")
    @patch("routes.quiz.table")
    def test_no_augmentation_when_node_has_no_course_id(
        self, mock_table, mock_graph, mock_quiz_ctx, mock_gemini
    ):
        mock_table.return_value.select.return_value = [{
            "id": "node-abc", "concept_name": "GenericConcept",
            "mastery_score": 0.5, "course_id": "",
        }]
        mock_table.return_value.insert.return_value = None
        mock_graph.return_value = {"nodes": [], "edges": []}
        mock_gemini.return_value = {"questions": []}

        with patch("services.course_context_service.get_course_context") as mock_ctx:
            from routes.quiz import generate_quiz
            generate_quiz(self._make_generate_body(), MagicMock())
            mock_ctx.assert_not_called()


if __name__ == "__main__":
    import unittest
    unittest.main(verbosity=2)
