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
    read_concepts_for_user_tool,
    read_misconceptions_for_course_tool,
)
from agents.tools.quiz_history import (
    QuizHistory,
    RecentQuizAttempt,
    read_recent_quiz_attempts_tool,
)
from services import events_service, prompt_dimensions


# `sink` (collect enqueued events instead of writing them) comes from
# tests/conftest.py. It used to be duplicated here, minus the post-yield
# flush_now() drain the other copy had.


@pytest.fixture(autouse=True)
def _dims():
    prompt_dimensions.clear()
    yield
    prompt_dimensions.clear()


def _ctx(user_id="u1", course_id="c1", feature="quiz"):
    return SimpleNamespace(
        deps=SimpleNamespace(user_id=user_id, course_id=course_id, feature=feature)
    )


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

    tools = sorted(e["payload"]["tool"] for e in sink)
    assert tools == ["quiz_context_digest", "read_recent_quiz_attempts"]
    assert {e["event_type"] for e in sink} == {"quiz.tool_empty"}
    assert {e["payload"]["concept_node_id"] for e in sink} == {"n1"}


def test_empty_digest_beside_real_attempts_is_flagged(sink):
    """THE #529 signature, and the case the seam previously could not see:
    the student has completed attempts on this concept, so the digest that
    summarizes them should exist — and doesn't.

    Keying the check on the attempt count instead short-circuits on
    `if count: return False` in exactly this situation, so the seam could
    never fire for the bug it is named after.
    """
    attempts = [
        RecentQuizAttempt(score=3, total=5, difficulty="medium", accuracy=0.6),
    ]
    with (
        _probe(True),
        patch(
            "agents.tools.quiz_history.read_recent_quiz_attempts",
            return_value=_history(summary=None, attempts=attempts),
        ),
    ):
        asyncio.run(read_recent_quiz_attempts_tool(_ctx(), "n1"))
    events_service.flush_now()

    # The attempt list was non-empty, so only the digest check fires.
    assert [e["payload"]["tool"] for e in sink] == ["quiz_context_digest"]
    assert sink[0]["payload"]["attempts"] == 1


def test_a_populated_digest_is_silent(sink):
    attempts = [
        RecentQuizAttempt(score=3, total=5, difficulty="medium", accuracy=0.6),
    ]
    with (
        _probe(True),
        patch(
            "agents.tools.quiz_history.read_recent_quiz_attempts",
            return_value=_history(summary="They confuse base cases.", attempts=attempts),
        ),
    ):
        asyncio.run(read_recent_quiz_attempts_tool(_ctx(), "n1"))
    events_service.flush_now()
    assert sink == []


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


def test_misconceptions_tool_flags_empty_when_the_class_has_aggregates(sink):
    """The canonical instance: this tool filtered `offering_id` with an
    abstract course id and returned zero rows for everyone, forever (#553).

    The probe therefore asks whether aggregates exist for THIS student's
    offerings of THIS course. Rows there plus an empty read is the signature
    of a keyspace mismatch — and it is the only formulation that catches
    #553 without firing on every class that simply has no aggregates yet.
    """
    with (
        _probe(True),
        patch(
            "agents.tools.graph_read.user_offering_ids_for_course",
            return_value=["off-1", "off-2"],
        ),
        patch(
            "agents.tools.graph_read.read_misconceptions_for_course",
            return_value=[],
        ),
    ):
        asyncio.run(read_misconceptions_for_course_tool(_ctx()))
    events_service.flush_now()

    assert [e["event_type"] for e in sink] == ["quiz.tool_empty"]
    assert sink[0]["payload"]["tool"] == "read_misconceptions_for_course"
    assert sink[0]["payload"]["expect"] == "course_has_aggregates"


def test_misconceptions_tool_is_silent_when_the_class_has_no_aggregates(sink):
    """First weeks of a term: enrolled, but nobody has generated class
    misconceptions yet. Flagging that would fire on every generation."""
    with (
        _probe(False),
        patch(
            "agents.tools.graph_read.user_offering_ids_for_course",
            return_value=["off-1"],
        ),
        patch(
            "agents.tools.graph_read.read_misconceptions_for_course",
            return_value=[],
        ),
    ):
        asyncio.run(read_misconceptions_for_course_tool(_ctx()))
    events_service.flush_now()
    assert sink == []


def test_misconceptions_tool_skips_the_probe_with_no_resolvable_offering(sink):
    """No offering scope means no safe probe — `offering_concept_stats` has
    no user_id, so an unscoped read would ask 'does any class anywhere have
    aggregates', which is true on any live database."""
    with (
        _probe(True),
        patch(
            "agents.tools.graph_read.user_offering_ids_for_course",
            return_value=[],
        ),
        patch(
            "agents.tools.graph_read.read_misconceptions_for_course",
            return_value=[],
        ),
    ):
        asyncio.run(read_misconceptions_for_course_tool(_ctx()))
    events_service.flush_now()
    assert sink == []


def test_misconceptions_tool_is_silent_when_it_returns_rows(sink):
    """And costs nothing: the offering resolution behind the probe is uncached
    and issues two unbounded PostgREST reads, so gating it on "a course id
    exists" instead of on the result being EMPTY made every quiz generation
    pay both round-trips even when the tool had rows to return —
    contradicting tool_signals' own contract (one owner-scoped indexed read,
    only on the empty path)."""
    resolve = MagicMock(return_value=["off-1"])
    with (
        _probe(True) as probe,
        patch("agents.tools.graph_read.user_offering_ids_for_course", resolve),
        patch(
            "agents.tools.graph_read.read_misconceptions_for_course",
            return_value=[Misconception(text="thinks recursion is iteration")],
        ),
    ):
        out = asyncio.run(read_misconceptions_for_course_tool(_ctx()))
    events_service.flush_now()
    assert sink == []
    assert len(out) == 1
    resolve.assert_not_called()
    probe.assert_not_called()


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


async def _async(value):
    return value


def _no_concepts():
    return patch(
        "agents.tools.retrieval.resolve_retrieval",
        return_value=SimpleNamespace(concept_mastery=lambda *a, **k: _async([])),
    )


def test_shared_tool_attributes_the_empty_to_its_actual_caller(sink):
    """`read_concepts_for_user` is registered on the tutor as well as the
    quiz. Its empties must be filed under the agent that ran it, or the
    quiz's rollups silently absorb the tutor's."""
    with _probe(True), _no_concepts():
        asyncio.run(read_concepts_for_user_tool(_ctx(feature="tutor")))
    events_service.flush_now()

    assert [e["event_type"] for e in sink] == ["quiz.tool_empty"]
    assert sink[0]["payload"]["feature"] == "tutor"
    assert sink[0]["payload"]["tool"] == "read_concepts_for_user"


def test_concepts_probe_is_scoped_to_the_course_the_tool_read(sink):
    """Regression: probing the whole graph flagged any student with
    concepts in one course and none in another — the ordinary case for
    anyone taking more than one class."""
    captured = {}

    def factory(name):
        m = MagicMock()

        def _select(cols, **kw):
            captured.update(kw)
            return []

        m.select.side_effect = _select
        return m

    with patch("services.tool_signals.table", side_effect=factory), _no_concepts():
        asyncio.run(read_concepts_for_user_tool(_ctx(course_id="c9")))
    assert captured["filters"]["course_id"] == "eq.c9"


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
