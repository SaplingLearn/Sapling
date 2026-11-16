"""Process-wide log privacy: what stdout (Railway's log store) never gets.

Both process entry points (``main.py``, ``worker/__main__.py``) run the root
logger at INFO and call ``install()`` right after configuring logging. It
does two things:

1. **Outbound URLs.** httpx logs every request it sends at INFO as
   ``HTTP Request: GET <full URL> "200 OK"``, query string included, and the
   PostgREST filters this backend builds put student data in that query
   string (``email=in.(...)`` in the admin allowlist, ``or=(email.ilike.<addr>)``
   in the waitlist check). ``quiet_http_clients()`` raises httpx/httpcore to
   WARNING: transport failures stay visible, the per-request line does not.

2. **Model output in tracebacks.** A pydantic-ai output-validation failure
   carries what the model wrote: ``ToolRetryError``'s message lists every
   error with ``input_value=<the model's text>``, ``UnexpectedModelBehavior``
   appends the response ``body``, and a pydantic ``ValidationError`` prints
   ``input_value`` too. The model's text is derived from the student's
   documents, notes and answers, so a ``logger.exception(...)`` or
   ``exc_info=e`` on one of those writes student content to the log. The
   record factory installed here pre-renders such a record's traceback with
   those messages reduced to their shape (type, error count, locations,
   error types; never an input), so every formatter, uvicorn's included,
   prints the redacted text. Records whose exception chain holds none of
   those types are left exactly as they were.

``safe_exception_text`` is the same reduction for a message argument
(``logger.warning("... %s", safe_exception_text(e))``), for a site that logs
the exception's text without a traceback.
"""

from __future__ import annotations

import logging
import traceback

# Third-party HTTP clients whose INFO/DEBUG lines carry full request URLs.
HTTP_CLIENT_LOGGERS = ("httpx", "httpcore")


def quiet_http_clients() -> None:
    """Raise httpx/httpcore to WARNING so no outbound request URL is logged.

    Idempotent. Nothing else in the app sets these loggers' levels, which is
    what keeps this effective.
    """
    for name in HTTP_CLIENT_LOGGERS:
        logging.getLogger(name).setLevel(logging.WARNING)


# ---------------------------------------------------------------------------
# Exception redaction
# ---------------------------------------------------------------------------


def _content_bearing_types() -> tuple[type[BaseException], ...]:
    types: list[type[BaseException]] = []
    try:
        from pydantic_core import ValidationError

        types.append(ValidationError)
    except ImportError:  # pragma: no cover - pydantic is a hard dependency
        pass
    try:
        from pydantic_ai.exceptions import ModelRetry, ToolRetryError, UnexpectedModelBehavior

        types.extend((ToolRetryError, UnexpectedModelBehavior, ModelRetry))
    except ImportError:  # pragma: no cover - pydantic-ai is a hard dependency
        pass
    return tuple(types)


_CONTENT_TYPES: tuple[type[BaseException], ...] | None = None


def _content_types() -> tuple[type[BaseException], ...]:
    global _CONTENT_TYPES
    if _CONTENT_TYPES is None:
        _CONTENT_TYPES = _content_bearing_types()
    return _CONTENT_TYPES


def _error_shape(errors: list, header: str) -> str:
    parts = []
    for err in errors:
        loc = ".".join(str(x) for x in (err.get("loc") or ())) or "__root__"
        parts.append(f"{loc} [type={err.get('type')}]")
    return f"{header}: " + "; ".join(parts) if parts else header


def safe_exception_text(exc: BaseException) -> str:
    """``exc``'s message without any model output or validated input.

    Exceptions that cannot carry model output keep their own text.
    """
    try:
        from pydantic_core import ValidationError

        if isinstance(exc, ValidationError):
            n = exc.error_count()
            errors = exc.errors(include_url=False, include_input=False, include_context=False)
            return _error_shape(errors, f"{n} validation error{'s' if n != 1 else ''} for {exc.title}")
    except ImportError:  # pragma: no cover
        pass
    try:
        from pydantic_ai.exceptions import ModelRetry, ToolRetryError, UnexpectedModelBehavior

        if isinstance(exc, ToolRetryError):
            content = exc.tool_retry.content
            if isinstance(content, list):
                return _error_shape(content, f"{len(content)} validation error(s) in model output")
            return f"retry prompt withheld ({len(str(content))} chars)"
        if isinstance(exc, UnexpectedModelBehavior):
            # `message` is pydantic-ai's own description; `body` is the
            # model response, which is dropped.
            withheld = f" (response body withheld, {len(exc.body)} chars)" if exc.body else ""
            return f"{exc.message}{withheld}"
        if isinstance(exc, ModelRetry):
            # Our own output validators write these and may quote the output.
            return f"model retry withheld ({len(str(exc))} chars)"
    except ImportError:  # pragma: no cover
        pass
    return str(exc)


def _chain(exc: BaseException) -> list[BaseException]:
    """The exception chain oldest-first, as ``traceback`` prints it."""
    out: list[BaseException] = []
    seen: set[int] = set()
    cur: BaseException | None = exc
    while cur is not None and id(cur) not in seen:
        seen.add(id(cur))
        out.append(cur)
        if cur.__cause__ is not None:
            cur = cur.__cause__
        elif cur.__context__ is not None and not cur.__suppress_context__:
            cur = cur.__context__
        else:
            cur = None
    out.reverse()
    return out


def chain_has_content(exc: BaseException | None) -> bool:
    types = _content_types()
    return bool(types) and exc is not None and any(isinstance(e, types) for e in _chain(exc))


def format_exception_redacted(exc: BaseException) -> str:
    """A traceback for ``exc`` (chain included) with every message passed
    through ``safe_exception_text``. Frames are kept; source lines are
    file lines, never runtime values."""
    lines: list[str] = []
    chain = _chain(exc)
    for i, e in enumerate(chain):
        if e.__traceback__ is not None:
            lines.append("Traceback (most recent call last):\n")
            lines.extend(traceback.format_tb(e.__traceback__))
        name = type(e).__qualname__
        mod = type(e).__module__
        if mod not in ("builtins", "__main__"):
            name = f"{mod}.{name}"
        lines.append(f"{name}: {safe_exception_text(e)}\n")
        if i + 1 < len(chain):
            nxt_note = _chain_note(chain[i + 1], e)
            if nxt_note:
                lines.append(nxt_note)
    return "".join(lines).rstrip("\n")


def _chain_note(newer: BaseException, older: BaseException) -> str | None:
    if newer.__cause__ is older:
        return "\nThe above exception was the direct cause of the following exception:\n\n"
    if newer.__context__ is older:
        return "\nDuring handling of the above exception, another exception occurred:\n\n"
    return None


def _exc_from(exc_info) -> BaseException | None:
    if isinstance(exc_info, BaseException):
        return exc_info
    if isinstance(exc_info, tuple) and len(exc_info) == 3:
        return exc_info[1]
    return None


_ORIGINAL_FACTORY = None


def _redacting_factory(*args, **kwargs) -> logging.LogRecord:
    record = _ORIGINAL_FACTORY(*args, **kwargs)  # type: ignore[misc]
    exc = _exc_from(record.exc_info)
    if exc is not None and chain_has_content(exc):
        try:
            # Formatter.format uses a pre-set exc_text instead of rendering
            # exc_info itself, so every formatter prints this text.
            record.exc_text = format_exception_redacted(exc)
        except Exception:  # never let logging fail
            record.exc_text = f"{type(exc).__qualname__}: <traceback withheld>"
    return record


def install_exception_redaction() -> None:
    """Wrap the LogRecord factory once (idempotent)."""
    global _ORIGINAL_FACTORY
    current = logging.getLogRecordFactory()
    if current is _redacting_factory:
        return
    _ORIGINAL_FACTORY = current
    logging.setLogRecordFactory(_redacting_factory)


def install() -> None:
    """Everything above, for a process entry point (idempotent)."""
    quiet_http_clients()
    install_exception_redaction()


__all__ = [
    "HTTP_CLIENT_LOGGERS",
    "chain_has_content",
    "format_exception_redacted",
    "install",
    "install_exception_redaction",
    "quiet_http_clients",
    "safe_exception_text",
]

