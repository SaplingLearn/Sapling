"""
backend/services/quiz/history.py — moved from routes/quiz.py (#118).

Attempt history and resume: the GET /attempts and GET /attempts/{id}
handler bodies (#542 D2/D4, #760).

Function bodies are verbatim from the route; names (leading
underscores included) are unchanged, and routes/quiz.py re-exports them.
"""
import logging

from starlette.concurrency import run_in_threadpool
from starlette.requests import Request

from db.connection import table
from services.auth_guard import require_self, guard_off_loop
from services.quiz.errors import QuizAPIError, QuizErrorCode
from services.encryption import decrypt_json_column
from services.quiz.attempts import (
    _aload_owned_attempt,
    _arecent_activity,
    _attempt_status,
    _sweep_abandoned,
)
from services.quiz.wire import _is_wire_question, _strip_answer_key, _written_response_text

# Log records keep the name they had in routes/quiz.py before the #118 split:
# the move must not change what an operator (or a caplog test) filters on.
logger = logging.getLogger("routes.quiz")


# PostgREST passes `offset` to Postgres as a bigint; anything past this is
# a client bug, and an empty page is a better answer than a 500.
_MAX_HISTORY_OFFSET = 1_000_000


async def list_attempts(
    request: Request,
    user_id: str,
    limit: int = 20,
    offset: int = 0,
):
    """#542 D4: paginated attempt history for the signed-in user — the
    plaintext scalars (#521/#527) finally get their reader. No question
    payloads here (and therefore no answer keys).

    #117: the first handler converted end to end onto the async DB seam
    (docs/design/async-db-client.md §4): its reads are `a*` calls, and the
    sync guard and the sweep's writes hop to a worker thread."""
    await guard_off_loop(require_self, user_id, request)
    limit = max(1, min(limit, 100))
    # Clamp BOTH ends: an unbounded offset is stringified into PostgREST's
    # offset param and Postgres rejects it as bigint-out-of-range — a 500
    # where an empty page is the honest answer.
    offset = max(0, min(offset, _MAX_HISTORY_OFFSET))
    # Lazy lifecycle sweep (#542 D2) — the read paths keep statuses honest.
    await run_in_threadpool(_sweep_abandoned, user_id)

    rows, total = await table("quiz_attempts").aselect_with_count(
        "id,concept_node_id,difficulty,score,total,mastery_before,"
        "mastery_after,completed_at,abandoned_at,created_at",
        filters={"user_id": f"eq.{user_id}"},
        # `id` is the unique tiebreaker: without it two attempts sharing a
        # created_at have undefined relative order across the separate
        # queries serving page N and N+1, so a row can repeat or vanish.
        # Same idiom as gamification_service.events_since's xp_events paging.
        order="created_at.desc,id.desc",
        limit=limit,
        offset=offset,
    )
    rows = rows or []

    node_ids = sorted({r["concept_node_id"] for r in rows if r.get("concept_node_id")})
    nodes: dict[str, dict] = {}
    if node_ids:
        node_rows = await table("graph_nodes").aselect(
            "id,concept_name,course_id",
            filters={"id": f"in.({','.join(node_ids)})", "user_id": f"eq.{user_id}"},
        ) or []
        nodes = {n["id"]: n for n in node_rows}

    # #760: derive status with the same answer activity GET /attempts/{id}
    # uses, or the two disagree about an old-but-active attempt (the list
    # said abandoned while the attempt itself said in_progress).
    open_ids = {
        r["id"] for r in rows
        if not r.get("completed_at") and not r.get("abandoned_at")
    }
    try:
        activity = await _arecent_activity(open_ids)
    except Exception:
        logger.exception("quiz: history activity read failed user=%s", user_id)
        activity = {}

    attempts = []
    for r in rows:
        node = nodes.get(r.get("concept_node_id")) or {}
        before, after = r.get("mastery_before"), r.get("mastery_after")
        delta = round(after - before, 4) if before is not None and after is not None else None
        attempts.append({
            "quiz_id": r["id"],
            "status": _attempt_status(r, last_activity_at=activity.get(r["id"])),
            "concept_node_id": r.get("concept_node_id"),
            "concept_name": node.get("concept_name"),
            "course_id": node.get("course_id"),
            "score": r.get("score"),
            "total": r.get("total"),
            "difficulty": r.get("difficulty"),
            "mastery_before": before,
            "mastery_after": after,
            "mastery_delta": delta,
            "created_at": r.get("created_at"),
            "completed_at": r.get("completed_at"),
        })
    return {"total": total, "attempts": attempts, "limit": limit, "offset": offset}


async def get_attempt(attempt_id: str, request: Request):
    """#542 D2: resume state for one attempt — enough to rebuild an
    in-progress quiz client-side: questions WITHOUT the answer key, plus
    the responses already recorded through /answer."""
    attempt = await _aload_owned_attempt(attempt_id, request)

    responses = await table("quiz_responses").aselect(
        "question_index,selected_index,answer_text,is_correct,time_ms,confidence,answered_at",
        filters={"attempt_id": f"eq.{attempt_id}"},
        order="question_index.asc",
    ) or []
    responses = [
        {**r, "answer_text": _written_response_text(r) if r.get("answer_text") else None}
        for r in responses
    ]
    last_activity = max(
        (r.get("answered_at") for r in responses if r.get("answered_at")),
        default=None,
    )
    status = _attempt_status(attempt, last_activity_at=last_activity)
    # Answering keeps an attempt alive, so exempt it from the sweep.
    await run_in_threadpool(
        _sweep_abandoned, attempt["user_id"],
        active_attempt_ids={attempt_id} if status == "in_progress" else None,
    )

    questions = decrypt_json_column(attempt["questions_json"]) or []
    if questions and not all(_is_wire_question(q) for q in questions):
        # A stored shape this code doesn't recognise has no safe keyless
        # projection — passing it through would ship whatever key it holds
        # (legacy rows store the answer under `a`). Refuse the resume.
        logger.warning(
            "quiz: attempt %s stores questions in an unrecognised shape; "
            "refusing to resume", attempt_id,
        )
        raise QuizAPIError(
            status_code=409,
            code=QuizErrorCode.QUIZ_ATTEMPT_NOT_RESUMABLE,
            message="This quiz can't be resumed. Start a new one.",
        )
    # Only an in-progress attempt hands back questions: a completed or
    # abandoned one would otherwise let a client keep answering (the write
    # paths refuse it, but there's no reason to ship the payload at all).
    resumable = status == "in_progress"
    return {
        "quiz_id": attempt["id"],
        "status": status,
        "resumable": resumable,
        "difficulty": attempt.get("difficulty"),
        "concept_node_id": attempt.get("concept_node_id"),
        "questions": _strip_answer_key(questions) if resumable else [],
        "responses": responses,
        "score": attempt.get("score"),
        "total": attempt.get("total"),
        "mastery_before": attempt.get("mastery_before"),
        "mastery_after": attempt.get("mastery_after"),
        "created_at": attempt.get("created_at"),
        "completed_at": attempt.get("completed_at"),
    }
