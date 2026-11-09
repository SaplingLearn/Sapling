"""Which identity a PostgREST call runs as: the service role or the student (#115).

docs/security/rls-step2-plan.md §4 and docs/design/async-db-client.md §2.4.
``db/connection.py::_scope_headers`` asks :func:`resolve_headers` before every
request; the answer is ``None`` (the client's own service-role headers, exactly
the bytes sent before this module existed) or a user-scoped
``{"apikey": <anon key>, "Authorization": "Bearer <minted JWT>"}``.

Resolution, first match wins (plan §4.2):

1. A :func:`service_scope` block or :func:`runs_as_service` function is
   active (a ContextVar) -> service.
2. The request was marked service at router/endpoint level
   (``scope["state"]["db_scope"] == "service"``, :func:`service_route` /
   :func:`admin_service_route`) -> service.
3. Inside a request, the ``db_user_scope`` flag's variant for the request's
   subject (resolved ONCE per request, as service, memoized on the state):
   ``off`` -> service; ``shadow`` -> service, plus a sampled user-scoped
   re-run of reads that is compared and logged (``db/connection.py``) and
   what can be known about writes without re-running them, all tallied for
   the rollout report (``db/scope_report.py``);
   ``enforce`` -> the minted user JWT.
4. ``shadow``/``enforce`` with no subject (no valid session) -> ``enforce``
   raises :class:`UnscopedQueryError` (500, fail closed); ``shadow`` logs
   ``db.unscoped_query`` and runs as service.
5. Outside any request (lifespan workers, the sweeper, scripts, seeds,
   threads that escaped the request context) -> service.

Per-request facts (the subject, the router mark, the memoized variant) live on
the request's ``scope["state"]`` dict, which ``services/request_context``'s
``RequestView`` shares with threadpool ``Depends``, ``asyncio.to_thread``,
BackgroundTasks and post-roll tasks. The subject is stamped by
``RequestIDMiddleware`` (it calls :func:`stamp_subject`) from the session
token's HMAC + expiry alone — ``auth_guard._decode_session``, no DB read — so
"load, then require_self" handlers are scoped before their first read.

Binding rules from docs/design/async-db-client.md §2.4:

* Never set an identity ContextVar from a SYNC dependency (the copy is
  one-way). The only ContextVar here is the service-scope flag, set and reset
  inside one ``with`` block or one wrapped call.
* ``@runs_as_service`` on an ``async def`` sets the var inside the coroutine.
* Never hold :func:`service_scope` across a ``yield``: the decorator refuses
  generator functions; wrap the inner DB call instead.
"""
from __future__ import annotations

import contextvars
import functools
import inspect
import logging
import math
import os
import random
import threading
from contextlib import contextmanager
from typing import Any, Callable, Iterator, Optional, TypeVar

import httpx
from starlette.requests import Request

from db import scope_report, user_jwt
from services import request_context

logger = logging.getLogger("sapling.db_scope")

FLAG_KEY = "db_user_scope"
OFF, SHADOW, ENFORCE = "off", "shadow", "enforce"

#: Keys on the request's ``scope["state"]`` dict.
SUBJECT_KEY = "db_subject"
SCOPE_KEY = "db_scope"
MODE_KEY = "db_user_scope_mode"
SERVICE = "service"

SHADOW_SAMPLE_RATE_ENV = "DB_USER_SCOPE_SHADOW_SAMPLE_RATE"


def _sample_rate_from_env(default: float = 0.1) -> float:
    raw = (os.getenv(SHADOW_SAMPLE_RATE_ENV) or "").strip()
    if not raw:
        return default
    try:
        rate = float(raw)
    except ValueError:
        rate = math.nan
    # float() accepts "nan"/"inf": NaN would make every `random() >= rate`
    # comparison False (shadow EVERY read), so anything non-finite is refused.
    if not math.isfinite(rate):
        logger.warning("%s=%r is not a finite number; using %s",
                       SHADOW_SAMPLE_RATE_ENV, raw, default)
        return default
    return min(max(rate, 0.0), 1.0)


#: Fraction of service-role reads that also run user-scoped under ``shadow``.
#: 0.1 by default; staging's traffic is small enough to compare every read
#: (``DB_USER_SCOPE_SHADOW_SAMPLE_RATE=1``; read at boot).
#:
#: A TUNING knob, not a feature gate (like ``JOBS_LEASE_SECONDS``): whether
#: shadow runs at all is the ``db_user_scope`` flag, per student; this only
#: sets how much of an already-on shadow is compared. It is an env var because
#: flag variants are strings, not numbers. Clamped to [0, 1]; non-finite or
#: unparseable values fall back to the default.
SHADOW_SAMPLE_RATE = _sample_rate_from_env()

F = TypeVar("F", bound=Callable[..., Any])

_SERVICE_SCOPE: contextvars.ContextVar[bool] = contextvars.ContextVar(
    "sapling_db_service_scope", default=False,
)


# ── Errors (mapped to responses in main.py) ─────────────────────────────────


class UnscopedQueryError(RuntimeError):
    """``enforce``: a request with no verified subject reached PostgREST from
    a path not marked service. 500 — fail closed, never service role."""


class ScopeUnavailable(RuntimeError):
    """``enforce``: the user-scoped credential could not be built (signing or
    anon key missing/bad) or PostgREST rejected it (401). 503 — never a
    fallback to the service role."""


class ScopedAccessDenied(httpx.HTTPStatusError):
    """``enforce``: PostgREST refused a user-scoped call (403 / 42501: an RLS
    ``WITH CHECK`` violation or a missing grant). Subclasses HTTPStatusError so
    an existing ``except httpx.HTTPStatusError`` around a write keeps seeing a
    403 status; when it propagates, main.py answers 404 (a row the policy
    hides already reads as "not found")."""


# ── Service-scope opt-outs ──────────────────────────────────────────────────


@contextmanager
def service_scope() -> Iterator[None]:
    """Run the block's PostgREST calls as the service role, in every mode.
    Each use must be justified (tests/test_service_scope_allowlist.py)."""
    token = _SERVICE_SCOPE.set(True)
    try:
        yield
    finally:
        _SERVICE_SCOPE.reset(token)


def in_service_scope() -> bool:
    return _SERVICE_SCOPE.get()


def runs_as_service(fn: F) -> F:
    """Decorator form of :func:`service_scope`, sync or async. Refuses
    generator functions: a scope held across a ``yield`` resets in another
    context (and raises) or silently leaks into the caller's next step."""
    if inspect.isgeneratorfunction(fn) or inspect.isasyncgenfunction(fn):
        raise TypeError(
            f"runs_as_service cannot wrap generator {fn.__qualname__}: wrap the "
            "DB call inside it with service_scope() instead"
        )
    if inspect.iscoroutinefunction(fn):
        @functools.wraps(fn)
        async def _async(*args, **kwargs):
            token = _SERVICE_SCOPE.set(True)
            try:
                return await fn(*args, **kwargs)
            finally:
                _SERVICE_SCOPE.reset(token)
        return _async  # type: ignore[return-value]

    @functools.wraps(fn)
    def _sync(*args, **kwargs):
        token = _SERVICE_SCOPE.set(True)
        try:
            return fn(*args, **kwargs)
        finally:
            _SERVICE_SCOPE.reset(token)
    return _sync  # type: ignore[return-value]


# ── Request state ───────────────────────────────────────────────────────────


def current_state() -> Optional[dict]:
    """The current request's shared state dict, or None outside a request."""
    view = request_context._REQUEST_CTX.get()
    state = view.state if view is not None else None
    return state if isinstance(state, dict) else None


def current_db_subject() -> Optional[str]:
    state = current_state()
    subject = state.get(SUBJECT_KEY) if state is not None else None
    return subject if isinstance(subject, str) and subject else None


def stamp_subject(request) -> None:
    """Record the request's subject from its session token (HMAC + expiry
    only, via the guard's own decoder; no DB read). Called by
    RequestIDMiddleware before the app runs. Never raises: no or a bad token
    simply leaves no subject (rule 4 above decides what that means)."""
    try:
        from services import auth_guard

        if not auth_guard.presented_session_token(request):
            return
        payload = auth_guard._decode_session(request)
        uid = payload.get("user_id") if isinstance(payload, dict) else None
        if isinstance(uid, str) and uid:
            request.scope.setdefault("state", {})[SUBJECT_KEY] = uid
    except Exception:
        return


def _resolve_mode(subject: Optional[str]) -> str:
    # The flag store reads `feature_flags`/`user_roles` (service-only), and
    # running them scoped would recurse into the very decision being made.
    with service_scope():
        try:
            from services.feature_flags import flag_variant

            mode = flag_variant(FLAG_KEY, subject)
        except Exception:
            logger.warning("db_user_scope: flag resolution failed; off", exc_info=True)
            return OFF
    return mode if mode in (OFF, SHADOW, ENFORCE) else OFF


def request_mode(state: dict) -> str:
    """This request's ``db_user_scope`` variant: resolved once, then read off
    the shared state (threadpool Depends, to_thread hops and BackgroundTasks
    all see the same answer)."""
    mode = state.get(MODE_KEY)
    if mode is None:
        mode = _resolve_mode(state.get(SUBJECT_KEY))
        state[MODE_KEY] = mode
    return mode


def _marked_service(state: dict) -> bool:
    return state.get(SCOPE_KEY) == SERVICE


# ── Router / endpoint opt-outs (plan §4.3) ──────────────────────────────────


def _state_of(request: Request) -> dict:
    return request.scope.setdefault("state", {})


def service_route(request: Request) -> None:
    """``Depends`` for a router or endpoint that runs as the service role
    (public, server-to-server, auth flows, cross-user projections). Sync on
    purpose: it writes the shared state dict, never a ContextVar."""
    _state_of(request)[SCOPE_KEY] = SERVICE


def admin_service_route(request: Request) -> None:
    """``Depends`` for admin routers: service role, but once the flag is past
    ``off`` it re-checks admin first, so a handler that forgot
    ``require_admin`` never runs service-scoped for a student. Under ``off``
    it only marks (no extra read, nothing changes)."""
    state = _state_of(request)
    state[SCOPE_KEY] = SERVICE
    if request_mode(state) != OFF:
        from services import auth_guard

        auth_guard.require_admin(request)


# ── Header resolution (called by db/connection.py::_scope_headers) ──────────


_warned: set[tuple] = set()
_warned_lock = threading.Lock()
_WARNED_MAX = 1_000


def _first_time(key: tuple) -> bool:
    with _warned_lock:
        if key in _warned:
            return False
        if len(_warned) >= _WARNED_MAX:
            _warned.clear()
        _warned.add(key)
        return True


def _emit(event: str, *, user_id: Optional[str], payload: dict,
          request_id: Optional[str] = None) -> None:
    try:
        from services import events_service

        events_service.log_event(
            event, category=events_service.SYSTEM_CATEGORY, user_id=user_id,
            request_id=request_id, payload=payload,
        )
    except Exception:  # pragma: no cover - log_event never raises
        logger.debug("db scope event %s not recorded", event, exc_info=True)


def _report_unscoped(mode: str, target: Optional[str]) -> None:
    """A request with no session subject reached PostgREST from a path not
    marked service: refused under enforce, ran as service under shadow (and
    would 500 under enforce).

    Every occurrence is COUNTED (tally + event). The log line is not: under
    shadow it is written once per (route, table) per process — an anonymous
    page that reads five tables would otherwise write five WARNING lines per
    hit. Under enforce each one is a refused request, logged every time."""
    route = request_context.current_route_template() or "?"
    tbl = target or "?"
    method = request_context.current_method()
    request_id = request_context.current_request_id()
    scope_report.record(
        event="db.unscoped_query", kind="no_subject", mode=mode, method=method,
        route=route, target=tbl, op=None, request_id=request_id,
        level=logging.ERROR if mode == ENFORCE else logging.WARNING,
        log=mode == ENFORCE or _first_time(("unscoped", route, tbl)),
    )
    _emit("db.unscoped_query", user_id=None, request_id=request_id,
          payload={"table": tbl, "route": route, "mode": mode, "kind": "no_subject",
                   "method": method or "?"})


def _user_headers(subject: str) -> dict:
    return {
        "apikey": user_jwt.anon_key(),
        "Authorization": f"Bearer {user_jwt.token_for(subject)}",
    }


def resolve_headers(target: Optional[str] = None) -> Optional[dict]:
    """The headers to override for one PostgREST call, or None for the
    client's service-role defaults. ``target`` (a table or rpc name) is for
    logging only. Never awaits; raises UnscopedQueryError / ScopeUnavailable
    under ``enforce`` instead of ever answering service role."""
    if _SERVICE_SCOPE.get():
        return None
    state = current_state()
    if state is None or _marked_service(state):
        return None
    mode = request_mode(state)
    if mode == OFF:
        return None
    subject = state.get(SUBJECT_KEY)
    if not subject:
        _report_unscoped(mode, target)
        if mode == ENFORCE:
            raise UnscopedQueryError(
                f"db_user_scope=enforce: no session subject for a query on {target or '?'}"
            )
        return None
    if mode == SHADOW:
        return None
    try:
        return _user_headers(subject)
    except (user_jwt.SigningKeyError, ValueError) as exc:
        logger.error("db_user_scope=enforce: cannot build the user-scoped credential (%s); "
                     "refusing the query rather than running it as service role", exc)
        raise ScopeUnavailable(str(exc)) from exc


def shadow_headers() -> Optional[dict]:
    """For a READ that just ran as service: user-scoped headers when this read
    should be re-run for comparison (``shadow``, a subject, sampled), else
    None. Never raises; a missing key is logged once and skips the shadow."""
    state = _shadow_state()
    if state is None or random.random() >= SHADOW_SAMPLE_RATE:
        return None
    try:
        return _user_headers(state[SUBJECT_KEY])
    except (user_jwt.SigningKeyError, ValueError) as exc:
        if _first_time(("shadow-key", str(exc))):
            logger.warning("db_user_scope=shadow: no user-scoped credential (%s); "
                           "shadow reads skipped", exc)
        return None


#: Shadow divergence kinds (the ``kind`` field of the line, the tally and the
#: event payload): the student's read came back with FEWER/MORE rows, the same
#: number of DIFFERENT ids, or an ERROR (``status`` + PostgREST ``code``:
#: 401 = token rejected, 403/42501 = missing grant or policy); a WRITE (or
#: write rpc) named another user in an owner column, filter or user parameter
#: (known without re-running it: RLS's WITH CHECK or USING on an owner column
#: refuses or silently skips it under enforce; see ``_other_user`` for what
#: this heuristic cannot see).
SHADOW_KINDS = ("fewer_rows", "more_rows", "different_ids", "error", "write_other_user")


def report_shadow_divergence(*, table: str, route: Optional[str], subject: Optional[str],
                             request_id: Optional[str], service_count: Optional[int],
                             scoped_count: Optional[int], kind: str,
                             method: Optional[str] = None, op: str = "select",
                             status: Optional[int] = None, code: Optional[str] = None) -> None:
    """A would-be denial seen in shadow: the same call, run as the student,
    would have returned a different row count / id set, failed, or (writes)
    targeted another user's row. Table, route template, counts and codes
    only — never row content. One WARNING line + the tally + one event."""
    scope_report.record(
        event="db.rls_shadow_divergence", kind=kind, mode=SHADOW, method=method,
        route=route, target=table, op=op, status=status, code=code,
        service_rows=service_count, scoped_rows=scoped_count,
        request_id=request_id, user=subject,
    )
    payload = {"table": table, "route": route or "?", "kind": kind,
               "method": method or "?", "op": op,
               "service_count": service_count, "scoped_count": scoped_count}
    # `status` only: rows written before this carried the same number again as
    # `error`; the admin reader still accepts that (routes/admin_analytics.py).
    if status is not None:
        payload["status"] = status
    if code:
        payload["code"] = code
    _emit("db.rls_shadow_divergence", user_id=subject, request_id=request_id, payload=payload)


def report_denied(target: str, status: int, *, code: Optional[str] = None,
                  op: str = "?") -> None:
    """A user-scoped call PostgREST refused (enforce). Logged + counted; the
    caller raises ScopedAccessDenied (-> 404). ``op`` is the operation the
    CALL SITE performed (db/connection.py passes it): the HTTP verb alone
    cannot tell an upsert from an insert."""
    route = request_context.current_route_template() or "?"
    method = request_context.current_method()
    request_id = request_context.current_request_id()
    subject = current_db_subject()
    scope_report.record(
        event="db.rls_denied", kind="denied", mode=ENFORCE, method=method, route=route,
        target=target, op=op, status=status, code=code, request_id=request_id, user=subject,
    )
    payload = {"table": target, "route": route, "status": status, "kind": "denied",
               "method": method or "?", "op": op}
    if code:
        payload["code"] = code
    _emit("db.rls_denied", user_id=subject, request_id=request_id, payload=payload)


def _shadow_state() -> Optional[dict]:
    """The request state when this call ran as service ONLY because of
    ``shadow`` (a subject, not service-marked), else None. The cheap gate
    every shadow hook passes first: two ContextVar reads and a dict lookup,
    and under ``off`` it returns before anything else is computed."""
    if _SERVICE_SCOPE.get():
        return None
    state = current_state()
    if state is None or state.get(MODE_KEY) != SHADOW or _marked_service(state):
        return None
    return state if state.get(SUBJECT_KEY) else None


#: The columns RLS keys a WRITE on, per table: a row or filter is the
#: subject's own when ANY listed column names the subject (party tables list
#: both sides). Unlisted tables key on ``user_id``. Mirrors the WITH CHECK /
#: USING columns of 20261108094129_rls_policies.sql. ``None`` = ownership is
#: not a column of the row (a room owner removing a member via owns_room), so
#: the heuristic does not judge that table at all.
_OWNER_COLUMNS: dict[str, Optional[tuple[str, ...]]] = {
    "users": ("id",),
    "rooms": ("owner_id",),
    "room_bans": ("banned_by",),
    "course_chunks": ("uploader_id",),
    "friendships": ("user_id", "friend_id"),
    "friend_requests": ("from_user_id", "to_user_id"),
    "room_members": None,
}
_DEFAULT_OWNER_COLUMNS: tuple[str, ...] = ("user_id",)

#: rpc parameters that name the user a function acts for (writes only: the
#: read-only SHADOW_READ_RPCS are re-run and compared instead).
_RPC_USER_PARAMS = ("p_user_id", "user_id", "p_owner_id", "p_uid")


def _filter_reaches_others(value: Any, subject: str) -> Optional[bool]:
    """One owner-column filter: True when it can match ANOTHER user's rows
    (``eq.<other>``, an ``in.(...)`` naming anyone else, any ``neq.``/``not.``),
    False when it pins the subject alone, None when it says nothing usable."""
    if isinstance(value, (list, tuple)):
        verdicts = [_filter_reaches_others(v, subject) for v in value]
        if any(v is False for v in verdicts):
            return False  # AND-ed: one pin to the subject bounds the rest
        return True if any(v is True for v in verdicts) else None
    if not isinstance(value, str):
        return None
    if value.startswith("eq."):
        return value[3:] != subject
    if value.startswith("in.(") and value.endswith(")"):
        ids = [v.strip().strip('"') for v in value[4:-1].split(",") if v.strip()]
        return any(i != subject for i in ids) if ids else None
    if value.startswith(("neq.", "not.")):
        return True
    return None


def _other_user(subject: str, target: str, op: str, data: Any,
                filters: Optional[dict]) -> bool:
    """Whether a write names a user other than the subject — a would-be
    denial under enforce, known without running it.

    A HEURISTIC, and a one-sided one: True is a real signal, False is not
    proof. It sees owner COLUMNS only (``_OWNER_COLUMNS``), so it is blind to
    writes keyed by a row id alone (``id=eq.<someone else's row>``), to tables
    whose policy goes through a parent row (messages, note_concepts,
    gradebook rows via enrollments), to room_members, and to rpc functions
    that take the user any other way than ``_RPC_USER_PARAMS``. The cross-user
    matrix under enforce is the gate for those
    (docs/security/db-user-scope-rollout.md)."""
    if op == "rpc":
        params = data if isinstance(data, dict) else {}
        return any(isinstance(params.get(k), str) and params[k] and params[k] != subject
                   for k in _RPC_USER_PARAMS)
    cols = _OWNER_COLUMNS.get(target, _DEFAULT_OWNER_COLUMNS)
    if not cols:
        return False
    rows = data if isinstance(data, list) else [data]
    for row in rows:
        if not isinstance(row, dict):
            continue
        named = [row[c] for c in cols if isinstance(row.get(c), str) and row[c]]
        if named and subject not in named:
            return True
    verdicts = [_filter_reaches_others(filters[c], subject)
                for c in cols if filters and c in filters]
    if any(v is False for v in verdicts):
        return False  # pinned to the subject on (one side of) the owner
    return any(v is True for v in verdicts)


def note_shadow_write(target: str, op: str, data: Any = None,
                      filters: Optional[dict] = None) -> None:
    """A write or rpc that ran as service under ``shadow``. Never re-executed
    (a mutation run twice is not an observation), so record only what is
    known without running it: the (route, table, op) inventory enforce will
    put under WITH CHECK, and — a would-be denial — a write or write rpc
    that names another user (``_other_user``). Never raises."""
    state = _shadow_state()
    if state is None:
        return
    try:
        subject = state[SUBJECT_KEY]
        route = request_context.current_route_template()
        method = request_context.current_method()
        request_id = request_context.current_request_id()
        scope_report.note_write(method=method, route=route, target=target, op=op,
                                request_id=request_id)
        if _other_user(subject, target, op, data, filters):
            report_shadow_divergence(
                table=target, route=route, subject=subject, request_id=request_id,
                service_count=None, scoped_count=None, kind="write_other_user",
                method=method, op=op,
            )
    except Exception:
        logger.debug("shadow write on %s not recorded", target, exc_info=True)
