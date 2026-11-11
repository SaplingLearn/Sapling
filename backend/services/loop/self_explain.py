"""POST /self-explain (A139): the student's self-explanation reply.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from services.loop.errors import HTTPException
from starlette.requests import Request
from learning import self_explain
from learning.self_explain_store import LOST as SELF_EXPLAIN_LOST
from learning.self_explain_store import close_prompt as close_self_explain_prompt
from models import SelfExplainBody
from services.tutor import save_message_sync as save_message

from services.loop.flags import _NO_OPEN_SELF_EXPLAIN, _prequestion_on, _self_explain_on
from services.loop.state import (
    _closing,
    _gate,
    _load_loop_state,
    _now_s,
    _refuse_while_closing,
    _request_id,
    _require_teaching,
    _session_scope,
    _update_loop_state,
)
from services.loop.pose import (
    _emit_self_explanation,
    _NO_POSE,
    _pose_prequestion,
    _posed_prequestion,
)

#: Every module of the package logs as the route always did (the ops-log
#: mirror and the tests key on this logger name).
logger = logging.getLogger("routes.learn_loop")


# ── The self-explanation reply (spec §13 A139) ─────────────────────────────


def self_explain_reply(body: SelfExplainBody, request: Request) -> dict:
    """The student's reply to the open self-explanation prompt, or a skip (an
    empty reply is a skip). Stored encrypted with its juncture
    (learning_self_explanations) and saved as the student's message; never
    graded, never evidence, never a misconception — no model reads it here (the
    next tutor turn may acknowledge it, flag-on prompt only). Then, when the
    prompt closed a segment, the next segment's prequestion is posed (A138:
    the self-explanation comes first, one open prompt at a time)."""
    _gate(body.user_id, request)
    _, course_id = _session_scope(body.session_id, body.user_id)
    if not _self_explain_on(body.user_id):
        raise HTTPException(status_code=409, detail=_NO_OPEN_SELF_EXPLAIN)
    state = _load_loop_state(body.session_id)
    _require_teaching(state)
    now = _now_s()
    _refuse_while_closing(state, now)  # a closing session writes nothing
    prompt = self_explain.open_prompt(state)
    if prompt is None or prompt.get("id") != body.prompt_id:
        raise HTTPException(status_code=409, detail=_NO_OPEN_SELF_EXPLAIN)
    reply = "" if body.skip else body.reply.strip()
    # Review fix: the row is the COMMIT POINT — closed only while it is 'open',
    # so of two concurrent replies the first stands and the other writes
    # nothing (a 409); the loop state, the transcript and the event follow it
    try:
        outcome = close_self_explain_prompt(
            prompt,
            user_id=body.user_id,
            session_id=body.session_id,
            course_id=course_id,
            reply=reply or None,
            closed_at=datetime.fromtimestamp(now, tz=timezone.utc),
        )
    except Exception as exc:
        logger.warning("self-explanation reply not stored", exc_info=True)
        raise HTTPException(status_code=503, detail="Your explanation could not be saved; try again") from exc
    if outcome == SELF_EXPLAIN_LOST:
        raise HTTPException(status_code=409, detail=_NO_OPEN_SELF_EXPLAIN)
    pq_on = _prequestion_on(body.user_id)
    out: dict = {}

    def close(doc: dict) -> None:
        # the reply is committed: a prompt a turn closed meanwhile, or a close
        # that started meanwhile, changes nothing here and refuses nothing.
        # Second review: exactly ONE request writes the reply's transcript row
        # and event — the one whose write first records it here, a slow winner
        # or its retry alike
        out.clear()
        out["emit"] = self_explain.mark_closed_by_reply(doc, body.prompt_id)
        cur = self_explain.open_prompt(doc)
        if _closing(doc, now) or cur is None or cur.get("id") != body.prompt_id:
            return
        self_explain.close_open(doc)
        if reply:
            self_explain.set_ack(doc, body.prompt_id)
        out["pose"] = _pose_prequestion(body.user_id, course_id, doc, now=now) if pq_on else _NO_POSE

    try:
        _update_loop_state(body.session_id, close, require_open=True, require_existing=True)
    except HTTPException as exc:
        if exc.status_code != 409:
            raise  # a retry finishes it (SAME)
        # the session closed meanwhile: the committed reply's row stands for
        # the admin report; with no write to decide it, no transcript row
        out.clear()
    request_id = _request_id(request)
    if out.get("emit"):
        if reply:
            try:
                save_message(body.session_id, "user", reply)
            except Exception:
                logger.warning("self-explanation reply row not saved", exc_info=True)
        _emit_self_explanation(
            body.user_id,
            request_id,
            body.session_id,
            prompt,
            "replied" if reply else "skipped",
            **({"reply_chars": len(reply)} if reply else {}),
        )
    prequestion = _posed_prequestion(body.user_id, body.session_id, request_id, out.get("pose", _NO_POSE))
    return {
        "recorded": True,
        "status": "replied" if reply else "skipped",
        **({"prequestion": prequestion} if prequestion else {}),
    }
