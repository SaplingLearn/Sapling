"""/api/learn/loop/* — the learning-loop tutor routes (PKG-07; spec §7, §9; A15–A20, A27).

Mounted at /api/learn/loop. Every endpoint is require_self + gate-404; every
model-calling endpoint also carries the A20 rate-limit dependency (and a
student-text endpoint the crisis screen ahead of it). The legacy learn routes
delegate to the same bodies (routes/learn.py) when the gate is true.

Split into ``services/loop/`` in #118. Each handler below is a thin wrapper
over the same-named function in that package, which holds the handler's body
verbatim; the wrapper keeps the FastAPI signature, the dependencies and the
docstring OpenAPI publishes. The route-level dependencies stay here:
`_kill_switch_first` (the spec §7 404 before anything else: the gate — the env
kill switch, then the session student's `learning_loop` flag — resolved once,
off the event loop, and carried to the handler) and `_screened` /
`_RATE_LIMITED`. A test patch must target the module that LOOKS UP the name
now (``patch_loop`` in ``tests/split_patches.py``).
"""

from __future__ import annotations

import config
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from learning import gate as loop_gate
from models import (
    ActionBody,
    ChatBody,
    CloseBody,
    LoopAttemptBody,
    LoopCheckAnswerBody,
    LoopCheckNextBody,
    LoopHintBody,
    LoopRatingBody,
    LoopReportBody,
    LoopGoalBody,
    PlanApproveBody,
    PosttestAnswerBody,
    PosttestShownBody,
    PosttestStartBody,
    PrequestionAnswerBody,
    ProbeAnswerBody,
    ProbeNextBody,
    ReviewAnswerBody,
    SelfExplainBody,
    StartSessionBody,
)
from services import crisis_support
from services.ai_budget import enforce_rate_limit
import services.loop as loop_service
from routes._docs import same_doc
from services.loop import _NOT_ENABLED


def _loop_gate_for_session(request: Request) -> bool | None:
    """The learning-loop gate for the SESSION user, resolved once per request and
    carried on `request.state.learning_loop` as `(user_id, answer)` (owner
    decision 00) — the value the handler's `_gate` (require_self first, which
    proves the body's user IS the session user) then reads instead of resolving
    again. `(None, False)` is the kill switch: off for everyone.

    A sync function, so as a dependency it runs in FastAPI's threadpool: the
    `learning_loop` flag read may reach the flag store and never runs on the
    event loop (an `async def` handler without this dependency resolves the
    gate in the threadpool itself: `services/loop/state.py::_agate`). The env
    kill switch is read first and, thrown, answers False with no read of any
    kind (no session lookup, no flag). None when no session user
    can be named (no cookie, an unapproved account): nothing is carried and the
    handler's own require_self answers. Called through the module
    (`loop_gate.…`), so a test that patches the loop's own gate name patches
    only what the handler reads."""
    carried = getattr(request.state, "learning_loop", None)
    if isinstance(carried, tuple) and len(carried) == 2:
        return carried[1]
    if not config.LEARNING_LOOP_ENABLED:
        request.state.learning_loop = (None, False)
        return False
    from services.auth_guard import get_session_user_id

    try:
        user_id = get_session_user_id(request)
    except HTTPException:
        return None
    loop_on = loop_gate.learning_loop_for_request(user_id)
    request.state.learning_loop = (user_id, loop_on)
    return loop_on


router = APIRouter()


def _kill_switch_first(request: Request) -> None:
    """The loop-off 404 BEFORE the rate limit (spec §7: every loop route 404s when the
    loop is off). Route dependencies run in order and before the handler's `_gate`,
    so a bare `enforce_rate_limit` dependency answered a thrown kill switch with 401
    (no session) or 429 instead of the 404. Off means the env kill switch (no
    session needed, no read of any kind) or the session student's `learning_loop`
    flag (read once, here, in the threadpool: a sync dependency). With
    no session and the switch not thrown it lets the request through to the
    limiter and the handler's `_gate` (require_self, then the gate's 404), as
    before the flag existed."""
    if _loop_gate_for_session(request) is False:
        raise HTTPException(status_code=404, detail=_NOT_ENABLED)


_RATE_LIMITED = [Depends(_kill_switch_first), Depends(enforce_rate_limit)]


def _screened(surface: str, *fields: str, respond) -> list:
    """`_RATE_LIMITED` for a route that takes student-written text: the crisis
    screen sits between the kill switch and the rate limit
    (docs/safety/crisis-support.md). A crisis turn is answered with the card
    before the limiter is even read, so it never meets a 429 and consumes no
    unit; any other request meets the same two dependencies as before."""
    return [
        Depends(_kill_switch_first),
        crisis_support.screened(surface, *fields, respond=respond),
        Depends(enforce_rate_limit),
    ]


# ── Endpoints ──────────────────────────────────────────────────────────────


@router.get("/status")
@same_doc(loop_service.status)
def status(request: Request, user_id: str = Query(...), session_id: str = Query(...)) -> dict:
    return loop_service.status(request, user_id, session_id)


@router.get("/sessions")
@same_doc(loop_service.list_open_sessions)
def list_open_sessions(
    request: Request,
    user_id: str = Query(...),
    course_id: str = Query(...),
    resume: str | None = Query(None),
) -> dict:
    return loop_service.list_open_sessions(request, user_id, course_id, resume)


@router.post("/chat", dependencies=_screened("loop_chat", "message", respond=crisis_support.turn_response))
@same_doc(loop_service.chat)
async def chat(body: ChatBody, request: Request):
    return await loop_service.chat(body, request)


@router.post("/chat/stream", dependencies=_screened("loop_chat", "message", respond=crisis_support.turn_stream))
@same_doc(loop_service.chat_stream)
async def chat_stream(body: ChatBody, request: Request):
    return await loop_service.chat_stream(body, request)


# crisis support: a crisis answer leaves the item posed and ungraded (no claim, no evidence)
@router.post(
    "/check/answer",
    dependencies=_screened("loop_check_answer", "answer", "reason", respond=crisis_support.turn_response),
)
@same_doc(loop_service.check_answer)
async def check_answer(body: LoopCheckAnswerBody, request: Request):
    return await loop_service.check_answer(body, request)


@router.post(
    "/check/answer/stream",
    dependencies=_screened("loop_check_answer", "answer", "reason", respond=crisis_support.turn_stream),
)
@same_doc(loop_service.check_answer_stream)
async def check_answer_stream(body: LoopCheckAnswerBody, request: Request):
    return await loop_service.check_answer_stream(body, request)


@router.post("/rating", dependencies=_RATE_LIMITED)
@same_doc(loop_service.rating)
def rating(body: LoopRatingBody, request: Request) -> dict:
    return loop_service.rating(body, request)


@router.post("/report", dependencies=_RATE_LIMITED)
@same_doc(loop_service.report_item)
def report_item(body: LoopReportBody, request: Request) -> dict:
    return loop_service.report_item(body, request)


@router.post("/posttest/start", dependencies=_RATE_LIMITED)
@same_doc(loop_service.posttest_start)
def posttest_start(body: PosttestStartBody, request: Request) -> dict:
    return loop_service.posttest_start(body, request)


# crisis support: a crisis answer leaves the pose open and unclaimed, nothing graded
@router.post(
    "/posttest/answer",
    dependencies=_screened(
        "loop_posttest_answer", "answer", "reason", respond=crisis_support.plain_response(graded=False)
    ),
)
@same_doc(loop_service.posttest_answer)
async def posttest_answer(body: PosttestAnswerBody, request: Request):
    return await loop_service.posttest_answer(body, request)


@router.post("/posttest/shown")
@same_doc(loop_service.posttest_shown)
def posttest_shown(body: PosttestShownBody, request: Request) -> dict:
    return loop_service.posttest_shown(body, request)


@router.get("/posttest/due")
@same_doc(loop_service.posttest_due)
def posttest_due(request: Request, user_id: str = Query("")) -> dict:
    return loop_service.posttest_due(request, user_id)


# crisis support: a crisis attempt stops the hint flow — nothing counts toward a hint
@router.post(
    "/step/attempt",
    dependencies=_screened(
        "loop_step_attempt",
        "attempt_text",
        respond=crisis_support.plain_response(genuine=False, counted=False),
    ),
)
@same_doc(loop_service.step_attempt)
def step_attempt(body: LoopAttemptBody, request: Request) -> dict:
    return loop_service.step_attempt(body, request)


@router.post("/hint")
@same_doc(loop_service.hint)
def hint(body: LoopHintBody, request: Request) -> dict:
    return loop_service.hint(body, request)


@router.post("/action", dependencies=_RATE_LIMITED)
@same_doc(loop_service.action)
async def action(body: ActionBody, request: Request):
    return await loop_service.action(body, request)


# crisis support: a crisis topic or goal opens no session (nothing is stashed or
# written). The legacy /api/learn routes that delegate here screen first themselves.
@router.post(
    "/start-session",
    dependencies=_screened("loop_start", "topic", "goal.text", respond=crisis_support.start_response),
)
@same_doc(loop_service.start_session)
async def start_session(body: StartSessionBody, request: Request):
    return await loop_service.start_session(body, request)


@router.post(
    "/start-session/stream",
    dependencies=_screened("loop_start", "topic", "goal.text", respond=crisis_support.start_stream),
)
@same_doc(loop_service.start_session_stream)
async def start_session_stream(body: StartSessionBody, request: Request):
    return await loop_service.start_session_stream(body, request)


@router.post("/check/next")
@same_doc(loop_service.check_next)
def check_next(body: LoopCheckNextBody, request: Request) -> dict:
    return loop_service.check_next(body, request)


@router.post(
    "/prequestion/answer",
    dependencies=_screened("loop_prequestion_answer", "answer", "reason", respond=crisis_support.turn_response),
)
@same_doc(loop_service.prequestion_answer)
async def prequestion_answer(body: PrequestionAnswerBody, request: Request):
    return await loop_service.prequestion_answer(body, request)


@router.post(
    "/prequestion/answer/stream",
    dependencies=_screened("loop_prequestion_answer", "answer", "reason", respond=crisis_support.turn_stream),
)
@same_doc(loop_service.prequestion_answer_stream)
async def prequestion_answer_stream(body: PrequestionAnswerBody, request: Request):
    return await loop_service.prequestion_answer_stream(body, request)


# ── The self-explanation reply (spec §13 A139) ─────────────────────────────


@router.post(
    "/self-explain",
    dependencies=_screened("loop_self_explain", "reply", respond=crisis_support.plain_response(recorded=False)),
)
@same_doc(loop_service.self_explain_reply)
def self_explain_reply(body: SelfExplainBody, request: Request) -> dict:
    return loop_service.self_explain_reply(body, request)


@router.post("/close")
@same_doc(loop_service.close)
async def close(body: CloseBody, request: Request) -> dict:
    return await loop_service.close(body, request)


@router.post("/goal")
@same_doc(loop_service.set_goal)
def set_goal(body: LoopGoalBody, request: Request) -> dict:
    return loop_service.set_goal(body, request)


@router.post("/probe/next")
@same_doc(loop_service.probe_next)
def probe_next(body: ProbeNextBody, request: Request) -> dict:
    return loop_service.probe_next(body, request)


@router.post("/probe/answer")
@same_doc(loop_service.probe_answer)
async def probe_answer(body: ProbeAnswerBody, request: Request) -> dict:
    return await loop_service.probe_answer(body, request)


@router.get("/plan")
@same_doc(loop_service.plan_get)
def plan_get(request: Request, user_id: str = Query(...), session_id: str = Query(...)) -> dict:
    return loop_service.plan_get(request, user_id, session_id)


@router.post("/plan/approve")
@same_doc(loop_service.plan_approve)
def plan_approve(body: PlanApproveBody, request: Request) -> dict:
    return loop_service.plan_approve(body, request)


@router.get("/review/next")
@same_doc(loop_service.review_next)
def review_next(
    request: Request, user_id: str = Query(...), course_id: str | None = Query(None)
) -> dict:
    return loop_service.review_next(request, user_id, course_id)


@router.post("/review/answer")
@same_doc(loop_service.review_answer)
async def review_answer(body: ReviewAnswerBody, request: Request) -> dict:
    return await loop_service.review_answer(body, request)


@router.get("/review/summary")
@same_doc(loop_service.review_summary)
def review_summary(
    request: Request, user_id: str = Query(...), course_id: str | None = Query(None)
) -> dict:
    return loop_service.review_summary(request, user_id, course_id)


@router.get("/review/active")
@same_doc(loop_service.review_active)
def review_active(request: Request, user_id: str = Query(...)) -> dict:
    return loop_service.review_active(request, user_id)
