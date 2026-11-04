"""Opt-in LIVE test: Gemini actually serves the quiz agent's output schema.

The hermetic suite (tests/test_quiz_schema_states.py) pins that the schema
carries no array-length bounds, but only the real model can say whether the
compiled constraint fits its serving limit. #726's nested `maxItems` bounds
passed every hermetic test and 400'd every live quiz ("The specified schema
produces a constraint that has too many states for serving") — this case is
the one that would have caught it.

It runs the REAL `quiz_agent` (system prompt, three read tools, `final_result`
output tool — the exact request shape the route sends) against the real
`quiz` model slot, asking for 3 questions. The tools read from fixtures, so
the call touches no database:

    RUN_LIVE_QUIZ=1 GEMINI_API_KEY=... pytest tests/test_live_quiz_schema.py

Marked `live_llm` (documented opt-out of the hermetic transport guard,
tests/conftest.py) and skipped otherwise. One billable run.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.live_llm

_OPTED_IN = os.getenv("RUN_LIVE_QUIZ") == "1"


@pytest.mark.skipif(
    not _OPTED_IN,
    reason="opt-in live test: set RUN_LIVE_QUIZ=1 (and GEMINI_API_KEY)",
)
def test_real_model_serves_the_quiz_schema_and_returns_a_quiz(monkeypatch):
    # Opted in but unconfigured is a failure, never a silent skip: the run
    # was asked to check the live schema and must not report success unchecked.
    assert os.getenv("GEMINI_API_KEY"), "RUN_LIVE_QUIZ=1 needs GEMINI_API_KEY"
    sys.path.insert(0, str(Path(__file__).parent / "evals"))
    from _retrieval_fixture import FixtureRetrieval

    import agents.tools.quiz_history as quiz_history
    from agents._providers import model_mode, model_name_for
    from agents.deps import SaplingDeps
    from agents.quiz import MAX_QUESTIONS, quiz_agent
    from routes.quiz import _agent_question_to_wire

    # Preconditions BEFORE the billable call: under the function-mode seam the
    # agent replays fixed E2E constants and would "pass" without Gemini ever
    # seeing the schema, and a re-pointed slot would bill the wrong model.
    assert model_mode() == "real", "unset SAPLING_MODEL_MODE: this test must reach Gemini"
    assert model_name_for("quiz") == "gemini-2.5-flash-lite"

    async def _no_history(user_id: str, concept_node_id: str) -> quiz_history.QuizHistory:
        return quiz_history.QuizHistory()

    # First attempt on the concept: no digest, no prior attempts, no DB read.
    monkeypatch.setattr(quiz_history, "read_recent_quiz_attempts", _no_history)

    deps = SaplingDeps(
        user_id="eval-user",
        course_id="eval-course",
        supabase=None,
        request_id="live-quiz-schema",
        # Consent off: the misconceptions tool returns [] before any read.
        share_class_context=False,
        # Concept mastery served from the committed eval fixture course.
        retrieval=FixtureRetrieval(),
    )
    message = (
        "Generate a quiz of 3 questions at medium difficulty for concept "
        "'Recursion' (concept_node_id=live-node-recursion). Follow the "
        "workflow in your system prompt; pass "
        "concept_node_id='live-node-recursion' to read_recent_quiz_attempts.\n"
        "question_format: multiple_choice. Only generate the requested format; "
        "mixed uses a useful variety.\n"
    )

    # A schema the model cannot serve fails here, on the first request, with
    # ModelHTTPError 400 INVALID_ARGUMENT — before any generation.
    result = quiz_agent.run_sync(message, deps=deps)

    questions = result.output.questions
    assert 1 <= len(questions) <= MAX_QUESTIONS
    wire = [_agent_question_to_wire(q, i + 1) for i, q in enumerate(questions)]
    survivors = [w for w in wire if w is not None]
    assert survivors, f"no generated question survived the route's checks: {questions!r}"
