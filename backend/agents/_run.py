"""Sync→async bridge for driving Pydantic AI agents from sync route handlers.

Some routes (study guide, social overview, the admin health probe) are plain
sync `def` handlers: their surrounding data access is synchronous httpx
`table()` calls that must not run on an event loop. FastAPI executes sync
handlers in a worker thread that has no running event loop, so spinning up a
fresh loop with ``asyncio.run`` to await a single agent run is safe here.

Async handlers should keep using ``await agent.run(...)`` directly; this helper
exists only for the synchronous seam.
"""

from __future__ import annotations

import asyncio
from typing import Any, Coroutine, TypeVar

T = TypeVar("T")


def run_agent_sync(coro: Coroutine[Any, Any, T]) -> T:
    """Run an agent coroutine to completion from synchronous code.

    Intended for FastAPI sync ``def`` handlers, which FastAPI runs in a worker
    thread with no event loop — there ``asyncio.run`` drives the agent.

    Some sync helpers are ALSO reached from *async* handlers via a sync call
    chain (e.g. ``_legacy_chat`` -> ``apply_graph_update`` ->
    ``update_course_context`` -> ``_generate_summary_with_gemini`` -> here,
    and the same shape from the async upload pipeline). A loop is already running on
    that thread, so ``asyncio.run`` can't be used and — critically — we must not
    block the event loop on an LLM round-trip. The old code let ``asyncio.run``
    raise and leaked a "coroutine 'run' was never awaited" warning. Instead,
    close ``coro`` (no warning) and raise a clear error so the (already
    ``try/except``-guarded) caller degrades gracefully; the async path should
    ``await`` the agent directly rather than route through this seam.
    """
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        # No loop on this thread: the sanctioned synchronous seam.
        return asyncio.run(coro)
    # A loop is already running: we can't drive the coroutine here without
    # blocking it. Close it to avoid a "never awaited" warning, then signal
    # the misuse clearly for the caller to handle.
    coro.close()
    raise RuntimeError(
        "run_agent_sync() was called from a running event loop; async callers "
        "must await the agent directly."
    )
