"""The Postgres-backed rate limiter behind `stateless_rate_limit` (#117).

Hermetic: the `claim_rate_limit()` SQL function is faked at the rpc seam (its
SQL is exercised against a real Postgres when the migration is checked). What
is pinned here is the app side:

* off (default): today's in-memory limiter, no DB call at all;
* on: one rpc per claim, as service role, its answer mapped to the same
  RateLimitClaim the in-memory store returns (a DbSlot refund handle, or
  retry_after clamped to [1, window]);
* a DB failure (or a pre-migration 404) falls back to memory, warning once;
* a DbSlot refund deletes exactly its own row, on a background thread;
* the async twins answer from an `async def` without a sync DB call on the
  loop, under both values of `async_db_client`.
"""
from __future__ import annotations

import asyncio
import logging

import httpx
import pytest

import db.async_connection as adb
import db.connection as dbconn
from db import scope as db_scope
from services import request_limits as rl

FLAG_ENV = "SAPLING_FLAG_STATELESS_RATE_LIMIT"


@pytest.fixture(autouse=True)
def _reset(monkeypatch):
    monkeypatch.setattr(rl, "_warned_fallback", False)
    monkeypatch.setattr(rl, "_submit_refund", lambda key, hit_id: rl._refund_db(key, hit_id))
    monkeypatch.delenv(FLAG_ENV, raising=False)


class FakeDb:
    """The rpc + delete seam, recording whether each call ran as service."""

    def __init__(self, answer=None, error: Exception | None = None):
        self.answer = answer if answer is not None else [{"hit_id": 41, "retry_after": None}]
        self.error = error
        self.rpcs: list[tuple[str, dict, bool]] = []
        self.deletes: list[tuple[str, dict, bool]] = []

    def rpc(self, name, params):
        self.rpcs.append((name, params, db_scope.in_service_scope()))
        if self.error:
            raise self.error
        return self.answer

    def table(self, name):
        db = self

        class _T:
            def delete(self, filters):
                db.deletes.append((name, filters, db_scope.in_service_scope()))
                return []
        return _T()


@pytest.fixture
def fake_db(monkeypatch):
    db = FakeDb()
    monkeypatch.setattr(dbconn, "rpc", db.rpc)
    monkeypatch.setattr(dbconn, "table", db.table)
    return db


def test_off_is_the_in_memory_limiter_and_touches_no_db(fake_db):
    for _ in range(2):
        assert rl.claim_rate_limit("k", limit=2, window_sec=60).retry_after is None
    blocked = rl.claim_rate_limit("k", limit=2, window_sec=60)
    assert blocked.retry_after is not None
    assert fake_db.rpcs == []
    assert isinstance(rl._rate_state["k"][0], float)


def test_on_claims_through_the_sql_function_as_service(fake_db, monkeypatch):
    monkeypatch.setenv(FLAG_ENV, "on")
    claim = rl.claim_rate_limit("quiz_generate:u1", limit=8, window_sec=120)
    assert claim == rl.RateLimitClaim(retry_after=None, slot=rl.DbSlot(41))
    assert fake_db.rpcs == [("claim_rate_limit",
                             {"p_key": "quiz_generate:u1", "p_limit": 8, "p_window_sec": 120},
                             True)]
    assert "quiz_generate:u1" not in rl._rate_state  # nothing recorded in memory


@pytest.mark.parametrize("answered,expected", [(30, 30), (0, 1), (999, 120)])
def test_on_maps_a_refusal_to_retry_after_clamped_to_the_window(fake_db, monkeypatch,
                                                                answered, expected):
    monkeypatch.setenv(FLAG_ENV, "on")
    fake_db.answer = [{"hit_id": None, "retry_after": answered}]
    assert rl.check_rate_limit("k", limit=1, window_sec=120) == expected


def test_a_db_failure_falls_back_to_memory_and_warns_once(fake_db, monkeypatch, caplog):
    monkeypatch.setenv(FLAG_ENV, "on")
    req = httpx.Request("POST", "http://x/rest/v1/rpc/claim_rate_limit")
    fake_db.error = httpx.HTTPStatusError("404", request=req,
                                          response=httpx.Response(404, request=req))
    with caplog.at_level(logging.WARNING, logger="sapling.request_limits"):
        first = rl.claim_rate_limit("k", limit=1, window_sec=60)
        second = rl.claim_rate_limit("k", limit=1, window_sec=60)
    assert first.retry_after is None and isinstance(first.slot, float)
    assert second.retry_after is not None  # the in-memory budget still applies
    assert caplog.text.count("using the per-process limiter") == 1


def test_an_unexpected_answer_falls_back_too(fake_db, monkeypatch):
    monkeypatch.setenv(FLAG_ENV, "on")
    fake_db.answer = []
    claim = rl.claim_rate_limit("k", limit=1, window_sec=60)
    assert claim.retry_after is None and isinstance(claim.slot, float)


def test_a_db_slot_refund_deletes_exactly_its_row_as_service(fake_db):
    rl.refund_rate_limit("quiz_generate:u1", rl.DbSlot(41))
    assert fake_db.deletes == [("rate_limit_hits",
                                {"id": "eq.41", "key": "eq.quiz_generate:u1"}, True)]


def test_a_db_slot_refund_never_blocks_its_caller(monkeypatch):
    submitted = []
    monkeypatch.setattr(rl, "_submit_refund", lambda key, hit_id: submitted.append((key, hit_id)))
    rl.refund_rate_limit("k", rl.DbSlot(7))
    assert submitted == [("k", 7)]


def test_memory_refunds_are_unchanged():
    claim = rl.claim_rate_limit("k", limit=1, window_sec=60)
    rl.refund_rate_limit("k", claim.slot)
    assert rl._rate_state["k"] == []


# ── async twins ─────────────────────────────────────────────────────────────


@pytest.mark.parametrize("async_mode", ["off", "on"])
def test_aclaim_on_uses_the_sql_function_off_the_loop(monkeypatch, no_sync_db_on_loop, async_mode):
    """Inside a request so `async_db_client` applies: off hops the sync rpc to
    a worker thread, on goes native; neither runs a sync call on the loop."""
    monkeypatch.setenv(FLAG_ENV, "on")
    monkeypatch.setenv("SAPLING_FLAG_ASYNC_DB_CLIENT", async_mode)
    monkeypatch.setattr(dbconn, "REST_URL", "http://supabase.test/rest/v1")
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append((request.url.path, asyncio._get_running_loop() is not None))
        if request.url.path.endswith("/rpc/claim_rate_limit"):
            return httpx.Response(200, json=[{"hit_id": 9, "retry_after": None}])
        return httpx.Response(200, json=[])
    transport = httpx.MockTransport(handler)
    monkeypatch.setattr(dbconn, "_client", httpx.Client(transport=transport))
    monkeypatch.setattr(adb, "_async_client", lambda: httpx.AsyncClient(transport=transport))

    from services import request_context

    async def run():
        token = request_context._REQUEST_CTX.set(request_context.RequestView({"type": "http"}))
        try:
            return await rl.aclaim_rate_limit("k", limit=3, window_sec=60)
        finally:
            request_context._REQUEST_CTX.reset(token)

    claim = asyncio.run(run())
    assert claim.slot == rl.DbSlot(9)
    rpc_calls = [on_loop for path, on_loop in seen if path.endswith("/rpc/claim_rate_limit")]
    assert rpc_calls == [async_mode == "on"]  # native on the loop only when on


def test_aclaim_off_is_memory_without_any_hop(fake_db):
    async def run():
        return await rl.aclaim_rate_limit("k", limit=1, window_sec=60)

    assert asyncio.run(run()).retry_after is None
    assert asyncio.run(run()).retry_after is not None
    assert fake_db.rpcs == []
