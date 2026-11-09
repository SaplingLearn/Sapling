"""
backend/routes/quiz.py — the /api/quiz HTTP surface.

Split into ``services/quiz/`` in #118. Each handler below is a thin wrapper
over the same-named function in that package, which holds the handler's body
verbatim; the wrapper keeps the FastAPI signature and the docstring OpenAPI
publishes. Every helper, constant and class that used to live in this file
moved under its old name (``services/quiz/__init__.py`` has the map) and is
re-exported here, so ``from routes.quiz import _foo`` keeps working. A test
patch must target the module that LOOKS UP the name now (see
``tests/split_patches.py``).
"""
from fastapi import APIRouter, BackgroundTasks, Request

import services.quiz as quiz_service
from models import AnswerQuestionBody, GenerateQuizBody, SubmitQuizBody
from services.quiz.config import quiz_config_payload

# ── Re-exports: every name that moved out of this file (#118) ────────────────
from services.quiz.attempts import (  # noqa: F401  (re-export, #118)
    _abandon_cutoff,
    _activity_filters,
    _already_completed,
    _aload_owned_attempt,
    _arecent_activity,
    _attempt_not_found,
    _attempt_status,
    _insert_attempt,
    _latest_answers,
    _load_owned_attempt,
    _parse_ts,
    _recent_activity,
    _refuse_if_abandoned,
    _refuse_if_completed,
    _sweep_abandoned,
)
from services.quiz.generation import (  # noqa: F401  (re-export, #118)
    _MCQ_TOPUP_RULE,
    _PREF_MODEL_NAMES,
    _WRITTEN_TOPUP_RULE,
    GeneratedQuiz,
    _generate_or_502,
    _log_generation_failed,
    _quiz_via_agent,
    _record_answer_key_flag,
    _resolve_model_pref,
    _topup_format_rule,
)
from services.quiz.grounding import (  # noqa: F401  (re-export, #118)
    _EMPTY_MATERIAL,
    _RAG_K,
    _UNKNOWN_MATERIAL,
    BuCodeLookup,
    CourseMaterial,
    CourseRow,
    _course_chunk_coverage,
    _course_material,
    _course_row,
    _do_not_repeat_block,
    _log_rag_uncovered,
    _resolve_bu_code,
)
from services.quiz.history import _MAX_HISTORY_OFFSET  # noqa: F401  (re-export, #118)
from services.quiz.limits import (  # noqa: F401  (re-export, #118)
    _USAGE_PAGE,
    _daily_spend_exceeded,
    _refund_generate_slot,
)
from services.quiz.practice import (  # noqa: F401  (re-export, #118)
    ReservedMisses,
    _missed_something,
    _renumber,
    _reserved_misses,
)
from services.quiz.submission import (  # noqa: F401  (re-export, #118)
    PROMPTS_DIR,
    _gamification_block,
    _grade_submission,
    _load_prompt,
    _release_submit_claim,
)
from services.quiz.wire import (  # noqa: F401  (re-export, #118)
    _ABBREVIATIONS,
    _CUT_BEFORE_NEWLINE,
    _DIFFICULTY_RANK,
    _INTERNAL_QUESTION_KEYS,
    _KEYLESS_OPTION_KEYS,
    _KEYLESS_QUESTION_KEYS,
    _MAX_ANSWER_CHARS,
    _MCQ_OPTIONS,
    _MIN_OPTIONS,
    _OPTION_LABELS,
    _SENTENCE_BREAK,
    _SHORT_ANSWER_MAX_WORDS,
    _SYMBOLIC_LETTER_RUN,
    _SYMBOLIC_NAMES,
    _SYMBOLIC_WORD_MIN,
    _WHOLE_STEM_ENDINGS,
    _agent_question_to_wire,
    _client_questions,
    _is_sentence,
    _is_symbolic_word,
    _is_wire_question,
    _resolved_difficulty,
    _strip_answer_key,
    _unfair_written_key,
    _validate_wire_question,
    _written_response_text,
)

router = APIRouter()


def _same_doc(source):
    """Give a wrapper its body's docstring BEFORE `router` registers it.

    FastAPI publishes a handler's docstring as the OpenAPI description, so the
    wrapper must carry it for /openapi.json to stay byte-identical across the
    #118 split. Only the docstring: `functools.wraps` would also set
    `__wrapped__`, and FastAPI would then read the body's parameter
    annotations (starlette types) instead of this wrapper's.
    """
    def apply(fn):
        fn.__doc__ = source.__doc__
        return fn
    return apply


# Request-side difficulties live in services/quiz/config.py (#540 A2):
# the concrete trio matches the quiz_attempts.difficulty CHECK (0025,
# extended with 'adaptive' by the #540 migration); 'adaptive' hands the
# per-question mix decision to the agent (A1).


@router.get("/config")
def quiz_config():
    """Selector options for the quiz UI (#540 A2). Single source of truth:
    the same constants bound the Pydantic request model, so a client that
    builds its selects from this payload can never send a value the route
    rejects. No user data, no auth needed."""
    return quiz_config_payload()


@router.post("/generate")
@_same_doc(quiz_service.generate_quiz)
async def generate_quiz(body: GenerateQuizBody, request: Request):
    return await quiz_service.generate_quiz(body, request)


@router.get("/attempts")
@_same_doc(quiz_service.list_attempts)
async def list_attempts(
    request: Request,
    user_id: str,
    limit: int = 20,
    offset: int = 0,
):
    return await quiz_service.list_attempts(request, user_id, limit, offset)


@router.get("/attempts/{attempt_id}")
@_same_doc(quiz_service.get_attempt)
async def get_attempt(attempt_id: str, request: Request):
    return await quiz_service.get_attempt(attempt_id, request)


@router.post("/attempts/{attempt_id}/answer")
@_same_doc(quiz_service.answer_question)
async def answer_question(attempt_id: str, body: AnswerQuestionBody, request: Request):
    return await quiz_service.answer_question(attempt_id, body, request)


@router.post("/attempts/{attempt_id}/abandon")
@_same_doc(quiz_service.abandon_attempt)
async def abandon_attempt(attempt_id: str, request: Request):
    return await quiz_service.abandon_attempt(attempt_id, request)


@router.post("/submit")
@_same_doc(quiz_service.submit_quiz)
def submit_quiz(body: SubmitQuizBody, background_tasks: BackgroundTasks, request: Request):
    return quiz_service.submit_quiz(body, background_tasks, request)
