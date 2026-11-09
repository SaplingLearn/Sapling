"""Content-free OpenTelemetry boundary for Pydantic AI instrumentation.

Pinned Pydantic AI also exports raw model_request_parameters despite
include_content=False. Logfire exempts that field from its scrubber. This
public-OTel adapter keeps only bounded operational metadata at every write;
it never modifies model requests, results, usage or exception propagation.
"""

from __future__ import annotations

from contextlib import ContextDecorator, contextmanager
from functools import wraps
from inspect import iscoroutinefunction
import math
import re

from opentelemetry import trace
from opentelemetry.trace import Link, Span, Status, StatusCode, Tracer, TracerProvider


_IDENTIFIERS = frozenset(
    {
        "gen_ai.system",
        "gen_ai.provider.name",
        "gen_ai.request.model",
        "gen_ai.response.model",
        "gen_ai.operation.name",
        "gen_ai.agent.call.id",
        "gen_ai.conversation.id",
        "gen_ai.tool.name",
        "gen_ai.tool.call.id",
        "gen_ai.response.id",
        "server.address",
        "error.type",
    }
)
_NUMBERS = frozenset(
    {
        "server.port",
        "operation.cost",
        "gen_ai.request.max_tokens",
        "gen_ai.request.temperature",
        "gen_ai.request.top_p",
        "gen_ai.request.seed",
        "gen_ai.request.presence_penalty",
        "gen_ai.request.frequency_penalty",
        "pydantic_ai.new_message_index",
    }
)
_TOKEN_SUFFIXES = (
    "input_tokens",
    "output_tokens",
    "cache_creation.input_tokens",
    "cache_read.input_tokens",
    "details.cache_write_tokens",
    "details.cache_read_tokens",
    "details.input_audio_tokens",
    "details.cache_audio_read_tokens",
    "details.output_audio_tokens",
    "details.thoughts_tokens",
    "details.thinking_tokens",
    "details.cached_content_tokens",
    "details.tool_use_prompt_tokens",
)
_TOKEN_KEYS = frozenset(
    prefix + suffix
    for prefix in ("gen_ai.usage.", "gen_ai.aggregated_usage.")
    for suffix in _TOKEN_SUFFIXES
)
_IDENTIFIER = re.compile(r"[A-Za-z0-9_.:/-]{1,256}\Z")


def _metadata(attributes):
    result = {}
    for key, value in (attributes or {}).items():
        if key in _IDENTIFIERS and type(value) is str and _IDENTIFIER.fullmatch(value):
            result[key] = value
        elif (
            key in _NUMBERS | _TOKEN_KEYS
            and type(value) in (int, float)
            and -1e15 <= value <= 1e15
            and math.isfinite(value)
        ):
            result[key] = value
        elif key == "pydantic_ai.variable_instructions" and type(value) is bool:
            result[key] = value
        elif (
            key == "gen_ai.response.finish_reasons"
            and isinstance(value, (list, tuple))
            and len(value) <= 8
            and all(type(v) is str and _IDENTIFIER.fullmatch(v) for v in value)
        ):
            result[key] = value
    return result


class _MetadataSpan(Span):
    def __init__(self, span):
        self._span = span

    @property
    def attributes(self):
        return _metadata(getattr(self._span, "attributes", {}))

    def get_span_context(self):
        return self._span.get_span_context()

    def is_recording(self):
        return self._span.is_recording()

    def end(self, end_time=None):
        self._span.end(end_time)

    def set_attribute(self, key, value):
        self.set_attributes({key: value})

    def set_attributes(self, attributes):
        self._span.set_attributes(_metadata(attributes))

    def add_event(self, name, attributes=None, timestamp=None):
        # Free-form event names/bodies and exception stacks can contain output.
        # Operational outcome remains available as status/type/token metadata.
        return None

    def add_link(self, context, attributes=None):
        if self.is_recording():
            self._span.add_link(context, attributes=_metadata(attributes))

    def update_name(self, name):
        self._span.update_name("AI operation")

    def set_status(self, status, description=None):
        code = status.status_code if isinstance(status, Status) else status
        self._span.set_status(Status(code))

    def record_exception(self, exception, attributes=None, timestamp=None, escaped=False):
        self.set_attribute("error.type", type(exception).__name__)


class _MetadataTracer(Tracer):
    def __init__(self, tracer):
        self._tracer = tracer

    def start_span(
        self,
        name,
        context=None,
        kind=trace.SpanKind.INTERNAL,
        attributes=None,
        links=None,
        start_time=None,
        record_exception=True,
        set_status_on_exception=True,
    ):
        safe_links = [
            Link(link.context, attributes=_metadata(link.attributes)) for link in links or ()
        ]
        return _MetadataSpan(
            self._tracer.start_span(
                "AI operation",
                context=context,
                kind=kind,
                attributes=_metadata(attributes),
                links=safe_links,
                start_time=start_time,
                record_exception=False,
                set_status_on_exception=False,
            )
        )

    def start_as_current_span(self, name, *args, **kwargs):
        return _SpanContext(lambda: self._span_scope(name, *args, **kwargs))

    @contextmanager
    def _span_scope(
        self,
        name,
        context=None,
        kind=trace.SpanKind.INTERNAL,
        attributes=None,
        links=None,
        start_time=None,
        record_exception=True,
        set_status_on_exception=True,
        end_on_exit=True,
    ):
        span = self.start_span(name, context, kind, attributes, links, start_time)
        with trace.use_span(
            span, end_on_exit=end_on_exit, record_exception=False, set_status_on_exception=False
        ):
            try:
                yield span
            except BaseException as exc:
                if record_exception:
                    span.record_exception(exc)
                if set_status_on_exception:
                    span.set_status(StatusCode.ERROR)
                raise


class _SpanContext(ContextDecorator):
    """Public Python context/decorator APIs, including awaited function bodies."""

    def __init__(self, factory):
        self._factory = factory

    def _recreate_cm(self):
        return type(self)(self._factory)

    def __enter__(self):
        self._active = self._factory()
        return self._active.__enter__()

    def __exit__(self, *error):
        return self._active.__exit__(*error)

    def __call__(self, function):
        if not iscoroutinefunction(function):
            return super().__call__(function)

        @wraps(function)
        async def wrapped(*args, **kwargs):
            with self._recreate_cm():
                return await function(*args, **kwargs)

        return wrapped


class ContentFreeTracerProvider(TracerProvider):
    def __init__(self, provider):
        self._provider = provider

    def get_tracer(
        self,
        instrumenting_module_name,
        instrumenting_library_version=None,
        schema_url=None,
        attributes=None,
    ):
        tracer = self._provider.get_tracer(
            instrumenting_module_name,
            instrumenting_library_version,
            schema_url,
            _metadata(attributes),
        )
        return _MetadataTracer(tracer)


def content_free_tracer_provider():
    """Resolve the public OTel provider; its normal deferred configuration stays intact."""
    return ContentFreeTracerProvider(trace.get_tracer_provider())
