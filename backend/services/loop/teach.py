"""The teach turns: POST /chat, /chat/stream, /action, /start-session and
/start-session/stream (the legacy /api/learn routes delegate here).
"""
from __future__ import annotations

import asyncio
from starlette.requests import Request
from models import ActionBody, ChatBody, StartSessionBody
from services.tutor import _consume_pending_off_loop
from services.auth_guard import guard_off_loop

from services.loop.flags import _ACTION_PROMPTS
from services.loop.state import _gate, _teaching_open
from services.loop.turn import _LoopTurn
from services.loop.opener import _LoopOpener
from services.loop.runner import _json_turn, _sse


async def chat(body: ChatBody, request: Request):
    loop_on = await guard_off_loop(_gate, body.user_id, request)
    await _consume_pending_off_loop(body.session_id, body.user_id)
    await asyncio.to_thread(_teaching_open, body.session_id, body.user_id)  # #117: off the loop
    return await _json_turn(
        lambda: _LoopTurn(body=body, request=request, message=body.message, loop_on=loop_on),
        "loop chat agent",
    )


async def chat_stream(body: ChatBody, request: Request):
    loop_on = await guard_off_loop(_gate, body.user_id, request)
    await _consume_pending_off_loop(body.session_id, body.user_id)
    await asyncio.to_thread(_teaching_open, body.session_id, body.user_id)  # #117: off the loop
    return _sse(_LoopTurn(body=body, request=request, message=body.message, loop_on=loop_on))


async def action(body: ActionBody, request: Request):
    """An "[ACTION: ...]" turn: in the check phase a hint at the item's current
    rung, otherwise the current phase. Assistant-only persistence; never graded
    (invariant 26)."""
    loop_on = await guard_off_loop(_gate, body.user_id, request)
    await _consume_pending_off_loop(body.session_id, body.user_id)
    await asyncio.to_thread(_teaching_open, body.session_id, body.user_id)  # #117: off the loop
    message = f"[ACTION: {_ACTION_PROMPTS.get(body.action_type, '')}]"
    chat_body = ChatBody(
        session_id=body.session_id,
        user_id=body.user_id,
        message=message,
        mode=body.mode,
        use_shared_context=body.use_shared_context,
    )
    return await _json_turn(
        lambda: _LoopTurn(
            body=chat_body,
            request=request,
            message=message,
            kind="action",
            persist_user_row=False,
            loop_on=loop_on,
        ),
        "loop action agent",
    )


# crisis support: a crisis topic or goal opens no session (nothing is stashed or
# written). The legacy /api/learn routes that delegate here screen first themselves.
async def start_session(body: StartSessionBody, request: Request):
    loop_on = await guard_off_loop(_gate, body.user_id, request)
    result = await _json_turn(
        lambda: _LoopOpener(body=body, request=request, loop_on=loop_on),
        "loop start-session agent",
    )
    out = {
        "session_id": result["session_id"],
        "initial_message": result["reply"],
        "graph_state": result["graph_state"],
    }
    if result.get("budget"):
        out["budget"] = result["budget"]
    if result.get("materials_unavailable"):
        out["materials_unavailable"] = True  # A128: present only when true
    return out


async def start_session_stream(body: StartSessionBody, request: Request):
    loop_on = await guard_off_loop(_gate, body.user_id, request)
    return _sse(_LoopOpener(body=body, request=request, loop_on=loop_on))
