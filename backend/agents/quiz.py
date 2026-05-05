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
from agents.tools.quiz_history import read_recent_quiz_attempts_tool


# Difficulty + question type are Literals so Gemini's enum constraint
# applies and downstream UI can branch on stable strings.
#
# `QuizQuestionType` is intentionally MCQ-only today. The frontend
# `submitQuiz` flow grades by `q["options"][i].correct` lookup — there's
# no UI for free-text answers, no fuzzy-match grading, no LLM-judged
# scoring. Generating short-answer questions through this path would
# emit unrenderable, ungradable items. Keep the type narrow until real
# short-answer support exists; revisit when that lands.
QuizDifficulty = Literal["easy", "medium", "hard"]
QuizQuestionType = Literal["multiple_choice"]


class QuizQuestion(BaseModel):
    """A single multiple-choice quiz question. Kept small so the parent
    Quiz schema doesn't trip Gemini's structured-output complexity limit."""

    question: str = Field(max_length=600)
    type: QuizQuestionType
    difficulty: QuizDifficulty
    # 3-6 options. The agent is required to populate this for every
    # question and to make `correct_answer` match exactly one of them.
    options: list[str] = Field(min_length=3, max_length=6)
    # The option text the agent considers correct. Must appear verbatim
    # in `options`; the route validates this and drops questions that
    # violate the contract rather than silently mis-marking them.
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
    "You generate adaptive multiple-choice quizzes for a student. Each "
    "question must target a specific concept the student has weak "
    "mastery on, OR address a class-level misconception you've seen, "
    "OR revive a concept the student hasn't reviewed in a while.\n\n"
    "Workflow:\n"
    "1. Call `read_concepts_for_user` to see the student's mastery per "
    "   concept for this course (returned sorted by mastery ASC — "
    "   weakest first). Each concept also carries `last_reviewed_at`, "
    "   which you use for spaced repetition (see rules below).\n"
    "2. Call `read_misconceptions_for_course` to see anonymized class "
    "   misconceptions. Use these to phrase distractors and to write "
    "   a question that probes the misconception.\n"
    "3. Call `read_recent_quiz_attempts(concept_node_id)` for the "
    "   target concept_node_id given in the user message. The "
    "   `summary` is a digest of past mistakes the student has made "
    "   on this concept — mine it for distractor inspiration. The "
    "   `recent_attempts` list (newest first) drives adaptive "
    "   difficulty (see rules below).\n"
    "4. Compose `Quiz.questions` so the WEAKEST and STALEST concepts "
    "   get the most questions, AND each item's `concept` field "
    "   exactly matches a concept_name returned by tool 1.\n\n"
    "Concept-selection rules (combine all three signals):\n"
    "- Bias question count toward the lowest-mastery concepts (the "
    "   weakest first in the tool 1 return).\n"
    "- SPACED REPETITION: also surface concepts whose "
    "   `last_reviewed_at` is older than ~7 days, even if their "
    "   mastery is mid-tier — they're due for review and decay over "
    "   time. Concepts with `last_reviewed_at = null` are unreviewed; "
    "   treat them as stale.\n"
    "- Don't drop high-mastery, recently-reviewed concepts entirely; "
    "   include 1 question on a strong-and-fresh concept to keep the "
    "   quiz from feeling punishing.\n\n"
    "Adaptive-difficulty rules (use `recent_attempts.accuracy`):\n"
    "- If the most recent 2-3 attempts on this concept averaged < "
    "   0.5 accuracy, drop the difficulty mix one step from what the "
    "   user asked (hard -> medium, medium -> easy, easy stays easy). "
    "   The student is struggling; keep them on track.\n"
    "- If the most recent 3 attempts all scored >= 0.8, you may "
    "   include 1-2 questions one step harder than the requested "
    "   difficulty to push them.\n"
    "- If `recent_attempts` is empty (first attempt), honor the "
    "   user-requested difficulty exactly.\n"
    "- Never override the user-requested difficulty by more than one "
    "   step in either direction. Stay close to what they asked for.\n\n"
    "Per-question rules (multiple-choice only — the type field is "
    "constrained to 'multiple_choice'):\n"
    "- 4 options, exactly one correct. The text in `correct_answer` "
    "   MUST appear verbatim in `options` — character-for-character. "
    "   Questions that violate this are dropped at the route layer.\n"
    "- Distractors should reflect plausible misconceptions, not random "
    "   noise. Combine signals from `read_misconceptions_for_course` "
    "   (class-wide) and `read_recent_quiz_attempts.summary` "
    "   (this student's prior errors) when writing them.\n"
    "- explanation: 1-3 sentences explaining WHY the correct answer "
    "   is correct — used in the post-quiz review screen.\n"
    "- difficulty: align with the student's mastery on the concept "
    "   AND the adaptive-difficulty rules above.\n\n"
    "Honor the requested num_questions. Don't invent concepts the "
    "student doesn't have."
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
        read_recent_quiz_attempts_tool,
    ],
)
