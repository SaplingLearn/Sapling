"""Quiz-generation agent.

Replaces routes/quiz.py:82's call_gemini_json + manual prompt-string
augmentation. The agent has tools to pull weak concepts + class
misconceptions on demand instead of pre-stuffing them into the prompt.

Per ADR 0003 convention 4: keep the output schema compact. Gemini's
structured-output API rejects rich nested schemas with too many states
for serving — Quiz is a flat top-level model with a list of
QuizQuestion items, no further nesting.
"""

from __future__ import annotations

import hashlib
from typing import Literal

from pydantic import BaseModel, Field
from pydantic_ai import Agent

from agents._providers import model_for
from agents.deps import SaplingDeps
from agents.tools.graph_read import (
    read_concepts_for_user_tool,
    read_misconceptions_for_course_tool,
)


# Difficulty + question type are Literals so Gemini's enum constraint
# applies and downstream UI can branch on stable strings.
QuizDifficulty = Literal["easy", "medium", "hard"]
QuizQuestionType = Literal["multiple_choice", "short_answer"]


class QuizQuestion(BaseModel):
    """A single quiz question. Kept small so the parent Quiz schema
    doesn't trip Gemini's structured-output complexity limit."""

    question: str = Field(max_length=600)
    type: QuizQuestionType
    difficulty: QuizDifficulty
    # Options are only used for multiple_choice; otherwise []. The agent
    # is instructed in the system prompt to leave it empty for short_answer.
    options: list[str] = Field(default_factory=list, max_length=6)
    # For multiple_choice: the option text the agent considers correct.
    # For short_answer: the canonical answer (or one acceptable phrasing).
    correct_answer: str = Field(max_length=400)
    explanation: str = Field(max_length=600)
    # Concept the question is testing — must be one of the user's known
    # concept_names per the prompt. Used by the route to award mastery
    # on a correct answer.
    concept: str = Field(max_length=120)


class Quiz(BaseModel):
    """The agent's structured output."""

    questions: list[QuizQuestion] = Field(min_length=1, max_length=20)


_SYSTEM_PROMPT = (
    "You generate adaptive quizzes for a student. Each question must "
    "target a specific concept the student has weak mastery on, OR "
    "address a class-level misconception you've seen.\n\n"
    "Workflow:\n"
    "1. Call `read_concepts_for_user` to see the student's mastery per "
    "   concept for this course (returned sorted by mastery ASC — "
    "   weakest first).\n"
    "2. Call `read_misconceptions_for_course` to see anonymized class "
    "   misconceptions. Use these to phrase distractors and to write "
    "   a question that probes the misconception.\n"
    "3. Compose `Quiz.questions` so the WEAKEST concepts get the most "
    "   questions, AND each item's `concept` field exactly matches a "
    "   concept_name returned by tool 1.\n\n"
    "Per-question rules:\n"
    "- multiple_choice: 4 options, exactly one correct. The correct "
    "   option text MUST appear verbatim in `options`. Distractors "
    "   should reflect plausible misconceptions, not random noise.\n"
    "- short_answer: leave `options=[]`. `correct_answer` is the "
    "   canonical answer (one acceptable phrasing).\n"
    "- explanation: 1-3 sentences explaining WHY the correct answer "
    "   is correct — used in the post-quiz review screen.\n"
    "- difficulty: align with the student's mastery on the concept; "
    "   weakest concepts get easy/medium, strongest get hard.\n\n"
    "Honor the requested num_questions and difficulty distribution "
    "in the user message. Don't invent concepts the student doesn't "
    "have."
)
_PROMPT_HASH = hashlib.sha256(_SYSTEM_PROMPT.encode("utf-8")).hexdigest()[:12]


quiz_agent = Agent[SaplingDeps, Quiz](
    model=model_for("quiz"),
    deps_type=SaplingDeps,
    output_type=Quiz,
    system_prompt=_SYSTEM_PROMPT,
    metadata={"prompt_version": _PROMPT_HASH, "agent": "quiz"},
    tools=[
        read_concepts_for_user_tool,
        read_misconceptions_for_course_tool,
    ],
)
