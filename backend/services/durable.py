"""Optional durable-execution shim.

When `DBOS_ENABLED=true` AND the `dbos` package is importable AND
`DBOS_DATABASE_URL` is set in the env, this module exposes real DBOS
workflow + step decorators so an in-flight upload can survive a worker
crash and resume from the last checkpoint.

When any of those preconditions fail (the default state in this repo),
the decorators degrade to identity passthroughs that don't add anything
to the wrapped function. Code is callable in both modes; the only
difference is durability.

This lets us land the integration code in main, document the path in
ADR 0011, and let operators flip the flag once their DBOS Postgres
schema is provisioned — without making `dbos` a hard import.
"""

from __future__ import annotations

import logging
import os
from functools import wraps
from typing import Any, Awaitable, Callable, TypeVar

logger = logging.getLogger(__name__)

F = TypeVar("F", bound=Callable[..., Awaitable[Any]])


_ENABLED = os.getenv("DBOS_ENABLED", "false").lower() == "true"
_HAS_DBOS = False
_dbos_workflow = None
_dbos_step = None

if _ENABLED:
    try:
        from dbos import DBOS  # type: ignore[import-not-found]
        # DBOS init must be done by the application entrypoint; we just
        # capture the decorators here and trust that DBOS() was called
        # in main.py BEFORE any decorated function is invoked.
        _dbos_workflow = DBOS.workflow
        _dbos_step = DBOS.step
        _HAS_DBOS = True
    except Exception as e:  # ImportError or DBOS init failure
        logger.warning(
            "DBOS_ENABLED=true but DBOS could not be loaded (%s). "
            "Durable decorators will degrade to no-ops.",
            e,
        )


def is_durable() -> bool:
    """Returns True if real DBOS decorators are active for this process."""
    return _HAS_DBOS


def workflow(fn: F) -> F:
    """Mark a function as a durable workflow.

    When DBOS is active, each step inside the workflow is checkpointed
    and a worker crash mid-flight resumes from the last completed step
    on retry. When DBOS is inactive, this is a no-op decorator.
    """
    if _HAS_DBOS and _dbos_workflow is not None:
        return _dbos_workflow()(fn)  # type: ignore[no-any-return]

    @wraps(fn)
    async def passthrough(*args: Any, **kwargs: Any) -> Any:
        return await fn(*args, **kwargs)

    return passthrough  # type: ignore[return-value]


def step(fn: F) -> F:
    """Mark an async function as a single durable step inside a workflow.

    No-op when DBOS is inactive.
    """
    if _HAS_DBOS and _dbos_step is not None:
        return _dbos_step()(fn)  # type: ignore[no-any-return]

    @wraps(fn)
    async def passthrough(*args: Any, **kwargs: Any) -> Any:
        return await fn(*args, **kwargs)

    return passthrough  # type: ignore[return-value]
