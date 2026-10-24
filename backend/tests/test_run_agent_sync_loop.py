# backend/tests/test_run_agent_sync_loop.py
"""Regression: run_agent_sync's event-loop handling.

`run_agent_sync` drives agents via ``asyncio.run`` from sync route handlers.
Called from a thread that already has a running loop (an async handler's sync
call chain, e.g. _legacy_chat -> apply_graph_update -> update_course_context
-> _generate_summary_with_gemini), it must never
(a) blindly ``asyncio.run`` — that raises opaquely — nor (b) leak the
coroutine it was handed (a "never awaited" warning). Cross-loop client safety
itself lives in `_LoopSafeGoogleModel` (see test_loop_safe_google_model.py).
"""
import asyncio
import inspect

import pytest

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
