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

from pydantic import BaseModel, Field, field_validator
from pydantic_ai import Agent

from agents._providers import model_for
from agents.deps import SaplingDeps
from agents.tools.graph_read import (
    read_concepts_for_user_tool,
    read_misconceptions_for_course_tool,
)
from agents.tools.quiz_history import read_recent_quiz_attempts_tool
from services.prompt_safety import INJECTION_GUARD_PROMPT


# Difficulty + question type are Literals so Gemini's enum constraint
# applies and downstream UI can branch on stable strings.
# Written formats use deterministic server grading; mixed is a request mode,
# not a question type. Every emitted item has one concrete answer format.
QuizDifficulty = Literal["easy", "medium", "hard"]
QuizQuestionType = Literal["multiple_choice", "short_answer", "numeric", "symbolic"]

# Output caps, enforced by OUR validation after the call, never by the schema
# Gemini compiles. Constrained decoding multiplies array bounds: each
# `maxItems` nested inside a bounded `questions` list is repeated per outer
# item. With #726's `accepted_answers` (8) beside `options` (4) inside
# `questions` (1..10), the `final_result` declaration plus the three read
# tools (function-calling mode ANY unions them) crossed gemini-2.5-flash-lite's
# "too many states for serving" limit, and every live quiz 400'd before
# generating anything. Measured live 2026-10-19: all bounds -> 400, either
# nesting alone -> served, none -> served. So the schema carries no length
# bounds at all, and the validators below clip over-long lists deterministically
# (keep the first N, in model order) instead of failing the whole Quiz, which
# would burn the output retries and 502. Pinned by tests/test_quiz_schema_states.py.
MAX_QUESTIONS = 10  # == services.quiz_config.QUIZ_MAX_QUESTIONS
MAX_OPTIONS = 4  # == routes.quiz._MCQ_OPTIONS (the route drops any other count)
MAX_ACCEPTED_ANSWERS = 8


def _clip(value, limit: int):
    """Keep the first `limit` entries of a raw list input, in model order.
    Anything that is not a list is left for normal validation to reject."""
    return value[:limit] if isinstance(value, list) else value


class QuizQuestion(BaseModel):
    """A single quiz question. Kept small so the parent
    Quiz schema doesn't trip Gemini's structured-output complexity limit."""

    # NOTE: no `max_length` on the string fields below. Gemini's
    # constrained-decoding structured output builds a length-counting
    # automaton per bounded string field; combined with the nested
    # options list this pushed the schema past Gemini's "too many
    # states for serving" limit on gemini-2.5-flash-lite / -flash
    # (only gemini-2.5-pro served it). Length is governed by the system
    # prompt instead (question/explanation: 1-3 sentences; concept must
    # match a concept_name).
    question: str
    type: QuizQuestionType
    difficulty: QuizDifficulty
    # MCQ has four choices; written formats have none. That conditional rule
    # lives in the ROUTE (routes/quiz.py::_agent_question_to_wire), never in a
    # model validator here: a validator failure rejects the whole Quiz, which
    # burns the agent's output retries and 502s the request over one bad item.
    # The route drops just that item. The list bounds are clipped by the
    # validator below, not declared on the fields (see MAX_OPTIONS above).
    options: list[str] = Field(default_factory=list)
    accepted_answers: list[str] = Field(default_factory=list)
    # The option text the agent considers correct. Must appear verbatim
    # in `options`; the route validates this and drops questions that
    # violate the contract rather than silently mis-marking them.
    correct_answer: str
    explanation: str
    # Concept the question is testing — must be one of the user's known
    # concept_names per the prompt. Used by the route to award mastery
    # on a correct answer.
    concept: str

    # The clips run BEFORE item validation, as decoding-time maxItems did: a
    # malformed surplus entry past the cap is discarded, never a reason to
    # reject the valid prefix and spend an output retry.
    @field_validator("options", mode="before")
    @classmethod
    def _clip_options(cls, options):
        return _clip(options, MAX_OPTIONS)

    @field_validator("accepted_answers", mode="before")
    @classmethod
    def _clip_accepted_answers(cls, accepted):
        return _clip(accepted, MAX_ACCEPTED_ANSWERS)


class Quiz(BaseModel):
    """The agent's structured output."""

    # 1..MAX_QUESTIONS, enforced here rather than as minItems/maxItems in the
    # schema (see MAX_QUESTIONS above).
    questions: list[QuizQuestion]

    @field_validator("questions", mode="before")
    @classmethod
    def _clip_questions(cls, questions):
        return _clip(questions, MAX_QUESTIONS)

    @field_validator("questions", mode="after")
    @classmethod
    def _require_questions(cls, questions: list[QuizQuestion]) -> list[QuizQuestion]:
        # Empty stays a validation error, so the bounded output retry still
        # fires exactly as it did for the old min_length=1.
        if not questions:
            raise ValueError("List should have at least 1 item after validation, not 0")
        return questions


_SYSTEM_PROMPT = (
    "You generate adaptive, course-grounded quizzes for a student. Each "
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
    "ADAPTIVE MODE (#540): when the user message says the quiz is in "
    "adaptive mode, there is no user-requested difficulty — you choose "
    "each question's difficulty yourself. Base the mix on mastery and "
    "`recent_attempts.accuracy`: struggling/low-accuracy concepts get "
    "easy-leaning questions, strong/high-accuracy ones get hard-leaning "
    "questions; with no history at all, center the mix on medium. The "
    "±1-step limits below do not apply in adaptive mode, but every "
    "question still carries a concrete easy|medium|hard difficulty — "
    "'adaptive' is never a per-question value. Note that PAST attempts "
    "in `recent_attempts` may carry difficulty 'adaptive' (that "
    "attempt's mix was agent-chosen); treat such an attempt's "
    "difficulty as unspecified and judge it by its accuracy alone.\n\n"
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
    "Multiple-choice question rules:\n"
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
    "\n\nCOURSE MATERIAL grounding:\n"
    "- If the user message contains a `COURSE MATERIAL` block, treat it as "
    "  the PRIMARY source of truth for question content. The MAJORITY of "
    "  questions must be grounded in and stay within the scope of that "
    "  material, so the quiz reflects what this class is actually covering.\n"
    "- You MAY supplement with foundational, on-topic aspects of the same "
    "  concept where the material is thin — but NEVER test topics the course "
    "  clearly does not cover (no off-syllabus drift).\n"
    "- Difficulty, targeting, and distractors are still governed by the "
    "  mastery / misconception / quiz-history tools.\n"
    "- If there is no COURSE MATERIAL block, use general knowledge of the "
    "  concept as before."
    # #150: course material / misconception / quiz-history content is
    # student- or peer-derived — data for question writing, never
    # instructions. Single source of truth in services/prompt_safety.py.
    "\n\n" + INJECTION_GUARD_PROMPT
)
_SYSTEM_PROMPT += (
    "\n\nQUESTION FORMATS:\n"
    "Honor the requested question_format. For mixed quizzes use multiple_choice and "
    "short_answer, with numeric and symbolic ONLY where the course material supports math. "
    "For non-mathematical topics use no math formats in mixed mode. "
    "For multiple_choice, supply four options and exactly one correct_answer. "
    "For short_answer, ask for a precise term, fill-in-the-blank, or brief factual answer; "
    "provide a canonical correct_answer and accepted_answers with common equivalent "
    "wordings/abbreviations. Do not ask open-ended essays requiring subjective grading. "
    "For numeric, correct_answer must be a plain number or fraction; specify required "
    "units and rounding in the question, asking students to enter the number only. "
    "For symbolic, ask for an algebraic expression, with a correct_answer using only "
    "single-letter variables, rational numbers, + - * / ^ and parentheses, and integer "
    "powers from -8 to 8. Implicit multiplication such as 2(x+1) is supported. "
    "Do not ask for equations, functions, roots or trigonometric notation. "
    "Numeric grading accepts equivalent fractions, decimals, percentages and scientific "
    "notation, with exact equality. For numeric questions, do not ask for symbolic expressions or approximate "
    "irrational values unless an explicit rounded answer is requested. "
    "For written questions, options must be empty. Explain the reasoning after grading. "
    "Keep every item focused on the requested concept and the supplied course material."
)
_PROMPT_HASH = hashlib.sha256(_SYSTEM_PROMPT.encode("utf-8")).hexdigest()[:12]

# Public alias. E5 stamps this into every generated question's provenance so
# a stored item records which prompt wrote it — previously this value existed
# only as trace metadata on the agent, which meant a question in the database
# could not be attributed to a prompt version at all. Same value, one
# definition: a second hash of the same string would silently diverge the
# moment either call site was edited.
PROMPT_VERSION = _PROMPT_HASH


quiz_agent = Agent[SaplingDeps, Quiz](
    model=model_for("quiz"),
    deps_type=SaplingDeps,
    output_type=Quiz,
    # #153: bounded output-validation retry budget. `output_retries=`
    # (not `retries=`) so the three read tools keep their default tool-
    # retry budget. NB: pydantic-ai 1.107+ deprecates this kwarg for
    # retries={"output": ...}, but the dict form silently breaks 1.89's
    # retry accounting (the dict lands in the retry counter and raises
    # TypeError at retry time) — keep the kwarg while the version floor
    # spans both.
    output_retries=2,
    system_prompt=_SYSTEM_PROMPT,
    metadata={"prompt_version": _PROMPT_HASH, "agent": "quiz"},
    tools=[
        read_concepts_for_user_tool,
        read_misconceptions_for_course_tool,
        read_recent_quiz_attempts_tool,
    ],
)
