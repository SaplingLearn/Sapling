"""One upload pipeline (#835): agents.document.run_document_agents.

The streaming route, the `/upload/sync` twin (process_document) and the
`document.process` worker all run the same steps; the route relays them as
SSE progress events and a queued upload replays the worker's recorded stages
as the SAME events (services/document_pipeline.py is the one vocabulary).
"""
from __future__ import annotations

import asyncio
from contextlib import ExitStack

import pytest

from agents import document as doc_agents
from services import document_jobs as dj
from services import document_pipeline as dp
from tests.test_document_upload_jobs import _agent_patches


def _steps(text="some text", *, is_syllabus=False):
    from agents.deps import SaplingDeps

    deps = SaplingDeps(user_id="u1", course_id="c1", supabase=None, request_id="rid-1")

    async def _collect():
        return [s async for s in dp.run_document_agents(text, deps)]

    patches = list(_agent_patches(is_syllabus=is_syllabus))
    if is_syllabus:
        from unittest.mock import AsyncMock, patch
        from types import SimpleNamespace

        from agents.syllabus_extraction import SyllabusAssignments

        patches.append(patch(
            "agents.syllabus_extraction.syllabus_extraction_agent.run",
            AsyncMock(return_value=SimpleNamespace(output=SyllabusAssignments(
                course_title="T", assignments=[], grading_categories=[]))),
        ))
    with ExitStack() as stack:
        mocks = [stack.enter_context(p) for p in patches]
        return asyncio.run(_collect()), mocks


@pytest.mark.parametrize("is_syllabus", [False, True])
def test_the_pipeline_yields_every_boundary_in_order(is_syllabus):
    steps, _ = _steps(is_syllabus=is_syllabus)
    assert [s.name for s in steps] == [dp.CLASSIFY, dp.CLASSIFIED, dp.EXTRACTED, dp.MERGED,
                                       dp.DONE]
    assert steps[1].category == "lecture_notes" and steps[1].is_syllabus is is_syllabus
    assert steps[2].concept_count == 1 and steps[3].merged == 1
    result = steps[-1].result
    assert result.graph_updated is True and steps[-1].merged == 1
    assert (result.syllabus is not None) is is_syllabus


def test_usage_is_recorded_with_the_deps_user_and_request():
    _, mocks = _steps()
    record = mocks[4]
    tasks = sorted(c.kwargs["task"] for c in record.call_args_list)
    assert tasks == ["classifier", "concepts", "summary"]
    for c in record.call_args_list:
        assert c.kwargs["user_id"] == "u1" and c.kwargs["request_id"] == "rid-1"


def test_process_document_returns_the_pipelines_result():
    from agents.deps import SaplingDeps

    deps = SaplingDeps(user_id="u1", course_id="c1", supabase=None, request_id="rid-1")
    with ExitStack() as stack:
        for p in _agent_patches():
            stack.enter_context(p)
        result = asyncio.run(doc_agents.process_document("some text", deps))
    assert result.classification.category == "lecture_notes"
    assert [c.name for c in result.concepts.concepts] == ["Backprop"]


def _dump(events):
    return [(e.type, e.step, e.message, e.data) for e in events]


@pytest.mark.parametrize("is_syllabus", [False, True])
def test_a_queued_upload_replays_exactly_the_streaming_routes_events(is_syllabus):
    """The worker records each step as a stage (with its numbers in
    `progress`); the watcher's events for those stages equal the inline
    route's events for the same steps."""
    steps, _ = _steps(is_syllabus=is_syllabus)
    inline = [ev for s in steps for ev in dp.step_events(s)]

    by = {s.name: s for s in steps}
    progress = {"char_count": 9, "category": by[dp.CLASSIFIED].category,
                "is_syllabus": by[dp.CLASSIFIED].is_syllabus,
                "concept_count": by[dp.EXTRACTED].concept_count,
                "merged_count": by[dp.MERGED].merged}
    queued, _rank = dj.events_between(0, {"stage": dj.SAVING, "progress": progress})
    # A queued upload also reports its own extraction first.
    assert _dump(queued[:2]) == _dump([dp.extracting_text_event(), dp.extracted_text_event(9)])
    assert _dump(queued[2:]) == _dump(inline)


def test_done_has_no_progress_events():
    assert dp.step_events(dp.PipelineStep(dp.DONE)) == []
