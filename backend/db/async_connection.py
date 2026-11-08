"""The async twin of db/connection.py (#117; docs/design/async-db-client.md).

``table(name)`` stays the one chokepoint and the one patch point: the handle it
returns (``SupabaseTable``) inherits :class:`AsyncTableMixin`, so every sync
verb has a coroutine sibling on the SAME object::

    rows = await table("graph_nodes").aselect("*", filters={"user_id": f"eq.{uid}"})

plus the module-level :func:`arpc` and :func:`apage_all` (an async generator).

Rollout switch, flag ``async_db_client`` (server-only, design §3):

* ``off`` (default) -- every ``a*`` method runs its sync sibling through
  ``anyio.to_thread.run_sync``: the same client, the same 40-token limiter and
  the same bytes on the wire as today, only reached from an ``async def``
  without blocking the event loop.
* ``on`` -- a native ``httpx.AsyncClient``, one per running event loop.

Resolved once per request and memoized on the request's ``scope["state"]``
beside ``db_user_scope`` (a cold flag snapshot is read off the loop). Outside
a request it is ``off``: workers, scripts, seeds and the sweeper stay sync.

What the native path shares with the sync one, so the two cannot drift:

* identity -- ``db.connection._scope_headers`` is asked right before every
  request, exactly as the sync verbs ask it (off / shadow / enforce, the
  ``service_scope`` opt-outs, fail-closed errors). The client itself holds NO
  identity: the service-role ``apikey`` + ``Authorization`` are set per
  request when the scope answers "service", so whichever request builds a
  loop's client first cannot leave its scope baked into it (design §2.1);
* errors -- the same ``db.connection._raise_for_status`` (so
  ``httpx.HTTPStatusError`` / ``ScopedAccessDenied`` / ``ScopeUnavailable``
  surface identically and main.py's handlers need no async variant);
* shadow reads -- the same ``db.connection._maybe_shadow`` (a non-blocking
  submit to the shadow pool);
* request shape -- each verb builds the same params/headers/json as its sync
  sibling; ``tests/test_async_db_client.py`` pins that on the wire under
  ``db_user_scope`` off / shadow / enforce.

Encryption is unchanged: the seam moves bytes, call sites still
``encrypt_if_present`` before a write and ``decrypt_if_present`` after a read.

The runtime half of design §4.2 lives here too: :func:`note_sync_call`, called
by ``db.connection._scope_headers`` before every SYNC request, logs
``db.sync_on_loop`` when that request is about to block a running event loop
(and raises instead under the test fixture that opts in).

This module imports nothing from ``db.connection`` at import time
(``db.connection`` imports it, for the mixin); :func:`_conn` resolves it at
call time, so a test that patches ``db.connection._scope_headers`` or
``_HEADERS`` patches both paths.
"""
from __future__ import annotations

import asyncio
import contextvars
import functools
import inspect
import logging
import threading
import weakref
from typing import Any, AsyncIterator, Optional

import anyio
import httpx

from db import scope as _scope

logger = logging.getLogger("sapling.db")

FLAG_KEY = "async_db_client"
ON = "on"
#: Key on the request's ``scope["state"]`` (beside ``db_user_scope_mode``).
MODE_KEY = "async_db_client_mode"

#: Design §2.3: today's effective concurrency per replica (the threadpool caps
#: the sync path at 40). Raise only when PostgREST's DB pool has headroom.
POOL_SIZE = 40
#: Read/write keep the sync client's 30 s; waiting on a connection or the pool
#: becomes a fast, visible failure instead of 30 silent seconds.
TIMEOUT = httpx.Timeout(30.0, connect=5.0, pool=5.0)
#: httpcore retries only ConnectError/ConnectTimeout, before anything was sent,
#: so this is safe for every verb. No application-level retries here: the sync
#: client has none, and the two paths keep the same error semantics.
CONNECT_RETRIES = 1

#: Default headers of the native client: NO identity (see the module doc).
_ANON_DEFAULTS = {"Content-Type": "application/json", "Prefer": "return=representation"}


def _conn():
    from db import connection

    return connection


# ── Runtime guard: a sync PostgREST call on a running event loop ────────────

#: Set while the async seam resolves headers inline (on the loop, legitimately).
_IN_ASYNC_SEAM: contextvars.ContextVar[bool] = contextvars.ContextVar(
    "sapling_db_in_async_seam", default=False,
)
#: Test seam: when True, :func:`note_sync_call` raises instead of logging.
#: Flipped by the ``no_sync_db_on_loop`` fixture in tests/db_fakes.py.
RAISE_ON_SYNC_ON_LOOP = False

_seen: set[tuple[str, str]] = set()
_seen_lock = threading.Lock()
_SEEN_MAX = 1_000


class SyncDbOnLoop(RuntimeError):
    """A sync PostgREST call ran on an event-loop thread (tests only)."""


def note_sync_call(target: Optional[str]) -> None:
    """Called by every sync verb before it sends. On an event-loop thread the
    call is about to block that loop for a whole PostgREST round trip: log
    ``db.sync_on_loop`` once per (route, table) per process. AnyIO /
    ``to_thread`` worker threads have no running loop, so the sanctioned hops
    pass. Never raises in production."""
    if _IN_ASYNC_SEAM.get() or asyncio._get_running_loop() is None:
        return
    from services.request_context import current_route_template

    route = current_route_template() or "?"
    tbl = target or "?"
    if RAISE_ON_SYNC_ON_LOOP:
        raise SyncDbOnLoop(f"sync PostgREST call on {tbl} blocked the event loop ({route})")
    key = (route, tbl)
    with _seen_lock:
        if key in _seen:
            return
        if len(_seen) >= _SEEN_MAX:
            _seen.clear()
        _seen.add(key)
    logger.warning("db.sync_on_loop table=%s route=%s: a sync PostgREST call blocked the "
                   "event loop; use the a* twin or run_in_threadpool", tbl, route)


# ── Per-event-loop client (design §2.1; the #354/#436 lesson) ──────────────
#
# An httpx.AsyncClient's pool binds to the loop that first used it; reusing it
# from another loop fails with "Event loop is closed". Resolved at the moment
# of use, never cached on a shared object. Keyed on id(loop) with a WEAK
# reference to the loop and pruned on every access, as in
# services/typesafe_client.py (a WeakKeyDictionary would be pinned by the
# client's own strong path back to its loop).

_clients: dict[int, tuple["weakref.ref[Any]", httpx.AsyncClient]] = {}
_clients_lock = threading.Lock()


def _build_client() -> httpx.AsyncClient:
    limits = httpx.Limits(max_connections=POOL_SIZE, max_keepalive_connections=POOL_SIZE)
    return httpx.AsyncClient(
        headers=dict(_ANON_DEFAULTS),
        timeout=TIMEOUT,
        transport=httpx.AsyncHTTPTransport(retries=CONNECT_RETRIES, limits=limits),
    )


def _prune_locked() -> None:
    for key, (loop_ref, _c) in list(_clients.items()):
        loop = loop_ref()
        if loop is None or loop.is_closed():
            del _clients[key]


def _async_client() -> httpx.AsyncClient:
    """This running loop's client. Nothing may await between this call and
    the request it serves."""
    loop = asyncio.get_running_loop()
    with _clients_lock:
        _prune_locked()
        entry = _clients.get(id(loop))
        if entry is not None and entry[0]() is loop and not entry[1].is_closed:
            return entry[1]
        client = _build_client()
        _clients[id(loop)] = (weakref.ref(loop), client)
        return client


async def aclose_clients() -> None:
    """Lifespan teardown: close the running loop's client; drop the others
    (their loops cannot run an aclose from here). Never raises."""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None
    with _clients_lock:
        entries = list(_clients.values())
        _clients.clear()
    for loop_ref, client in entries:
        if loop is not None and loop_ref() is loop and not client.is_closed:
            try:
                await client.aclose()
            except Exception:
                pass


# ── Mode + scope resolution (both memoized per request, read off the loop) ──


def _resolve_flag(subject: Optional[str]) -> str:
    try:
        from services.feature_flags import flag_variant

        return flag_variant(FLAG_KEY, subject)
    except Exception:
        logger.warning("async_db_client: flag resolution failed; off", exc_info=True)
        return "off"


async def _native() -> bool:
    """Whether this call takes the native AsyncClient (flag ``on``)."""
    state = _scope.current_state()
    if state is None:
        return False  # outside a request: off until the flag graduates
    mode = state.get(MODE_KEY)
    if mode is None:
        subject = _scope.current_db_subject()
        from services.feature_flags import cached_explain

        try:
            res = cached_explain(FLAG_KEY, subject)
        except Exception:
            res = None
        mode = res.variant if res is not None else await anyio.to_thread.run_sync(
            _resolve_flag, subject)
        state[MODE_KEY] = mode
    return mode == ON


async def _prime_scope() -> None:
    """Resolve this request's ``db_user_scope`` variant OFF the loop before
    the first native call asks for headers: a cold flag snapshot is a sync
    read, and ``resolve_headers`` would otherwise do it inline. After this,
    header resolution is pure CPU (a cached or freshly minted JWT)."""
    if _scope.in_service_scope():
        return
    state = _scope.current_state()
    if state is None or state.get(_scope.SCOPE_KEY) == _scope.SERVICE:
        return
    if state.get(_scope.MODE_KEY) is None:
        await anyio.to_thread.run_sync(_scope.request_mode, state)


def _accepts_write_op(fn) -> bool:
    try:
        return "write_op" in inspect.signature(fn).parameters
    except (TypeError, ValueError):
        return False


def _headers(target: str, write_op: Optional[str] = None, **write_kw) -> Optional[dict]:
    """``db.connection._scope_headers`` for one native call, asked exactly as
    the sync verbs ask it (a ``_scope_headers`` that also takes the write
    details, harden2/w5b, gets them too)."""
    fn = _conn()._scope_headers
    token = _IN_ASYNC_SEAM.set(True)
    try:
        if write_op is not None and _accepts_write_op(fn):
            return fn(target, write_op, **write_kw)
        return fn(target)
    finally:
        _IN_ASYNC_SEAM.reset(token)


def _identity(headers: Optional[dict], scoped: Optional[dict]) -> dict:
    """Per-request headers for the identity-free client: the verb's own,
    then the scoped pair or (service) the sync client's own credentials."""
    if scoped is None:
        h = _conn()._HEADERS
        scoped = {"apikey": h["apikey"], "Authorization": h["Authorization"]}
    return {**(headers or {}), **scoped}


async def _offload(fn, *args, **kwargs):
    return await anyio.to_thread.run_sync(functools.partial(fn, *args, **kwargs))


# ── The a* verbs ────────────────────────────────────────────────────────────


class AsyncTableMixin:
    """Coroutine twins of ``SupabaseTable``'s verbs. Each mirrors its sync
    sibling's request exactly; see the module doc."""

    name: str
    url: str

    async def aselect(
        self,
        columns: str = "*",
        filters: Optional[dict] = None,
        order: Optional[str] = None,
        limit: Optional[int] = None,
        offset: Optional[int] = None,
        timeout: Optional[float] = None,
    ) -> list:
        if not await _native():
            return await _offload(self.select, columns, filters=filters, order=order,
                                  limit=limit, offset=offset, timeout=timeout)
        await _prime_scope()
        c = _conn()
        params: dict = {"select": columns}
        if filters:
            params.update(filters)
        if order:
            params["order"] = order
        if limit:
            params["limit"] = str(limit)
        if offset is not None:
            params["offset"] = str(offset)
        kw = {"timeout": timeout} if timeout is not None else {}
        scoped = _headers(self.name)
        r = await _async_client().get(self.url, params=params,
                                      headers=_identity(None, scoped), **kw)
        c._raise_for_status(r, scoped, self.name)
        rows = r.json()
        if scoped is None:
            c._maybe_shadow(self.name, self.url, params, None, timeout, rows)
        return rows

    async def aselect_with_count(
        self,
        columns: str = "*",
        filters: Optional[dict] = None,
        order: Optional[str] = None,
        limit: Optional[int] = None,
        offset: Optional[int] = None,
        timeout: Optional[float] = None,
    ) -> tuple[list, int]:
        if not await _native():
            return await _offload(self.select_with_count, columns, filters=filters,
                                  order=order, limit=limit, offset=offset, timeout=timeout)
        await _prime_scope()
        c = _conn()
        params: dict = {"select": columns}
        if filters:
            params.update(filters)
        if order:
            params["order"] = order
        if limit is not None:
            params["limit"] = str(limit)
        if offset is not None:
            params["offset"] = str(offset)
        headers = {"Prefer": "count=exact"}
        kw = {"timeout": timeout} if timeout is not None else {}
        scoped = _headers(self.name)
        r = await _async_client().get(self.url, params=params,
                                      headers=_identity(headers, scoped), **kw)
        c._raise_for_status(r, scoped, self.name)
        rows = r.json()
        if scoped is None:
            c._maybe_shadow(self.name, self.url, params, headers, timeout, rows)
        total = 0
        cr = r.headers.get("Content-Range") or r.headers.get("content-range")
        if cr and "/" in cr:
            try:
                total = int(cr.rsplit("/", 1)[1])
            except ValueError:
                total = 0
        return rows, total

    async def ainsert(self, data) -> list:
        if not await _native():
            return await _offload(self.insert, data)
        await _prime_scope()
        scoped = _headers(self.name, "insert", data=data)
        r = await _async_client().post(self.url, json=data, headers=_identity(None, scoped))
        _conn()._raise_for_status(r, scoped, self.name)
        return r.json()

    async def aupdate(self, data: dict, filters: dict, *,
                      prefer_return_minimal: bool = False) -> list:
        if not await _native():
            return await _offload(self.update, data, filters,
                                  prefer_return_minimal=prefer_return_minimal)
        await _prime_scope()
        headers = {"Prefer": "return=minimal"} if prefer_return_minimal else None
        scoped = _headers(self.name, "update", data=data, filters=filters)
        r = await _async_client().patch(self.url, params=filters, json=data,
                                        headers=_identity(headers, scoped))
        _conn()._raise_for_status(r, scoped, self.name)
        if prefer_return_minimal:
            return []
        return r.json()

    async def aupsert(
        self,
        data,
        on_conflict: str = "id",
        *,
        ignore_duplicates: bool = False,
        columns: Optional[str] = None,
    ) -> list:
        if not await _native():
            return await _offload(self.upsert, data, on_conflict,
                                  ignore_duplicates=ignore_duplicates, columns=columns)
        await _prime_scope()
        resolution = "ignore-duplicates" if ignore_duplicates else "merge-duplicates"
        headers = {"Prefer": f"return=representation,resolution={resolution}"}
        params = {"on_conflict": on_conflict}
        if columns:
            params["select"] = columns
        scoped = _headers(self.name, "upsert", data=data)
        r = await _async_client().post(self.url, headers=_identity(headers, scoped),
                                       params=params, json=data)
        _conn()._raise_for_status(r, scoped, self.name)
        return r.json()

    async def adelete(self, filters: dict) -> list:
        if not await _native():
            return await _offload(self.delete, filters)
        await _prime_scope()
        scoped = _headers(self.name, "delete", filters=filters)
        r = await _async_client().delete(self.url, params=filters,
                                         headers=_identity(None, scoped))
        _conn()._raise_for_status(r, scoped, self.name)
        return r.json()


async def arpc(function_name: str, params: dict) -> list:
    """The coroutine twin of ``db.connection.rpc``. Never retried."""
    c = _conn()
    if not await _native():
        return await _offload(c.rpc, function_name, params)
    await _prime_scope()
    url = f"{c.REST_URL}/rpc/{function_name}"
    target = f"rpc/{function_name}"
    # Same rule as the sync rpc(): a read-only function in SHADOW_READ_RPCS is
    # not noted as a write and is shadow-compared like a select.
    read_only = function_name in c.SHADOW_READ_RPCS
    scoped = _headers(target, None if read_only else "rpc")
    r = await _async_client().post(url, json=params, headers=_identity(None, scoped))
    c._raise_for_status(r, scoped, target)
    rows = r.json()
    if scoped is None and read_only:
        c._maybe_shadow(target, url, {}, None, None, rows, op="rpc", json_body=params)
    return rows


async def apage_all(
    handle,
    columns: str = "*",
    *,
    filters: Optional[dict] = None,
    order: str,
    page: Optional[int] = None,
    timeout: Optional[float] = None,
) -> AsyncIterator[dict]:
    """The async twin of ``db.connection.page_all``: same contract (a SHORT
    page is the only proof of the end; ``order`` must be a total order)."""
    c = _conn()
    page = c.MAX_ROWS if page is None else page
    if page > c.MAX_ROWS:
        raise ValueError(
            f"page={page} exceeds PostgREST max_rows ({c.MAX_ROWS}); "
            "every page would come back short and the read would stop early"
        )
    seen = 0
    offset = 0
    extra = {"timeout": timeout} if timeout is not None else {}
    while True:
        rows, total = await handle.aselect_with_count(
            columns, filters=filters, order=order, limit=page, offset=offset, **extra,
        )
        rows = rows or []
        for row in rows:
            yield row
        seen += len(rows)
        if len(rows) < page or (total > 0 and seen >= total):
            return
        offset += page
