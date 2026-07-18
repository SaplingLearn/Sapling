# backend/tests/test_run_agent_sync_loop.py
"""Regression: run_agent_sync's loop handling + fresh-client agent runs.

The module-level google client is unsafe across event loops: a connection it
pooled on one loop trips `RuntimeError: Event loop is closed` when reused after
that loop is gone. `run_agent_sync` drives agents on throwaway per-request
loops (`asyncio.run`), so agents run through it must use a FRESH client, and it
must never (a) blindly `asyncio.run` from inside a running loop or (b) leak the
coroutine it was handed.
"""
import asyncio
import inspect

import pytest

from agents._providers import _provider, fresh_model_for, model_name_for
from agents._run import run_agent_sync


def test_runs_coroutine_when_no_loop():
    async def work():
        return 7

    assert run_agent_sync(work()) == 7


def test_from_running_loop_raises_and_closes_coro():
    """Called from an async context it must not asyncio.run (that would raise
    opaquely) nor leak the coroutine (a "never awaited" warning); it closes the
    coroutine and raises a clear error the caller can degrade on."""
    async def scenario():
        async def agent_call():
            return 1

        coro = agent_call()
        with pytest.raises(RuntimeError, match="running event loop"):
            run_agent_sync(coro)
        # Closed, not abandoned — so no "coroutine was never awaited" warning.
        assert inspect.getcoroutinestate(coro) == inspect.CORO_CLOSED

    asyncio.run(scenario())


def test_fresh_model_for_uses_a_fresh_provider():
    m = fresh_model_for("concept_describe")
    assert m.provider is not _provider
    assert m.model_name == model_name_for("concept_describe")
    # Distinct client each call — no cross-loop connection reuse.
    assert fresh_model_for("concept_describe").provider is not m.provider
