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

    Must be called from a thread with no running event loop (the case for
    FastAPI sync handlers and direct unit-test calls under TestClient).
    """
    return asyncio.run(coro)
