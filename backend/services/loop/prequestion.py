"""POST /prequestion/answer (JSON and stream, A138): the student's guess and
the turn that explains its answer.
"""
from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime, timezone
from collections.abc import Callable
from services.loop.errors import HTTPException
from starlette.requests import Request
from learning import prequestion as prequestion_rules
from learning.prequestion_store import store_answer as store_prequestion_answer
from learning.prequestion_store import stored_answer as stored_prequestion_answer
from models import ChatBody, PrequestionAnswerBody
from services.tutor import save_message_sync as save_message
from services.tutor import _consume_pending_off_loop
from services.tutor import _agent_turn_or_http_error
from services.auth_guard import guard_off_loop
from services.check_item_service import get_check_item

from services.loop.flags import (
    _ANSWER_CLAIM,
    _GUESS_IN_FLIGHT,
    _NO_OPEN_PREQUESTION,
    _PREQUESTION_CUE,
    _prequestion_on,
)
from services.loop.state import (
    _gate,
    _live,
    _load_loop_state,
    _now_s,
    _pending_grade,
    _refuse_while_closing,
    _request_id,
    _require_teaching,
    _session_scope,
    _update_loop_state,
)
from services.loop.pose import _emit_prequestion, _spend_prequestion_item, _without_claim
from services.loop.turn import _LoopTurn
from services.loop.runner import _json_turn, _sse

#: Every module of the package logs as the route always did (the ops-log
#: mirror and the tests key on this logger name).
logger = logging.getLogger("routes.learn_loop")


# ── The segment prequestion's answer (spec §13 A138) ───────────────────────
#
# One request records the guess and serves its explanation: the guess is
# stored encrypted (learning_prequestions), the item is revealed for the
# student at once (learning_reveals, A88 — before any text goes out), the
# card's record moves to `answered`, the guess is saved as the student's
# message, and the turn that explains it runs (its lead, from code, is the
# answer; A51 m1). Nothing is graded: no grade_answer, no evidence (invariant
# 26: this route is not an evidence writer), no misconception, no help-ledger
# rung, no band-control input. A retry after a failed explanation (a stored
# guess) ignores the guess fields and serves the explanation again; so does
# the next teach turn, whatever it is.


def _validated_guess(body: PrequestionAnswerBody, item) -> tuple[bool, dict | None]:
    """(no_idea, guess) for a posed prequestion: "no idea"; a choice among the
    item's own letters, with an optional reason (multiple choice); or a
    non-empty answer (free). Anything else is a 422 and nothing is stored."""
    if body.no_idea:
        return True, None
    if item.format == "mc_reason":
        option = (body.option or "").strip()
        if option not in {o.letter for o in item.options or []}:
            raise HTTPException(status_code=422, detail="Choose one of the options, or say you have no idea.")
        return False, {"option": option, "reason": body.reason.strip()}
    answer = body.answer.strip()
    if not answer:
        raise HTTPException(status_code=422, detail="Write a guess, or say you have no idea.")
    return False, {"answer": answer}


async def _prequestion_answer(body: PrequestionAnswerBody, request: Request) -> tuple[dict, tuple[str, str]]:
    """Record the guess (a stored one stands) and return (loop state, scope)
    for the explaining turn. 409 when no prequestion with this hash is open on
    the plan's current concept — or the flag is off for the student."""
    scope = await asyncio.to_thread(_session_scope, body.session_id, body.user_id)  # #117
    course_id = scope[1]
    # #117: every sync PostgREST read and write below hops off the event loop
    if not await asyncio.to_thread(_prequestion_on, body.user_id):
        raise HTTPException(status_code=409, detail=_NO_OPEN_PREQUESTION)
    state = await asyncio.to_thread(_load_loop_state, body.session_id)
    _require_teaching(state)
    if _pending_grade(state):
        raise HTTPException(status_code=409, detail="Finish checking the saved answer before continuing")
    node = state.get("concept")
    rec = prequestion_rules.record_for(state, node)
    if (
        rec is None
        or state.get("current")
        or rec.get("question_hash") != body.question_hash
        or rec.get("status") not in (prequestion_rules.POSED, prequestion_rules.ANSWERED)
    ):
        raise HTTPException(status_code=409, detail=_NO_OPEN_PREQUESTION)
    item = (
        await asyncio.to_thread(get_check_item, rec["check_item_id"])
        if rec.get("check_item_id") else None
    )
    if item is None:  # A23 withdrawal / A124, A123 holds: nothing left to explain
        raise HTTPException(status_code=409, detail=_NO_OPEN_PREQUESTION)
    if rec.get("status") == prequestion_rules.ANSWERED:
        return state, scope  # a retry: the stored guess stands
    no_idea, guess = _validated_guess(body, item)
    now = _now_s()
    claim = str(uuid.uuid4())

    # Review fix (spec §13 A138): the guess commits under a CLAIM, the way a
    # grade does (C2). (1) A compare-and-set write claims the open card — or
    # answers 409 and writes nothing: the card is not open, a check is, the
    # session is closing, or another request holds the claim. While it holds,
    # nothing supersedes the card, no check opens and no close starts. (2) The
    # stored row is the COMMIT POINT: written, then read back — the first stored
    # guess stands, and whatever this request sent, THAT guess is committed and
    # explained (second review: a 409 here stranded a student whose first
    # request stored its guess and then failed — every retry with another
    # guess, "No idea" or an edited reason was refused for good); the
    # transcript and the event are built from it. (3) The reveal, before any
    # text is served. (4) The record moves to `answered` under the claim — only
    # while the card is still `posed` and no check is open (a claim that went
    # stale may have lost its card to a check). A failure before (4) gives the
    # claim back; any retry finishes the commit.
    def take(doc: dict) -> None:
        _refuse_while_closing(doc, now)
        cur = prequestion_rules.open_record(doc, node)
        if cur is None or cur.get("question_hash") != item.question_hash or doc.get("current"):
            raise HTTPException(status_code=409, detail=_NO_OPEN_PREQUESTION)
        if _live(cur, _ANSWER_CLAIM, now):
            raise HTTPException(status_code=409, detail=_GUESS_IN_FLIGHT)
        records = dict(prequestion_rules.records(doc))
        records[node] = {**cur, _ANSWER_CLAIM: claim, f"{_ANSWER_CLAIM}_at": now}
        doc[prequestion_rules.KEY] = records

    def give_back(doc: dict) -> None:
        cur = prequestion_rules.record_for(doc, node)
        if cur is not None and cur.get(_ANSWER_CLAIM) == claim:
            records = dict(prequestion_rules.records(doc))
            records[node] = _without_claim(cur)
            doc[prequestion_rules.KEY] = records

    await asyncio.to_thread(
        _update_loop_state, body.session_id, take, require_open=True, require_existing=True
    )
    posed = rec.get("posed_at")
    posed_at = datetime.fromtimestamp(
        float(posed) if isinstance(posed, (int, float)) and not isinstance(posed, bool) else now, tz=timezone.utc
    )
    try:
        await asyncio.to_thread(
            store_prequestion_answer,
            user_id=body.user_id,
            session_id=body.session_id,
            course_id=course_id or None,
            node_id=node,
            item=item,
            no_idea=no_idea,
            guess=guess,
            posed_at=posed_at,
        )
        stored = await asyncio.to_thread(stored_prequestion_answer, body.user_id, body.session_id, node)
        if stored is None or stored.get("question_hash") != item.question_hash:
            raise RuntimeError("the stored prequestion answer could not be read back")
    except Exception as exc:
        logger.warning("prequestion guess not stored", exc_info=True)
        await asyncio.to_thread(_give_back_quietly, body.session_id, give_back)
        raise HTTPException(status_code=503, detail="Your guess could not be saved; try again") from exc
    if (bool(stored["no_idea"]), stored["guess"]) != (no_idea, guess):
        logger.info("prequestion answer: a stored earlier guess stands and is the one explained")
    # its answer is about to be shown: spent now (A88, before any text), so the
    # item never serves this student again — a check, a review item or a
    # post-test item; its ledger 'posed' row closes
    await asyncio.to_thread(_spend_prequestion_item, body.user_id, body.session_id, item.question_hash, at=now)

    def commit(doc: dict) -> None:
        cur = prequestion_rules.record_for(doc, node)
        if (
            cur is None
            or cur.get(_ANSWER_CLAIM) != claim
            or cur.get("status") != prequestion_rules.POSED
            or doc.get("current")
        ):
            # the claim went stale and the card was superseded or re-claimed,
            # or a check opened: no explanation over it (second review, item 3)
            raise HTTPException(status_code=409, detail=_NO_OPEN_PREQUESTION)
        records = dict(prequestion_rules.records(doc))
        records[node] = {
            **_without_claim(cur), "status": prequestion_rules.ANSWERED, "answered_at": now,
            "no_idea": bool(stored["no_idea"]),
        }
        doc[prequestion_rules.KEY] = records

    # #117: the loop_state write and the transcript row are sync PostgREST
    # calls, so they hop off the event loop (spec §13 A149)
    state = await asyncio.to_thread(
        _update_loop_state, body.session_id, commit, require_open=True, require_existing=True
    )
    stored_guess = stored["guess"] or {}
    await asyncio.to_thread(
        save_message,
        body.session_id,
        "user",
        prequestion_rules.render_guess(
            no_idea=bool(stored["no_idea"]),
            answer=str(stored_guess.get("answer") or ""),
            option=stored_guess.get("option"),
            reason=str(stored_guess.get("reason") or ""),
        ),
    )
    await asyncio.to_thread(
        _emit_prequestion,
        body.user_id,
        _request_id(request),
        body.session_id,
        node,
        "answered",
        question_hash=item.question_hash,
        no_idea=bool(stored["no_idea"]),
        format=item.format,
        difficulty=int(item.difficulty),
    )
    return state, scope


def _give_back_quietly(session_id: str, give_back: Callable[[dict], None]) -> None:
    """Give an answer claim back after a failure (never raises: a claim that
    cannot be given back goes stale after LOOP_GRADING_CLAIM_STALE_S)."""
    try:
        _update_loop_state(session_id, give_back)
    except Exception:
        logger.warning("prequestion answer claim not given back; it goes stale", exc_info=True)


def _prequestion_turn(
    state: dict, scope: tuple[str, str], body: PrequestionAnswerBody, request: Request, *, loop_on: bool
) -> _LoopTurn:
    """The turn that explains the answered prequestion: a teach turn on the
    plan's concept, its message the route's cue (trusted server text; the
    guess is the student's saved message, enveloped in the history, A51)."""
    chat_body = ChatBody(session_id=body.session_id, user_id=body.user_id, message=_PREQUESTION_CUE)
    return _LoopTurn(
        body=chat_body,
        request=request,
        message=_PREQUESTION_CUE,
        kind="prequestion",
        persist_user_row=False,
        state=state,
        scope=scope,
        loop_on=loop_on,
    )


async def prequestion_answer(body: PrequestionAnswerBody, request: Request):
    loop_on = await guard_off_loop(_gate, body.user_id, request)
    await _consume_pending_off_loop(body.session_id, body.user_id)
    state, scope = await _agent_turn_or_http_error(_prequestion_answer(body, request), what="loop prequestion")
    return await _json_turn(
        lambda: _prequestion_turn(state, scope, body, request, loop_on=loop_on), "loop prequestion agent"
    )


async def prequestion_answer_stream(body: PrequestionAnswerBody, request: Request):
    loop_on = await guard_off_loop(_gate, body.user_id, request)
    await _consume_pending_off_loop(body.session_id, body.user_id)
    state, scope = await _agent_turn_or_http_error(_prequestion_answer(body, request), what="loop prequestion")
    # #117: building the turn reads the session's state; off the event loop
    return _sse(
        await asyncio.to_thread(_prequestion_turn, state, scope, body, request, loop_on=loop_on)
    )
