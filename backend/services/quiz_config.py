"""Quiz selector configuration — the single source of truth (#540 A2).

Both the Pydantic request model (`models.GenerateQuizBody`) and the
`GET /api/quiz/config` endpoint read these constants, so the client can
build its selectors from the endpoint and never again offer a value the
route rejects (the pre-#540 UI offered "15 questions" against a le=10
cap, and an "Adaptive" difficulty the route 400'd).

Standalone constants module: no imports from models/routes/services so
it can be imported from anywhere without cycles.
"""

QUIZ_MIN_QUESTIONS = 1

# The cap is a Gemini structured-output constraint before it is a product
# choice. Measured 2026-08-12 (#540 A2, scripts/bench_quiz_question_cap.py):
# on gemini-2.5-flash-lite a 10-question schema serves at ~5.1s median
# (~260 in / ~1500 out tokens), while 15- and 20-question schemas are
# REJECTED outright — HTTP 400 INVALID_ARGUMENT "too many states for
# serving" — before any generation happens. 10 is therefore the hard
# ceiling for a single structured call on the quiz task's model tier
# (matches agents/quiz.py:77-80); raising it requires a model-tier change
# or batched generation, which is #537 revamp scope.
QUIZ_MAX_QUESTIONS = 10

# The selector values the product offers (config endpoint → client).
# Must all sit within [QUIZ_MIN_QUESTIONS, QUIZ_MAX_QUESTIONS].
QUIZ_NUM_QUESTION_OPTIONS = (3, 5, 10)

# Concrete difficulties — what the agent can emit per question and what
# quiz_attempts.difficulty accepted before the adaptive migration.
CONCRETE_DIFFICULTIES = ("easy", "medium", "hard")

# Request-side difficulties: 'adaptive' asks the agent to pick the
# per-question mix itself (A1); the response reports what it chose via
# `resolved_difficulty`.
REQUESTED_DIFFICULTIES = CONCRETE_DIFFICULTIES + ("adaptive",)

# MCQ-only today — mirrors agents/quiz.py::QuizQuestionType. Grows when
# the #537 revamp adds real short-answer grading.
QUIZ_QUESTION_TYPES = ("mcq",)


def quiz_config_payload() -> dict:
    """The GET /api/quiz/config response body."""
    return {
        "num_questions": {
            "min": QUIZ_MIN_QUESTIONS,
            "max": QUIZ_MAX_QUESTIONS,
            "options": list(QUIZ_NUM_QUESTION_OPTIONS),
        },
        "difficulties": list(REQUESTED_DIFFICULTIES),
        "question_types": list(QUIZ_QUESTION_TYPES),
    }
