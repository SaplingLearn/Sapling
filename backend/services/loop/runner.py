"""The run sites: the JSON turn and the SSE turn (budget, plan, one model run
or the deterministic text, complete) and the guardrail mapping around them.
"""
from __future__ import annotations

import asyncio
import logging
from pydantic_ai import capture_run_messages
from pydantic_ai.exceptions import UnexpectedModelBehavior
from pydantic_ai.usage import RunUsage
from sse_starlette.sse import EventSourceResponse
from agents.usage import UnfinishedRun
from services.tutor import _agent_turn_or_http_error
from services import ai_budget
from services.agent_events import SSE_CACHE_CONTROL, SaplingEvent, sapling_event_to_sse
from services.ai_budget import AIBudgetExceeded
from services.chat_stream import stream_structured_turn

from services.loop.state import _budget_event, _BudgetPaused
from services.loop.continuation import _loop_continuation_text, _requests_of
from services.loop.turn import _LoopTurn

#: Every module of the package logs as the route always did (the ops-log
#: mirror and the tests key on this logger name).
logger = logging.getLogger("routes.learn_loop")


# ── Run sites ──────────────────────────────────────────────────────────────


async def _run_turn_json(turn: _LoopTurn) -> dict:
    """The JSON run site (chat, action, check-answer turns, opener): budget →
    plan → deterministic text or ONE model run → complete. The run is
    counted (A39: once per model RUN; its tool round and output retries are
    uncharged but bounded by LOOP_LIMITS / LOOP_OUTPUT_RETRIES) right before
    it. A tool run that ends without a structured turn (#646; UnexpectedModelBehavior
    — the run is still billed) is finished by the tool-less continuation.
    Persist ordering mirrors routes.learn._chat_turn_json."""
    await asyncio.to_thread(turn.begin_activity)
    # #117: the budget read, the plan's reads and the turn's writes are sync
    # PostgREST calls; each hops off the event loop, in the same order
    decision = await asyncio.to_thread(
        ai_budget.check, turn.user_id, "tutor", turn.band, **turn.budget_counters()
    )
    try:
        await asyncio.to_thread(turn.plan, decision)
    except BaseException:
        await asyncio.shield(asyncio.to_thread(turn.touch_served_at))
        raise
    if turn.paused:
        await asyncio.shield(asyncio.to_thread(turn.touch_served_at))
        raise _BudgetPaused(decision)
    if turn.tier == "none":
        return {
            "graph_update": {},
            "mastery_changes": [],
            **(await asyncio.to_thread(turn.complete, turn.text, {}, [])),
        }
    try:
        reply = None
        usage = RunUsage()
        await asyncio.to_thread(ai_budget.count_tutor_call, turn.user_id)
        with capture_run_messages() as messages:
            try:
                result = await turn.agent.run(turn.assembled, usage=usage, **turn.run_kwargs)
            except UnexpectedModelBehavior:
                logger.warning("Loop tool run ended without a structured turn", exc_info=True)
                turn.record_usage(UnfinishedRun(usage))
            else:
                turn.record_usage(result)
                reply = turn.render(result.output)
        if reply is None:
            reply = await _continue_turn(turn, list(messages))
        return {
            "graph_update": {},
            "mastery_changes": [],
            **(await asyncio.to_thread(turn.complete, reply, {}, [])),
        }
    except BaseException:
        await asyncio.shield(asyncio.to_thread(turn.touch_served_at))
        raise


async def _continue_turn(turn: _LoopTurn, messages: list) -> str:
    """The #646 rescue of a planned turn whose run ended without a structured
    turn: `_loop_continuation_text` over the failed run's messages."""
    try:
        reply = await _loop_continuation_text(turn, messages)
    except UnexpectedModelBehavior:
        logger.warning("Tool-less loop continuation failed", exc_info=True)
        reply = None
    if not reply:
        raise UnexpectedModelBehavior("loop_tutor produced no structured turn")
    return reply


def _pre_done_events(data: dict) -> list[SaplingEvent]:
    evs = [
        SaplingEvent(type="learner_state", step="loop", message="Learner state.", data=ls)
        for ls in (data.get("learner_state") or [])
    ]
    if data.get("hint_offer"):
        evs.append(
            SaplingEvent(
                type="hint_offer", step="loop", message="Hint available.", data=data["hint_offer"]
            )
        )
    if data.get("check"):  # a check item activated by this turn (A27 trigger 1)
        pose = data["check"]
        evs.append(
            SaplingEvent(
                type="check",
                step="loop",
                message="Check item.",
                data={k: pose[k] for k in ("question_hash", "format", "difficulty")},
            )
        )
    return evs


async def _stream_turn(turn: _LoopTurn):
    """The SSE run site (chat, check-answer turns, opener). Loop events are
    yielded AROUND stream_structured_turn, never from inside it. The stream's
    `transform` is the turn's leak strip, applied to the cumulative text before
    any token is sent; `complete` gets the raw render and records the leak.
    Its Rung-1 fallback is the tool-less JSON turn (#646)."""
    try:
        await asyncio.to_thread(turn.begin_activity)
        # #117: the budget read and the plan's reads, off the event loop
        decision = await asyncio.to_thread(
            ai_budget.check, turn.user_id, "tutor", turn.band, **turn.budget_counters()
        )
        await asyncio.to_thread(turn.plan, decision)
    except Exception:
        # ADR 0024 honest degrade: nothing was shown or written — one terminal error
        logger.exception("Loop turn could not be planned")
        await asyncio.shield(asyncio.to_thread(turn.touch_served_at))
        yield sapling_event_to_sse(_stream_error(turn, _STREAM_UNAVAILABLE))
        return
    for ev in turn.pre_events():
        yield sapling_event_to_sse(ev)
    if turn.paused:
        await asyncio.shield(asyncio.to_thread(turn.touch_served_at))
        yield sapling_event_to_sse(_budget_event(decision))
        return
    if decision.level == "hard":
        # a deterministic turn served at the hard level carries the pause notice
        yield sapling_event_to_sse(_budget_event(decision))
    if turn.tier == "none":
        try:
            extra = await asyncio.to_thread(turn.complete, turn.text, {}, [])  # #117
        except Exception:
            # Behaviour 19: stream_agent_turn's on_complete guard, for the template path
            logger.warning("Deterministic loop turn failed to persist", exc_info=True)
            yield sapling_event_to_sse(_stream_error(turn, _STREAM_INTERRUPTED))
            return
        data = {"graph_update": {}, "mastery_changes": [], **extra}
        for ev in _pre_done_events(data):
            yield sapling_event_to_sse(ev)
        yield sapling_event_to_sse(
            SaplingEvent(type="done", step="reply", message="Complete.", data=data)
        )
        return
    usage = RunUsage()

    def record_incomplete_usage(known_usage) -> None:
        # Completed responses from an exhausted/cancelled stream still cost.
        # An in-flight response may report nothing; never invent its token bill.
        if known_usage is not None and _requests_of(UnfinishedRun(known_usage)):
            turn.record_usage(UnfinishedRun(known_usage))

    async def fallback(messages: list) -> dict:
        """Rung 1 (m2): the SAME planned turn — no second plan(), no second
        retrieval — billed for the failed streamed run and continued from its
        messages (tool results) by the tool-less continuation."""
        reply = await _continue_turn(turn, messages)
        return {
            "graph_update": {},
            "mastery_changes": [],
            **(await asyncio.to_thread(turn.complete, reply, {}, [])),
        }

    await asyncio.to_thread(ai_budget.count_tutor_call, turn.user_id)  # #117
    shown = ""  # A88 (M1): the text the student has been shown
    scanned = ""  # the last `shown` whose scan returned (A105, review m3)
    attempts: list[str] = []  # A93 (M4): retracted attempts relayed but never scanned
    finished = False
    try:
        async for ev in stream_structured_turn(
            agent=turn.agent,
            user_message=turn.assembled,
            run_kwargs={**turn.run_kwargs, "usage": usage},
            deps=turn.deps,
            on_complete=turn.complete,
            nonstream_fallback=fallback,
            on_usage=turn.record_usage,
            on_incomplete_usage=record_incomplete_usage,
            request_id=turn.request_id,
            transform=turn.redact,
            transform_final=turn.serve,
            render_final=turn.render,
            render_partial=turn.render_partial,
        ):
            if ev.type == "token":
                delta = str((ev.data or {}).get("delta") or "")
                if delta:
                    shown += delta
                    # A93 (M3) / A101: EVERY delta is scanned (the suffix + the
                    # overlap) and recorded before this chunk goes out — off the
                    # event loop, awaited, so the ordering holds
                    await asyncio.to_thread(turn.record_relayed, shown)
                    scanned = shown
            elif ev.type == "retract":
                # A105 (review m3): every delta of the attempt was already scanned
                # before it went out; only text relayed and never scanned is kept
                if shown and shown != scanned:
                    attempts.append(shown)
                shown = scanned = ""
            elif ev.type == "done":
                finished = True
                for extra_ev in _pre_done_events(ev.data or {}):
                    yield sapling_event_to_sse(extra_ev)
            yield sapling_event_to_sse(ev)
    finally:
        # A85: an errored, disconnected or cancelled stream moves the anchor
        if not finished:
            await asyncio.shield(asyncio.to_thread(turn.touch_served_at))
        # A93 (M4) / A88 (M1): a retracted attempt, or what an unfinished stream
        # relayed, that no scan has covered is scanned and recorded. A105 (review
        # m3): in a worker thread — the turn's lock may be held by a scan still in
        # flight, and waiting for it must not block the event loop — and SHIELDED,
        # so a second cancellation cannot stop the write: the thread finishes it.
        pending = [text for text in attempts if text]
        if not finished and shown and shown != scanned:
            pending.append(shown)
        if pending:

            def _scan_pending() -> None:
                for text in pending:
                    turn.record_relayed(text)

            await asyncio.shield(asyncio.to_thread(_scan_pending))


_STREAM_UNAVAILABLE = "The tutor is unavailable. Please retry."


_STREAM_INTERRUPTED = "The tutor was interrupted. Please retry."


def _stream_error(turn: _LoopTurn, message: str) -> SaplingEvent:
    """A terminal `error` event in services/chat_stream.py's shape; retryable, as
    a loop turn writes no graph or mastery rows before it completes."""
    return SaplingEvent(
        type="error",
        step="reply",
        message=message,
        data={"request_id": turn.request_id, "retryable": True},
    )


def _sse(turn: _LoopTurn) -> EventSourceResponse:
    return EventSourceResponse(
        _stream_turn(turn),
        headers={"X-Request-ID": turn.request_id, "Cache-Control": SSE_CACHE_CONTROL},
    )


async def _json_turn(make, what: str) -> dict:
    """Build the turn INSIDE the guardrail mapping (a read failure is a 502,
    like the legacy JSON routes) and run it; a paused turn becomes PKG-06b's
    429."""

    async def _turn() -> dict:
        # #117: building the turn reads the session's state; off the event loop
        return await _run_turn_json(await asyncio.to_thread(make))

    try:
        return await _agent_turn_or_http_error(_turn(), what=what)
    except _BudgetPaused as paused:
        raise AIBudgetExceeded(paused.decision) from None
