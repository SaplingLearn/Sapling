"""The user-scoped PostgREST client (#115, RLS step 2): db/scope.py, db/user_jwt.py
and the `_scope_headers()` seam in db/connection.py.

Hermetic. The wire is a recording fake for `db.connection._client`; the
"requests" run through a small app carrying the real RequestIDMiddleware (which
stamps the session subject) or through `main.app` itself.

What is pinned:

* flag ``off``: every verb sends exactly the bytes it sent before this seam
  existed (no ``headers=`` argument added; the client's service-role defaults
  untouched), no token is minted, and nothing is shadowed;
* ``enforce``: ``apikey`` = the anon key, ``Authorization`` = a minted JWT whose
  claims and signature are checked here (HS256 and ES256), cached per subject
  until near expiry; fail closed with no key (503) or no subject (500), and a
  PostgREST 403 maps to 404;
* ``shadow``: the service-role answer is what the caller gets; a sampled read is
  re-run user-scoped and a divergence logged + evented; writes never shadowed;
* ``service_scope`` / ``runs_as_service``: sync, async, nested, and across the
  sanctioned thread hops (and NOT across a raw thread, by design);
* the auth guard, the flag store and the auth router stay service role under
  enforce, or every request would 500.
"""
from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import json
import logging
import threading
from unittest.mock import MagicMock

import pytest
from fastapi import BackgroundTasks, Depends, FastAPI, Request
from fastapi.testclient import TestClient

import db.connection as dbconn
from db import scope as db_scope
from db import user_jwt
from db.connection import rpc, table
from services import auth_guard
from services.request_context import RequestIDMiddleware

LOCAL_SECRET = b"super-secret-jwt-token-with-at-least-32-characters-long"
OCT_JWK = json.dumps({"kty": "oct", "k": base64.urlsafe_b64encode(LOCAL_SECRET).rstrip(b"=").decode(),
                      "kid": "local-hs"})
ANON = "anon-key-for-tests"
FLAG_ENV = "SAPLING_FLAG_DB_USER_SCOPE"


def _b64d(part: str) -> bytes:
    return base64.urlsafe_b64decode(part + "=" * (-len(part) % 4))


def _decode(token: str) -> tuple[dict, dict, bytes, bytes]:
    h, p, s = token.split(".")
    return json.loads(_b64d(h)), json.loads(_b64d(p)), f"{h}.{p}".encode(), _b64d(s)


# ── Fixtures ────────────────────────────────────────────────────────────────


class Wire:
    """A recording stand-in for the shared httpx client. ``rows(method, url,
    headers)`` decides each answer; ``status`` likewise (default 200)."""

    def __init__(self):
        self.calls: list[tuple[str, tuple, dict]] = []
        self.rows = lambda method, url, headers: []
        self.status = lambda method, url, headers: 200
        self.client = MagicMock(name="wire")
        for verb in ("get", "post", "patch", "delete"):
            getattr(self.client, verb).side_effect = self._make(verb)

    def _make(self, verb):
        def _call(*args, **kwargs):
            self.calls.append((verb, args, kwargs))
            url = args[0]
            headers = kwargs.get("headers")
            resp = MagicMock(name="resp")
            resp.status_code = self.status(verb, url, headers)
            resp.json.return_value = self.rows(verb, url, headers)
            resp.headers = {}
            if resp.status_code >= 400:
                import httpx

                req = httpx.Request(verb.upper(), url)
                resp.request = req
                resp.raise_for_status.side_effect = httpx.HTTPStatusError(
                    "err", request=req, response=httpx.Response(resp.status_code, request=req))
            else:
                resp.raise_for_status.return_value = None
            return resp
        return _call

    def scoped(self):
        return [c for c in self.calls if "Bearer " in str((c[2].get("headers") or {}).get("Authorization", ""))]

    def for_table(self, name):
        return [c for c in self.calls if c[1] and str(c[1][0]).endswith(f"/{name}")]


@pytest.fixture
def wire(monkeypatch):
    w = Wire()
    monkeypatch.setattr(dbconn, "_client", w.client)
    return w


@pytest.fixture(autouse=True)
def _fresh(monkeypatch):
    user_jwt.clear_token_cache()
    monkeypatch.delenv(FLAG_ENV, raising=False)
    monkeypatch.delenv(user_jwt.SIGNING_KEY_ENV, raising=False)
    monkeypatch.delenv(user_jwt.ANON_KEY_ENV, raising=False)
    db_scope._warned.clear()
    yield
    user_jwt.clear_token_cache()


@pytest.fixture
def keys(monkeypatch):
    monkeypatch.setenv(user_jwt.SIGNING_KEY_ENV, OCT_JWK)
    monkeypatch.setenv(user_jwt.ANON_KEY_ENV, ANON)


@pytest.fixture
def real_guard(monkeypatch):
    """The real session decoder + guard (the conftest stubs them), with a live
    account. Session cookies are minted with the real minter."""
    monkeypatch.setattr(auth_guard, "_decode_session", auth_guard._real_decode_session)
    monkeypatch.setattr(auth_guard, "get_session_user_id", auth_guard._real_get_session_user_id)


@pytest.fixture
def events(monkeypatch):
    seen: list[tuple[str, dict]] = []
    monkeypatch.setattr(db_scope, "_emit",
                        lambda event, *, user_id, payload, request_id=None: seen.append((event, payload)))
    return seen


def _cookie(user_id: str) -> dict:
    from services.session_tokens import mint_session

    return {"sapling_session": mint_session(user_id)}


def _app(handler, *, path="/probe", method="get", dependencies=None) -> TestClient:
    app = FastAPI()
    app.add_middleware(RequestIDMiddleware)
    getattr(app, method)(path, dependencies=dependencies or [])(handler)
    for exc, status in ((db_scope.ScopedAccessDenied, 404), (db_scope.ScopeUnavailable, 503),
                        (db_scope.UnscopedQueryError, 500)):
        app.add_exception_handler(exc, lambda r, e, s=status: _json(s))
    return TestClient(app, raise_server_exceptions=False)


def _json(status):
    from fastapi.responses import JSONResponse

    return JSONResponse({"status": status}, status_code=status)


def _read_notes():
    return {"rows": table("notes").select("id", filters={"user_id": "eq.u1"})}


# ── Flag off: nothing changes ───────────────────────────────────────────────


def _every_verb():
    t = table("notes")
    t.select("id", filters={"a": "eq.1"})
    t.select_with_count("id", limit=5, offset=0)
    t.insert({"a": 1})
    t.update({"a": 2}, {"id": "eq.1"})
    t.update({"a": 2}, {"id": "eq.1"}, prefer_return_minimal=True)
    t.upsert({"a": 3}, on_conflict="a")
    t.delete({"id": "eq.1"})
    rpc("fn", {"x": 1})


#: The exact (verb, args, kwargs) each call sent before the seam existed.
_LEGACY = [
    ("get", (f"{dbconn.REST_URL}/notes",), {"params": {"select": "id", "a": "eq.1"}}),
    ("get", (f"{dbconn.REST_URL}/notes",),
     {"params": {"select": "id", "limit": "5", "offset": "0"}, "headers": {"Prefer": "count=exact"}}),
    ("post", (f"{dbconn.REST_URL}/notes",), {"json": {"a": 1}}),
    ("patch", (f"{dbconn.REST_URL}/notes",), {"params": {"id": "eq.1"}, "json": {"a": 2}, "headers": None}),
    ("patch", (f"{dbconn.REST_URL}/notes",),
     {"params": {"id": "eq.1"}, "json": {"a": 2}, "headers": {"Prefer": "return=minimal"}}),
    ("post", (f"{dbconn.REST_URL}/notes",),
     {"headers": {"Prefer": "return=representation,resolution=merge-duplicates"},
      "params": {"on_conflict": "a"}, "json": {"a": 3}}),
    ("delete", (f"{dbconn.REST_URL}/notes",), {"params": {"id": "eq.1"}}),
    ("post", (f"{dbconn.REST_URL}/rpc/fn",), {"json": {"x": 1}}),
]


def test_service_role_client_defaults_are_unchanged():
    assert dbconn._HEADERS == {
        "apikey": dbconn.SUPABASE_KEY,
        "Authorization": f"Bearer {dbconn.SUPABASE_KEY}",
        "Content-Type": "application/json",
        "Prefer": "return=representation",
    }


def test_outside_a_request_every_verb_is_byte_identical(wire, monkeypatch):
    monkeypatch.setenv(FLAG_ENV, "enforce")  # even enforce: no request -> service
    _every_verb()
    assert wire.calls == _LEGACY


def test_flag_off_in_a_request_is_byte_identical_and_mints_nothing(wire, real_guard, monkeypatch, keys):
    monkeypatch.setenv(FLAG_ENV, "off")

    def _boom(*_a, **_k):
        raise AssertionError("minted a token with the flag off")
    monkeypatch.setattr(user_jwt, "token_for", _boom)
    monkeypatch.setattr(dbconn, "_maybe_shadow", lambda *a, **k: (_ for _ in ()).throw(
        AssertionError("shadowed with the flag off")) if db_scope.shadow_headers() else None)

    def handler(request: Request):
        _every_verb()
        return {"ok": True}

    r = _app(handler).get("/probe", cookies=_cookie("u1"))
    assert r.status_code == 200
    assert wire.calls == _LEGACY


def test_flag_off_is_resolved_once_per_request(wire, real_guard, monkeypatch):
    calls = []
    import services.feature_flags as ff
    monkeypatch.setattr(ff, "flag_variant", lambda key, uid: calls.append((key, uid)) or "off")

    def handler():
        table("a").select()
        table("b").select()
        table("c").insert({})
        return {}

    _app(handler).get("/probe", cookies=_cookie("u1"))
    assert calls == [("db_user_scope", "u1")]


# ── Enforce ────────────────────────────────────────────────────────────────


def test_enforce_sends_the_anon_key_and_a_minted_user_jwt(wire, real_guard, keys, monkeypatch):
    monkeypatch.setenv(FLAG_ENV, "enforce")
    r = _app(lambda: _read_notes()).get("/probe", cookies=_cookie("user_abc"))
    assert r.status_code == 200
    (verb, args, kwargs), = wire.for_table("notes")
    headers = kwargs["headers"]
    assert headers["apikey"] == ANON
    token = headers["Authorization"].removeprefix("Bearer ")
    header, claims, signing_input, sig = _decode(token)
    assert header == {"alg": "HS256", "typ": "JWT", "kid": "local-hs"}
    assert hmac.compare_digest(sig, hmac.new(LOCAL_SECRET, signing_input, hashlib.sha256).digest())
    assert claims["iss"] == "sapling-api" and claims["sub"] == "user_abc"
    assert claims["role"] == "authenticated" and claims["aud"] == "authenticated"
    assert claims["exp"] - claims["iat"] == 300


def test_enforce_every_verb_is_scoped(wire, real_guard, keys, monkeypatch):
    monkeypatch.setenv(FLAG_ENV, "enforce")

    def handler():
        _every_verb()
        return {}

    _app(handler).get("/probe", cookies=_cookie("u1"))
    notes = [c for c in wire.calls if str(c[1][0]).endswith(("/notes", "/rpc/fn"))]
    assert len(notes) == len(_LEGACY)
    for verb, args, kwargs in notes:
        assert kwargs["headers"]["apikey"] == ANON, (verb, kwargs)
        assert kwargs["headers"]["Authorization"].startswith("Bearer ey")
    # The verb's own headers survive the merge.
    by_prefer = [c[2]["headers"].get("Prefer") for c in notes]
    assert "count=exact" in by_prefer and "return=minimal" in by_prefer
    assert "return=representation,resolution=merge-duplicates" in by_prefer


def test_es256_signing_key(monkeypatch):
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.hazmat.primitives.asymmetric.utils import encode_dss_signature

    private = ec.generate_private_key(ec.SECP256R1())
    nums = private.private_numbers()

    def b64(n):
        return base64.urlsafe_b64encode(n.to_bytes(32, "big")).rstrip(b"=").decode()

    jwk = {"kty": "EC", "crv": "P-256", "kid": "sapling-es-1", "d": b64(nums.private_value),
           "x": b64(nums.public_numbers.x), "y": b64(nums.public_numbers.y)}
    monkeypatch.setenv(user_jwt.SIGNING_KEY_ENV, json.dumps(jwk))
    header, claims, signing_input, sig = _decode(user_jwt.mint("user_es"))
    assert header == {"alg": "ES256", "typ": "JWT", "kid": "sapling-es-1"}
    assert claims["sub"] == "user_es" and claims["iss"] == "sapling-api"
    assert len(sig) == 64
    der = encode_dss_signature(int.from_bytes(sig[:32], "big"), int.from_bytes(sig[32:], "big"))
    private.public_key().verify(der, signing_input, ec.ECDSA(hashes.SHA256()))  # raises if bad


def test_token_cache_reuses_until_near_expiry_and_follows_the_key(monkeypatch, keys):
    clock = [1_000_000]
    monkeypatch.setattr(user_jwt, "_now", lambda: clock[0])
    first = user_jwt.token_for("u1")
    clock[0] += user_jwt.TOKEN_TTL_S - user_jwt.REFRESH_MARGIN_S - 1
    assert user_jwt.token_for("u1") == first
    assert user_jwt.token_for("u2") != first
    clock[0] += 2  # inside the refresh margin
    second = user_jwt.token_for("u1")
    assert second != first and _decode(second)[1]["iat"] == clock[0]
    # Rotating the key never serves a token signed by the old one.
    other = json.dumps({"kty": "oct", "k": base64.urlsafe_b64encode(b"x" * 40).rstrip(b"=").decode()})
    monkeypatch.setenv(user_jwt.SIGNING_KEY_ENV, other)
    assert user_jwt.token_for("u1") != second


@pytest.mark.parametrize("bad", ["", "not json", json.dumps({"kty": "oct", "k": "c2hvcnQ"}),
                                 json.dumps({"kty": "RSA"}), json.dumps({"kty": "EC", "crv": "P-256"})])
def test_bad_or_missing_signing_key_is_refused(monkeypatch, bad):
    if bad:
        monkeypatch.setenv(user_jwt.SIGNING_KEY_ENV, bad)
    with pytest.raises(user_jwt.SigningKeyError):
        user_jwt.mint("u1")


@pytest.mark.parametrize("missing", [user_jwt.SIGNING_KEY_ENV, user_jwt.ANON_KEY_ENV])
def test_enforce_without_a_key_fails_closed(wire, real_guard, keys, monkeypatch, missing):
    monkeypatch.setenv(FLAG_ENV, "enforce")
    monkeypatch.delenv(missing)
    r = _app(lambda: _read_notes()).get("/probe", cookies=_cookie("u1"))
    assert r.status_code == 503
    assert wire.for_table("notes") == []  # never sent, least of all as service role


def test_enforce_without_a_subject_fails_closed(wire, keys, monkeypatch, events):
    monkeypatch.setenv(FLAG_ENV, "enforce")
    r = _app(lambda: _read_notes()).get("/probe")  # no session cookie
    assert r.status_code == 500
    assert wire.for_table("notes") == []
    assert [e for e, _ in events] == ["db.unscoped_query"]


def test_shadow_without_a_subject_runs_as_service_and_reports(wire, keys, monkeypatch, events, caplog):
    monkeypatch.setenv(FLAG_ENV, "shadow")
    with caplog.at_level(logging.WARNING, logger="sapling.db_scope"):
        r = _app(lambda: _read_notes()).get("/probe")
    assert r.status_code == 200
    (_, _, kwargs), = wire.for_table("notes")
    assert "headers" not in kwargs
    assert events[0][0] == "db.unscoped_query" and events[0][1]["table"] == "notes"
    assert "db_user_scope.divergence event=db.unscoped_query kind=no_subject mode=shadow" in caplog.text


def test_enforce_postgrest_403_is_scoped_access_denied_404(wire, real_guard, keys, monkeypatch, events):
    monkeypatch.setenv(FLAG_ENV, "enforce")
    wire.status = lambda verb, url, headers: 403 if headers and "Bearer ey" in str(headers) else 200

    def handler():
        table("notes").insert({"a": 1})
        return {}

    r = _app(handler, method="post").post("/probe", cookies=_cookie("u1"))
    assert r.status_code == 404
    assert [e for e, _ in events] == ["db.rls_denied"]


def test_enforce_postgrest_401_is_scope_unavailable_503(wire, real_guard, keys, monkeypatch):
    monkeypatch.setenv(FLAG_ENV, "enforce")
    wire.status = lambda verb, url, headers: 401 if headers and "Bearer ey" in str(headers) else 200
    r = _app(lambda: _read_notes()).get("/probe", cookies=_cookie("u1"))
    assert r.status_code == 503


def test_scoped_access_denied_still_reads_as_an_http_status_error():
    """A route's `except httpx.HTTPStatusError` around a write keeps working."""
    import httpx

    assert issubclass(db_scope.ScopedAccessDenied, httpx.HTTPStatusError)


@pytest.mark.parametrize("exc,status", [
    (db_scope.ScopedAccessDenied("x", request=MagicMock(), response=MagicMock()), 404),
    (db_scope.ScopeUnavailable("x"), 503),
    (db_scope.UnscopedQueryError("x"), 500),
])
def test_main_maps_the_scope_errors(exc, status):
    import main

    handler = main.app.exception_handlers[type(exc)]
    req = MagicMock()
    req.url.path = "/api/notes/x"
    req.state.request_id = "rid-12345678"
    resp = asyncio.run(handler(req, exc))
    assert resp.status_code == status


# ── Shadow ─────────────────────────────────────────────────────────────────


@pytest.fixture
def inline_shadow(monkeypatch):
    monkeypatch.setattr(dbconn, "_submit_shadow", lambda fn, *args: fn(*args))
    monkeypatch.setattr(db_scope.random, "random", lambda: 0.0)


def test_shadow_serves_the_service_answer_and_logs_divergence(
        wire, real_guard, keys, monkeypatch, inline_shadow, events, caplog):
    monkeypatch.setenv(FLAG_ENV, "shadow")
    wire.rows = lambda verb, url, headers: (
        [{"id": "n1"}] if headers and "Bearer ey" in str(headers) else [{"id": "n1"}, {"id": "n2"}])
    with caplog.at_level(logging.WARNING, logger="sapling.db_scope"):
        r = _app(lambda: _read_notes()).get("/probe", cookies=_cookie("u1"))
    assert r.json() == {"rows": [{"id": "n1"}, {"id": "n2"}]}  # the service-role answer
    service, scoped = wire.for_table("notes")
    assert "headers" not in service[2]
    assert scoped[2]["headers"]["apikey"] == ANON
    assert events == [("db.rls_shadow_divergence",
                       {"table": "notes", "route": "/probe", "kind": "fewer_rows", "method": "GET",
                        "op": "select", "service_count": 2, "scoped_count": 1})]
    assert "db.rls_shadow_divergence" in caplog.text


def test_shadow_agreement_is_silent(wire, real_guard, keys, monkeypatch, inline_shadow, events):
    monkeypatch.setenv(FLAG_ENV, "shadow")
    wire.rows = lambda verb, url, headers: [{"id": "n1"}]
    _app(lambda: _read_notes()).get("/probe", cookies=_cookie("u1"))
    assert len(wire.for_table("notes")) == 2 and events == []


def test_shadow_scoped_error_is_reported_not_raised(wire, real_guard, keys, monkeypatch, inline_shadow, events):
    monkeypatch.setenv(FLAG_ENV, "shadow")
    wire.status = lambda verb, url, headers: 403 if headers and "Bearer ey" in str(headers) else 200
    r = _app(lambda: _read_notes()).get("/probe", cookies=_cookie("u1"))
    assert r.status_code == 200
    assert events[0][1]["error"] == "403" and events[0][1]["scoped_count"] == -1


def test_shadow_never_reruns_writes_or_rpc(wire, real_guard, keys, monkeypatch, inline_shadow):
    monkeypatch.setenv(FLAG_ENV, "shadow")

    def handler():
        t = table("notes")
        t.insert({"a": 1})
        t.update({"a": 1}, {"id": "eq.1"})
        t.upsert({"a": 1})
        t.delete({"id": "eq.1"})
        rpc("apply_mastery_delta", {})
        return {}

    _app(handler, method="post").post("/probe", cookies=_cookie("u1"))
    writes = [c for c in wire.calls if str(c[1][0]).endswith(("/notes", "/rpc/apply_mastery_delta"))]
    assert len(writes) == 5
    assert wire.scoped() == []


def test_shadow_unsampled_reads_are_not_rerun(wire, real_guard, keys, monkeypatch):
    monkeypatch.setenv(FLAG_ENV, "shadow")
    monkeypatch.setattr(db_scope.random, "random", lambda: 0.99)
    submitted = []
    monkeypatch.setattr(dbconn, "_submit_shadow", lambda fn, *a: submitted.append(a))
    _app(lambda: _read_notes()).get("/probe", cookies=_cookie("u1"))
    assert submitted == []


def test_shadow_without_keys_skips_quietly(wire, real_guard, monkeypatch, inline_shadow):
    monkeypatch.setenv(FLAG_ENV, "shadow")
    r = _app(lambda: _read_notes()).get("/probe", cookies=_cookie("u1"))
    assert r.status_code == 200 and len(wire.for_table("notes")) == 1


def test_shadow_compare_runs_off_the_request_thread(wire, real_guard, keys, monkeypatch):
    """The real pool: the comparison is submitted, never awaited by the
    request; it finishes on a worker thread and releases its slot."""
    monkeypatch.setenv(FLAG_ENV, "shadow")
    monkeypatch.setattr(db_scope.random, "random", lambda: 0.0)
    done = threading.Event()
    real = dbconn._shadow_compare

    def _wrapped(*args):
        try:
            real(*args)
        finally:
            done.set()
    monkeypatch.setattr(dbconn, "_shadow_compare", _wrapped)
    _app(lambda: _read_notes()).get("/probe", cookies=_cookie("u1"))
    assert done.wait(5)
    assert dbconn._shadow_slots._value == dbconn._SHADOW_IN_FLIGHT_MAX


# ── service_scope / runs_as_service ─────────────────────────────────────────


def test_service_scope_nests_and_resets():
    assert not db_scope.in_service_scope()
    with db_scope.service_scope():
        with db_scope.service_scope():
            assert db_scope.in_service_scope()
        assert db_scope.in_service_scope()
    assert not db_scope.in_service_scope()


def test_runs_as_service_sync_and_async():
    @db_scope.runs_as_service
    def sync_fn():
        return db_scope.in_service_scope()

    @db_scope.runs_as_service
    async def async_fn():
        await asyncio.sleep(0)
        return db_scope.in_service_scope()

    assert sync_fn() is True
    assert asyncio.run(async_fn()) is True
    assert asyncio.iscoroutinefunction(async_fn)
    assert not db_scope.in_service_scope()


def test_runs_as_service_refuses_generators():
    with pytest.raises(TypeError):
        @db_scope.runs_as_service
        def gen():
            yield 1

    with pytest.raises(TypeError):
        @db_scope.runs_as_service
        async def agen():
            yield 1


def test_service_scope_follows_the_sanctioned_thread_hops_only():
    from starlette.concurrency import run_in_threadpool

    async def main():
        with db_scope.service_scope():
            via_to_thread = await asyncio.to_thread(db_scope.in_service_scope)
            via_threadpool = await run_in_threadpool(db_scope.in_service_scope)
            raw: list[bool] = []
            t = threading.Thread(target=lambda: raw.append(db_scope.in_service_scope()))
            t.start()
            t.join()
        return via_to_thread, via_threadpool, raw[0]

    assert asyncio.run(main()) == (True, True, False)


def test_service_scope_beats_enforce_inside_a_request(wire, real_guard, keys, monkeypatch):
    monkeypatch.setenv(FLAG_ENV, "enforce")

    @db_scope.runs_as_service
    def svc_read():
        return table("users").select("id")

    def handler():
        svc_read()
        with db_scope.service_scope():
            table("feature_flags").select("key")
        table("notes").select("id")
        return {}

    _app(handler).get("/probe", cookies=_cookie("u1"))
    assert "headers" not in wire.for_table("users")[0][2]
    assert "headers" not in wire.for_table("feature_flags")[0][2]
    assert wire.for_table("notes")[0][2]["headers"]["apikey"] == ANON


def test_background_task_keeps_scope_and_its_service_opt_out(wire, real_guard, keys, monkeypatch):
    """BackgroundTasks run after the response with the request's state: an
    undecorated task stays user-scoped, a @runs_as_service one is service."""
    monkeypatch.setenv(FLAG_ENV, "enforce")

    def user_task():
        table("notes").select("id")

    @db_scope.runs_as_service
    def svc_task():
        table("offering_concept_stats").select("id")

    def handler(background_tasks: BackgroundTasks):
        background_tasks.add_task(user_task)
        background_tasks.add_task(svc_task)
        return {}

    _app(handler).get("/probe", cookies=_cookie("u1"))
    assert wire.for_table("notes")[0][2]["headers"]["apikey"] == ANON
    assert "headers" not in wire.for_table("offering_concept_stats")[0][2]


def test_router_marks_service(wire, real_guard, keys, monkeypatch):
    monkeypatch.setenv(FLAG_ENV, "enforce")
    client = _app(lambda: _read_notes(), dependencies=[Depends(db_scope.service_route)])
    assert client.get("/probe").status_code == 200  # no subject, still fine: service
    assert client.get("/probe", cookies=_cookie("u1")).status_code == 200
    assert wire.scoped() == []


def test_admin_router_rechecks_admin_once_past_off(wire, real_guard, keys, monkeypatch):
    seen = []
    monkeypatch.setattr(auth_guard, "require_admin", lambda request: seen.append("checked"))
    client = _app(lambda: {"ok": 1}, dependencies=[Depends(db_scope.admin_service_route)])

    monkeypatch.setenv(FLAG_ENV, "off")
    client.get("/probe", cookies=_cookie("u1"))
    assert seen == []  # off: marks only, no extra read

    monkeypatch.setenv(FLAG_ENV, "enforce")
    client.get("/probe", cookies=_cookie("u1"))
    assert seen == ["checked"]


# ── The guard, the flag store and the auth router stay service ─────────────


def test_guard_and_flag_store_reads_stay_service_under_enforce(wire, real_guard, keys, monkeypatch):
    monkeypatch.setenv(FLAG_ENV, "")  # resolved from the (fake) store, not the env
    import services.feature_flags as ff

    def rows(verb, url, headers):
        if url.endswith("/users"):
            return [{"id": "u1", "deleted_at": None, "is_approved": True}]
        if url.endswith("/feature_flags"):
            return [{"key": "db_user_scope", "default_variant": "enforce", "rollout_percent": 0,
                     "rollout_variant": None, "updated_at": None, "updated_by": None}]
        return []
    wire.rows = rows
    ff.clear_feature_flags_cache()

    def handler(request: Request):
        uid = auth_guard.get_session_user_id(request)
        return {"uid": uid, **_read_notes()}

    r = _app(handler).get("/probe", cookies=_cookie("u1"))
    assert r.status_code == 200, r.text
    for name in ("users", "feature_flags", "feature_flag_targets"):
        assert wire.for_table(name), name
        assert all("headers" not in c[2] or "Bearer ey" not in str(c[2]["headers"])
                   for c in wire.for_table(name)), name
    assert wire.for_table("notes")[0][2]["headers"]["apikey"] == ANON


def test_require_admin_role_read_stays_service_under_enforce(wire, real_guard, keys, monkeypatch):
    monkeypatch.setenv(FLAG_ENV, "enforce")
    monkeypatch.setattr(auth_guard, "require_admin", auth_guard._real_require_admin)
    monkeypatch.setattr(auth_guard, "account_state", lambda uid: auth_guard.ACCOUNT_ACTIVE)
    wire.rows = lambda verb, url, headers: (
        [{"role_id": 1, "roles": {"slug": "admin"}}] if url.endswith("/user_roles") else [])

    def handler(request: Request):
        auth_guard.require_admin(request)
        return {}

    assert _app(handler).get("/probe", cookies=_cookie("u1")).status_code == 200
    assert wire.for_table("user_roles") and wire.scoped() == []


def test_auth_router_and_test_login_stay_service_under_enforce(wire, monkeypatch):
    """Through main.app: POST /api/auth/test-login signs every Playwright
    journey in, and /api/auth/me reads `users`; under enforce with no keys at
    all, neither may fail closed (the auth router is service role)."""
    import main

    monkeypatch.setenv(FLAG_ENV, "enforce")
    client = TestClient(main.app, raise_server_exceptions=False)
    r = client.post("/api/auth/test-login", json={"user_id": "user_andres"})
    assert r.status_code == 200, r.text
    wire.rows = lambda verb, url, headers: (
        [{"id": "user_andres", "is_approved": True, "onboarding_completed": True,
          "deleted_at": None}] if url.endswith("/users") else [])
    r = client.get("/api/auth/me", cookies={"sapling_session": "x"})
    assert r.status_code == 200, r.text
    assert wire.scoped() == []


def test_public_catalog_route_needs_no_session_under_enforce(wire, monkeypatch):
    import main

    monkeypatch.setenv(FLAG_ENV, "enforce")
    r = TestClient(main.app, raise_server_exceptions=False).get("/api/semesters")
    assert r.status_code == 200, r.text
    assert wire.scoped() == []


def test_boot_warns_when_the_flag_could_not_leave_off(monkeypatch, caplog):
    import config

    monkeypatch.setenv(FLAG_ENV, "enforce")
    with caplog.at_level(logging.ERROR, logger="sapling.config"):
        config._warn_db_user_scope_config()
    assert "SUPABASE_JWT_SIGNING_KEY is not set" in caplog.text
