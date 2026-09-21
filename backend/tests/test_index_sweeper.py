"""services/index_sweeper.py — what drains the indexing queue (#482).

A status column nothing drains is the bug #482 is about in a new form:
`scripts/backfill_document_chunks.py` existed for months and was invoked by
nothing. The sweeper claims stale rows through `claim_documents_for_indexing`
(whose atomicity is covered against a real Postgres in the migration's
verification) and re-drives each through the shared entry point.
"""
import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from services import index_sweeper


@pytest.fixture
def real_mode(monkeypatch):
    monkeypatch.setenv("SAPLING_MODEL_MODE", "real")
    monkeypatch.delenv("INDEX_SWEEPER_ENABLED", raising=False)


@pytest.fixture
def claims(monkeypatch):
    """A claimable queue: each call to the claim RPC hands out as many rows as
    it asks for, like the SQL function, and records what it was asked."""
    asked = []
    state = {"rows": []}

    def fake_rpc(fn, params):
        asked.append((fn, dict(params)))
        n = params["batch_size"]
        taken, state["rows"] = state["rows"][:n], state["rows"][n:]
        return taken

    monkeypatch.setattr(index_sweeper, "rpc", fake_rpc)
    return state, asked


@pytest.fixture
def driven(monkeypatch):
    seen = []
    monkeypatch.setattr(
        index_sweeper, "index_document", lambda d, **kw: seen.append((d, kw))
    )
    return seen


def test_each_claimed_document_is_re_driven(real_mode, claims, driven):
    state, _ = claims
    state["rows"] = [{"id": "d1"}, {"id": "d2"}]

    assert index_sweeper.sweep_once() == 2
    # claimed=True: the claim function already spent the attempt, so a second
    # claim inside index_document would double-count and halve the budget.
    assert driven == [("d1", {"claimed": True}), ("d2", {"claimed": True})]


def test_the_claim_carries_the_configured_bounds(real_mode, claims, driven):
    _, asked = claims

    index_sweeper.sweep_once()

    assert asked == [("claim_documents_for_indexing",
                      {"max_attempts": 3, "lease_seconds": 600, "batch_size": 1})]


def test_each_lease_starts_when_its_own_work_does(real_mode, claims, monkeypatch):
    """Review round 1: claiming ten at once started ten leases together, then
    indexed them one by one — so a slow batch could outlive the lease on its
    last documents, letting another instance or an admin force claim them
    mid-queue and spend a second attempt on a healthy document. One claim per
    document means no document ever waits on a running lease."""
    state, _ = claims
    state["rows"] = [{"id": "d1"}, {"id": "d2"}, {"id": "d3"}]
    order = []
    real_rpc = index_sweeper.rpc

    def tracing_rpc(fn, params):
        taken = real_rpc(fn, params)
        order.extend(f"claim:{r['id']}" for r in taken)
        return taken

    monkeypatch.setattr(index_sweeper, "rpc", tracing_rpc)
    monkeypatch.setattr(index_sweeper, "index_document",
                        lambda d, **kw: order.append(f"index:{d}"))

    assert index_sweeper.sweep_once() == 3
    assert order == ["claim:d1", "index:d1", "claim:d2", "index:d2",
                     "claim:d3", "index:d3"]


def test_a_sweep_stops_at_its_batch_size(real_mode, claims, driven, monkeypatch):
    state, asked = claims
    state["rows"] = [{"id": f"d{i}"} for i in range(25)]
    monkeypatch.setattr(index_sweeper, "BATCH_SIZE", 10)

    assert index_sweeper.sweep_once() == 10
    assert len(asked) == 10
    assert len(state["rows"]) == 15   # left for the next sweep


def test_a_claim_that_fails_mid_sweep_ends_the_sweep(real_mode, monkeypatch, driven):
    calls = []

    def flaky(fn, params):
        calls.append(1)
        if len(calls) == 1:
            return [{"id": "d1"}]
        raise RuntimeError("connection reset")

    monkeypatch.setattr(index_sweeper, "rpc", flaky)

    assert index_sweeper.sweep_once() == 1
    assert len(calls) == 2


def test_one_bad_document_does_not_abort_the_batch(real_mode, claims, monkeypatch):
    state, _ = claims
    state["rows"] = [{"id": "d1"}, {"id": "d2"}]
    seen = []

    def half_broken(doc_id, **kw):
        seen.append(doc_id)
        if doc_id == "d1":
            raise RuntimeError("boom")

    monkeypatch.setattr(index_sweeper, "index_document", half_broken)

    assert index_sweeper.sweep_once() == 1
    assert seen == ["d1", "d2"]


def test_a_failed_claim_is_a_quiet_zero(real_mode, monkeypatch, driven):
    """Before the migration runs, the RPC does not exist. That is a warning
    every interval, never a crash of the loop or of the app."""
    def missing(fn, params):
        raise RuntimeError("404 Could not find the function claim_documents_for_indexing")

    monkeypatch.setattr(index_sweeper, "rpc", missing)

    assert index_sweeper.sweep_once() == 0
    assert driven == []


def test_it_is_inert_outside_real_model_mode(monkeypatch, claims, driven):
    """Function-mode E2E must never sweep."""
    monkeypatch.setenv("SAPLING_MODEL_MODE", "function")
    _, asked = claims

    assert index_sweeper.sweep_once() == 0
    assert asked == []


@pytest.mark.parametrize("value", ["false", "0", "off", "no", " FALSE "])
def test_the_kill_switch(monkeypatch, real_mode, value):
    monkeypatch.setenv("INDEX_SWEEPER_ENABLED", value)
    assert index_sweeper.sweeper_enabled() is False


def test_it_is_on_by_default_in_real_mode(real_mode):
    """A queue nothing drains is the bug being fixed. Defaulting the drain off
    would repeat what happened to DBOS, which ADR 0011 leaves off everywhere."""
    assert index_sweeper.sweeper_enabled() is True


# ── lifecycle ───────────────────────────────────────────────────────────────


def test_start_and_stop(real_mode, monkeypatch):
    monkeypatch.setattr(index_sweeper, "sweep_once", lambda: 0)

    async def scenario():
        index_sweeper.start_sweeper()
        task = index_sweeper._task
        assert task is not None and not task.done()
        await index_sweeper.stop_sweeper()
        assert task.cancelled() or task.done()
        assert index_sweeper._task is None

    asyncio.run(scenario())


def test_start_is_a_noop_when_disabled(monkeypatch):
    monkeypatch.setenv("SAPLING_MODEL_MODE", "function")

    async def scenario():
        index_sweeper.start_sweeper()
        assert index_sweeper._task is None
        await index_sweeper.stop_sweeper()   # and stopping nothing is safe

    asyncio.run(scenario())


def test_the_loop_survives_a_sweep_that_raises(real_mode, monkeypatch):
    """One bad sweep must not end recovery for the life of the process."""
    calls = []

    def flaky():
        calls.append(1)
        if len(calls) == 1:
            raise RuntimeError("transient")
        return 0

    monkeypatch.setattr(index_sweeper, "sweep_once", flaky)
    monkeypatch.setattr(index_sweeper, "SWEEP_INTERVAL_SECONDS", 0)

    async def scenario():
        index_sweeper.start_sweeper()
        for _ in range(200):
            if len(calls) >= 2:
                break
            await asyncio.sleep(0.01)
        await index_sweeper.stop_sweeper()

    asyncio.run(scenario())
    assert len(calls) >= 2


def test_the_app_lifespan_starts_and_stops_the_sweeper():
    """Pin the wiring: a refactor that drops either call from `_lifespan`
    would otherwise fail no test and leave the queue undrained."""
    from fastapi.testclient import TestClient

    with (
        patch("main.start_sweeper") as start,
        patch("main.stop_sweeper", new=AsyncMock()) as stop,
        patch("main.ensure_bucket_exists", new=AsyncMock()),
    ):
        from main import app

        with TestClient(app):
            start.assert_called_once()
            stop.assert_not_called()
        stop.assert_awaited_once()
