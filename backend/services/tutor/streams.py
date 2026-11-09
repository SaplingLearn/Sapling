"""The streamed tutor turns (#118, moved verbatim from routes/learn.py): the
`chat_stream` and `start_session_stream` handler bodies over
services/chat_stream.py::stream_agent_turn; routes/learn.py wraps them.
"""
from __future__ import annotations

import asyncio
import uuid

from sse_starlette.sse import EventSourceResponse
from starlette.concurrency import run_in_threadpool
from starlette.requests import Request

from agents.usage import record_agent_usage
from models import ChatBody, StartSessionBody
from services import ai_budget, crisis_support, events_service
from services.agent_events import SSE_CACHE_CONTROL, sapling_event_to_sse
from services.auth_guard import guard_off_loop, require_self
from services.chat_stream import stream_agent_turn
from services.graph_service import get_graph
from services.request_context import current_request_id
from services.tutor.course import _get_course_id_for_topic, _session_course_id, _session_offering
from services.tutor.messages import (
    _load_message_history,
    _persisted_turn,
    _replay_events,
    _save_turn_rows,
    _turn_row_ids,
)
from services.quiz_ask import open_quiz_ask
from services.tutor.pending import _materialize_turn_session, _require_turn_session
from services.tutor.run import (
    _continuation_text,
    _kill_switch_budget,
    _observe_persisted_turn,
    _prepare_chat_run,
    _ran_on,
    _usage_session_id,
)
from services.tutor.turns import _chat_turn_json, _start_session_agent, _start_texts
from services.tutor_sessions import stash_pending


async def chat_stream(body: ChatBody, request: Request, loop_handler=None):
    """SSE token-streaming chat turn (#70) with live graph deltas (#74).

    The JSON /chat pipeline (`_chat_turn_json`, on the fast tier) is the
    server-side Rung-1 fallback, and the client keeps the JSON route as its
    own non-streaming rung. No DBOS
    wrap here — stream routes are deliberately outside durable execution
    (ADR 0011); retries are client-driven, and idempotent when the client
    sends the same ``turn_id`` on the stream and on its fallback/retry
    (#761): the writes dedupe on turn-derived ids, and a turn that already
    persisted is replayed (here and on /chat) instead of run again.
    """
    await guard_off_loop(require_self, body.user_id, request)
    if crisis := await crisis_support.screen_async(body.user_id, "tutor_chat", body.message):
        return crisis_support.sse_response(crisis, request)
    # #761 entry checks (not discarded, owned) before the rate-limit read (A93 review)
    await _require_turn_session(body.session_id, body.user_id)
    # A20: one rate-limit read for both paths, AFTER the ownership check (A93 review).
    # #117: off the event loop (it reads llm_usage).
    await asyncio.to_thread(ai_budget.enforce_rate_limit_for, body.user_id)
    # Learning loop (spec §7): `loop_handler` is the loop's handler when the
    # route-entry gate is true (the default; routes/learn.py evaluates it,
    # owner decision 00); below is the kill-switch path (spec §11.6),
    # cost-bounded by _kill_switch_budget (A20).
    if loop_handler is not None:
        request.state.learning_loop = True  # A38 00: the loop handler reads no second gate
        return await loop_handler(body, request)
    await asyncio.to_thread(_kill_switch_budget, body.user_id)
    await _materialize_turn_session(body.session_id, body.user_id)

    request_id = (
        getattr(request.state, "request_id", None)
        or current_request_id()
        or str(uuid.uuid4())
    )

    # #761: a re-sent turn that already persisted replays its stored reply
    # over the same event vocabulary instead of running again.
    replay = await _persisted_turn(body.session_id, body.turn_id)
    if replay is not None:
        return EventSourceResponse(
            _replay_events(replay),
            headers={"X-Request-ID": request_id, "Cache-Control": SSE_CACHE_CONTROL},
        )

    # A92: the llm_usage session id, resolved here off the event loop (the
    # usage hook below runs on it, inside the stream).
    usage_session_id = await asyncio.to_thread(_usage_session_id, body.session_id, body.user_id)

    # Load prior turns BEFORE the new user row is written, so history is
    # conversation state up to (not including) this turn.
    user_row_id, assistant_row_id = _turn_row_ids(body)
    course_id, message_history = await asyncio.gather(
        _session_course_id(body.session_id),
        _load_message_history(body.session_id, exclude_id=user_row_id),
    )

    agent, assembled, run_kwargs, deps = await run_in_threadpool(
        _prepare_chat_run,
        user_id=body.user_id,
        session_id=body.session_id,
        course_id=course_id,
        mode=body.mode,
        user_message=body.message,
        message_history=message_history,
        use_shared_context=body.use_shared_context,
        request_id=request_id,
        model_pref=body.model_pref,
    )
    # No extra model override here: _prepare_chat_run already applied the
    # seam-aware fast/smart preference (_resolve_model_pref), and the agent's
    # own model is _LoopSafeGoogleModel in real mode / FunctionModel under
    # SAPLING_MODEL_MODE=function — forcing a GoogleModel here would bypass
    # the e2e seam and re-create the cross-loop client problem #453 solved.

    #: What the streamed run actually ran on — set by `_usage` (on_usage runs
    #: before on_complete), read by `_persist` for the #640 router's event.
    ran: dict = {}

    async def _persist(reply: str, graph_update: dict, mastery_changes: list) -> dict:
        # Mirrors chat()'s ordering: user row, then assistant row. Runs only
        # after the agent run completes, so a disconnect mid-generation
        # persists nothing. Encryption happens inside save_message. Async, so
        # stream_agent_turn shields it: a disconnect from here on still lets
        # the turn finish persisting (#761).
        await _save_turn_rows(body, reply, graph_update or None,
                              user_row_id=user_row_id, assistant_row_id=assistant_row_id)
        # #117: same event as the JSON route, from the on_complete hook so a
        # disconnected mid-generation turn emits nothing. request_id is
        # explicit. The request contextvars (request id, DNT/GPC, request
        # view) DO survive here: Starlette runs the streaming body in a child
        # task whose context was copied before RequestIDMiddleware reset its
        # own, and the shielded persist task copies it again — so the PostHog
        # mirror still honours DNT/GPC. Pinned by tests/test_sse_request_context.py.
        events_service.log_event(
            "chat.message_sent",
            category="usage",
            user_id=body.user_id,
            request_id=request_id,
            payload={"mode": body.mode, "session_id": body.session_id},
            content=body.message,
        )
        # #640: the streamed twin of `_chat_turn_json`'s router call, labelled
        # with the run `_usage` saw (on_usage runs before on_complete).
        ran_on = ran.get("on") or _ran_on(None, agent, run_kwargs, body.model_pref)
        _observe_persisted_turn(
            body, history=message_history, ran_on=ran_on, request_id=request_id,
        )
        return {}

    async def _fallback() -> dict:
        # Rung 1 only (agent failed before any token, no writes landed —
        # stream_agent_turn's writes-guard enforces that). _chat_turn_json
        # persists its own user + assistant rows and emits its own
        # chat.message_sent, so _persist must not also run —
        # stream_agent_turn enforces that exclusivity. model_pref="fast"
        # (D2): the second chance runs on the fast tier.
        return await _chat_turn_json(body, request, model_pref="fast")

    def _usage(run_result) -> None:
        # #118: streaming turns report usage via the final AgentRunResultEvent,
        # surfaced by stream_agent_turn's on_usage hook after the run completes.
        # request_id is explicit so the row is tied to its turn (and to the
        # turn's decision.made) by construction, not by ambient context.
        record_agent_usage(
            run_result, feature="chat_tutor", task="chat_tutor", user_id=body.user_id,
            session_id=usage_session_id,
            request_id=request_id,
        )
        ran["on"] = _ran_on(run_result, agent, run_kwargs, body.model_pref)

    async def event_stream():
        async for ev in stream_agent_turn(
            agent=agent,
            user_message=assembled,
            run_kwargs=run_kwargs,
            deps=deps,
            on_complete=_persist,
            nonstream_fallback=_fallback,
            on_usage=_usage,
            request_id=request_id,
            continuation=lambda rr: _continuation_text(agent, rr, run_kwargs, request_id=request_id),
        ):
            yield sapling_event_to_sse(ev)

    return EventSourceResponse(
        event_stream(),
        headers={"X-Request-ID": request_id, "Cache-Control": SSE_CACHE_CONTROL},
    )


async def start_session_stream(body: StartSessionBody, request: Request, loop_handler=None):
    """Streamed session opener — runs chat_tutor_agent and streams the
    greeting (#152/#151).

    The JSON /start-session route shares the same `_start_session_agent`
    pipeline and remains the client's non-streaming fallback.
    PENDING_SESSIONS lazy materialization is preserved exactly: the row is
    still written on first chat, by _consume_pending.

    Rung 1 (agent fails before any token, no writes landed) falls back to
    `_start_session_agent` — the JSON route's own pipeline, on the fast
    tier (D2). `stream_agent_turn` guarantees AT MOST one of `on_complete`
    (`_stash`, below) / `nonstream_fallback` (`_fallback`, below) runs per
    turn — never both — so PENDING_SESSIONS is stashed at most once:
    `_stash` on the streamed-success path, `_start_session_agent`
    internally on the Rung-1 fallback path. A Rung-2 error (failure after
    the greeting started streaming) stashes NOTHING for this session_id —
    the client never received it in a `done` event, so a retry simply mints
    a fresh session.
    """
    await guard_off_loop(require_self, body.user_id, request)
    if crisis := await crisis_support.screen_async(body.user_id, "tutor_start", *_start_texts(body)):
        return crisis_support.sse_response(crisis, request, session_id=None)
    # A20: one rate-limit read for both paths, AFTER the ownership check (A93 review).
    # #117: off the event loop (it reads llm_usage).
    await asyncio.to_thread(ai_budget.enforce_rate_limit_for, body.user_id)
    # Learning loop (spec §7): the loop's handler when the route-entry gate is
    # true (the default); below is the kill-switch path (spec §11.6),
    # cost-bounded by _kill_switch_budget (A20).
    if loop_handler is not None:
        request.state.learning_loop = True  # A38 00: the loop handler reads no second gate
        return await loop_handler(body, request)
    await asyncio.to_thread(_kill_switch_budget, body.user_id)
    request_id = (
        getattr(request.state, "request_id", None)
        or current_request_id()
        or str(uuid.uuid4())
    )
    session_id = str(uuid.uuid4())
    # PKG-14 (spec §13 A99): a quiz-ask session's help row, before any tutor text;
    # A106 (review m2): it runs on the quiz node's course, never the client's
    target = await asyncio.to_thread(open_quiz_ask, body, session_id=session_id)
    if target is not None:
        body = body.model_copy(update={"course_id": target.course_id})

    course_id = body.course_id or await _get_course_id_for_topic(body.topic, body.user_id)
    offering_id = await run_in_threadpool(_session_offering, body, course_id)

    user_message = (
        f"Student wants to learn about: {body.topic}\n\n"
        "Begin the session with a warm greeting and your first question or explanation."
    )

    agent, assembled, run_kwargs, deps = await run_in_threadpool(
        _prepare_chat_run,
        user_id=body.user_id,
        session_id=session_id,
        course_id=course_id,
        mode=body.mode,
        user_message=user_message,
        message_history=[],
        use_shared_context=body.use_shared_context,
        request_id=request_id,
        model_pref=body.model_pref,
    )
    # No extra model override here: _prepare_chat_run already applied the
    # seam-aware fast/smart preference (_resolve_model_pref), and the agent's
    # own model is _LoopSafeGoogleModel in real mode / FunctionModel under
    # SAPLING_MODEL_MODE=function — forcing a GoogleModel here would bypass
    # the e2e seam and re-create the cross-loop client problem #453 solved.

    def _stash(reply: str, graph_update: dict, mastery_changes: list) -> dict:
        # Streamed agent path succeeded. Same lazy contract as the JSON
        # route: nothing hits `sessions` until the first chat turn calls
        # _consume_pending. Mutually exclusive with `_fallback` below — see
        # the docstring above.
        stash_pending(session_id, {
            "user_id": body.user_id,
            "mode": body.mode,
            "topic": body.topic,
            "course_id": course_id,
            "offering_id": offering_id,
            "use_shared_context": body.use_shared_context,
            "assistant_reply": reply,
            "graph_update": graph_update,
        })
        return {"session_id": session_id, "graph_state": get_graph(body.user_id)}

    async def _fallback() -> dict:
        # Rung 1 only (agent failed before any token, no writes landed).
        # Reuses the SAME session_id already minted above — via
        # `session_id=` — so this turn only ever has one session_id,
        # whichever path serves it. `_start_session_agent` stashes
        # PENDING_SESSIONS itself; `_stash` above must NOT also run, and
        # stream_agent_turn enforces that exclusivity (at most one of
        # on_complete/nonstream_fallback executes per turn — see
        # stream_agent_turn's docstring). model_pref="fast" (D2): the
        # second chance runs on the fast tier.
        return await _start_session_agent(body, session_id, model_pref="fast",
                                          request_id=request_id)

    def _usage(run_result) -> None:
        # #118: same hook as /chat/stream — the opener runs the same
        # chat_tutor agent, so it rolls up under the same feature/task. Explicit
        # request_id, as in /chat/stream.
        record_agent_usage(
            run_result, feature="chat_tutor", task="chat_tutor", user_id=body.user_id,
            session_id=session_id,
            request_id=request_id,
        )

    async def event_stream():
        async for ev in stream_agent_turn(
            agent=agent,
            user_message=assembled,
            run_kwargs=run_kwargs,
            deps=deps,
            on_complete=_stash,
            nonstream_fallback=_fallback,
            on_usage=_usage,
            request_id=request_id,
            continuation=lambda rr: _continuation_text(agent, rr, run_kwargs, request_id=request_id),
        ):
            yield sapling_event_to_sse(ev)

    return EventSourceResponse(
        event_stream(),
        headers={"X-Request-ID": request_id, "Cache-Control": SSE_CACHE_CONTROL},
    )
