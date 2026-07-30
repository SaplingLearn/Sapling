# backend/services/chat_stream.py
"""Translate a Pydantic AI chat run into Sapling SSE events.

The single seam for streaming chat turns (ADR 0006 vocabulary). Iterates
`agent.run_stream_events()` — the only API that yields BOTH text deltas and
mid-run tool events in one pass — and emits:

    status:start -> token* -> (progress:<tool> -> graph_update)* -> done

Graph deltas are READ from `deps.graph_updates` / `deps.mastery_changes`,
which the graph tools populate as they write through
`graph_service.apply_graph_update` (ADR 0004). This module never writes the
graph and never persists a message: persistence is the route's, via
`on_complete`.

At most one of `on_complete` / `nonstream_fallback` runs per turn — never
both, and the error rungs run neither. See `stream_agent_turn` for the rungs.
"""

from __future__ import annotations

import logging
from typing import Any, AsyncIterator, Awaitable, Callable

from services.agent_events import SaplingEvent

logger = logging.getLogger(__name__)


def merge_graph_updates(updates: list[dict]) -> dict:
    """Merge tool-emitted payloads into one {key: [items]} dict.

    Mirrors the merge in `routes.learn._chat_via_agent` verbatim: keys
    concatenate (setdefault + extend), never clobber.
    """
    merged: dict = {}
    for gu in updates:
        for key, items in gu.items():
            merged.setdefault(key, []).extend(items)
    return merged


def _text_from(event: Any) -> str | None:
    """Extract a NEW text chunk from a stream event, or None.

    Dispatches on class name, which matters more than it looks (all three
    shapes below were observed live against gemini-2.5-pro on 2026-07-16):

      PartStartEvent  -> part.content        the reply's FIRST chunk
      PartDeltaEvent  -> delta.content_delta each subsequent chunk
      PartEndEvent    -> part.content        the FULL assembled text — SKIP

    Reading `part.content` generically would emit the whole reply a second
    time when PartEndEvent lands ("hello world" -> "hello worldhello
    world"). Reading only deltas would drop the opening chunk. Both are
    regression-tested.

    Class-name dispatch alone is NOT enough, though: `PartStartEvent` and
    `PartDeltaEvent` wrap ANY part kind, not just text — a `ThinkingPart` /
    `ThinkingPartDelta` (pydantic-ai 1.89.1, `pydantic_ai.messages`) rides
    the exact same event classes with the exact same attribute names
    (`.part.content` / `.delta.content_delta`). Gate on the part's own
    discriminator so reasoning content can never masquerade as reply text:
    `TextPart.part_kind == "text"`, `TextPartDelta.part_delta_kind ==
    "text"` (verified by inspecting the installed library — `ThinkingPart`/
    `ThinkingPartDelta` carry `"thinking"` in the same fields). Today
    `_build_pro_model_settings` never sets `include_thoughts`, so this is
    latent — but the moment thought summaries are enabled, an ungated
    reader would stream raw chain-of-thought into a student's chat bubble.
    """
    cls_name = type(event).__name__

    if cls_name == "PartDeltaEvent":
        delta = getattr(event, "delta", None)
        if getattr(delta, "part_delta_kind", None) != "text":
            return None
        content_delta = getattr(delta, "content_delta", None)
        return content_delta if isinstance(content_delta, str) and content_delta else None

    if cls_name == "PartStartEvent":
        part = getattr(event, "part", None)
        if getattr(part, "part_kind", None) != "text":
            return None
        content = getattr(part, "content", None)
        return content if isinstance(content, str) and content else None

    # PartEndEvent / FinalResultEvent / tool + result events carry no NEW text.
    return None


def _tool_name_from(event: Any) -> str | None:
    for path in ("part.tool_name", "tool_name", "result.tool_name"):
        obj: Any = event
        try:
            for attr in path.split("."):
                obj = getattr(obj, attr)
            if isinstance(obj, str):
                return obj
        except AttributeError:
            continue
    return None


async def _rung1_fallback_events(
    nonstream_fallback: Callable[[], Awaitable[dict]] | None,
    request_id: str,
) -> AsyncIterator[SaplingEvent]:
    """The Rung-1 tail shared by 'agent failed before text' and 'agent
    finished but produced a blank reply' (#153): degrade to the route's
    non-streaming turn when one exists, else a terminal `error`. The
    fallback owns its own persistence, so callers must NOT also run
    on_complete.

    Callers guarantee NO graph/mastery writes landed before entering (the
    writes-guard in `stream_agent_turn` short-circuits to a terminal
    `retryable: False` error instead), so both error events here are safely
    `retryable: True` — re-running the turn has nothing to double-apply."""
    if nonstream_fallback is None:
        yield SaplingEvent(
            type="error",
            step="reply",
            message="The tutor is unavailable. Please retry.",
            data={"request_id": request_id, "retryable": True},
        )
        return
    try:
        fallback_result = await nonstream_fallback()
    except Exception:
        logger.exception("Nonstream fallback also failed")
        yield SaplingEvent(
            type="error",
            step="reply",
            message="The tutor is unavailable. Please retry.",
            data={"request_id": request_id, "retryable": True},
        )
        return
    # nonstream_fallback persisted its own rows; the caller must NOT call
    # on_complete after this. Wire shape: ONE token carrying the whole
    # fallback reply, then done.
    yield SaplingEvent(
        type="token", step="reply", message="",
        data={"delta": fallback_result.get("reply", "")},
    )
    yield SaplingEvent(
        type="done", step="reply", message="Complete.", data=fallback_result
    )


async def stream_agent_turn(
    *,
    agent: Any,
    user_message: str,
    run_kwargs: dict,
    deps: Any,
    on_complete: Callable[[str, dict, list], dict | None],
    nonstream_fallback: Callable[[], Awaitable[dict]] | None = None,
    on_usage: Callable[[Any], None] | None = None,
    request_id: str = "",
) -> AsyncIterator[SaplingEvent]:
    """Stream one agent turn as SaplingEvents.

    on_complete(reply, merged_graph_update, mastery_changes) -> extra `done`
    data. It persists; on the success path it is called once, after the run
    completes and BEFORE `done` is yielded, so a mid-generation disconnect
    (which cancels this generator at its current yield) persists nothing.

    on_usage(run_result) -> observability hook (#118): called once with the
    final `AgentRunResult` after the stream completes, BEFORE on_complete —
    tokens were spent even if persistence subsequently fails. Routes pass
    `agents.usage.record_agent_usage` here. Not called on the error rungs
    (no result event was seen) nor on the Rung-1 nonstream fallback, which
    records its own usage (`record_agent_usage` inside the route's JSON
    turn). It IS called on the degenerate blank-reply rung (#153) — there
    the agent run completed and billed before its output was judged
    unusable. A hook failure is swallowed: usage capture must never break
    the stream.

    nonstream_fallback() -> awaitable returning the route's non-streaming
    turn result (the same agent pipeline the JSON route serves, on the fast
    tier), used ONLY when the agent fails before emitting any text
    (Rung 1). It owns its own persistence, so on_complete is NOT called on
    that branch — calling both double-writes.

    Writes-guard (#470, generalized): a fallback re-RUNS the whole turn, so
    it is only safe when the failed run wrote nothing. If any graph/mastery
    tool write landed (`deps.graph_updates` / `deps.mastery_changes`
    non-empty) at Rung-1 time, the fallback is NOT invoked — the turn ends
    in a terminal `error` carrying `retryable: False`, telling the client
    to skip its own JSON-fallback rung too. Every `error` event carries
    `retryable` (additive, #151a): True unless writes landed.

    Invariant: AT MOST one of on_complete / nonstream_fallback runs per
    turn — never both. The error rungs run NEITHER: Rung 2 (failure after
    tokens streamed), Rung 1 with writes, Rung 1 with no fallback, and a
    Rung-1 fallback that itself raises all yield an `error` event and
    persist nothing to the transcript (regression-tested in
    test_chat_stream.py).

    A run that COMPLETES with a whitespace-only reply (#153: gemini-2.5-pro
    sometimes emits a bare-newline final text after an end-of-turn tool
    call) is degenerate, not a success: the joined streamed chunks stand in
    when they carry real text; otherwise the turn takes the Rung-1 ladder
    above rather than persisting an empty assistant row.
    """
    yield SaplingEvent(type="status", step="start", message="Starting.")

    chunks: list[str] = []
    final_output: str | None = None
    run_result: Any = None
    # High-water marks: how much of deps.* we have already emitted.
    graph_hw = 0
    mastery_hw = 0

    try:
        async for event in agent.run_stream_events(user_message, **run_kwargs):
            text = _text_from(event)
            if text:
                chunks.append(text)
                yield SaplingEvent(
                    type="token", step="reply", message="", data={"delta": text}
                )
                continue

            cls_name = type(event).__name__

            if cls_name == "FunctionToolCallEvent":
                tool = _tool_name_from(event) or "tool"
                yield SaplingEvent(
                    type="progress", step=tool, message=f"Calling {tool}."
                )
                continue

            if cls_name == "FunctionToolResultEvent":
                # A graph tool may have just written. Emit only what is new.
                new_nodes = merge_graph_updates(deps.graph_updates[graph_hw:])
                new_mastery = deps.mastery_changes[mastery_hw:]
                graph_hw = len(deps.graph_updates)
                mastery_hw = len(deps.mastery_changes)
                if new_nodes or new_mastery:
                    yield SaplingEvent(
                        type="graph_update",
                        step="graph",
                        message="Knowledge graph updated.",
                        data={"nodes": new_nodes, "mastery_changes": new_mastery},
                    )
                continue

            if cls_name == "AgentRunResultEvent":
                run_result = getattr(event, "result", None)
                output = getattr(run_result, "output", None)
                if isinstance(output, str):
                    final_output = output

    # Catches UsageLimitExceeded / UnexpectedModelBehavior (both Exception
    # subclasses) and anything else the model or a tool raises. Deliberately
    # NOT BaseException: asyncio.CancelledError must propagate so a client
    # disconnect stays a cancellation — never a fallback re-run.
    except Exception as exc:
        write_count = len(deps.graph_updates) + len(deps.mastery_changes)
        if chunks:
            # Rung 2: text already shown. Never silently re-run — the user
            # would see the reply restart. Terminal error; persist nothing.
            # retryable is False when tool writes landed: a client re-send
            # would re-run the turn and re-apply them.
            logger.warning("Chat stream failed mid-generation", exc_info=exc)
            yield SaplingEvent(
                type="error",
                step="reply",
                message="The tutor was interrupted. Please retry.",
                data={"request_id": request_id, "retryable": write_count == 0},
            )
            return

        if write_count:
            # Rung 1 with writes (#470 generalized): the fallback would
            # re-run the whole turn and its tools would apply the writes
            # AGAIN — double mastery for one student turn. Terminal error;
            # the writes stay (they were real tool actions), and
            # retryable: False tells the client to skip its JSON rung too.
            logger.warning(
                "Chat agent failed before first token but AFTER %d graph "
                "write(s); terminal error instead of a fallback that would "
                "re-apply them", write_count, exc_info=exc,
            )
            yield SaplingEvent(
                type="error",
                step="reply",
                message="The tutor was interrupted. Please retry.",
                data={"request_id": request_id, "retryable": False},
            )
            return

        # Rung 1: nothing shown, nothing written — degrade to the route's
        # non-streaming turn.
        logger.warning(
            "Chat agent failed before first token; using the nonstream "
            "fallback", exc_info=exc,
        )
        async for ev in _rung1_fallback_events(nonstream_fallback, request_id):
            yield ev
        return

    joined = "".join(chunks)
    reply = final_output if final_output is not None else joined

    # Usage first, persistence second: the tokens were spent regardless of
    # whether on_complete manages to persist — including on the degenerate
    # blank-reply rung below, where the agent run DID complete and bill.
    # Guarded — instrumentation must never turn a streamed reply into an
    # error event.
    if on_usage is not None and run_result is not None:
        try:
            on_usage(run_result)
        except Exception:
            logger.debug("on_usage hook failed; usage row dropped", exc_info=True)

    if not reply.strip():
        # Degenerate output (#153, ADR-0023 follow-up): gemini-2.5-pro
        # occasionally follows an end-of-turn tool call with a bare-newline
        # final text, making the run OUTPUT whitespace-only. The real reply
        # may still have streamed earlier in the turn — prefer the joined
        # chunks. If nothing non-blank streamed either, never persist an
        # empty assistant row: degrade exactly like Rung 1 (legacy fallback
        # owns the turn, or a terminal `error` without one). Tool writes
        # that already landed stay, matching the existing Rung-1 contract
        # for a failure after a tool write.
        if joined.strip():
            reply = joined
        elif deps.graph_updates or deps.mastery_changes:
            # Tool writes ALREADY LANDED this turn (append-only mastery
            # events, graph upserts). The nonstream fallback would re-run
            # the whole turn and its tools would apply the writes AGAIN —
            # double mastery for one student turn (PR #470 review). A
            # terminal error is the honest degrade: the writes stay (they
            # were real tool actions), nothing is persisted to the
            # transcript, and the client's ADR-0020 interrupted+Retry
            # treatment applies — with retryable: False so it never re-runs
            # the turn via its JSON rung either.
            logger.warning(
                "Agent turn produced a blank reply AFTER %d graph write(s); "
                "terminal error instead of a fallback that would re-apply "
                "them", len(deps.graph_updates) + len(deps.mastery_changes),
            )
            yield SaplingEvent(
                type="error",
                step="reply",
                message="The tutor was interrupted. Please retry.",
                data={"request_id": request_id, "retryable": False},
            )
            return
        else:
            logger.warning(
                "Agent turn produced a blank reply and no writes; "
                "degrading to Rung 1",
            )
            async for ev in _rung1_fallback_events(nonstream_fallback, request_id):
                yield ev
            return

    merged = merge_graph_updates(deps.graph_updates)
    mastery = list(deps.mastery_changes)

    try:
        extra = on_complete(reply, merged, mastery) or {}
    except Exception as exc:
        # Persistence failed AFTER the reply fully streamed. Letting this
        # propagate would abort the ASGI response mid-stream with no closing
        # event (sse_starlette has already flushed headers), leaving the
        # client an unstructured network error. Emit the structured error
        # instead so the ADR-0020 interrupted-turn treatment (keep partial
        # text, offer Retry) applies; the turn persisted at most a partial
        # write, and Retry re-sends it.
        logger.warning("on_complete persistence failed after streamed reply", exc_info=exc)
        yield SaplingEvent(
            type="error",
            step="reply",
            message="The tutor was interrupted. Please retry.",
            data={
                "request_id": request_id,
                "retryable": not (deps.graph_updates or deps.mastery_changes),
            },
        )
        return

    yield SaplingEvent(
        type="done",
        step="reply",
        message="Complete.",
        data={
            "reply": reply,
            "graph_update": merged,
            "mastery_changes": mastery,
            **extra,
        },
    )
