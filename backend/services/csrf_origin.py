"""Origin check for cookie-authenticated unsafe requests (sec2 M1, CSRF).

`SameSite=Lax` stops a cross-SITE page from sending the session cookie on a
POST, but every `*.saplinglearn.com` host is the SAME site, so it did nothing
against a sibling subdomain (staging, a preview, anything taken over), and
the backend never looked at where a request came from. This middleware does.

The rule, for POST / PUT / PATCH / DELETE that carry a session cookie (either
name, any value — verifying it is the guard's job, not ours):

1. ``Origin`` present -> it must be one this deployment trusts: the CORS
   allowlist (``services/cors_origins.py``, the same list ``main.py`` hands
   CORSMiddleware); on the staging backend, a frontend-staging PR preview
   origin (``oauth_state._clean_return_to``); on a local/test backend, any
   http loopback origin (the E2E stack is opened as localhost OR 127.0.0.1,
   on per-slot ports). Else 403.
2. No ``Origin`` but a ``Referer`` -> the referer's origin must be trusted.
3. Neither, but a ``Sec-Fetch-Site`` header -> 403. That header is sent by
   every current browser and only by browsers, and a browser always sends
   ``Origin`` on an unsafe request, so this is a browser request stripped of
   both: refuse it.
4. Neither, and no ``Sec-Fetch-*`` -> a NON-BROWSER client, allowed: the
   frontend server's own calls (the session BFF's ``POST /api/auth/logout``
   revoke, the middleware), scripts, the test client. CSRF needs a victim's
   browser, and a browser never sends this shape.

Through the frontend's same-origin ``/api`` rewrite the browser's own
``Origin`` (the frontend's origin, which is FRONTEND_URL) and ``Sec-Fetch-*``
headers are forwarded unchanged, so a same-origin call passes rule 1 and a
sibling subdomain's call (``Origin: https://staging.saplinglearn.com`` at the
prod backend) fails it.

Requests WITHOUT a session cookie are not checked: there is no ambient
credential to ride. Exempt paths authenticate with something a cross-site
page cannot attach:

* ``/api/internal/`` — server-to-server bearer token (Canopy metrics, the
  cross-environment account copy).
* ``/api/email/unsubscribe`` — the signed ``?t=`` token is the credential; a
  mail provider's one-click POST and the backend-rendered confirm form (whose
  origin can be the API host) must work with or without a session cookie.

OAuth callbacks are GETs and never checked.
"""
from __future__ import annotations

import json
import logging
from collections.abc import Callable, Iterable
from urllib.parse import urlsplit

from services.session_tokens import SESSION_COOKIE_NAMES

logger = logging.getLogger("sapling.csrf_origin")

UNSAFE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})
EXEMPT_PREFIXES = ("/api/internal/", "/api/email/unsubscribe")

_FORBIDDEN_BODY = json.dumps({"detail": "Cross-origin request refused"}).encode()


def _origin_of(url: str) -> str | None:
    """`scheme://host[:port]` of a URL (lower-cased), or None."""
    try:
        parts = urlsplit(url.strip())
    except ValueError:
        return None
    if parts.scheme not in {"http", "https"} or not parts.netloc:
        return None
    return f"{parts.scheme}://{parts.netloc}".lower()


def _has_session_cookie(cookie_header: str) -> bool:
    for pair in cookie_header.split(";"):
        name, sep, _value = pair.strip().partition("=")
        if sep and name.strip() in SESSION_COOKIE_NAMES:
            return True
    return False


def _extra_origin_trusted(origin: str) -> bool:
    """Origins trusted beyond the static allowlist, decided per request off
    the live APP_ENV: the staging backend's PR previews, and any http
    loopback origin on a local/test backend (never on a deployed one)."""
    import config
    from services.auth.oauth_state import _clean_return_to
    from services.cors_origins import LOCAL_APP_ENVS

    if _clean_return_to(origin) is not None:
        return True
    if (getattr(config, "APP_ENV", "") or "").strip().lower() not in LOCAL_APP_ENVS:
        return False
    parts = urlsplit(origin)
    return parts.scheme == "http" and (parts.hostname or "") in {"localhost", "127.0.0.1", "::1"}


def decide(
    method: str,
    path: str,
    headers: dict[str, str],
    trusted: frozenset[str],
    extra_trusted: Callable[[str], bool] = _extra_origin_trusted,
) -> str | None:
    """None when the request may proceed, else the refusal reason. Pure:
    `headers` is lower-cased name -> value."""
    if method.upper() not in UNSAFE_METHODS:
        return None
    if any(path.startswith(prefix) for prefix in EXEMPT_PREFIXES):
        return None
    if not _has_session_cookie(headers.get("cookie", "")):
        return None

    def ok(origin: str | None) -> bool:
        return bool(origin) and (origin in trusted or extra_trusted(origin))

    raw_origin = headers.get("origin")
    if raw_origin is not None:
        return None if ok(_origin_of(raw_origin)) else "origin not allowed"
    referer = headers.get("referer")
    if referer:
        return None if ok(_origin_of(referer)) else "referer not allowed"
    if "sec-fetch-site" in headers:
        return "browser request without origin"
    return None  # a non-browser client (server-side call, script)


class CsrfOriginMiddleware:
    """Pure ASGI middleware applying `decide` (403 JSON on refusal)."""

    def __init__(self, app, allowed_origins: Iterable[str]):
        self.app = app
        self.trusted = frozenset(o.strip().rstrip("/").lower() for o in allowed_origins if o)

    async def __call__(self, scope, receive, send):
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return
        headers: dict[str, str] = {}
        for raw_name, raw_value in scope.get("headers") or ():
            name = raw_name.decode("latin-1").lower()
            value = raw_value.decode("latin-1")
            # Repeated Cookie headers are joined; any other repeat keeps the
            # first (a second Origin is not something a browser sends).
            if name == "cookie" and name in headers:
                headers[name] = f"{headers[name]}; {value}"
            else:
                headers.setdefault(name, value)
        reason = decide(scope.get("method", "GET"), scope.get("path", ""), headers, self.trusted)
        if reason is None:
            await self.app(scope, receive, send)
            return
        logger.warning("csrf: refused %s %s (%s)", scope.get("method"), scope.get("path"), reason)
        await send({
            "type": "http.response.start",
            "status": 403,
            "headers": [
                (b"content-type", b"application/json"),
                (b"content-length", str(len(_FORBIDDEN_BODY)).encode()),
                (b"cache-control", b"no-store"),
            ],
        })
        await send({"type": "http.response.body", "body": _FORBIDDEN_BODY})
