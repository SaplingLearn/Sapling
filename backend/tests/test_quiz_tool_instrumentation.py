"""F5 + F6 where they actually run: inside the agent tool wrappers.

The unit tests for `tool_signals` and `prompt_dimensions` prove the seams
work. These prove they are WIRED — which is the half that silently rots,
and the half whose absence let #529 hide for 51 days.
"""

import asyncio
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from agents.tools.graph_read import (
    Misconception,
    read_misconceptions_for_course_tool,
)
from agents.tools.quiz_history import QuizHistory, read_recent_quiz_attempts_tool
from services import events_service, prompt_dimensions


@pytest.fixture
def sink():
    events_service.reset_for_tests()
    rows: list[dict] = []

    def _capture(name):
        m = MagicMock()
        m.insert.side_effect = lambda payload: rows.extend(
            payload if isinstance(payload, list) else [payload]
        )
        return m

    with patch("services.events_service.table", side_effect=_capture):
        yield rows


@pytest.fixture(autouse=True)
def _dims():
    prompt_dimensions.clear()
    yield
    prompt_dimensions.clear()


def _ctx(user_id="u1", course_id="c1"):
    return SimpleNamespace(deps=SimpleNamespace(user_id=user_id, course_id=course_id))


def _probe(has_rows: bool):
    def factory(name):
        m = MagicMock()
        m.select.return_value = [{"id": "x"}] if has_rows else []
        return m
    return patch("services.tool_signals.table", side_effect=factory)


# ── read_recent_quiz_attempts_tool ──────────────────────────────────────────


def _history(summary=None, attempts=()):
    return QuizHistory(summary=summary, recent_attempts=list(attempts))


def test_history_tool_records_digest_presence(sink):
    """F6: the one dimension the route cannot see. It is resolved inside the
    tool, so it has to survive the to_thread hop back to the route."""
    prompt_dimensions.start_capture()
    with (
        _probe(False),
        patch(
            "agents.tools.quiz_history.read_recent_quiz_attempts",
            return_value=_history(summary="They confuse base and recursive cases."),
        ),
    ):
        asyncio.run(read_recent_quiz_attempts_tool(_ctx(), "n1"))

    dims = prompt_dimensions.snapshot()
    assert dims["digest_present"] is True
    assert dims["digest_chars"] > 0


def test_history_tool_records_an_absent_digest_too(sink):
    """'The digest was missing' is exactly as interesting as its size —
    recording only the present case would make #529 invisible again."""
    prompt_dimensions.start_capture()
    with (
        _probe(False),
        patch(
            "agents.tools.quiz_history.read_recent_quiz_attempts",
            return_value=_history(summary=None),
        ),
    ):
        asyncio.run(read_recent_quiz_attempts_tool(_ctx(), "n1"))

    assert prompt_dimensions.snapshot()["digest_present"] is False


def test_history_tool_flags_empty_history_for_a_student_who_has_attempts(sink):
    with (
        _probe(True),
        patch(
            "agents.tools.quiz_history.read_recent_quiz_attempts",
            return_value=_history(),
        ),
    ):
        asyncio.run(read_recent_quiz_attempts_tool(_ctx(), "n1"))
    events_service.flush_now()

    assert [e["event_type"] for e in sink] == ["quiz.tool_empty"]
    assert sink[0]["payload"]["tool"] == "read_recent_quiz_attempts"
    assert sink[0]["payload"]["concept_node_id"] == "n1"


def test_history_tool_is_silent_for_a_genuinely_new_student(sink):
    with (
        _probe(False),
        patch(
            "agents.tools.quiz_history.read_recent_quiz_attempts",
            return_value=_history(),
        ),
    ):
        asyncio.run(read_recent_quiz_attempts_tool(_ctx(), "n1"))
    events_service.flush_now()
    assert sink == []


def test_history_tool_still_returns_its_payload_when_flagging(sink):
    """Instrumentation observes; it must not change what the model sees."""
    with (
        _probe(True),
        patch(
            "agents.tools.quiz_history.read_recent_quiz_attempts",
            return_value=_history(summary="digest text"),
        ),
    ):
        out = asyncio.run(read_recent_quiz_attempts_tool(_ctx(), "n1"))
    assert "digest text" in out.summary


# ── read_misconceptions_for_course_tool ─────────────────────────────────────


def test_misconceptions_tool_flags_empty_for_an_enrolled_student(sink):
    """The canonical instance: this tool filtered `offering_id` with an
    abstract course id and returned zero rows for everyone, forever."""
    with (
        _probe(True),
        patch(
            "agents.tools.graph_read.read_misconceptions_for_course",
            return_value=[],
        ),
    ):
        asyncio.run(read_misconceptions_for_course_tool(_ctx()))
    events_service.flush_now()

    assert [e["event_type"] for e in sink] == ["quiz.tool_empty"]
    assert sink[0]["payload"]["tool"] == "read_misconceptions_for_course"
    assert sink[0]["payload"]["expect"] == "enrolled"


def test_misconceptions_tool_is_silent_when_it_returns_rows(sink):
    with (
        _probe(True),
        patch(
            "agents.tools.graph_read.read_misconceptions_for_course",
            return_value=[Misconception(text="thinks recursion is iteration")],
        ),
    ):
        out = asyncio.run(read_misconceptions_for_course_tool(_ctx()))
    events_service.flush_now()
    assert sink == []
    assert len(out) == 1


def test_misconceptions_tool_records_its_block_size(sink):
    prompt_dimensions.start_capture()
    with (
        _probe(False),
        patch(
            "agents.tools.graph_read.read_misconceptions_for_course",
            return_value=[
                Misconception(text="a"), Misconception(text="b"),
            ],
        ),
    ):
        asyncio.run(read_misconceptions_for_course_tool(_ctx()))
    assert prompt_dimensions.snapshot()["misconceptions"] == 2


def test_tools_work_outside_a_capture_scope(sink):
    """The tutor registers these tools and does not open a capture scope.
    Recording must never require one."""
    with (
        _probe(False),
        patch(
            "agents.tools.graph_read.read_misconceptions_for_course",
            return_value=[],
        ),
    ):
        asyncio.run(read_misconceptions_for_course_tool(_ctx()))
    assert prompt_dimensions.snapshot() == {}
