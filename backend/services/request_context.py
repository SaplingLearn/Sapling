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


#: ADR 0028: the request carried a browser privacy signal — Global Privacy
#: Control (`Sec-GPC: 1`) or Do Not Track (`DNT: 1`). Third-party analytics
#: (the PostHog queue) sends nothing captured during such a request.
#: Our own `events` table is first-party observability and is unaffected.
#: False outside a request (the sweeper, scripts).
_PRIVACY_SIGNAL_CTX: contextvars.ContextVar[bool] = contextvars.ContextVar(
    "sapling_privacy_signal", default=False,
)


def current_request_id() -> str | None:
    """Return the current request's ID, or None if outside a request scope."""
    return _REQUEST_ID_CTX.get()


def privacy_signal_in(headers) -> bool:
    """Whether a header mapping carries `Sec-GPC: 1` or `DNT: 1`."""
    return (
        (headers.get("sec-gpc") or "").strip() == "1"
        or (headers.get("dnt") or "").strip() == "1"
    )


def request_has_privacy_signal() -> bool:
    """True when the current request sent `Sec-GPC: 1` or `DNT: 1`."""
    return _PRIVACY_SIGNAL_CTX.get()


class RequestView:
    """The two things the PostHog seam needs from the current request, and
    nothing else — NOT the ASGI scope (headers, cookies, query string) for
    any longer than the request itself.

    * ``state`` — the request's ``scope["state"]`` dict. Starlette's
      ``request.state`` is a view over it, so ``auth_guard``'s
      ``request.state.user_id`` lands here, and the handler, a threadpool
      ``Depends`` and the request's BackgroundTasks all share it.
    * ``route_template()`` — the matched route template. Routing stamps
      ``scope["route"]`` after this view is made, so while the request is
      in flight the view reads it from the scope; :meth:`detach` (called by
      the middleware when the request ends) resolves the template once and
      drops the scope. A context copied into a task or thread during the
      request therefore never keeps the scope — its headers and session
      cookie — alive after the response.
    """

    __slots__ = ("state", "_scope", "_template")

    def __init__(self, scope: dict) -> None:
        self.state: dict = scope.setdefault("state", {})
        self._scope: dict | None = scope
        self._template: str | None = None

    def route_template(self) -> str | None:
        scope = self._scope
        return self._template if scope is None else route_template_of(scope)

    def detach(self) -> None:
        """Resolve the template one last time and let go of the scope."""
        if self._scope is not None:
            self._template = route_template_of(self._scope)
            self._scope = None


#: The current request's RequestView (ADR 0028). None outside a request.
_REQUEST_CTX: contextvars.ContextVar[RequestView | None] = contextvars.ContextVar(
    "sapling_request_view", default=None,
)


def route_template_of(scope: dict | None) -> str | None:
    """The matched route's FULL mounted template (`/api/profile/{user_id}`)
    for a scope.

    ``scope["route"]`` is not enough on its own across FastAPI versions.
    Before 0.138, ``include_router(prefix=...)`` copied every route with the
    prefix baked in, so its ``path_format`` was the full template. From 0.138
    (``_IncludedRouter``) the scope carries the ORIGINAL route, whose
    ``path_format`` is relative to its router (`/{user_id}/settings`), and the
    prefix lives only in FastAPI's private scope state.

    So the prefix is recovered from the request path instead, using only the
    route's public pattern: the split of the path whose remainder the route
    fully matches WITH the parameter values routing bound
    (``scope["path_params"]``). That is exactly the router's (literal) mount
    prefix on 0.138, and the empty string before it, where the pattern
    already covers the whole path. Everything the route templates stays
    templated, so no path parameter value — e.g. another user's id — lands
    in the result. Without an agreeing split, the shortest matching prefix
    is used (it only ever shortens the literal part); with no match at all,
    the route's own template is returned unchanged.
    """
    route = (scope or {}).get("route")
    template = getattr(route, "path_format", None)
    if not isinstance(template, str):
        template = getattr(route, "path", None)
    if not isinstance(template, str):
        return None
    pattern = getattr(route, "path_regex", None)
    path = (scope or {}).get("path")
    if pattern is not None and isinstance(path, str):
        root = (scope or {}).get("root_path") or ""
        if root and path.startswith(root):
            path = path[len(root):]
        # Every "/" boundary, plus the end (a route declared as "" under its
        # router's prefix matches an empty remainder).
        splits = [*(j for j, ch in enumerate(path) if ch == "/"), len(path)]
        matches = [(i, m) for i in splits if (m := pattern.fullmatch(path[i:]))]
        # Prefer the split whose captured parameters are the ones routing
        # actually bound (a `{rest:path}` parameter matches at several
        # splits; only the real one agrees with scope["path_params"]).
        bound = (scope or {}).get("path_params") or {}
        convertors = getattr(route, "param_convertors", None) or {}
        for i, m in matches:
            if _agrees(m.groupdict(), bound, convertors):
                return (path[:i] + template) or None
        if matches:
            return (path[:matches[0][0]] + template) or None
    return template or None


def _agrees(captured: dict, bound: dict, convertors: dict) -> bool:
    for key, raw in captured.items():
        if key not in bound:
            continue
        try:
            value = convertors[key].convert(raw) if key in convertors else raw
        except Exception:
            return False
        if value != bound[key]:
            return False
    return True


def current_route_template() -> str | None:
    """The current request's matched route template, or None (no request, or
    nothing matched yet)."""
    view = _REQUEST_CTX.get()
    return view.route_template() if view is not None else None


def current_session_user() -> str | None:
    """The current request's authenticated user, as auth_guard stamped it on
    ``request.state.user_id``.

    Read from the request's ``scope["state"]`` dict (Starlette's
    ``request.state`` is a view over it), not from a contextvar a handler
    sets: that dict is the one object every part of the request shares — the
    handler, a threadpool ``Depends``, and the request's BackgroundTasks —
    so a stamp made anywhere is visible everywhere. None outside a request.
    """
    view = _REQUEST_CTX.get()
    state = view.state if view is not None else None
    user = state.get("user_id") if isinstance(state, dict) else None
    return user if isinstance(user, str) and user else None


def new_request_id() -> str:
    """Mint a fresh request ID. Module-level so tests can monkeypatch."""
    return str(uuid.uuid4())


class RequestIDMiddleware(BaseHTTPMiddleware):
    """Stamp every request with an ID; surface it as `X-Request-ID` on the
    response; emit one structured log line per request with duration."""

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        # ADR 0028: held for the WHOLE dispatch — including the error-event
        # emission below, which runs after the request-id var is reset — so
        # the error.5xx mirror honours the same DNT/GPC signal as everything
        # the handler emitted. The downstream task copies both at call_next,
        # so the handler, threadpool Depends and BackgroundTasks see them.
        privacy_token = _PRIVACY_SIGNAL_CTX.set(privacy_signal_in(request.headers))
        view = RequestView(request.scope)
        view_token = _REQUEST_CTX.set(view)
        try:
            return await self._dispatch(request, call_next)
        finally:
            # Copies of this context (tasks, threads, BackgroundTasks) keep
            # the view: from here on it holds the template, not the scope.
            view.detach()
            _REQUEST_CTX.reset(view_token)
            _PRIVACY_SIGNAL_CTX.reset(privacy_token)

    async def _dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        incoming = request.headers.get("x-request-id", "").strip()
        rid = incoming if _SAFE_ID.match(incoming) else new_request_id()
        request.state.request_id = rid
        token = _REQUEST_ID_CTX.set(rid)
        start = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception:
            # A truly UNHANDLED exception (not a raised HTTPException — those
            # are converted to responses by handlers running INSIDE the app)
            # propagates through this dispatch on its way to Starlette's
            # outermost ServerErrorMiddleware, so no response object ever
            # reaches the >=400 seam below. Emit the error.5xx HERE — with the
            # real duration and request id — then re-raise so the 500 response
            # is still produced normally. Exactly-once: this request never
            # reaches the response-path emission.
            _REQUEST_ID_CTX.reset(token)
            from services import events_service

            crash_payload = {
                "path": request.url.path,
                "method": request.method,
                "status_code": 500,
                "duration_ms": round((time.perf_counter() - start) * 1000, 1),
            }
            crash_template = route_template_of(request.scope)
            if crash_template:
                crash_payload["route"] = crash_template
            events_service.log_event(
                "error.5xx",
                category="error",
                user_id=getattr(request.state, "user_id", None),
                request_id=rid,
                payload=crash_payload,
            )
            raise
        finally:
            # Idempotent under the except-path's early reset (reset of an
            # already-reset token would raise; guard by only resetting when
            # the var still holds this request's id).
            if _REQUEST_ID_CTX.get() == rid:
                _REQUEST_ID_CTX.reset(token)

        # One log line per request, severity tracking the response code.
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

        # #117: persist 4xx/5xx as observability events (the error rollups in
        # /api/admin/analytics). Errors ONLY — 2xx/3xx traffic would swamp the
        # events table for zero analytical value. Notes:
        # - the request-id contextvar was already reset in the `finally`
        #   above, so `rid` is passed explicitly;
        # - only the PATH is recorded, never the full URL — query strings
        #   carry search terms and other user input;
        # - `route` is the matched FastAPI template (bounded cardinality);
        #   unmatched requests (e.g. a bare 404) simply omit it;
        # - user_id comes off request.state, stamped by
        #   auth_guard.get_session_user_id on a successful decode (the shared
        #   ASGI scope is the only channel that propagates back out of
        #   BaseHTTPMiddleware's downstream task).
        if response.status_code >= 400:
            # Local import: events_service imports current_request_id from
            # this module at import time, so a top-level import here would be
            # circular.
            from services import events_service

            payload = {
                "path": request.url.path,
                "method": request.method,
                "status_code": response.status_code,
                "duration_ms": round(dur_ms, 1),
            }
            template = route_template_of(request.scope)
            if template:
                payload["route"] = template
            events_service.log_event(
                "error.5xx" if response.status_code >= 500 else "error.4xx",
                category="error",
                user_id=getattr(request.state, "user_id", None),
                request_id=rid,
                payload=payload,
            )

        # Always echo back so clients can capture it from successful responses too.
        response.headers["X-Request-ID"] = rid
        return response
