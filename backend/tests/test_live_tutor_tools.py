"""Opt-in LIVE test: the real model actually reaches for a graph reader.

The hermetic suite proves the #149 wiring (registration, schema validation,
deps scoping) with scripted FunctionModel turns; it proves nothing about
whether the REAL model, given the real prompt, ever chooses the new tools.
This single billable case closes that gap.

Runs only when explicitly requested:

    RUN_LIVE_TUTOR_TOOLS=1 GEMINI_API_KEY=... pytest tests/test_live_tutor_tools.py

Marked `live_llm` (documented opt-out of the hermetic transport guard,
tests/conftest.py) and skipped otherwise. Uses FixtureRetrieval, so the
live call still touches no database.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.live_llm

_OPTED_IN = (
    os.getenv("RUN_LIVE_TUTOR_TOOLS") == "1" and bool(os.getenv("GEMINI_API_KEY"))
)


@pytest.mark.skipif(
    not _OPTED_IN,
    reason="opt-in live test: set RUN_LIVE_TUTOR_TOOLS=1 (and GEMINI_API_KEY)",
)
def test_real_model_chooses_a_graph_reader_for_a_graph_question():
    sys.path.insert(0, str(Path(__file__).parent / "evals"))
    from _retrieval_fixture import FixtureRetrieval

    from agents.chat_tutor import socratic_agent
    from agents.deps import SaplingDeps

    deps = SaplingDeps(
        user_id="eval-user",
        course_id="eval-course",
        supabase=None,
        request_id="live-tutor-tools",
        session_id="live-session",
        retrieval=FixtureRetrieval(),
    )

    # Review-recency is answerable ONLY via the graph readers (the tools
    # carry last_reviewed_at; nothing else does) — the same elicitation the
    # socratic_stale_concept_review eval case uses. Up to 3 attempts: a
    # live model is sampled, and this test asserts a capability, not a
    # per-sample guarantee.
    graph_readers = {"read_graph_neighborhood", "read_concepts_for_user"}
    attempts: list[list[str]] = []
    for _ in range(3):
        result = socratic_agent.run_sync(
            "Which of my tracked concepts have I gone the longest without "
            "reviewing? Check when I last reviewed each one and pick the "
            "rustiest for us to work on.",
            deps=deps,
        )
        tool_calls = [
            part.tool_name
            for message in result.all_messages()
            for part in getattr(message, "parts", []) or []
            if type(part).__name__ == "ToolCallPart"
        ]
        attempts.append(tool_calls)
        if graph_readers & set(tool_calls):
            assert isinstance(result.output, str) and result.output.strip()
            return

    raise AssertionError(
        f"real model never chose a graph reader across {len(attempts)} "
        f"attempts; tool calls per attempt: {attempts!r}"
    )
