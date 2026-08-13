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

# MCQ-only today — the SAME token as agents/quiz.py::QuizQuestionType and
# the per-question wire `type` field, so a client keying on this config can
# compare against real payloads. Grows when the #537 revamp adds real
# short-answer grading.
QUIZ_QUESTION_TYPES = ("multiple_choice",)

# ── Mastery model (#543 E1) ─────────────────────────────────────────────────
#
# How one quiz moves a concept's mastery score:
#
#     after = clamp01(before + correct*MASTERY_DELTA_PER_CORRECT
#                            - wrong*MASTERY_DELTA_PER_WRONG)
#
# The pedagogy these numbers encode: mastery is earned faster than it is
# lost (0.03 vs 0.02), so a student who mostly succeeds trends upward even
# with occasional misses, and a bad quiz dents progress without erasing it.
# ~17 consecutive correct answers take a concept from 0 to mastered, which
# is roughly three or four full quizzes — slow enough that the tier means
# something, fast enough to be visible within a study session.
#
# THE OPEN QUESTION (deliberately NOT answered here — see
# docs/quiz-mastery-model.md): the delta is per-ITEM and flat, so a
# 10-question hard quiz moves mastery 3.3x as much as a 3-question easy
# one, and a hard item counts exactly as much as an easy one. Scaling by
# difficulty and/or normalizing by quiz length are both defensible; each
# changes the numbers the #393 E2E journey pins (+0.09 for 3/3). #543
# lands this seam ONLY — the revamp (#537) decides the model, and any
# change ships in the same commit as the journey update.
MASTERY_DELTA_PER_CORRECT = 0.03
MASTERY_DELTA_PER_WRONG = 0.02


def mastery_after(before: float, *, score: int, total: int) -> float:
    """The post-quiz mastery score, clamped to [0, 1]."""
    wrong = max(0, total - score)
    raw = (
        before
        + score * MASTERY_DELTA_PER_CORRECT
        - wrong * MASTERY_DELTA_PER_WRONG
    )
    return max(0.0, min(1.0, raw))


# ── Cost + abuse guards (#544 F1/F2) ────────────────────────────────────────
#
# Generation is an unbounded LLM call behind a button: before #544 nothing
# stopped a held-down key or a scripted loop from spending real money.
#
# The rate limit is sized for a human: a student comparing difficulties or
# retaking a concept might legitimately generate a handful of quizzes in a
# few minutes; nobody legitimately generates 10 in one.
QUIZ_GENERATE_RATE_LIMIT = 8
QUIZ_GENERATE_RATE_WINDOW_SEC = 300   # 5 minutes

# Daily per-user LLM spend ceiling. The SPEND it measures is cross-feature
# (llm_usage records every agent call, not just quiz ones), but the ceiling
# is only ENFORCED on quiz generation — the one unbounded LLM call behind a
# button. Other entry points stay unguarded for now; moving this into a
# shared guard is its own piece of work, not something to imply here.
# A generation on the default flash-lite tier costs well under a cent, so
# this is ~2 orders of magnitude above any real study day — it exists to
# bound a runaway, not to ration normal use. Deliberately fail-OPEN: if the
# usage read errors we serve the quiz rather than denying every student.
QUIZ_DAILY_SPEND_CAP_USD = 2.00

# Wall-clock ceiling on one generation (agent run incl. its tool calls).
# Past this the student is staring at a spinner and would rather be told to
# try again; the request also stops holding a worker slot.
QUIZ_GENERATION_TIMEOUT_SEC = 90


# ── Generation honesty (#543 E2) ────────────────────────────────────────────
#
# Questions whose correct_answer doesn't match an option verbatim are
# dropped (routes/quiz.py::_agent_question_to_wire). If enough of a quiz
# drops, one bounded top-up run refills it — bounded because a retry loop
# on a drifting model burns tokens without converging, and a slightly
# short quiz beats a slow one.
QUIZ_TOPUP_DROP_RATIO = 0.34   # >1/3 of the requested count lost → top up
QUIZ_TOPUP_MAX_RETRIES = 1


# #542 D2: an in-progress attempt older than this is considered abandoned
# (derived status + the lazy per-user sweep that stamps abandoned_at).
# 24h: a quiz is a single sitting — anything paused across a day is not
# coming back, and the resume endpoint stops offering it. Deliberately
# generous vs. a session-length TTL so a student who steps away mid-quiz
# for hours can still resume.
QUIZ_ATTEMPT_ABANDON_TTL_HOURS = 24


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
