"""Request correlation IDs + structured duration logging.

Pattern: a starlette middleware reads/generates `X-Request-ID` on every
request, stashes it on `request.state.request_id`, and attaches it to a
contextvar so downstream code (loggers, agents, error handlers) can read
it without threading it through every signature.

Clients may set the header themselves to correlate retries; we trust
caller-supplied IDs but cap their length and character set. Otherwise
we generate a fresh uuid4.

Each request also gets a single structured log line at completion with
the request_id, method, path, status code, and duration. (This absorbs
the old RequestLogMiddleware so we don't run two middlewares writing to
the same `request.state.request_id`.)
"""

from __future__ import annotations

import contextvars
import logging
import re
import time
import uuid
from typing import Awaitable, Callable

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware


_REQUEST_ID_CTX: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "sapling_request_id", default=None,
)

# Defensive: only accept caller-supplied IDs that are 8–128 chars of
# hex/uuid-ish characters. Anything else, ignore and generate fresh.
_SAFE_ID = re.compile(r"^[A-Za-z0-9_\-]{8,128}$")

_log = logging.getLogger("sapling.request")


def current_request_id() -> str | None:
    """Return the current request's ID, or None if outside a request scope."""
    return _REQUEST_ID_CTX.get()


def new_request_id() -> str:
    """Mint a fresh request ID. Module-level so tests can monkeypatch."""
    return str(uuid.uuid4())


class RequestIDMiddleware(BaseHTTPMiddleware):
    """Stamp every request with an ID; surface it as `X-Request-ID` on the
    response; emit one structured log line per request with duration."""

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        incoming = request.headers.get("x-request-id", "").strip()
        rid = incoming if _SAFE_ID.match(incoming) else new_request_id()
        request.state.request_id = rid
        token = _REQUEST_ID_CTX.set(rid)
        start = time.perf_counter()
        try:
            response = await call_next(request)
        finally:
            _REQUEST_ID_CTX.reset(token)

        # One log line per request, severity tracking the response code.
        # Unhandled exceptions are converted to 500 by the @app.exception_handler
        # in main.py, so they show up here as 5xx with no special-casing.
        dur_ms = (time.perf_counter() - start) * 1000
        level = (
            logging.ERROR if response.status_code >= 500
            else logging.WARNING if response.status_code >= 400
            else logging.INFO
        )
        _log.log(
            level,
            "[%s] %s %s -> %d (%.1fms)",
            rid, request.method, request.url.path, response.status_code, dur_ms,
        )

        # Always echo back so clients can capture it from successful responses too.
        response.headers["X-Request-ID"] = rid
        return response
