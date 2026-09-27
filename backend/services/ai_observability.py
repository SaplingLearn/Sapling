"""PostHog LLM analytics from Pydantic AI's OpenTelemetry spans — allowlisted.

``logfire.instrument_pydantic_ai()`` already emits one span per agent run,
model request and tool call. ``posthog_ai_span_processors()`` hands
``logfire.configure`` one extra span processor that forwards those spans to
PostHog's AI ingestion endpoint, where they become ``$ai_generation`` /
``$ai_span`` / ``$ai_trace`` events — in privacy mode, because the content
never leaves this module.

**Why an allowlist, not a denylist or Logfire's scrubber.** The app decrypts
names, notes, chat messages and document text straight into prompts, and
Pydantic AI puts prompts, completions, system instructions, tool arguments
and tool results on span attributes and span events. Logfire's scrubber is
pattern-based and happens to run before ``additional_span_processors`` in the
pinned version — neither property is something to stake student data on. So
``AllowlistSpanProcessor`` rebuilds every span from scratch, copying across
ONLY the keys in ``_ALLOWED_KEYS`` / ``_ALLOWED_NUMERIC_PREFIXES`` with
scalar values, and nothing else: no events, no links, no status description,
and a resource cut down to the service name. A key Pydantic AI adds tomorrow
is dropped until someone adds it here on purpose.

What survives — enough for PostHog's LLM analytics (model, tokens, cost,
latency, errors), none of it content:

* model / provider / operation: ``gen_ai.request.model``,
  ``gen_ai.response.model``, ``gen_ai.system``, ``gen_ai.provider.name``,
  ``gen_ai.operation.name``, ``gen_ai.response.finish_reasons``, and the
  numeric request knobs (temperature, max_tokens, top_p, top_k, seed)
* tokens: every numeric ``gen_ai.usage.*`` / ``gen_ai.aggregated_usage.*``
* cost: ``operation.cost``
* latency: the span's own start/end timestamps
* agent / tool NAMES: ``gen_ai.agent.name``, ``agent_name``,
  ``gen_ai.tool.name`` (never ``gen_ai.tool.call.arguments`` / ``.result``,
  ``tool_arguments``, ``tool_response``)
* status CODE, and ``error.type`` — the exception CLASS, taken from the
  span's exception event when the span has no ``error.type`` of its own
* attribution: ``posthog.distinct_id`` (the user UUID) and ``$ai_session_id``
  (a chat session id or request id), from ``bind_ai_context``.

Gated by ``services.posthog_client.disabled_reason`` — the same gate as the
event client, so tests and the function-mode E2E lanes build no processor and
no exporter at all.
"""

from __future__ import annotations

import contextvars
import logging
import threading
from typing import Any, Sequence

from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import ReadableSpan, SpanProcessor
from opentelemetry.trace import Status

logger = logging.getLogger("sapling.ai_observability")

_AI_SESSION_ID: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "posthog_ai_session_id", default=None,
)
_AI_DISTINCT_ID: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "posthog_ai_distinct_id", default=None,
)

DISTINCT_ID_ATTR = "posthog.distinct_id"
SESSION_ID_ATTR = "$ai_session_id"

_ALLOWED_KEYS: frozenset[str] = frozenset({
    # model / provider / operation
    "gen_ai.operation.name",
    "gen_ai.system",
    "gen_ai.provider.name",
    "gen_ai.request.model",
    "gen_ai.response.model",
    "gen_ai.response.finish_reasons",
    "gen_ai.request.temperature",
    "gen_ai.request.max_tokens",
    "gen_ai.request.top_p",
    "gen_ai.request.top_k",
    "gen_ai.request.seed",
    # cost
    "operation.cost",
    # agent / tool names
    "gen_ai.agent.name",
    "agent_name",
    "gen_ai.tool.name",
    # errors (class name only)
    "error.type",
    # attribution (UUIDs), stamped by this module
    DISTINCT_ID_ATTR,
    SESSION_ID_ATTR,
})

# Token counts. Numeric values only — a string under these prefixes is dropped.
_ALLOWED_NUMERIC_PREFIXES: tuple[str, ...] = ("gen_ai.usage.", "gen_ai.aggregated_usage.")

# Names, models and enums are short; anything longer is not what we allowed.
_MAX_STR_LEN = 128

_RESOURCE_KEYS = ("service.name", "service.version", "deployment.environment")


def bind_ai_context(
    *, session_id: str | None, distinct_id: str | None, request_id: str | None,
) -> None:
    """Attribute the agent runs that follow (in this context) to a user.

    Called from ``SaplingDeps.__post_init__``. Chat runs carry their persisted
    session id; other request-scoped runs use the request id as a one-request
    AI session, so unrelated uploads/quizzes are not grouped together.
    Never raises — it runs inside a dataclass constructor.
    """
    try:
        resolved = session_id or request_id
        _AI_SESSION_ID.set(str(resolved) if resolved else None)
        _AI_DISTINCT_ID.set(str(distinct_id) if distinct_id else None)
    except Exception:  # pragma: no cover - defensive
        logger.debug("bind_ai_context failed", exc_info=True)


def _scalar_ok(value: Any) -> bool:
    if isinstance(value, bool) or isinstance(value, (int, float)):
        return True
    if isinstance(value, str):
        return len(value) <= _MAX_STR_LEN
    return False


def _allowed_value(key: str, value: Any) -> bool:
    if key.startswith(_ALLOWED_NUMERIC_PREFIXES):
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if key not in _ALLOWED_KEYS:
        return False
    if isinstance(value, (list, tuple)):
        return all(_scalar_ok(v) for v in value)
    return _scalar_ok(value)


def _error_type(span: ReadableSpan) -> str | None:
    for event in span.events or ():
        if event.name == "exception":
            exc_type = (event.attributes or {}).get("exception.type")
            if isinstance(exc_type, str) and len(exc_type) <= _MAX_STR_LEN:
                return exc_type
    return None


def sanitize_span(
    span: ReadableSpan, *, attribution: dict[str, str] | None = None,
) -> ReadableSpan:
    """A copy of ``span`` carrying only allowlisted, content-free data."""
    attributes: dict[str, Any] = {}
    for key, value in (span.attributes or {}).items():
        if _allowed_value(key, value):
            attributes[key] = tuple(value) if isinstance(value, list) else value
    if "error.type" not in attributes:
        error_type = _error_type(span)
        if error_type:
            attributes["error.type"] = error_type
    for key, value in (attribution or {}).items():
        if value:
            attributes[key] = value

    resource_attrs = {
        k: v for k, v in (span.resource.attributes if span.resource else {}).items()
        if k in _RESOURCE_KEYS and _scalar_ok(v)
    }
    return ReadableSpan(
        name=span.name,
        context=span.context,
        parent=span.parent,
        resource=Resource(resource_attrs),
        attributes=attributes,
        events=(),
        links=(),
        kind=span.kind,
        # Status CODE only: the description is an exception message.
        status=Status(span.status.status_code),
        start_time=span.start_time,
        end_time=span.end_time,
        instrumentation_scope=span.instrumentation_scope,
    )


def _is_ai_span(span: ReadableSpan) -> bool:
    from posthog.ai.otel import is_ai_span

    return is_ai_span(span)


class AllowlistSpanProcessor(SpanProcessor):
    """Sanitize AI spans, then hand them to ``delegate`` (PostHog's exporter).

    Non-AI spans (HTTP, DB, everything Logfire traces that is not Pydantic
    AI) never reach the delegate at all. Every hook swallows its own errors:
    an analytics exporter must not be able to break a span Logfire needs.
    """

    # Attribution is captured at span START (the contextvars are the caller's
    # there; on_end can run on another thread) and applied at END, without
    # writing it onto the live span — that span also goes to Logfire.
    _MAX_PENDING = 10_000

    def __init__(self, delegate: SpanProcessor) -> None:
        self._delegate = delegate
        self._pending: dict[int, dict[str, str]] = {}
        self._lock = threading.Lock()

    def on_start(self, span: Any, parent_context: Any = None) -> None:
        try:
            distinct_id = _AI_DISTINCT_ID.get()
            session_id = _AI_SESSION_ID.get()
            if not (distinct_id or session_id):
                return
            attribution = {}
            if distinct_id:
                attribution[DISTINCT_ID_ATTR] = distinct_id
            if session_id:
                attribution[SESSION_ID_ATTR] = session_id
            with self._lock:
                if len(self._pending) >= self._MAX_PENDING:
                    # Spans that never ended (should not happen): forget the
                    # oldest rather than grow without bound.
                    self._pending.pop(next(iter(self._pending)))
                self._pending[span.context.span_id] = attribution
        except Exception:
            logger.debug("AllowlistSpanProcessor.on_start failed", exc_info=True)

    def on_end(self, span: ReadableSpan) -> None:
        try:
            with self._lock:
                attribution = self._pending.pop(span.context.span_id, None)
            if not _is_ai_span(span):
                return
            self._delegate.on_end(sanitize_span(span, attribution=attribution))
        except Exception:
            logger.debug("AllowlistSpanProcessor.on_end failed", exc_info=True)

    def shutdown(self) -> None:
        try:
            self._delegate.shutdown()
        except Exception:
            logger.debug("AllowlistSpanProcessor.shutdown failed", exc_info=True)

    def force_flush(self, timeout_millis: int = 30_000) -> bool:
        try:
            return self._delegate.force_flush(timeout_millis)
        except Exception:
            return False


def posthog_ai_span_processors() -> Sequence[SpanProcessor]:
    """The processors to add to Logfire's pipeline: [] whenever PostHog is off.

    Evaluated once, at main.py import (``logfire.configure``), so the gate's
    inputs (env, pytest) must already be settled then — they are: the E2E
    lanes export SAPLING_MODEL_MODE before uvicorn starts.
    """
    from services.posthog_client import disabled_reason

    reason = disabled_reason()
    if reason is not None:
        return []
    try:
        import config
        from posthog.ai.otel import PostHogSpanProcessor

        return [
            AllowlistSpanProcessor(
                PostHogSpanProcessor(
                    api_key=config.posthog_project_token(),
                    host=config.posthog_host(),
                ),
            ),
        ]
    except Exception:
        logger.warning("PostHog AI tracing init failed; AI spans not exported", exc_info=True)
        return []
