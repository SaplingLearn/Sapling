"""The async DB seam (#117; docs/design/async-db-client.md): db/async_connection.py.

Hermetic. Both clients run on ``httpx.MockTransport`` with ONE handler, so what
is compared is the request that actually reaches the wire (method, URL with its
query string, every header, body) -- not the kwargs each client was handed.

Pinned:

* header/request parity: every verb's native ``a*`` request equals its sync
  sibling's under ``db_user_scope`` off / shadow / enforce, and both call the
  shadow hook with the same arguments;
* ``async_db_client`` off: the ``a*`` verbs run the sync verb on a worker
  thread (same client, nothing on the loop); resolved once per request;
* the native client holds no identity, pools 40 connections, 5 s pool/connect
  timeouts, one connect retry; one client per running loop;
* the same errors on both paths (HTTPStatusError, ScopedAccessDenied);
* ``service_scope()`` around an ``await`` keeps the call service role;
* the runtime ``db.sync_on_loop`` guard: logs (or, under the fixture, raises)
  for a sync call on the loop, and stays quiet for the sanctioned hops.
"""
from __future__ import annotations

import asyncio
import base64
import json
import logging

import httpx
import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from starlette.concurrency import run_in_threadpool

import db.async_connection as adb
import db.connection as dbconn
from db import scope as db_scope
from db import user_jwt
from db.async_connection import apage_all, arpc
from db.connection import rpc, table
from services import auth_guard
from services.request_context import RequestIDMiddleware

#: Captured before conftest's autouse net replaces it for every test.
_REAL_ASYNC_CLIENT = adb._async_client

LOCAL_SECRET = b"super-secret-jwt-token-with-at-least-32-characters-long"
OCT_JWK = json.dumps({"kty": "oct", "k": base64.urlsafe_b64encode(LOCAL_SECRET).rstrip(b"=").decode(),
                      "kid": "local-hs"})
ANON = "anon-key-for-tests"
SCOPE_ENV = "SAPLING_FLAG_DB_USER_SCOPE"
ASYNC_ENV = "SAPLING_FLAG_ASYNC_DB_CLIENT"


# ── The wire ───────────────────────────────────────────────────────────────


class Wire:
    """One MockTransport handler behind BOTH clients. Records every request
    with the thread it was sent from."""

    def __init__(self):
        self.requests: list[httpx.Request] = []
        self.threads: list[bool] = []  # True = sent from an event-loop thread
        self.status = lambda request: 200
        self.rows = lambda request: (
            [{"id": "r1"}] if "/notes" in request.url.path else [])

    def handler(self, request: httpx.Request) -> httpx.Response:
        if "/feature_flag" not in request.url.path:  # the flag store's own reads
            self.requests.append(request)
            self.threads.append(asyncio._get_running_loop() is not None)
        return httpx.Response(self.status(request), json=self.rows(request),
                              headers={"Content-Range": "0-0/7"})

    def seen(self) -> list[tuple]:
        return [(r.method, str(r.url), sorted(r.headers.items()), r.content)
                for r in self.requests]


@pytest.fixture
def wire(monkeypatch):
    monkeypatch.setattr(dbconn, "REST_URL", "http://supabase.test/rest/v1")
    w = Wire()
    transport = httpx.MockTransport(w.handler)
    monkeypatch.setattr(dbconn, "_client", httpx.Client(
        transport=transport, headers=dbconn._HEADERS, timeout=30.0))

    def _build():
        return httpx.AsyncClient(transport=transport, headers=dict(adb._ANON_DEFAULTS),
                                 timeout=adb.TIMEOUT)
    monkeypatch.setattr(adb, "_build_client", _build)
    monkeypatch.setattr(adb, "_async_client", _REAL_ASYNC_CLIENT)
    adb._clients.clear()
    yield w
    adb._clients.clear()


@pytest.fixture(autouse=True)
def _fresh(monkeypatch):
    import config

    if not config.SESSION_SECRET:  # CI sets one; a bare worktree has no .env
        monkeypatch.setattr(config, "SESSION_SECRET", "s" * 64)
        monkeypatch.setattr(auth_guard, "SESSION_SECRET", "s" * 64)
    user_jwt.clear_token_cache()
    for env in (SCOPE_ENV, ASYNC_ENV, user_jwt.SIGNING_KEY_ENV, user_jwt.ANON_KEY_ENV):
        monkeypatch.delenv(env, raising=False)
    db_scope._warned.clear()
    adb._seen.clear()
    yield
    user_jwt.clear_token_cache()


@pytest.fixture
def keys(monkeypatch):
    monkeypatch.setenv(user_jwt.SIGNING_KEY_ENV, OCT_JWK)
    monkeypatch.setenv(user_jwt.ANON_KEY_ENV, ANON)


@pytest.fixture
def real_guard(monkeypatch):
    monkeypatch.setattr(auth_guard, "_decode_session", auth_guard._real_decode_session)
    monkeypatch.setattr(auth_guard, "get_session_user_id", auth_guard._real_get_session_user_id)


@pytest.fixture
def shadow_calls(monkeypatch):
    seen: list[tuple] = []
    monkeypatch.setattr(dbconn, "_maybe_shadow", lambda *a, **k: seen.append((a, k)))
    return seen


def _cookie(user_id: str) -> dict:
    from services.session_tokens import mint_session

    return {"sapling_session": mint_session(user_id)}


def _app(handler, *, path="/probe") -> TestClient:
    app = FastAPI()
    app.add_middleware(RequestIDMiddleware)
    app.get(path)(handler)
    return TestClient(app)


def _every_verb():
    t = table("notes")
    t.select("id", filters={"a": "eq.1"}, order="id", limit=3, offset=0, timeout=4.0)
    t.select_with_count("id", limit=5, offset=0)
    t.insert({"a": 1})
    t.update({"a": 2}, {"id": "eq.1"})
    t.update({"a": 2}, {"id": "eq.1"}, prefer_return_minimal=True)
    t.upsert({"a": 3}, on_conflict="a")
    t.upsert({"a": 3}, on_conflict="a", ignore_duplicates=True, columns="id")
    t.delete({"id": "eq.1"})
    rpc("fn", {"x": 1})


async def _every_verb_async():
    t = table("notes")
    await t.aselect("id", filters={"a": "eq.1"}, order="id", limit=3, offset=0, timeout=4.0)
    await t.aselect_with_count("id", limit=5, offset=0)
    await t.ainsert({"a": 1})
    await t.aupdate({"a": 2}, {"id": "eq.1"})
    await t.aupdate({"a": 2}, {"id": "eq.1"}, prefer_return_minimal=True)
    await t.aupsert({"a": 3}, on_conflict="a")
    await t.aupsert({"a": 3}, on_conflict="a", ignore_duplicates=True, columns="id")
    await t.adelete({"id": "eq.1"})
    await arpc("fn", {"x": 1})


def _sync_handler():
    _every_verb()
    return {}


async def _async_handler():
    await _every_verb_async()
    return {}


# ── Parity on the wire ─────────────────────────────────────────────────────


@pytest.mark.parametrize("scope_mode", ["off", "shadow", "enforce"])
def test_native_requests_match_the_sync_client_on_the_wire(
        wire, real_guard, keys, shadow_calls, monkeypatch, scope_mode):
    monkeypatch.setenv(SCOPE_ENV, scope_mode)
    monkeypatch.setenv(ASYNC_ENV, "on")

    assert _app(_sync_handler).get("/probe", cookies=_cookie("u1")).status_code == 200
    sync_seen, sync_shadow = wire.seen(), list(shadow_calls)
    wire.requests.clear()
    shadow_calls.clear()
    assert _app(_async_handler).get("/probe", cookies=_cookie("u1")).status_code == 200

    assert len(sync_seen) == 9
    assert wire.seen() == sync_seen
    # The shadow hook is asked about the same reads, with the same arguments.
    assert shadow_calls == sync_shadow
    if scope_mode == "enforce":
        assert all(dict(h)["apikey"] == ANON for _m, _u, h, _b in sync_seen)
        assert sync_shadow == []
    else:
        assert all(dict(h)["apikey"] == dbconn.SUPABASE_KEY for _m, _u, h, _b in sync_seen)
        assert len(sync_shadow) == 2  # the two reads; writes and rpc never


def test_native_path_outside_a_request_is_off(wire, monkeypatch):
    monkeypatch.setenv(ASYNC_ENV, "on")  # outside a request: off until graduation
    asyncio.run(_every_verb_async())
    assert len(wire.requests) == 9
    assert wire.threads == [False] * 9  # every call ran on a worker thread


def test_flag_off_offloads_the_sync_verb(wire, real_guard, no_sync_db_on_loop, monkeypatch):
    monkeypatch.setenv(ASYNC_ENV, "off")
    _app(_sync_handler).get("/probe", cookies=_cookie("u1"))
    sync_seen = wire.seen()
    wire.requests.clear()
    wire.threads.clear()
    assert _app(_async_handler).get("/probe", cookies=_cookie("u1")).status_code == 200
    assert wire.seen() == sync_seen
    assert wire.threads == [False] * 9  # the sync client, off the loop


def test_flag_on_sends_from_the_loop_natively(wire, real_guard, monkeypatch):
    monkeypatch.setenv(ASYNC_ENV, "on")
    _app(_async_handler).get("/probe", cookies=_cookie("u1"))
    assert wire.threads == [True] * 9


def test_mode_is_resolved_once_per_request(wire, real_guard, monkeypatch):
    calls = []
    import services.feature_flags as ff

    monkeypatch.setattr(ff, "cached_explain", lambda key, uid: None)
    monkeypatch.setattr(ff, "flag_variant",
                        lambda key, uid: calls.append((key, uid, asyncio._get_running_loop()))
                        or ("on" if key == adb.FLAG_KEY else "off"))
    _app(_async_handler).get("/probe", cookies=_cookie("u1"))
    keys_asked = [(k, u) for k, u, _loop in calls]
    assert keys_asked.count((adb.FLAG_KEY, "u1")) == 1
    assert keys_asked.count((db_scope.FLAG_KEY, "u1")) == 1
    # A cold flag store is read off the loop, never inline.
    assert all(loop is None for _k, _u, loop in calls)
    assert wire.threads == [True] * 9


def test_service_scope_across_an_await_stays_service(wire, real_guard, keys, monkeypatch):
    monkeypatch.setenv(SCOPE_ENV, "enforce")
    monkeypatch.setenv(ASYNC_ENV, "on")

    async def handler():
        with db_scope.service_scope():
            await table("notes").aselect("id")
        await table("notes").aselect("id")
        return {}

    _app(handler).get("/probe", cookies=_cookie("u1"))
    service, scoped = (dict(r.headers) for r in wire.requests)
    assert service["apikey"] == dbconn.SUPABASE_KEY
    assert scoped["apikey"] == ANON


# ── Errors ─────────────────────────────────────────────────────────────────


def test_http_errors_surface_identically(wire, real_guard, monkeypatch):
    monkeypatch.setenv(ASYNC_ENV, "on")
    wire.status = lambda request: 500
    outcomes = {}

    def sync_handler():
        try:
            table("notes").select("id")
        except httpx.HTTPStatusError as e:
            outcomes["sync"] = e.response.status_code
        return {}

    async def async_handler():
        try:
            await table("notes").aselect("id")
        except httpx.HTTPStatusError as e:
            outcomes["async"] = e.response.status_code
        return {}

    _app(sync_handler).get("/probe", cookies=_cookie("u1"))
    _app(async_handler).get("/probe", cookies=_cookie("u1"))
    assert outcomes == {"sync": 500, "async": 500}


def test_enforce_403_is_scoped_access_denied_on_the_native_path(wire, real_guard, keys, monkeypatch):
    monkeypatch.setenv(SCOPE_ENV, "enforce")
    monkeypatch.setenv(ASYNC_ENV, "on")
    monkeypatch.setattr(db_scope, "_emit", lambda *a, **k: None)
    wire.status = lambda request: 403
    seen = {}

    async def handler():
        try:
            await table("notes").ainsert({"a": 1})
        except db_scope.ScopedAccessDenied as e:
            seen["status"] = e.response.status_code
        return {}

    _app(handler).get("/probe", cookies=_cookie("u1"))
    assert seen == {"status": 403}


# ── The client ─────────────────────────────────────────────────────────────


def test_the_native_client_holds_no_identity_and_is_bounded(monkeypatch):
    built = {}
    real_transport = httpx.AsyncHTTPTransport

    def _transport(**kw):
        built.update(kw)
        return real_transport(**kw)
    monkeypatch.setattr(adb.httpx, "AsyncHTTPTransport", _transport)
    client = adb._build_client()
    try:
        assert "apikey" not in client.headers and "authorization" not in client.headers
        assert client.timeout == httpx.Timeout(30.0, connect=5.0, pool=5.0)
        assert built["retries"] == 1
        assert built["limits"] == httpx.Limits(max_connections=40, max_keepalive_connections=40)
    finally:
        asyncio.run(client.aclose())


def test_one_client_per_running_loop(monkeypatch):
    monkeypatch.setattr(adb, "_async_client", _REAL_ASYNC_CLIENT)
    adb._clients.clear()

    async def twice():
        return adb._async_client(), adb._async_client()

    a1, a2 = asyncio.run(twice())
    b1, _ = asyncio.run(twice())
    assert a1 is a2
    assert b1 is not a1
    adb._clients.clear()


def test_aclose_clients_closes_the_running_loops_client(monkeypatch):
    monkeypatch.setattr(adb, "_async_client", _REAL_ASYNC_CLIENT)
    adb._clients.clear()

    async def run():
        c = adb._async_client()
        await adb.aclose_clients()
        return c

    assert asyncio.run(run()).is_closed
    assert adb._clients == {}


def test_apage_all_pages_past_a_full_page(wire, real_guard, monkeypatch):
    monkeypatch.setenv(ASYNC_ENV, "on")
    pages = {"0": [{"id": i} for i in range(2)], "2": [{"id": 2}]}
    wire.rows = lambda request: pages[request.url.params["offset"]]
    out = {}

    async def handler():
        out["rows"] = [r async for r in apage_all(table("notes"), "id", order="id", page=2)]
        return {}

    _app(handler).get("/probe", cookies=_cookie("u1"))
    assert out["rows"] == [{"id": 0}, {"id": 1}, {"id": 2}]


# ── The runtime guard (design §4.2) ────────────────────────────────────────


def test_a_sync_call_on_the_loop_is_logged_once(wire, caplog):
    async def blocking():
        table("notes").select("id")
        table("notes").select("id")

    with caplog.at_level(logging.WARNING, logger="sapling.db"):
        asyncio.run(blocking())
    assert caplog.text.count("db.sync_on_loop") == 1


def test_the_fixture_turns_it_into_a_raise(wire, no_sync_db_on_loop):
    async def blocking():
        table("notes").select("id")

    with pytest.raises(adb.SyncDbOnLoop):
        asyncio.run(blocking())


def test_sanctioned_hops_and_the_async_seam_pass(wire, no_sync_db_on_loop, caplog):
    async def hops():
        await run_in_threadpool(table("notes").select, "id")
        await asyncio.to_thread(table("notes").select, "id")
        await table("notes").aselect("id")

    with caplog.at_level(logging.WARNING, logger="sapling.db"):
        asyncio.run(hops())
    assert "db.sync_on_loop" not in caplog.text


def test_a_sync_handler_never_trips_it(wire, real_guard, no_sync_db_on_loop):
    def handler(request: Request):
        table("notes").select("id")
        return {}

    assert _app(handler).get("/probe", cookies=_cookie("u1")).status_code == 200
