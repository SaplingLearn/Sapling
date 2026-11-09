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
from services.tutor.run import (  # noqa: F401  (re-export, #118)
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


@router.post("/start-session")
@same_doc(tutor_service.start_session)
async def start_session(body: StartSessionBody, request: Request):
    return await tutor_service.start_session(body, request)


@router.post("/chat")
@same_doc(tutor_service.chat)
async def chat(body: ChatBody, request: Request):
    return await tutor_service.chat(body, request)


@router.post("/chat/stream")
@same_doc(tutor_service.chat_stream)
async def chat_stream(body: ChatBody, request: Request):
    return await tutor_service.chat_stream(body, request)


@router.post("/start-session/stream")
@same_doc(tutor_service.start_session_stream)
async def start_session_stream(body: StartSessionBody, request: Request):
    return await tutor_service.start_session_stream(body, request)


@router.post("/end-session")
@same_doc(tutor_service.end_session)
def end_session(body: EndSessionBody, request: Request):
    return tutor_service.end_session(body, request)


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
    return await tutor_service.action(body, request)


@router.post("/mode-switch")
@same_doc(tutor_service.mode_switch)
async def mode_switch(body: ModeSwitchBody, request: Request):
    return await tutor_service.mode_switch(body, request)
