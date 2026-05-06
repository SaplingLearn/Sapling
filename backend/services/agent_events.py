"""SSE event shapes and translator for Pydantic AI agent streams.

Dispatches by type(event).__name__ — never imports Pydantic AI types,
so the mapper survives event-class renames between versions. The
route is the only consumer.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


SaplingEventType = Literal["status", "progress", "result", "error"]


class SaplingEvent(BaseModel):
    """The single event shape the frontend consumes over SSE."""

    type: SaplingEventType
    step: str = Field(
        description="Pipeline step ('classify', 'summarize', "
                    "'graph_update', 'finalize'). Stable for switch."
    )
    message: str = Field(description="Human-readable progress text.")
    data: dict[str, Any] | None = Field(
        default=None,
        description="Optional structured payload (final result, etc.).",
    )


# Match lists span both Pydantic AI 1.89's actual emitter names and
# the legacy/spec names; the mapper survives churn in either direction.
_START_NAMES = {"AgentRunStartEvent", "AgentStartEvent"}
_TOOL_CALL_NAMES = {"FunctionToolCallEvent", "ToolCallEvent", "BuiltinToolCallEvent"}
_TOOL_RESULT_NAMES = {"FunctionToolResultEvent", "ToolReturnEvent", "BuiltinToolResultEvent"}
_FINAL_RESULT_NAMES = {"FinalResultEvent", "AgentRunResultEvent"}


def map_to_sapling_event(event: Any) -> SaplingEvent | None:
    """Translate a Pydantic AI stream event to a SaplingEvent (or None).

    Token-level deltas (PartDeltaEvent / PartStartEvent / PartEndEvent /
    ModelResponseStreamEvent / HandleResponseEvent) drop to None — we
    don't expose mid-completion text. Errors are surfaced by the route,
    not the mapper. The mapper never raises.
    """
    cls_name = type(event).__name__

    if cls_name in _START_NAMES:
        return SaplingEvent(
            type="status",
            step="start",
            message="Starting document processing.",
        )

    if cls_name in _TOOL_CALL_NAMES:
        tool_name = _tool_name_from(event)
        return SaplingEvent(
            type="progress",
            step=tool_name or "tool_call",
            message=f"Calling {tool_name}." if tool_name else "Calling a tool.",
        )

    if cls_name in _TOOL_RESULT_NAMES:
        tool_name = _tool_name_from(event)
        return SaplingEvent(
            type="progress",
            step=tool_name or "tool_result",
            message=f"{tool_name} completed." if tool_name else "Tool completed.",
        )

    if cls_name in _FINAL_RESULT_NAMES:
        output = getattr(event, "output", None) or getattr(event, "result", None)
        data: dict[str, Any] | None = None
        if output is not None and hasattr(output, "model_dump"):
            data = output.model_dump()
        return SaplingEvent(
            type="result",
            step="finalize",
            message="Processing complete.",
            data=data,
        )

    # Token-level deltas, internal model-message events, etc. → skip.
    return None


def _tool_name_from(event: Any) -> str | None:
    """Best-effort tool-name extraction across Pydantic AI versions."""
    for attr_path in ("tool_name", "part.tool_name", "call.tool_name", "name"):
        obj: Any = event
        try:
            for part in attr_path.split("."):
                obj = getattr(obj, part)
            if isinstance(obj, str):
                return obj
        except AttributeError:
            continue
    return None


def sapling_event_to_sse(event: SaplingEvent) -> dict[str, str]:
    """Format for sse_starlette.EventSourceResponse: SSE event name +
    JSON-encoded full payload, so the frontend can switch on type and
    still read the full structured event."""
    return {"event": event.type, "data": event.model_dump_json()}
