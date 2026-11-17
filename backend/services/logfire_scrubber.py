"""Keep student content out of Logfire: agent spans, tool calls and URLs.

Sapling's users are students, some of them minors, and the text that flows
through the agents is theirs: uploaded documents, notes, chat turns, quiz
answers. None of it may reach logfire.pydantic.dev. What Logfire keeps is
metadata: span names, models, token counts, latency, status, route templates,
and for content only a LENGTH and a short SHA-256 FINGERPRINT (enough to tell
two runs saw the same body, never what it said). There is no preview: an
80-character prefix of a short answer IS the answer.

Three layers, because Logfire's own scrubber cannot see everything:

1. **At the source** (``PYDANTIC_AI_INSTRUMENTATION``): pydantic-ai is
   instrumented with ``include_content=False``. In pydantic-ai 1.107 that
   removes the text of ``gen_ai.input.messages`` / ``gen_ai.output.messages``
   (model request spans), ``pydantic_ai.all_messages`` and
   ``gen_ai.system_instructions`` (agent run spans), ``final_result``, the
   tool-call arguments and results (``tool_arguments`` / ``tool_response`` on
   instrumentation versions 1-2, ``gen_ai.tool.call.arguments`` /
   ``gen_ai.tool.call.result`` on 3+), and exception messages (only the type
   is recorded). This layer matters most: Logfire 4.37's scrubber treats
   ``gen_ai.input.messages``, ``gen_ai.output.messages``,
   ``gen_ai.system_instructions``, ``pydantic_ai.all_messages`` and
   ``model_request_parameters`` as SAFE keys and never routes them to a
   callback.
2. **At span start** (``QueryStringStripProcessor``): the ASGI
   instrumentation writes the full URL, query string included, to
   ``http.url`` / ``http.target`` (old semconv) or ``url.full`` /
   ``url.query`` (new), and Logfire builds the span message from them —
   ``GET /path ? q='…'``, query parameters spelled out. Those are SAFE keys
   too. Worse, Logfire exports a *pending span* copied from the attributes
   at span START (``RemovePendingSpansExporter`` drops it only when the final
   span lands in the same batch), so a hook that runs after the start is too
   late. This processor, passed to ``logfire.configure`` as an additional
   span processor, runs its ``on_start`` before Logfire's pending-span
   processor and rewrites those attributes to the path only, for every
   span. ``strip_query_request_hook`` repeats it on the FastAPI request
   span as a second line.
3. **The scrubbing callback** (``scrub_value`` + ``EXTRA_PATTERNS``), for
   every attribute Logfire DOES route: any content-bearing attribute is
   replaced whole by ``[redacted, type:…, length:…, sha256:…]``, and a URL
   attribute loses its query string. Defence in depth for content a future
   pydantic-ai/logfire version or another integration writes under a
   non-SAFE key.

Wiring lives in main.py: ``logfire.configure(scrubbing=ScrubbingOptions(
callback=scrub_value, extra_patterns=ALL_PATTERNS),
additional_span_processors=[QueryStringStripProcessor()])``,
``logfire.instrument_pydantic_ai(**PYDANTIC_AI_INSTRUMENTATION)`` and
``logfire.instrument_fastapi(..., server_request_hook=strip_query_request_hook)``.
tests/test_logfire_scrubber.py runs real spans through that wiring.
"""

from __future__ import annotations

import json
import re
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from logfire import ScrubMatch
from opentelemetry.sdk.trace import SpanProcessor

from services.fingerprint import fingerprint_text


# Layer 1: pydantic-ai instrumentation settings (see module docstring).
PYDANTIC_AI_INSTRUMENTATION: dict[str, Any] = {
    "include_content": False,
    "include_binary_content": False,
}


# Attribute names (any JsonPath segment) whose value is prompt text, model
# output, tool arguments or tool results. The exact names pydantic-ai 1.107 /
# logfire 4.37 write are listed first; the rest are other GenAI conventions
# (OpenInference, Vercel AI, legacy gen_ai.*) kept for defence in depth.
# Conservative: over-redacting a debug attribute costs little; a leak cannot
# be taken back.
EXTRA_PATTERNS: tuple[str, ...] = (
    # pydantic-ai, model request / agent run spans
    r"gen_ai\.input\.messages",
    r"gen_ai\.output\.messages",
    r"gen_ai\.system_instructions",
    r"all_messages",  # pydantic_ai.all_messages, all_messages_events (v1)
    r"final_result",
    # pydantic-ai tool spans: v1-2 names, then v3+ (OTel GenAI) names
    r"tool_arguments",
    r"tool_response",
    r"gen_ai\.tool\.call\.arguments",
    r"gen_ai\.tool\.call\.result",
    # other GenAI conventions
    r"gen_ai\.prompt",
    r"gen_ai\.completion",
    r"input\.value",
    r"output\.value",
    r"ai\.input\.messages",
    r"ai\.output\.value",
    r"user_prompt",
    r"prompt",
    r"completion",
    r"messages",
    r"\bcontent\b",
    # v1 event mode puts the message events under a bare `events` key
    r"^events$",
)

# URL attributes: kept, minus the query string and fragment. Anchored so a
# VALUE that merely mentions "url" never matches (Logfire tests keys AND
# string values against the patterns; a whole-string match is left alone).
URL_PATTERNS: tuple[str, ...] = (
    r"^(?:http\.url|http\.target|url\.full|url\.query|http\.request\.url)$",
)

_CONTENT_RE = re.compile("|".join(EXTRA_PATTERNS), re.IGNORECASE)
_URL_KEY_RE = re.compile("|".join(URL_PATTERNS), re.IGNORECASE)

# Everything main.py hands Logfire as extra_patterns.
ALL_PATTERNS: tuple[str, ...] = EXTRA_PATTERNS + URL_PATTERNS


def _fingerprint(value: str) -> str:
    """16 hex chars of SHA-256 (services.fingerprint, shared with the quiz
    drift warnings), so a redacted body can be matched to a known copy."""
    return fingerprint_text(value, length=16)


def redact(value: Any) -> str:
    """The whole value as ``[redacted, type:…, length:…, sha256:…]``.

    Strings are measured and hashed as they are. Anything else is measured
    and hashed as canonical JSON, so nested keys (a dict of answers keyed by
    the student's own text) are hidden along with the values. A value that
    is not plain JSON (an unknown object, a cycle, NaN) is never stringified
    — ``repr`` could be the content — and becomes a bare ``[redacted]``.
    """
    if isinstance(value, str):
        kind, text = "string", value
    else:
        try:
            text = json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False)
        except (TypeError, ValueError):
            return "[redacted]"
        kind = type(value).__name__
    return f"[redacted, type:{kind}, length:{len(text)}, sha256:{_fingerprint(text)}]"


def strip_query(url: Any) -> Any:
    """``url`` without its query string and fragment. Non-strings pass through
    untouched; an unparsable string is redacted rather than guessed at."""
    if not isinstance(url, str):
        return url
    try:
        parts = urlsplit(url)
    except ValueError:
        return redact(url)
    if not parts.query and not parts.fragment:
        return url
    return urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))


def _is_content_key(seg: Any) -> bool:
    return isinstance(seg, str) and bool(_CONTENT_RE.search(seg))


def _is_url_key(seg: Any) -> bool:
    return isinstance(seg, str) and bool(_URL_KEY_RE.search(seg))


def _classify(path: tuple[Any, ...] | str) -> str | None:
    """'content', 'query', 'url' or None for a JsonPath (or a bare attribute name)."""
    segs = (path,) if isinstance(path, str) else tuple(path)
    if any(_is_content_key(s) for s in segs):
        return "content"
    if any(isinstance(s, str) and s.lower() == "url.query" for s in segs):
        return "query"  # a bare query string has no path worth keeping
    if any(_is_url_key(s) for s in segs):
        return "url"
    return None


def _sanitize(kind: str, value: Any) -> Any:
    if kind == "url":
        return strip_query(value)
    return redact(value)


def scrub_value(match: ScrubMatch) -> Any:
    """Logfire scrubbing callback.

    Content-bearing paths → ``redact`` (length + hash, no preview). URL paths →
    the URL without its query string. Anything else (Logfire's own default
    patterns: password, secret, api key, session, cookie, …) → ``None``, which
    tells Logfire to apply its full ``[Scrubbed due to …]`` redaction.
    """
    kind = _classify(match.path)
    if kind is None:
        return None
    return _sanitize(kind, match.value)


def scrub_attribute(name: str, value: Any) -> Any:
    """Pure entry point (tests, ad-hoc callers): the value Logfire would keep
    for attribute ``name``."""
    kind = _classify(name)
    if kind is None:
        return value
    return _sanitize(kind, value)


_URL_ATTRIBUTES = ("http.url", "http.target", "url.full", "http.request.url")


def _strip_span_urls(span: Any) -> None:
    attrs = getattr(span, "attributes", None) or {}
    for key in _URL_ATTRIBUTES:
        value = attrs.get(key)
        if isinstance(value, str) and ("?" in value or "#" in value):
            span.set_attribute(key, strip_query(value))
    query = attrs.get("url.query")
    if isinstance(query, str) and not query.startswith("[redacted"):
        span.set_attribute("url.query", redact(query))


class QueryStringStripProcessor(SpanProcessor):
    """Layer 2: strip query strings from URL attributes when a span STARTS.

    Must be registered through ``logfire.configure(additional_span_processors=
    [...])``: Logfire adds those to its processor chain before its own
    pending-span processor, so the pending span it exports is built from the
    already-stripped attributes. The final span is the same object, so it is
    covered too (an attribute set after start is caught by the request hook
    and, for non-SAFE keys, by ``scrub_value``).
    """

    def on_start(self, span: Any, parent_context: Any = None) -> None:
        try:
            _strip_span_urls(span)
        except Exception:  # pragma: no cover  # noqa: BLE001 — never break tracing
            return


def strip_query_request_hook(span: Any, scope: dict | None = None) -> None:
    """ASGI ``server_request_hook``: drop the query string from the request
    span's URL attributes before the span ends (layer 2).

    Runs after the instrumentation set its attributes; ``set_attribute``
    overwrites them. Logfire derives the span message from ``http.target``
    at export, so the message loses the query too. Never raises (the
    instrumentation wraps hooks in ``failsafe``, but a hook that throws
    would still lose the request's other attributes).
    """
    try:
        if span is None or not span.is_recording():
            return
        _strip_span_urls(span)
    except Exception:  # pragma: no cover  # noqa: BLE001 — defensive; never fail a request
        return
