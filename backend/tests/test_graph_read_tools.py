"""
Unit tests for backend/agents/tools/graph_read.py

Tests cover:
  - read_concepts_for_user: ordering, missing-concept-name drop, error fallback.
  - read_misconceptions_for_course: None course_id short-circuit.
  - read_misconceptions_for_course: table read + missing-text drop.

Mocks `db.connection.table` via patch on the imported reference inside
`agents.tools.graph_read`, mirroring the pattern used in
`tests/test_documents_routes.py`.
"""
from __future__ import annotations

import asyncio
from unittest.mock import patch

from agents.tools.graph_read import (
    read_concepts_for_user,
    read_misconceptions_for_course,
)


def _run(coro):
    """Drive an async coroutine to completion in a sync test."""
    return asyncio.run(coro)


# ── read_concepts_for_user ────────────────────────────────────────────────


class TestReadConceptsForUser:
    def test_returns_sorted_ascending_and_drops_missing_names(self):
        # Supabase honors order=mastery_score.asc server-side; we mirror
        # that here so we can assert the post-mapping shape is preserved.
        rows = [
            {
                "concept_name": "pointers",
                "mastery_score": 0.1,
                "last_studied_at": "2026-05-01T12:00:00Z",
            },
            {
                # Row missing concept_name should be dropped.
                "concept_name": "",
                "mastery_score": 0.25,
                "last_studied_at": None,
            },
            {
                "concept_name": "recursion",
                "mastery_score": 0.4,
                "last_studied_at": "2026-04-28T08:00:00Z",
            },
            {
                "concept_name": "loops",
                "mastery_score": 0.85,
                "last_studied_at": None,
            },
        ]
        with patch("agents.tools.graph_read.table") as t:
            t.return_value.select.return_value = rows
            result = _run(read_concepts_for_user("user_andres", "course_cs101"))

        # Ordering matches input (server-sorted ASC); dropped row is gone.
        assert [c.concept_name for c in result] == [
            "pointers",
            "recursion",
            "loops",
        ]
        assert result[0].mastery == 0.1
        assert result[0].last_reviewed_at == "2026-05-01T12:00:00Z"
        assert result[2].last_reviewed_at is None

        # Verify the underlying read uses the right table + order arg.
        t.assert_called_with("graph_nodes")
        select_kwargs = t.return_value.select.call_args
        assert "mastery_score.asc" in str(select_kwargs)
        assert "course_cs101" in str(select_kwargs)
        assert "user_andres" in str(select_kwargs)

    def test_returns_empty_on_supabase_error(self):
        with patch("agents.tools.graph_read.table") as t:
            t.return_value.select.side_effect = RuntimeError("boom")
            result = _run(read_concepts_for_user("user_andres", "course_cs101"))

        assert result == []

    def test_omits_course_filter_when_course_id_none(self):
        with patch("agents.tools.graph_read.table") as t:
            t.return_value.select.return_value = []
            _run(read_concepts_for_user("user_andres", None))

        select_kwargs = t.return_value.select.call_args
        # course_id should not appear when None was passed.
        assert "course_id" not in str(select_kwargs.kwargs.get("filters") or {})


# ── read_misconceptions_for_course ────────────────────────────────────────


class TestReadMisconceptionsForCourse:
    def test_returns_empty_when_course_id_is_none(self):
        # No table call should happen at all.
        with patch("agents.tools.graph_read.table") as t:
            result = _run(read_misconceptions_for_course(None))

        assert result == []
        t.assert_not_called()

    def test_reads_table_and_drops_missing_text(self):
        rows = [
            {
                "concept_name": "pointers",
                "common_misconceptions": [
                    "Dangling pointers always crash",
                    "",  # blank — should be dropped
                    "Memory leaks are caught by GC",
                ],
            },
            {
                "concept_name": "recursion",
                "common_misconceptions": [
                    "All recursion is infinite",
                    "Dangling pointers always crash",  # dup — case-insensitive
                ],
            },
            {
                "concept_name": "loops",
                "common_misconceptions": None,  # missing array — should be skipped
            },
        ]
        with patch("agents.tools.graph_read.table") as t:
            t.return_value.select.return_value = rows
            result = _run(read_misconceptions_for_course("course_cs101"))

        assert [m.text for m in result] == [
            "Dangling pointers always crash",
            "Memory leaks are caught by GC",
            "All recursion is infinite",
        ]
        # Each entry carries the originating concept.
        assert result[0].related_concept == "pointers"
        assert result[1].related_concept == "pointers"
        assert result[2].related_concept == "recursion"

        t.assert_called_with("course_concept_stats")
        select_kwargs = t.return_value.select.call_args
        assert "course_cs101" in str(select_kwargs)
