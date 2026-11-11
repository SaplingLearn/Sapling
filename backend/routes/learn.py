"""
backend/routes/learn.py — the /api/learn HTTP surface (the AI tutor).

Split into ``services/tutor/`` in #118. Each handler below is a thin wrapper
over the same-named function in that package, which holds the handler's body
verbatim; the wrapper keeps the FastAPI signature and the docstring OpenAPI
publishes. Every helper and constant that used to live in this file moved
under its old name (``services/tutor/__init__.py`` has the map) and is
re-exported here, so ``from routes.learn import _foo`` keeps working. A test
patch must target the module that LOOKS UP the name now (``patch_tutor`` in
``tests/split_patches.py``).
"""
from __future__ import annotations

from fastapi import APIRouter, Query, Request

import services.tutor as tutor_service
from db.scope import service_route
from learning.gate import learning_loop_for_request
from models import StartSessionBody, ChatBody, EndSessionBody, ActionBody, ModeSwitchBody, RenameSessionBody
from routes._docs import same_doc

# ── Re-exports: every name that moved out of this file (#118) ────────────────
from services.tutor.course import (  # noqa: F401  (re-export, #118)
    _get_catalog_chunk,
    _get_course_id_for_topic,
    _get_course_info,
    _get_session_offering_id,
    _session_course_id,
    _session_offering,
)
from services.tutor.messages import (  # noqa: F401  (re-export, #118)
    _TURN_MESSAGE_NS,
    _load_message_history,
    _message_row,
    _persisted_turn,
    _replay_events,
    _save_turn_rows,
    _turn_message_id,
    _turn_row_ids,
    save_message,
    save_message_sync,
)
from services.tutor.pending import (  # noqa: F401  (re-export, #118)
    _consume_pending,
    _consume_pending_off_loop,
    _open_turn_session,
    get_user_name,
)
from services.tutor.pending import (  # noqa: F401  (re-export, #118)
    _materialize_turn_session,
    _require_turn_session,
)
from services.tutor.run import (  # noqa: F401  (re-export, #118)
    KILL_SWITCH_BUDGET_BAND,
    _kill_switch_budget,
    _usage_session_id,
    _CONTINUATION_INSTRUCTIONS,
    _CONTINUATION_NUDGE,
    _CONTINUATION_RUN_KEYS,
    _PREF_MODEL_NAMES,
    _PRO_THINKING_BUDGET,
    _build_deep_turn_model_settings,
    _continuation_text,
    _new_run_text,
    _observe_persisted_turn,
    _prepare_chat_run,
    _ran_on,
    _resolve_model_pref,
)
from services.tutor.sessions import (  # noqa: F401  (re-export, #118)
    _SESSION_COUNT_CONCURRENCY,
    MODE_DISPLAY_NAMES,
    SESSION_LIST_MAX,
    _session_summary,
    _stored_session_summary,
)
from services.tutor.turns import (  # noqa: F401  (re-export, #118)
    _MODEL_TROUBLE_DETAIL,
    _USAGE_LIMIT_DETAIL,
    _action_turn,
    _agent_turn_or_http_error,
    _chat_turn_json,
    _chat_via_agent,
    _start_session_agent,
)
# Names this file imported from the session store under its own aliases.
from services.tutor_sessions import (  # noqa: F401  (re-export, #118)
    PENDING_SESSIONS,
    SESSION_NOT_FOUND as _SESSION_NOT_FOUND,
    elapsed_minutes as _elapsed_minutes,
    row_may_exist as _session_row_may_exist,
)

router = APIRouter()


def _loop_delegate(name: str):
    """The learning loop's handler `name` (its body in services/loop/, #118),
    resolved lazily, at the hand-off: nothing of the loop loads with the
    legacy tutor (the PKG-06 inertness probe imports the app with the loop
    route stubbed). Here, not in services/tutor/: the tutor body is handed this
    callable and calls it at its hand-off point (spec §7), so the tutor domain
    never imports the loop's.

    #115 (spec §13 A148): a delegated request runs as the loop router does,
    as the service role under `db_user_scope` — the loop's tables are
    service-only. Marked on the request's shared state (not a ContextVar), so
    a streamed loop response keeps it after this handler returns. Marked when
    the body hands off, never before: the checks ahead of the hand-off run as
    the student."""

    def delegate(body, request: Request):
        import services.loop as loop_service

        service_route(request)
        return getattr(loop_service, name)(body, request)

    return delegate


def _loop_for(user_id: str, name: str):
    """Owner decision 00 (A38): the learning-loop gate, evaluated ONCE at
    route entry. The loop's handler when it is on (the default), else None:
    the tutor body then runs the kill-switch path (spec §11.6). The gate is
    the env kill switch alone (PKG-14b): no read of any kind, so evaluating it
    before the body's own checks changes nothing they do."""
    return _loop_delegate(name) if learning_loop_for_request(user_id) else None


@router.post("/start-session")
@same_doc(tutor_service.start_session)
async def start_session(body: StartSessionBody, request: Request):
    return await tutor_service.start_session(
        body, request, loop_handler=_loop_for(body.user_id, "start_session")
    )


@router.post("/chat")
@same_doc(tutor_service.chat)
async def chat(body: ChatBody, request: Request):
    return await tutor_service.chat(body, request, loop_handler=_loop_for(body.user_id, "chat"))


@router.post("/chat/stream")
@same_doc(tutor_service.chat_stream)
async def chat_stream(body: ChatBody, request: Request):
    return await tutor_service.chat_stream(
        body, request, loop_handler=_loop_for(body.user_id, "chat_stream")
    )


@router.post("/start-session/stream")
@same_doc(tutor_service.start_session_stream)
async def start_session_stream(body: StartSessionBody, request: Request):
    return await tutor_service.start_session_stream(
        body, request, loop_handler=_loop_for(body.user_id, "start_session_stream")
    )


@router.post("/end-session")
@same_doc(tutor_service.end_session)
def end_session(body: EndSessionBody, request: Request):
    # A body without user_id is the session user's (the body resolves it);
    # the gate reads no user, so it is evaluated on whatever id is known.
    return tutor_service.end_session(
        body, request, loop_handler=_loop_for(body.user_id, "end_session")
    )


@router.get("/sessions/{user_id}")
@same_doc(tutor_service.list_sessions)
async def list_sessions(user_id: str, request: Request, limit: int = 10):
    return await tutor_service.list_sessions(user_id, request, limit)


@router.patch("/sessions/{session_id}")
@same_doc(tutor_service.rename_session)
def rename_session(session_id: str, body: RenameSessionBody, request: Request):
    return tutor_service.rename_session(session_id, body, request)


@router.delete("/sessions/{session_id}")
@same_doc(tutor_service.delete_session)
def delete_session(session_id: str, request: Request, user_id: str | None = Query(None)):
    return tutor_service.delete_session(session_id, request, user_id)


@router.get("/sessions/{session_id}/resume")
@same_doc(tutor_service.resume_session)
async def resume_session(session_id: str, request: Request):
    return await tutor_service.resume_session(session_id, request)


@router.post("/action")
@same_doc(tutor_service.action)
async def action(body: ActionBody, request: Request):
    return await tutor_service.action(body, request, loop_handler=_loop_for(body.user_id, "action"))


@router.post("/mode-switch")
@same_doc(tutor_service.mode_switch)
async def mode_switch(body: ModeSwitchBody, request: Request):
    return await tutor_service.mode_switch(body, request)
