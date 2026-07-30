"""Optional durable-execution shim (ADR 0011 / #154).

When ALL of the following hold:

  - DBOS_ENABLED=true
  - the `dbos` package is importable (backend/requirements-durable.txt,
    installed separately from requirements.txt/requirements.lock)
  - DBOS_DATABASE_URL is a non-empty Postgres connection string

this module exposes real DBOS workflow + step decorators so an in-flight
upload can survive a worker crash and resume from the last checkpoint.

When any precondition fails (the default state in this repo — the flag is
off), the decorators degrade to identity passthroughs that don't add
anything to the wrapped function. Code is callable in both modes; the only
difference is durability. If the flag is on but the `dbos` import fails, or
DBOS_DATABASE_URL is missing, we log a warning and degrade to passthrough
rather than crash at import time — this module is imported by
agents/document.py, which is imported by main.py, so an import-time raise
here would take the whole app down before validate_config() even runs.

Construction + launch is a SEPARATE step from decoration, deliberately:
`init_dbos()` (called from main.py's `_lifespan`, after the #174 secrets
validation) constructs the `DBOS` singleton and calls `DBOS.launch()`. That
split is required by import order, not just style — `agents.document`
applies `@workflow`/`@step` to `process_document`/`_step_*` at IMPORT time,
which happens well before the FastAPI lifespan runs `init_dbos()`. Verified
against the installed dbos==2.28.0 (backend/requirements-durable.txt) that
this decorate-before-construct-before-launch order is exactly the supported
pattern: `DBOS.workflow()`/`DBOS.step()` register onto a lazily-created
global `DBOSRegistry` (`dbos/_dbos.py::_get_or_create_dbos_registry`, no
`DBOS` instance required), and `DBOS.__init__` picks up that SAME registry
in `self._registry = _get_or_create_dbos_registry()` (`dbos/_dbos.py:417`)
whenever the instance is later constructed — so registrations recorded
before construction are not lost. If a future dbos major version drops this
registry indirection, decorating agents.document at import time would need
to move to something init_dbos() runs directly; the fact that our decorator
capture (below) and DBOS() construction (in init_dbos) are already two
separate steps rather than one makes that migration a local change, not a
redesign.

Fail-loud contract for init_dbos(): if the operator has explicitly set
DBOS_ENABLED=true and anything raises while constructing/launching DBOS, we
RAISE rather than silently falling back to passthrough — same posture as
#174's validate_config() in the lifespan. A silent no-op would betray an
explicit opt-in: routes would look durable (X-Request-ID idempotency, the
`@workflow`/`@step` decorations are present in the source) while silently
running with zero crash-resume, and nobody would know until the next
incident.
"""

from __future__ import annotations

import logging
import os
from functools import wraps
from typing import Any, Awaitable, Callable, TypeVar

logger = logging.getLogger(__name__)

F = TypeVar("F", bound=Callable[..., Awaitable[Any]])


_ENABLED = os.getenv("DBOS_ENABLED", "false").lower() == "true"
_DATABASE_URL = os.getenv("DBOS_DATABASE_URL", "").strip()
_HAS_DBOS = False
_dbos_workflow = None
_dbos_step = None

if _ENABLED:
    if not _DATABASE_URL:
        logger.warning(
            "DBOS_ENABLED=true but DBOS_DATABASE_URL is not set. Durable "
            "decorators will degrade to passthroughs until a database URL "
            "is provided (see docs/decisions/0011-durable-execution-dbos.md)."
        )
    else:
        try:
            from dbos import DBOS  # type: ignore[import-not-found]

            # Only capture the decorator factories here. Constructing the
            # DBOS() singleton and calling DBOS.launch() happens later, in
            # init_dbos() — see the module docstring for why that split is
            # required (agents.document decorates at import time, well
            # before main.py's lifespan runs).
            _dbos_workflow = DBOS.workflow
            _dbos_step = DBOS.step
            _HAS_DBOS = True
        except Exception as e:  # ImportError or anything else at import
            logger.warning(
                "DBOS_ENABLED=true but DBOS could not be imported (%s). "
                "Durable decorators will degrade to passthroughs.",
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


def init_dbos() -> bool:
    """Construct and launch the DBOS runtime, once, from main.py's
    `_lifespan` (after the #174 secrets validation, before `yield`).

    No-op returning False when `is_durable()` is False (the default —
    DBOS_ENABLED unset, `dbos` not importable, or DBOS_DATABASE_URL
    missing). Logs one INFO line either way so the active mode is visible
    in app logs (and, since #119, in Logfire).

    When durable, this is the ONE place the `DBOS` singleton is
    constructed and `DBOS.launch()` is called:

      - Config: verified against dbos==2.28.0's `DBOSConfig` TypedDict
        (`dbos/_dbos_config.py`). `name` is the only required key
        (`translate_dbos_config_to_config_file` raises
        `DBOSInitializationError` without it). We set `system_database_url`
        to DBOS_DATABASE_URL — that is the checkpoint store our
        `@workflow`/`@step` decorators read/write. We deliberately do NOT
        set the (deprecated) `database_url` / `application_database_url`
        keys: those provision a SEPARATE "application database" used only
        by `@DBOS.transaction`-decorated functions, which Sapling doesn't
        use (`dbos/_dbos_config.py::get_system_database_url` reads
        `system_database_url` first and only falls back to deriving a
        sys-db name from `database_url` when `system_database_url` is
        absent — so passing ours directly is both sufficient and the
        documented default path).
      - Migrations: `DBOS.launch()` runs the system-database migrations
        ITSELF (`dbos/_dbos.py::DBOS._launch` calls
        `self._sys_db.run_migrations()` before doing anything else) — no
        separate `dbos migrate` CLI step is required for normal operation.
        (`dbos.run_dbos_database_migrations()` exists as a standalone
        helper for the case where the app's DB role lacks DDL grants and
        migrations must be pre-provisioned by a different role — not our
        setup; Supabase-adjacent Postgres roles here have DDL rights.)
      - Recovery: `DBOS.launch()` ALSO auto-recovers PENDING workflows for
        this executor on startup (`DBOS._launch` queries
        `self._sys_db.get_pending_workflows(...)` and resumes each one on
        a background thread) — no explicit recovery call is needed on the
        happy path. See tests/test_dbos_resume.py for a crash/resume proof
        against a real Postgres.

    Fail-loud: ANY exception while constructing/launching is logged and
    RE-RAISED. The operator explicitly set DBOS_ENABLED=true; a caught-and-
    ignored failure here would leave `@workflow`/`@step` decorated code
    running un-launched (undefined behavior per agents/document.py's
    docstring) with no signal until something breaks downstream. Same
    posture as #174's validate_config().
    """
    if not is_durable():
        logger.info("durable execution off — passthrough decorators")
        return False

    try:
        from dbos import DBOS, DBOSConfig  # type: ignore[import-not-found]

        config: DBOSConfig = {
            "name": "sapling",
            "system_database_url": _DATABASE_URL,
        }
        DBOS(config=config)
        DBOS.launch()
    except Exception:
        logger.exception(
            "DBOS_ENABLED=true but DBOS failed to construct/launch. Failing "
            "startup loudly rather than serving requests with un-launched "
            "durable decorators."
        )
        raise

    logger.info("durable execution ACTIVE (DBOS launched)")
    return True


def shutdown_dbos() -> None:
    """Tear down the DBOS runtime from main.py's `_lifespan` shutdown path.

    No-op when not durable. Never raises — shutdown must not be the thing
    that turns a clean deploy rollover into a crash loop; any failure here
    is logged instead.
    """
    if not is_durable():
        return
    try:
        from dbos import DBOS  # type: ignore[import-not-found]

        DBOS.destroy()
    except Exception:
        logger.exception("Error shutting down DBOS; continuing shutdown.")
