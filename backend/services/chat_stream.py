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

Exactly one of `on_complete` / `legacy_fallback` runs per turn — see
`stream_agent_turn` for the rungs.
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


async def stream_agent_turn(
    *,
    agent: Any,
    user_message: str,
    run_kwargs: dict,
    deps: Any,
    on_complete: Callable[[str, dict, list], dict | None],
    legacy_fallback: Callable[[], Awaitable[dict]] | None = None,
    request_id: str = "",
) -> AsyncIterator[SaplingEvent]:
    """Stream one agent turn as SaplingEvents.

    on_complete(reply, merged_graph_update, mastery_changes) -> extra `done`
    data. It persists; it is called exactly once, after the run completes and
    BEFORE `done` is yielded, so a mid-generation disconnect (which cancels
    this generator at its current yield) persists nothing.

    legacy_fallback() -> awaitable returning the route's pre-agent result,
    used ONLY when the agent fails before emitting any text (Rung 1). It is
    async because the routes' legacy paths are (`_legacy_chat`). It owns its
    own persistence, so on_complete is NOT called on that branch — calling
    both double-writes.
    """
    yield SaplingEvent(type="status", step="start", message="Starting.")

    chunks: list[str] = []
    final_output: str | None = None
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
                output = getattr(getattr(event, "result", None), "output", None)
                if isinstance(output, str):
                    final_output = output

    # Catches UsageLimitExceeded / UnexpectedModelBehavior (both Exception
    # subclasses) and anything else the model or a tool raises. Deliberately
    # NOT BaseException: asyncio.CancelledError must propagate so a client
    # disconnect stays a cancellation — never a "fallback to legacy".
    except Exception as exc:
        if chunks:
            # Rung 2: text already shown. Never silently re-run — the user
            # would see the reply restart. Terminal error; persist nothing.
            logger.warning("Chat stream failed mid-generation", exc_info=exc)
            yield SaplingEvent(
                type="error",
                step="reply",
                message="The tutor was interrupted. Please retry.",
                data={"request_id": request_id},
            )
            return

        # Rung 1: nothing shown yet — degrade to the route's legacy path.
        logger.warning("Chat agent failed before first token; using legacy", exc_info=exc)
        if legacy_fallback is None:
            yield SaplingEvent(
                type="error",
                step="reply",
                message="The tutor is unavailable. Please retry.",
                data={"request_id": request_id},
            )
            return
        try:
            legacy = await legacy_fallback()
        except Exception:
            logger.exception("Legacy fallback also failed")
            yield SaplingEvent(
                type="error",
                step="reply",
                message="The tutor is unavailable. Please retry.",
                data={"request_id": request_id},
            )
            return
        # legacy_fallback persisted its own rows; do NOT call on_complete.
        yield SaplingEvent(
            type="token", step="reply", message="",
            data={"delta": legacy.get("reply", "")},
        )
        yield SaplingEvent(
            type="done", step="reply", message="Complete.", data=legacy
        )
        return

    reply = final_output if final_output is not None else "".join(chunks)
    merged = merge_graph_updates(deps.graph_updates)
    mastery = list(deps.mastery_changes)

    extra = on_complete(reply, merged, mastery) or {}

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
