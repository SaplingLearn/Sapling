"""The tutor's non-streamed agent turns (#118, moved verbatim from
routes/learn.py): the guardrail -> HTTP mapping, the session opener, the chat
turn and the hint/confused/skip action turn. `start_session`, `chat` and
`action` are the handler bodies; routes/learn.py wraps them.
"""
from __future__ import annotations

import asyncio
import logging
import uuid

from pydantic_ai.exceptions import UsageLimitExceeded, UnexpectedModelBehavior
from starlette.concurrency import run_in_threadpool
from starlette.requests import Request

from agents.usage import record_agent_usage
from models import ActionBody, ChatBody, StartSessionBody
from services import events_service
from services.auth_guard import guard_off_loop, require_self
from services.chat_stream import merge_graph_updates
from services.graph_service import get_graph
from services.request_context import current_request_id
from services.tutor.course import _get_course_id_for_topic, _session_course_id, _session_offering
from services.tutor.errors import HTTPException
from services.tutor.messages import (
    _load_message_history,
    _persisted_turn,
    _save_turn_rows,
    _turn_row_ids,
    save_message,
)
from services.tutor.pending import _open_turn_session
from services.tutor.run import (
    _continuation_text,
    _new_run_text,
    _observe_persisted_turn,
    _prepare_chat_run,
    _ran_on,
)
from services.tutor_sessions import astash_pending

# Log records keep the name they had in routes/learn.py before the #118 split:
# the move must not change what an operator (or a caplog test) filters on.
logger = logging.getLogger("routes.learn")


# Guardrail → HTTP status mapping (the notes precedent — routes/notes.py::
# _run_note_worker, #329). The two Pydantic AI guardrail failures are
# distinct and must not be conflated: a budget trip is deterministic
# (retrying the same turn fails identically → 413, cause-naming detail, no
# "try again" wording), while unexpected/degenerate model output is
# transient upstream trouble (→ 502, retry-friendly detail; a WARNING, not
# an exception log — pages should fire on the bare-Exception 502 below,
# which IS a bug).
_USAGE_LIMIT_DETAIL = (
    "This turn exceeded the tutor's processing budget — the conversation or "
    "message is too long to answer in one turn. Retrying the same message "
    "will hit the same limit; try a shorter message or a fresh session."
)
_MODEL_TROUBLE_DETAIL = "The tutor had trouble answering that. Please try again."


async def _agent_turn_or_http_error(turn, *, what: str):
    """Await an agent-served tutor turn, mapping guardrail failures to HTTP
    statuses. Shared by /chat, /start-session and /action (#151a — the old
    behavior degraded to the deleted `call_gemini_multiturn` pipeline)."""
    try:
        return await turn
    except UsageLimitExceeded as e:
        logger.warning("%s hit its usage budget; returning 413", what, exc_info=e)
        raise HTTPException(status_code=413, detail=_USAGE_LIMIT_DETAIL) from e
    except UnexpectedModelBehavior as e:
        logger.warning(
            "%s returned unexpected model behavior; returning 502", what, exc_info=e
        )
        raise HTTPException(status_code=502, detail=_MODEL_TROUBLE_DETAIL) from e
    except HTTPException:
        # Known states raised inside the turn (auth, 404s) pass through.
        raise
    except Exception as e:
        logger.exception("Unexpected %s failure; returning 502", what)
        raise HTTPException(status_code=502, detail=_MODEL_TROUBLE_DETAIL) from e


async def _start_session_agent(
    body: StartSessionBody,
    session_id: str | None = None,
    *,
    model_pref: str | None = None,
    request_id: str | None = None,
) -> dict:
    """Core start-session pipeline on chat_tutor_agent: _prepare_chat_run
    (empty history) -> agent.run -> record_agent_usage -> stash
    PENDING_SESSIONS. Replaces `_start_session_legacy` (#151a) with the same
    signature and return shape.

    Shared by the JSON route and the streaming route's Rung-1
    `nonstream_fallback` (agent failed before any token).

    `session_id`: the streaming route already minted one up front (it needs
    it for SaplingDeps before it knows whether the streamed agent or this
    fallback will serve the turn); passing it through here means a turn only
    ever has ONE session_id and PENDING_SESSIONS is stashed exactly once,
    regardless of which path serves it. `None` (the JSON route's case)
    mints a fresh one.

    `model_pref`: explicit override for the fast/smart knob; `None` falls
    through to `body.model_pref`. The streaming fallback forces "fast" (D2):
    a different, faster model is a materially better second chance than
    re-rolling the same tier, and it bounds the client's 45s idle window.

    A whitespace-only greeting raises UnexpectedModelBehavior (the #153
    bare-newline-after-tool-call quirk) so the caller's guardrail mapping —
    or the stream's Rung-1 ladder — handles it instead of stashing an empty
    greeting.

    Returns {"session_id", "reply", "graph_update", "mastery_changes",
    "graph_state"} — a superset of what the JSON route needs, and exactly
    the shape the streaming `done` event / frontend `ChatResult` expects.
    """
    if session_id is None:
        session_id = str(uuid.uuid4())

    # `request_id`: the streaming route's Rung-1 fallback passes the turn's
    # own, so its usage rows join the turn regardless of ambient context.
    request_id = request_id or current_request_id() or str(uuid.uuid4())

    # Use abstract course_id from body, or resolve it from the topic. The graph
    # + shared context key on this abstract id; the session row keys on the
    # offering `_session_offering` picks (a client-named course is gated, #115).
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
        model_pref=model_pref if model_pref is not None else body.model_pref,
    )

    try:
        result = record_agent_usage(
            await agent.run(assembled, **run_kwargs),
            feature="chat_tutor", task="chat_tutor", user_id=body.user_id,
            request_id=request_id,
        )
        # str — chat_tutor agents return plain Markdown. Read every text
        # part this turn wrote (`_new_run_text`), not `.output`: `.output` is
        # only the FINAL model response, so a Claude turn that explains,
        # calls a tool, then adds a line would persist just that line (ADR
        # 0030). (The stale-history hazard doesn't apply here — this call
        # passes `message_history=[]` — but the same reader keeps all three
        # non-streamed paths and the stream persisting identical text.)
        reply = _new_run_text(result)
        if not reply.strip():
            # Same textless shape as the chat turns (#646), and this is the
            # LAST rung on the opener path: a streamed /start-session/stream
            # turn that goes textless with no writes degrades to Rung 1,
            # which is this function on the fast tier — Flash-Lite, the
            # model that produces textless turns in the first place. Raising
            # here ends the student's very first interaction on "The tutor
            # is unavailable". Finish the turn if the model will; the
            # opener's tool results are in its messages just like a chat
            # turn's.
            try:
                rescued = await _continuation_text(agent, result, run_kwargs, request_id=request_id)
            except Exception:
                logger.warning(
                    "Continuation after a textless session greeting failed",
                    exc_info=True,
                )
                rescued = None
            if rescued:
                logger.info("Textless session greeting rescued by a continuation")
                reply = rescued
            else:
                raise UnexpectedModelBehavior(
                    "chat_tutor produced a whitespace-only session greeting"
                )
    except Exception as exc:
        # PR #472 review: THIS run's tools may have written graph/mastery
        # before the failure. Stamp the write-state so the streaming
        # route's fallback error can set retryable correctly — a client
        # retry after real writes would re-apply them.
        exc.sapling_wrote = bool(deps.graph_updates or deps.mastery_changes)
        raise

    # Graph writes (if any) already landed in-band via the agent's tools;
    # merge their payloads for the response echo, exactly like the chat turn.
    graph_update = merge_graph_updates(deps.graph_updates)

    # Lazy-session contract preserved: nothing hits `sessions` until the
    # first chat turn calls _consume_pending — exactly once per session_id.
    await astash_pending(session_id, {
        "user_id": body.user_id,
        "mode": body.mode,
        "topic": body.topic,
        "course_id": course_id,        # abstract — graph + shared-context key
        "offering_id": offering_id,    # term-scoped — the session-row key
        "use_shared_context": body.use_shared_context,
        "assistant_reply": reply,
        "graph_update": graph_update,
    })

    return {
        "session_id": session_id,
        "reply": reply,
        "graph_update": graph_update,
        "mastery_changes": list(deps.mastery_changes),
        "graph_state": await run_in_threadpool(get_graph, body.user_id),
    }


async def start_session(body: StartSessionBody, request: Request):
    await guard_off_loop(require_self, body.user_id, request)
    result = await _agent_turn_or_http_error(
        _start_session_agent(body), what="start-session agent"
    )
    return {
        "session_id": result["session_id"],
        "initial_message": result["reply"],
        "graph_state": result["graph_state"],
    }


async def _chat_via_agent(
    *,
    user_id: str,
    session_id: str,
    course_id: str,
    mode: str,
    user_message: str,
    message_history: list,
    use_shared_context: bool,
    request_id: str,
    model_pref: str | None = None,
) -> tuple[dict, tuple[str, str | None]]:
    """Run chat_tutor_agent and return the wire response shape.

    Returns ``({"reply": str, "graph_update": dict, "mastery_changes": list},
    (model_tier, tutor_model))`` — the wire dict, and what the run actually
    ran on (see `_ran_on`), kept out of the dict so it can never leak.
    Graph changes are persisted in-band during the agent run by
    `apply_graph_update_tool` / `update_mastery_tool` (registered on
    chat_tutor); the tools also accumulate their payloads on `deps` so the
    route can echo `graph_update` (for graph_update_json / concepts_covered)
    and the real `mastery_changes` deltas back to the client. Both are
    empty when nothing changed this turn.

    `use_shared_context=False` flips the model into "no class-aggregate"
    mode by appending a constraint instruction to the user message —
    the chat tutor's class-aggregate tools (read_user_progress, etc.)
    aggregate per-user data, but a future shared-context tool would
    need this guard rail. Keeping the constraint in-band rather than
    branching the agent surface keeps the agent definition stable.
    """
    agent, user_message, run_kwargs, deps = await run_in_threadpool(
        _prepare_chat_run,
        user_id=user_id,
        session_id=session_id,
        course_id=course_id,
        mode=mode,
        user_message=user_message,
        message_history=message_history,
        use_shared_context=use_shared_context,
        request_id=request_id,
        model_pref=model_pref,
    )

    try:
        result = record_agent_usage(
            await agent.run(user_message, **run_kwargs),
            feature="chat_tutor", task="chat_tutor", user_id=deps.user_id,
            request_id=request_id,
        )
        # `.output` alone is a HISTORY read on this path: `_prepare_chat_run`
        # puts `message_history` into `run_kwargs`, so a textless model
        # response makes `.output` resolve to the PREVIOUS turn's assistant
        # message — fully formed, non-blank, and therefore invisible to the
        # `not reply.strip()` guard below. Trust it only when this run
        # actually produced text, mirroring `stream_agent_turn`'s narrowing.
        # This matters here more than anywhere: `_chat_turn_json` is both the
        # POST /api/learn/chat route AND the streamed route's Rung-1
        # fallback, which is exactly where the streaming fix now sends
        # textless turns. And `.output` is only the FINAL model response even
        # when this run did write text: a Claude turn that explains, calls a
        # tool, then adds a line would persist just that line (ADR 0030) — so
        # the reply is always this run's own joined text.
        reply = _new_run_text(result)

        if not reply.strip():
            # #153 / ADR-0023 follow-up: gemini-2.5-pro occasionally follows an
            # end-of-turn tool call with a bare-newline final text; and per the
            # narrowing above, a turn that ended after tool calls with no text
            # part reaches here blank instead of replaying history.
            #
            # Try to FINISH the turn before failing it (#646). Unlike the
            # streamed route there is no Rung-1 ladder below this — this IS
            # that rung — so the alternative is a 502 for a turn whose tools
            # have already run. Fire regardless of whether writes landed:
            # nothing else will re-run, so there is no better answer waiting.
            try:
                rescued = await _continuation_text(agent, result, run_kwargs, request_id=request_id)
            except Exception:
                # Second model call; a failure here must degrade to the
                # pre-#646 behaviour, never surface as its own error.
                logger.warning(
                    "Continuation after a textless JSON turn failed",
                    exc_info=True,
                )
                rescued = None
            if rescued:
                logger.info("Textless JSON turn rescued by a continuation")
                reply = rescued
            else:
                # Still nothing: this turn produced no reply. Treat it as
                # degenerate model output so the caller's
                # UnexpectedModelBehavior handling — the route's 502 mapping,
                # or the stream fallback's Rung-1 ladder — applies instead of
                # persisting a stale or empty assistant row.
                # Usage was recorded above — tokens were spent.
                raise UnexpectedModelBehavior(
                    "chat_tutor produced no reply text this turn"
                )
    except Exception as exc:
        # PR #472 review: THIS run's tools may have written graph/mastery
        # before the failure. Stamp the write-state so the streaming
        # route's fallback error can set retryable correctly — a client
        # retry after real writes would re-apply them.
        exc.sapling_wrote = bool(deps.graph_updates or deps.mastery_changes)
        raise

    # Merge all graph update payloads accumulated by tools during this run
    # into a single dict so the route can persist graph_update_json and
    # end_session can derive concepts_covered correctly.
    merged_graph_update = merge_graph_updates(deps.graph_updates)

    response = {
        "reply": reply,
        "graph_update": merged_graph_update,
        # Real before/after deltas accumulated by update_mastery_tool.
        # Empty when no mastery moved this turn.
        "mastery_changes": deps.mastery_changes,
    }
    # Out of band, never in the wire dict: what this run actually ran on, for
    # the #640 router's event.
    return response, _ran_on(result, agent, run_kwargs, model_pref)


async def _chat_turn_json(
    body: ChatBody,
    request: Request,
    *,
    model_pref: str | None = None,
) -> dict:
    """One full non-streaming chat turn: agent run, persistence, and the
    #117 `chat.message_sent` emission — the SINGLE emission site for
    JSON-served turns (#151a; the streamed route's on_complete hook is the
    streamed twin, and at most one of the two serves any turn).

    Shared by the JSON /chat route (wrapped in the guardrail → status
    mapping) and the streaming route's Rung-1 `nonstream_fallback`, which
    forces `model_pref="fast"` (D2): a different, faster model is a
    materially better second chance than re-rolling the same tier, and it
    bounds the client's 45s idle window.

    Persist ordering preserved: prior turns load BEFORE the new user row is
    written; the user row and assistant row are written only after the agent
    run succeeds, so a failed turn persists nothing.

    This is also one of the two points the observe-only tutor router (#640)
    is scheduled from — see `_observe_persisted_turn`.
    """
    # Unify with the middleware-stamped request ID so agent traces and
    # any downstream error payloads share the same correlation key.
    request_id = (
        getattr(request.state, "request_id", None)
        or current_request_id()
        or str(uuid.uuid4())
    )

    # The session keys on the offering; the agent's graph tools key on the
    # abstract course derived from it. Load prior turns BEFORE writing the
    # new user row, so the message_history we hand the agent contains only
    # the conversation state up to (but not including) the current turn.
    user_row_id, assistant_row_id = _turn_row_ids(body)
    course_id, message_history = await asyncio.gather(
        _session_course_id(body.session_id),
        _load_message_history(body.session_id, exclude_id=user_row_id),
    )

    response, ran_on = await _chat_via_agent(
        user_id=body.user_id,
        session_id=body.session_id,
        course_id=course_id,
        mode=body.mode,
        user_message=body.message,
        message_history=message_history,
        use_shared_context=body.use_shared_context,
        request_id=request_id,
        model_pref=model_pref if model_pref is not None else body.model_pref,
    )

    # Encryption happens inside save_message (`encrypt_if_present`).
    await _save_turn_rows(body, response["reply"], response.get("graph_update") or None,
                          user_row_id=user_row_id, assistant_row_id=assistant_row_id)

    # #117: one chat.message_sent per persisted turn. The message text is
    # fingerprinted via content= — it never enters a payload. request_id is
    # explicit, the same id whichever path (JSON route or the stream's
    # fallback) serves the turn.
    events_service.log_event(
        "chat.message_sent",
        category="usage",
        user_id=body.user_id,
        request_id=request_id,
        payload={"mode": body.mode, "session_id": body.session_id},
        content=body.message,
    )
    _observe_persisted_turn(
        body, history=message_history, ran_on=ran_on, request_id=request_id,
    )

    return response


async def chat(body: ChatBody, request: Request):
    await guard_off_loop(require_self, body.user_id, request)
    await _open_turn_session(body.session_id, body.user_id)
    # #761: the client's fallback for a stream whose `done` it never saw. If
    # that turn already persisted, answer with it instead of running it again.
    replay = await _persisted_turn(body.session_id, body.turn_id)
    if replay is not None:
        return replay
    return await _agent_turn_or_http_error(
        _chat_turn_json(body, request), what="chat agent"
    )


async def _action_turn(body: ActionBody, request: Request) -> dict:
    """One hint/confused/skip turn on chat_tutor_agent (#151a, D3-A1):
    same "[ACTION: ...]" user message the legacy pipeline sent, full prior
    history, persist assistant-only (today's shape — action turns never
    write a user row). Graph writes land in-band via the agent's tools.

    Function-mode note: dispatch is by task, and this runs task
    "chat_tutor" — the E2E lane's chat_tutor handler covers it with no new
    handler registration.
    """
    action_prompts = {
        "hint": "The student asked for a hint. Give a small scaffold or clue without giving away the answer.",
        "confused": "The student said they are confused. Identify the likely point of confusion and re-explain with a different analogy.",
        "skip": "The student wants to skip this concept. Acknowledge and transition to the next recommended concept.",
    }
    action_message = f"[ACTION: {action_prompts.get(body.action_type, '')}]"

    request_id = (
        getattr(request.state, "request_id", None)
        or current_request_id()
        or str(uuid.uuid4())
    )

    # Session keys on the offering; the graph + shared context key on the
    # abstract course derived from it.
    course_id, message_history = await asyncio.gather(
        _session_course_id(body.session_id), _load_message_history(body.session_id),
    )

    agent, assembled, run_kwargs, deps = await run_in_threadpool(
        _prepare_chat_run,
        user_id=body.user_id,
        session_id=body.session_id,
        course_id=course_id,
        mode=body.mode,
        user_message=action_message,
        message_history=message_history,
        use_shared_context=body.use_shared_context,
        request_id=request_id,
        model_pref=body.model_pref,
    )

    result = record_agent_usage(
        await agent.run(assembled, **run_kwargs),
        feature="chat_tutor", task="chat_tutor", user_id=body.user_id,
        request_id=request_id,
    )
    # History-bearing run (`_load_message_history` above), so `.output` alone
    # would hand back the previous turn's assistant message when this turn's
    # model response carries no text part — and `save_message` below would
    # persist that duplicate — and is only the FINAL model response anyway,
    # dropping text written before a tool call (ADR 0030). See `_new_run_text`.
    reply = _new_run_text(result)
    if not reply.strip():
        # #153: degenerate whitespace-only output, or a turn that ended after
        # tool calls with no text at all. Finish the turn if the model will
        # (#646) — an action turn has no fallback rung at all, so the
        # alternative is failing work the tools already did.
        try:
            rescued = await _continuation_text(agent, result, run_kwargs, request_id=request_id)
        except Exception:
            logger.warning(
                "Continuation after a textless action turn failed", exc_info=True
            )
            rescued = None
        if rescued:
            logger.info("Textless action turn rescued by a continuation")
            reply = rescued
        else:
            # Surface through the guardrail mapping rather than persisting an
            # empty or stale assistant row.
            raise UnexpectedModelBehavior(
                "chat_tutor produced no action reply text this turn"
            )

    graph_update = merge_graph_updates(deps.graph_updates)
    await save_message(body.session_id, "assistant", reply, graph_update or None)
    return {"reply": reply, "graph_update": graph_update}


async def action(body: ActionBody, request: Request):
    await guard_off_loop(require_self, body.user_id, request)
    await _open_turn_session(body.session_id, body.user_id)
    return await _agent_turn_or_http_error(
        _action_turn(body, request), what="action agent"
    )
