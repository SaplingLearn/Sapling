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
    def test_returns_summary_and_stats_when_found(self, mock_table):
        summary_row = {
            "course_id": "c1",
            "semester": "Spring 2026",
            "student_count": 3,
            "avg_class_mastery": 0.5,
            "top_struggling_concepts": [],
            "top_mastered_concepts": [],
            "summary_text": "ok",
            "updated_at": "2026-01-01T00:00:00Z",
        }
        stats_rows = [{"course_id": "c1", "concept_name": "Loops"}]

        def _table(name):
            m = MagicMock()
            if name == "course_summary":
                m.select.return_value = [summary_row]
            elif name == "course_concept_stats":
                m.select.return_value = stats_rows
            return m

        mock_table.side_effect = _table

        from services.course_context_service import get_course_context
        result = get_course_context("c1")
        self.assertIn("course_summary", result)
        self.assertEqual(result["concept_stats"], stats_rows)

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
    def test_no_op_when_no_enrollment(self, mock_table):
        uc = MagicMock()
        uc.select.return_value = []

        def _table(name):
            if name == "user_courses":
                return uc
            return MagicMock()

        mock_table.side_effect = _table

        from services.course_context_service import update_course_context
        update_course_context("c1")
        uc.select.assert_called()


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
            {
                "id": "n1",
                "mastery_score": 0.4,
                "times_studied": 2,
                "course_id": "course-cs101",
                "subject": "CS101",
            }
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

        mock_update_ctx.assert_called_once_with("course-cs101")

    @patch("services.graph_service.table")
    @patch("services.course_context_service.update_course_context",
           side_effect=RuntimeError("DB down"))
    def test_update_course_context_exception_does_not_raise(
        self, mock_update_ctx, mock_table
    ):
        """A failure in update_course_context must never surface to the caller."""
        node_tbl = MagicMock()
        node_tbl.select.return_value = [
            {"id": "n1", "mastery_score": 0.4, "times_studied": 2, "course_id": "c1", "subject": "CS101"}
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
    def test_no_context_call_for_general_subject(self, mock_update_ctx, mock_table):
        """Nodes with subject='General' should NOT trigger a context refresh."""
        node_tbl = MagicMock()
        node_tbl.select.return_value = [
            {"id": "n1", "mastery_score": 0.4, "times_studied": 0, "subject": "General"}
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

    @patch("services.course_context_service.get_course_context", return_value={})
    def test_build_system_prompt_no_course_id(self, mock_ctx):
        from routes.learn import build_system_prompt
        prompt = build_system_prompt("socratic", "Alice", "{}")
        self.assertNotIn("COURSE INTELLIGENCE", prompt)
        mock_ctx.assert_not_called()

    @patch("services.course_context_service.get_course_context", return_value={})
    def test_build_system_prompt_course_id_but_empty_ctx(self, mock_ctx):
        from routes.learn import build_system_prompt
        prompt = build_system_prompt("socratic", "Alice", "{}", course_id="c1")
        self.assertNotIn("COURSE INTELLIGENCE", prompt)
        mock_ctx.assert_called_once_with("c1")

    @patch("routes.learn._get_course_info", return_value={"course_code": "CS", "course_name": "101"})
    @patch("services.course_context_service.get_course_context")
    def test_build_system_prompt_injects_shared_block(self, mock_ctx, _mock_info):
        mock_ctx.return_value = {
            "course_summary": {"student_count": 10},
            "concept_stats": [],
        }

        from routes.learn import build_system_prompt
        prompt = build_system_prompt("socratic", "Alice", "{}", course_id="c1")
        self.assertIn("COURSE INTELLIGENCE", prompt)
        self.assertIn("CS", prompt)
        mock_ctx.assert_called_once_with("c1")

    @patch("routes.learn._get_course_info", return_value={"course_code": "", "course_name": "OnlyName"})
    @patch("services.course_context_service.get_course_context")
    def test_build_system_prompt_mode_appended_after_shared_block(self, mock_ctx, _mock_info):
        """Mode prompt must always be the last section."""
        mock_ctx.return_value = {"course_summary": {"student_count": 5}, "concept_stats": []}

        from routes.learn import build_system_prompt, MODE_PROMPTS
        prompt = build_system_prompt("expository", "Bob", "{}", course_id="c1")
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
            "mastery_score": 0.3, "subject": "CS101", "course_id": "c1",
        }]
        mock_table.return_value.insert.return_value = None
        mock_graph.return_value = {"nodes": [], "edges": []}
        mock_ctx.return_value = {
            "concept_stats": [{
                "common_misconceptions": ["Dangling pointers", "Memory leaks"],
                "prerequisite_gaps": ["Pointer arithmetic"],
            }],
        }
        mock_gemini.return_value = {"questions": []}

        from routes.quiz import generate_quiz
        generate_quiz(self._make_generate_body())

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
            "mastery_score": 0.5, "subject": "CS101", "course_id": "c1",
        }]
        mock_table.return_value.insert.return_value = None
        mock_graph.return_value = {"nodes": [], "edges": []}
        mock_gemini.return_value = {"questions": []}

        from routes.quiz import generate_quiz
        generate_quiz(self._make_generate_body())

        actual_prompt = mock_gemini.call_args[0][0]
        # The base quiz_generation.txt mentions "misconceptions" in its rules;
        # assert the course-level addendum header is NOT present when ctx is empty.
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
            "mastery_score": 0.3, "subject": "CS101", "course_id": "c1",
        }]
        mock_table.return_value.insert.return_value = None
        mock_graph.return_value = {"nodes": [], "edges": []}
        mock_ctx.return_value = {
            "concept_stats": [{
                "common_misconceptions": [f"mistake_{i}" for i in range(20)],
                "prerequisite_gaps": [],
            }],
        }
        mock_gemini.return_value = {"questions": []}

        from routes.quiz import generate_quiz
        generate_quiz(self._make_generate_body())

        actual_prompt = mock_gemini.call_args[0][0]
        self.assertIn("mistake_9", actual_prompt)
        self.assertNotIn("mistake_10", actual_prompt)

    @patch("routes.quiz.call_gemini_json")
    @patch("routes.quiz.get_quiz_context", return_value=None)
    @patch("routes.quiz.get_graph")
    @patch("routes.quiz.table")
    def test_no_augmentation_when_node_has_no_subject(
        self, mock_table, mock_graph, mock_quiz_ctx, mock_gemini
    ):
        mock_table.return_value.select.return_value = [{
            "id": "node-abc", "concept_name": "GenericConcept",
            "mastery_score": 0.5, "subject": "",
        }]
        mock_table.return_value.insert.return_value = None
        mock_graph.return_value = {"nodes": [], "edges": []}
        mock_gemini.return_value = {"questions": []}

        with patch("services.course_context_service.get_course_context") as mock_ctx:
            from routes.quiz import generate_quiz
            generate_quiz(self._make_generate_body())
            mock_ctx.assert_not_called()


if __name__ == "__main__":
    import unittest
    unittest.main(verbosity=2)
