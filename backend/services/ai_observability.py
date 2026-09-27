"""PostHog AI Observability attributes for Pydantic AI OpenTelemetry spans."""

from __future__ import annotations

import contextvars
from typing import Any

from config import POSTHOG_HOST, POSTHOG_PROJECT_TOKEN


_AI_SESSION_ID: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "posthog_ai_session_id", default=None
)
_AI_DISTINCT_ID: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "posthog_ai_distinct_id", default=None
)


def bind_ai_context(
    *, session_id: str | None, distinct_id: str | None, request_id: str | None
) -> None:
    """Bind the current agent run to its conversation and authenticated user.

    Chat runs supply their persisted session ID. Other request-scoped agent
    workflows use their request ID as a one-request AI session, which keeps
    independent uploads, notes, and quizzes from being grouped together.
    """
    resolved_session_id = session_id or request_id
    _AI_SESSION_ID.set(str(resolved_session_id) if resolved_session_id else None)
    _AI_DISTINCT_ID.set(str(distinct_id) if distinct_id else None)


class AIAttributionSpanProcessor:
    """Add request-scoped PostHog attribution to Pydantic AI spans."""

    def on_start(self, span: Any, parent_context: Any = None) -> None:
        session_id = _AI_SESSION_ID.get()
        distinct_id = _AI_DISTINCT_ID.get()
        if session_id:
            span.set_attribute("$ai_session_id", session_id)
        if distinct_id:
            span.set_attribute("posthog.distinct_id", distinct_id)

    def on_end(self, span: Any) -> None:
        return None

    def shutdown(self) -> None:
        return None

    def force_flush(self, timeout_millis: int = 30_000) -> bool:
        return True


def posthog_ai_span_processors() -> list[Any]:
    """Return PostHog processors when the existing optional client is configured."""
    if not POSTHOG_PROJECT_TOKEN or not POSTHOG_HOST:
        return []

    # This optional import keeps production deployments without PostHog
    # configuration as no-ops, matching the existing product-analytics client.
    from posthog.ai.otel import PostHogSpanProcessor

    return [
        AIAttributionSpanProcessor(),
        PostHogSpanProcessor(api_key=POSTHOG_PROJECT_TOKEN, host=POSTHOG_HOST),
    ]
