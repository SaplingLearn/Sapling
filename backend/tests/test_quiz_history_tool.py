"""Unit tests for agents/tools/quiz_history.py.

The agent's prompt-driven *use* of this tool (spaced repetition,
adaptive difficulty) is covered by the eval set in
tests/evals/quiz_generation.py. These tests pin only the pure logic:
shape coercion, accuracy math, table-filter wiring, error handling.
"""

from __future__ import annotations

import asyncio

import pytest
from unittest.mock import MagicMock, patch

from agents.tools.quiz_history import (
    QuizHistory,
    RecentQuizAttempt,
    _coerce_summary,
    read_recent_quiz_attempts,
)


# ── _coerce_summary (pure) ───────────────────────────────────────────────────


class TestCoerceSummary:
    def test_none_returns_none(self):
        assert _coerce_summary(None) is None

    def test_empty_string_returns_none(self):
        assert _coerce_summary("   ") is None

    def test_plain_string_passes_through_trimmed(self):
        assert _coerce_summary("  student confuses for/while  ") == (
            "student confuses for/while"
        )

    def test_dict_with_summary_key(self):
        assert _coerce_summary({"summary": "missing base case"}) == (
            "missing base case"
        )

    def test_dict_falls_back_through_aliases(self):
        # Older prompt versions wrote `notes` instead of `summary`.
        assert _coerce_summary({"notes": "swapped order of args"}) == (
            "swapped order of args"
        )

    def test_dict_flattens_misconception_lists_when_no_top_string(self):
        out = _coerce_summary({
            "misconceptions": ["off-by-one", "  ", "wrong return type"],
            "weak_areas": ["recursion"],
        })
        assert out is not None
        assert "off-by-one" in out
        assert "wrong return type" in out
        assert "recursion" in out

    def test_dict_with_no_useful_content_returns_none(self):
        assert _coerce_summary({"unrelated": 42}) is None


# ── read_recent_quiz_attempts (I/O) ──────────────────────────────────────────


def _table_factory(*, context_json=None, attempt_rows=None):
    """Build a side_effect for `table()` returning per-table mocks."""
    attempt_rows = attempt_rows or []

    def factory(name: str):
        mock = MagicMock()
        if name == "quiz_context":
            mock.select.return_value = (
                [{"context_json": context_json}] if context_json is not None else []
            )
        elif name == "quiz_attempts":
            mock.select.return_value = attempt_rows
        else:
            mock.select.return_value = []
        return mock

    return factory


class TestReadRecentQuizAttempts:
    def test_no_history_returns_empty_history(self):
        with patch(
            "agents.tools.quiz_history.table",
            side_effect=_table_factory(),
        ):
            history = asyncio.run(
                read_recent_quiz_attempts("user_andres", "node1")
            )

        assert isinstance(history, QuizHistory)
        assert history.summary is None
        assert history.recent_attempts == []

    def test_summary_from_quiz_context_is_returned(self):
        with patch(
            "agents.tools.quiz_history.table",
            side_effect=_table_factory(
                context_json={"summary": "tends to confuse for and while loops"}
            ),
        ):
            history = asyncio.run(
                read_recent_quiz_attempts("user_andres", "node1")
            )

        assert history.summary == "tends to confuse for and while loops"

    def test_attempts_are_mapped_with_accuracy(self):
        rows = [
            {
                "score": 4,
                "total": 5,
                "difficulty": "medium",
                "completed_at": "2026-05-03T20:00:00Z",
            },
            {
                "score": 1,
                "total": 5,
                "difficulty": "hard",
                "completed_at": "2026-05-02T20:00:00Z",
            },
        ]
        with patch(
            "agents.tools.quiz_history.table",
            side_effect=_table_factory(attempt_rows=rows),
        ):
            history = asyncio.run(
                read_recent_quiz_attempts("user_andres", "node1")
            )

        assert len(history.recent_attempts) == 2
        first = history.recent_attempts[0]
        assert isinstance(first, RecentQuizAttempt)
        assert first.score == 4
        assert first.total == 5
        assert first.difficulty == "medium"
        assert first.accuracy == pytest.approx(0.8)
        # Second attempt: 1/5 = 0.2
        assert history.recent_attempts[1].accuracy == pytest.approx(0.2)

    def test_attempts_with_zero_or_null_fields_are_skipped(self):
        # submit_quiz writes score+total atomically, so any row with
        # null score, null total, or total=0 is corruption — drop it
        # rather than passing the LLM a bogus 0% accuracy that could
        # trigger a spurious adaptive downshift. The valid 3/5 row
        # stays.
        rows = [
            {"score": 0, "total": 0, "difficulty": "easy", "completed_at": "x"},
            {"score": None, "total": 5, "difficulty": "easy", "completed_at": "y"},
            {"score": 3, "total": None, "difficulty": "easy", "completed_at": "y2"},
            {"score": 3, "total": 5, "difficulty": "medium", "completed_at": "z"},
        ]
        with patch(
            "agents.tools.quiz_history.table",
            side_effect=_table_factory(attempt_rows=rows),
        ):
            history = asyncio.run(
                read_recent_quiz_attempts("user_andres", "node1")
            )

        assert len(history.recent_attempts) == 1
        kept = history.recent_attempts[0]
        assert kept.score == 3
        assert kept.total == 5
        assert kept.difficulty == "medium"

    def test_corrupt_rows_are_dropped(self):
        # Rows where score is outside [0, total] are corrupt — passing
        # them to the LLM as e.g. "score=7, total=5" would prompt the
        # agent to wonder whether to trust the data at all. Drop them
        # entirely. A valid neighbour row in the same response stays.
        rows = [
            {"score": 7, "total": 5, "difficulty": "hard", "completed_at": "x"},
            {"score": -1, "total": 5, "difficulty": "easy", "completed_at": "y"},
            {"score": 4, "total": 5, "difficulty": "medium", "completed_at": "z"},
        ]
        with patch(
            "agents.tools.quiz_history.table",
            side_effect=_table_factory(attempt_rows=rows),
        ):
            history = asyncio.run(
                read_recent_quiz_attempts("user_andres", "node1")
            )
        assert len(history.recent_attempts) == 1
        assert history.recent_attempts[0].score == 4
        assert history.recent_attempts[0].total == 5
        assert history.recent_attempts[0].accuracy == pytest.approx(0.8)

    def test_filters_passed_to_quiz_attempts_select(self):
        captured: dict = {}

        def factory(name: str):
            mock = MagicMock()
            if name == "quiz_attempts":
                def select(*args, **kwargs):
                    captured["filters"] = kwargs.get("filters")
                    captured["order"] = kwargs.get("order")
                    captured["limit"] = kwargs.get("limit")
                    return []
                mock.select.side_effect = select
            elif name == "quiz_context":
                mock.select.return_value = []
            else:
                mock.select.return_value = []
            return mock

        with patch("agents.tools.quiz_history.table", side_effect=factory):
            asyncio.run(read_recent_quiz_attempts("user_andres", "node1"))

        # Filters must scope to this user + concept, and exclude
        # in-flight attempts (completed_at IS NOT NULL). Order newest
        # first so adaptive-difficulty math reads recency correctly.
        assert captured["filters"]["user_id"] == "eq.user_andres"
        assert captured["filters"]["concept_node_id"] == "eq.node1"
        assert captured["filters"]["completed_at"] == "not.is.null"
        assert captured["order"] == "completed_at.desc"
        assert captured["limit"] == 5

    def test_db_error_degrades_to_empty(self):
        def factory(name: str):
            mock = MagicMock()
            mock.select.side_effect = RuntimeError("connection reset")
            return mock

        with patch("agents.tools.quiz_history.table", side_effect=factory):
            history = asyncio.run(
                read_recent_quiz_attempts("user_andres", "node1")
            )

        # Failure must NOT propagate — the agent can still generate a
        # quiz without history; it just won't be adaptive.
        assert history.summary is None
        assert history.recent_attempts == []
