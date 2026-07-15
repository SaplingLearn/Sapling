"""Quiz-context agent.

Replaces the inline `call_gemini_json` in `routes/quiz.py::_update_context`.
Maintains the per-concept "learning notes" that steer the next quiz. Output
mirrors the legacy `quiz_context_update.txt` JSON schema exactly, so the stored
`quiz_context.context_json` shape is unchanged.
"""

from __future__ import annotations

import hashlib
from typing import Literal

from pydantic import BaseModel, Field
from pydantic_ai import Agent

from agents._providers import model_for


class QuizContext(BaseModel):
    """Typed quiz-context notes. Serializes (model_dump) to the legacy
    context_json shape consumed by `save_quiz_context`."""

    weak_areas: list[str] = Field(
        default_factory=list,
        description="Specific subtopics or skills the student is weak on.",
    )
    common_mistakes: list[str] = Field(
        default_factory=list,
        description="Specific misconceptions or common mistakes the student revealed.",
    )
    questions_seen_summary: str = Field(
        default="",
        description="Brief summary of question themes the student has now seen.",
    )
    recommended_difficulty: Literal["easy", "medium", "hard"] = Field(
        default="medium",
        description="Difficulty the next quiz should target.",
    )
    notes: str = Field(
        default="",
        description="Free-form observations to help generate a better next quiz.",
    )


_SYSTEM_PROMPT = (
    "You maintain learning notes about a student's understanding of a single "
    "concept, used to generate better quizzes over time. Given the concept, the "
    "previous notes (may be empty), and the quiz the student just completed "
    "(score and per-question results), update the notes: what subtopics the "
    "student is weak on, what misconceptions they revealed, a brief summary of "
    "question themes they've now seen (so they aren't repeated), the difficulty "
    "the next quiz should be, and any other helpful observations. Base every "
    "note on the provided results — do not invent performance the data doesn't show."
)
_PROMPT_HASH = hashlib.sha256(_SYSTEM_PROMPT.encode("utf-8")).hexdigest()[:12]


quiz_context_agent = Agent[None, QuizContext](
    model=model_for("quiz_context"),
    output_type=QuizContext,
    system_prompt=_SYSTEM_PROMPT,
    metadata={"prompt_version": _PROMPT_HASH, "agent": "quiz_context"},
)
