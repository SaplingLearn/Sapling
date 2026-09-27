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
* attribution: ``posthog.distinct_id`` (the user id) and ``$ai_session_id``
  (a chat session id or request id), from ``bind_ai_context``.

**Attribution is bound per agent run, never ambiently.** ``bind_ai_context`` is
a context manager: it sets the attribution for the spans started inside it
and resets it on exit, so nothing leaks into later runs, the rest of the
request, or its BackgroundTasks. ``install_agent_run_boundary`` wraps
``pydantic_ai.Agent.iter`` — the one entry that ``run``, ``run_sync``,
``run_stream`` and ``run_stream_events`` all go through — so every run binds
from its own ``deps`` (``SaplingDeps.user_id`` / ``session_id`` /
``request_id``) and unbinds when it ends; a deps-less run binds the request's
session user, if any. It is installed only when PostHog is on.

**Consent is decided when each span ENDS, not when the run starts.** The
run boundary only records WHO the run is for (the deps user, else the
request's session user, else nobody) and starts warming that user's consent
answer in the background — it does no I/O itself. ``on_end`` then asks
``analytics_consent.consent_for`` (cached; never blocks an event loop — a miss
there is a "no"): a student who opted out, a deleted account, an unreadable or
not-yet-known answer SUPPRESSES the span — not exported at all, not even
anonymously — and so does a request carrying ``Sec-GPC: 1`` / ``DNT: 1``
(captured when the span starts). Checking at the end means a run that was in
flight when its user was deleted or opted out stops exporting from that
moment. A run with no actor (the sweeper, a placeholder id like "backfill")
is exported without a ``posthog.distinct_id``.

**Fail closed on bookkeeping too.** Every Pydantic AI span gets an entry at
start; a span whose entry is missing at end (evicted at the
``_MAX_PENDING`` cap, or never seen) is dropped rather than exported
unattributed.

PostHog reads ``posthog.distinct_id`` per SPAN: its OTLP capture resolves the
distinct id from span attributes first and falls back to resource attributes
(``rust/capture/src/otel/identity.rs``, ``extract_distinct_id_for_span`` —
"span attributes taking precedence over resource attributes ... distinct_id
must be resolved per-span"). A resource attribute is per process, so the span
is the only place a multi-user server can put it.

Gated by ``services.posthog_client.disabled_reason`` — the same gate as the
event client, so tests and the function-mode E2E lanes build no processor and
no exporter at all.
"""

from __future__ import annotations

import contextvars
import functools
import logging
import threading
from contextlib import asynccontextmanager, contextmanager
from typing import Any, Iterator, NamedTuple, Sequence

from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import ReadableSpan, SpanProcessor
from opentelemetry.trace import Status

from services.request_context import request_has_privacy_signal

logger = logging.getLogger("sapling.ai_observability")


class _Attribution(NamedTuple):
    suppress: bool
    #: The user to check consent for when each span ends (None = no actor).
    candidate: str | None
    session_id: str | None


_SUPPRESSED = _Attribution(True, None, None)

#: The attribution for spans started in this context: None = nothing bound
#: (spans export unattributed), or an _Attribution set by bind_ai_context.
_AI_ATTRIBUTION: contextvars.ContextVar[_Attribution | None] = contextvars.ContextVar(
    "posthog_ai_attribution", default=None,
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


def _resolve_attribution(
    *, session_id: str | None, distinct_id: str | None, request_id: str | None,
) -> _Attribution:
    """Who the run is for. No consent read here (see on_end) — only a
    non-blocking warm-up so the answer is cached by the time spans end."""
    from services.analytics_consent import is_placeholder, warm
    from services.request_context import current_session_user

    if request_has_privacy_signal():
        return _SUPPRESSED
    candidate: str | None = None
    if not is_placeholder(distinct_id):
        candidate = str(distinct_id).strip()
    else:
        # No actor named (a deps-less run, a placeholder id): the request's
        # own user, if any — both to attribute and to honour their opt-out.
        actor = current_session_user()
        if not is_placeholder(actor):
            candidate = str(actor).strip()
    if candidate is not None:
        warm(candidate)
    resolved = session_id or request_id
    return _Attribution(False, candidate, str(resolved) if resolved else None)


@contextmanager
def bind_ai_context(
    *, session_id: str | None, distinct_id: str | None, request_id: str | None,
) -> Iterator[None]:
    """Attribute the agent spans started inside this block, then unbind.

    Chat runs carry their persisted session id; other request-scoped runs use
    the request id as a one-request AI session, so unrelated uploads/quizzes
    are not grouped together. Fails closed: if the attribution cannot be
    resolved, the block's spans are suppressed. Never raises on its own
    account, and does no blocking I/O (it runs on the event loop).
    """
    try:
        attribution = _resolve_attribution(
            session_id=session_id, distinct_id=distinct_id, request_id=request_id,
        )
    except Exception:
        logger.debug("AI attribution resolution failed; suppressing", exc_info=True)
        attribution = _SUPPRESSED
    token = _AI_ATTRIBUTION.set(attribution)
    try:
        yield
    finally:
        try:
            _AI_ATTRIBUTION.reset(token)
        except ValueError:  # pragma: no cover - exited from another context
            logger.debug("bind_ai_context exited in a different context")


@contextmanager
def bind_ai_context_for_deps(deps: Any) -> Iterator[None]:
    """``bind_ai_context`` from an agent run's deps (a SaplingDeps, or None)."""
    from services.request_context import current_request_id

    with bind_ai_context(
        session_id=getattr(deps, "session_id", None),
        distinct_id=getattr(deps, "user_id", None),
        request_id=getattr(deps, "request_id", None) or current_request_id(),
    ):
        yield


_BOUNDARY_MARK = "__sapling_ai_attribution__"
_original_agent_iter: Any = None


def install_agent_run_boundary() -> None:
    """Bind/unbind attribution around every Pydantic AI agent run. Idempotent.

    Wraps ``Agent.iter`` (public API; ``run``/``run_stream``/
    ``run_stream_events`` all enter through it), so there is one boundary
    for every call site instead of a ``with`` at each of them — and a new
    call site cannot forget it. The wrapper only adds a context around the
    original; arguments and the yielded run are untouched.
    """
    global _original_agent_iter
    from pydantic_ai import Agent

    current = Agent.iter
    if getattr(current, _BOUNDARY_MARK, False):
        return
    original = current

    @asynccontextmanager
    async def iter_with_attribution(self, *args: Any, **kwargs: Any):
        with bind_ai_context_for_deps(kwargs.get("deps")):
            async with original(self, *args, **kwargs) as run:
                yield run

    functools.update_wrapper(iter_with_attribution, original)
    setattr(iter_with_attribution, _BOUNDARY_MARK, True)
    _original_agent_iter = original
    Agent.iter = iter_with_attribution


def uninstall_agent_run_boundary() -> None:
    """Undo ``install_agent_run_boundary`` (test-only)."""
    global _original_agent_iter
    from pydantic_ai import Agent

    if _original_agent_iter is not None and getattr(Agent.iter, _BOUNDARY_MARK, False):
        Agent.iter = _original_agent_iter
    _original_agent_iter = None


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


#: Instrumentation scopes whose spans can be AI spans. Pydantic AI creates
#: every agent-run / model-request / tool span on a tracer named
#: "pydantic-ai" (models/instrumented.py), under Logfire as well. Spans from
#: any other scope (HTTP, DB, httpx, ...) — the vast majority — are rejected
#: on a string compare, with no lock and no allowlist work.
_AI_SCOPES: frozenset[str] = frozenset({"pydantic-ai"})

# Identity markers in AllowlistSpanProcessor._pending.
_SUPPRESS_MARK = object()   # DNT/GPC or a suppressed binding: never export
_UNBOUND_MARK = object()    # started outside any run binding: export unattributed
_MISSING = object()         # no entry at end (evicted / unseen): never export


def _span_attribution(entry: Any) -> dict[str, str] | None:
    """The attributes to stamp on an ending span, or None to DROP it.

    Consent is (re-)checked here, at the end of every span, against the
    cached answer — so a deletion or opt-out that lands mid-run takes effect
    for the rest of that run. Non-blocking on an event loop (a miss is a no).
    """
    if entry is _UNBOUND_MARK:
        return {}
    attribution: dict[str, str] = {}
    if entry.session_id:
        attribution[SESSION_ID_ATTR] = entry.session_id
    if entry.candidate is None:
        return attribution
    from services.analytics_consent import Consent, consent_for

    if consent_for(entry.candidate) is not Consent.ALLOWED:
        return None
    attribution[DISTINCT_ID_ATTR] = entry.candidate
    return attribution


def _may_be_ai(span: Any) -> bool:
    scope = getattr(span, "instrumentation_scope", None)
    return scope is not None and scope.name in _AI_SCOPES


def _fallback_is_ai_span(span: ReadableSpan) -> bool:  # pragma: no cover
    prefixes = ("gen_ai.", "llm.", "ai.", "traceloop.")
    if span.name.startswith(prefixes):
        return True
    return any(k.startswith(prefixes) for k in (span.attributes or {}))


class AllowlistSpanProcessor(SpanProcessor):
    """Sanitize AI spans, then hand them to ``delegate`` (PostHog's exporter).

    Only spans from the Pydantic AI tracer that PostHog would also classify
    as AI spans reach the delegate; everything else Logfire traces never
    does. Every hook swallows its own errors: an analytics exporter must not
    be able to break a span Logfire needs.
    """

    # Attribution is captured at span START (the contextvars are the caller's
    # there; on_end can run on another thread) and applied at END, without
    # writing it onto the live span — that span also goes to Logfire.
    _MAX_PENDING = 10_000

    def __init__(self, delegate: SpanProcessor) -> None:
        self._delegate = delegate
        # span_id -> _Attribution | _SUPPRESS_MARK | _UNBOUND_MARK
        self._pending: dict[int, Any] = {}
        self._lock = threading.Lock()
        # Resolved once, not per span end.
        try:
            from posthog.ai.otel import is_ai_span
        except Exception:  # pragma: no cover - posthog[otel] missing
            is_ai_span = _fallback_is_ai_span
        self._is_ai_span = is_ai_span

    def on_start(self, span: Any, parent_context: Any = None) -> None:
        if not _may_be_ai(span):
            return
        try:
            bound = _AI_ATTRIBUTION.get()
            if request_has_privacy_signal() or (bound is not None and bound.suppress):
                entry: Any = _SUPPRESS_MARK
            else:
                entry = bound if bound is not None else _UNBOUND_MARK
            with self._lock:
                if len(self._pending) >= self._MAX_PENDING:
                    # Spans that never ended (should not happen): forget the
                    # oldest rather than grow without bound. Its end then
                    # finds no entry and is DROPPED (fail closed), never
                    # exported without the suppression it was started under.
                    self._pending.pop(next(iter(self._pending)))
                self._pending[span.context.span_id] = entry
        except Exception:
            logger.debug("AllowlistSpanProcessor.on_start failed", exc_info=True)

    def on_end(self, span: ReadableSpan) -> None:
        if not _may_be_ai(span):
            return
        try:
            with self._lock:
                entry = self._pending.pop(span.context.span_id, _MISSING)
            if entry is _MISSING or entry is _SUPPRESS_MARK:
                return
            if not self._is_ai_span(span):
                return
            attribution = _span_attribution(entry)
            if attribution is None:
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


#: The live processor (None when PostHog is off), for flush_ai_spans.
_processor: AllowlistSpanProcessor | None = None


def flush_ai_spans(timeout_millis: int = 10_000) -> None:
    """Export every AI span already queued (bounded). Never raises.

    Called before a PostHog person delete, so a span from before the account
    deletion cannot arrive after it and re-create the person.
    """
    processor = _processor
    if processor is None:
        return
    try:
        processor.force_flush(timeout_millis)
    except Exception:  # pragma: no cover - force_flush already swallows
        logger.debug("flush_ai_spans failed", exc_info=True)


def posthog_ai_span_processors() -> Sequence[SpanProcessor]:
    """The processors to add to Logfire's pipeline: [] whenever PostHog is off.

    Evaluated once, at main.py import (``logfire.configure``), so the gate's
    inputs (env, pytest) must already be settled then — they are: the E2E
    lanes export SAPLING_MODEL_MODE before uvicorn starts.
    """
    global _processor
    from services.posthog_client import disabled_reason

    reason = disabled_reason()
    if reason is not None:
        return []
    try:
        import config
        from posthog.ai.otel import PostHogSpanProcessor

        processor = AllowlistSpanProcessor(
            PostHogSpanProcessor(
                api_key=config.posthog_project_token(),
                host=config.posthog_host(),
            ),
        )
        install_agent_run_boundary()
        _processor = processor
        return [processor]
    except Exception:
        logger.warning("PostHog AI tracing init failed; AI spans not exported", exc_info=True)
        return []
