"""Optional durable-execution shim (ADR 0011 / #154).

When ALL of the following hold:

  - DBOS_ENABLED=true
  - the `dbos` package is importable (backend/requirements-durable.txt,
    installed separately from requirements.txt/requirements.lock)
  - DBOS_DATABASE_URL is a non-empty Postgres connection string

this module exposes real DBOS workflow + step decorators, and
`workflow_id()` (below) lets a caller pin an invocation to a specific DBOS
workflow id. The product-level crash semantic this enables: a CLIENT RETRY
of the same logical operation (same idempotency key, e.g. `/upload/sync`'s
`X-Request-ID`) attaches to the SAME workflow instead of starting a new
one, resuming at the last completed step instead of re-running every
agent call. Nothing resumes for the ORIGINAL caller — their HTTP
connection is already gone once the worker crashes — but DBOS's own
background auto-recovery (`init_dbos()` -> `DBOS.launch()`, see below)
independently completes an abandoned in-flight workflow even without a
retry, and a later same-id retry receives THAT recorded result instead of
re-running the pipeline.

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

Fail-loud contract for init_dbos(): an explicit DBOS_ENABLED=true opt-in
must not degrade silently. The failure mode that matters most: if a
precondition above (import, DBOS_DATABASE_URL) already failed, the
decorators are ALREADY identity passthroughs by the time init_dbos() runs
(this module logged one WARNING at import time, nothing more) —
`@workflow`/`@step` code then runs and SUCCEEDS with zero durability, no
further signal, on routes that look durable in the source (X-Request-ID
idempotency, the decorations are present). init_dbos() now RAISES in that
case too, not just on a construct/launch failure — same posture as #174's
validate_config(). See init_dbos()'s own docstring for exactly which raises
when.

(This is a DIFFERENT failure mode from decorators going real with `DBOS()`
never constructed anywhere — that already fails LOUD on its own:
dbos/_core.py's `workflow_wrapper` raises `DBOSException("... invoked
before DBOS initialized")` on every such call, deterministically, verified
against dbos==2.28.0 at `dbos/_core.py:1369-1372`. That was the actual
state of every decorated call before #154 shipped this file's init_dbos()
— a deterministic exception (a 502 via routes/documents.py's exception
handling) on every call, not a silent no-op. See ADR 0011's #154 update.)
"""

from __future__ import annotations

import contextlib
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
# Set when `dbos` fails to import with DBOS_ENABLED=true. init_dbos() cites
# this in its RuntimeError so an operator sees WHY activation failed, not
# just THAT it did (Finding B / #154 review round).
_IMPORT_ERROR: str | None = None

if _ENABLED:
    if not _DATABASE_URL:
        logger.warning(
            "DBOS_ENABLED=true but DBOS_DATABASE_URL is not set. Durable "
            "decorators will degrade to passthroughs until a database URL "
            "is provided (see docs/decisions/0011-durable-execution-dbos.md). "
            "init_dbos() will raise at startup until this is fixed."
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
            _IMPORT_ERROR = str(e)
            logger.warning(
                "DBOS_ENABLED=true but DBOS could not be imported (%s). "
                "Durable decorators will degrade to passthroughs. "
                "init_dbos() will raise at startup until this is fixed.",
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


def workflow_id(wfid: str) -> "contextlib.AbstractContextManager[None]":
    """Pin `wfid` as the DBOS workflow id for the next workflow invocation
    started inside this `with` block (only the FIRST one started inside
    the block gets it — see `SetWorkflowID`'s own docstring).

    Why this matters: a caller that re-enters this context with the SAME
    `wfid` (e.g. a client retry presenting the same idempotency key)
    attaches to the SAME workflow row instead of starting a new one, and
    does not re-execute already-checkpointed `@step` calls inside it.
    Verified against the installed dbos==2.28.0:

      - `from dbos import SetWorkflowID` — re-exported at the top of
        `dbos/__init__.py` (`dbos/__init__.py:8`), defined at
        `dbos/_context.py:454`. A plain SYNC context manager (`__enter__`/
        `__exit__`, no `async with` needed): `__enter__` sets
        `ctx.id_assigned_for_next_workflow = wfid` on the ambient
        DBOSContext (`dbos/_context.py:471-485`), which
        `workflow_wrapper` (`dbos/_core.py`) reads when starting the next
        `@workflow`-decorated call.
      - Same-id reattach: `workflow_wrapper` inserts/updates the workflow's
        row keyed on `workflow_uuid` via an upsert
        (`dbos/_sys_db.py::_insert_workflow_status`, `dbos/_sys_db.py:718`,
        ON CONFLICT DO UPDATE). A plain (non-recovery, non-dequeue) call
        whose `workflow_uuid` already has a row does NOT re-run the
        workflow body — `should_execute` stays True only for the original
        inserting call (or a recovery/dequeue request); every other direct
        call instead gets `_deferred_workflow_result`, which awaits the
        existing workflow's recorded result (`dbos/_core.py:1452-1459`;
        the owner-mismatch check is `dbos/_sys_db.py:875-880`). This holds
        for BOTH a completed (SUCCESS) row — the recorded output returns
        immediately, no re-execution — and a still-PENDING one, which
        blocks until SOME execution finishes it (typically
        `DBOS.launch()`'s own background auto-recovery of PENDING rows for
        this executor — see `init_dbos()`) and records a result. Either
        way, already-checkpointed `@step` calls inside are never re-run.

    No-op (`contextlib.nullcontext()`) when `is_durable()` is False, so
    callers don't need to branch on the flag themselves.
    """
    if is_durable():
        from dbos import SetWorkflowID  # dbos/_context.py:454; dbos/__init__.py:8

        return SetWorkflowID(wfid)
    return contextlib.nullcontext()


def init_dbos() -> bool:
    """Construct and launch the DBOS runtime, once, from main.py's
    `_lifespan` (after the #174 secrets validation, before `yield`).

    Three outcomes:

    - DBOS_ENABLED unset/false (the default): no-op, returns False. Logs
      one INFO line. `@workflow`/`@step` stay identity passthroughs.
    - DBOS_ENABLED=true but `is_durable()` is False — a precondition
      failed at import time (`dbos` not importable, or DBOS_DATABASE_URL
      missing; this module already logged one WARNING and degraded the
      decorators to passthrough): RAISES `RuntimeError` naming exactly
      which precondition failed. Without this, an explicit opt-in would
      silently run with zero durability — routes look durable in the
      source (the `@workflow`/`@step` decorations are present) while every
      request quietly loses crash-resume, with no signal beyond the one
      WARNING line at boot. Same posture as #174's validate_config().
    - DBOS_ENABLED=true and `is_durable()` is True: constructs `DBOS` and
      calls `DBOS.launch()` (below). ANY exception here is logged and
      RE-RAISED too — same fail-loud posture, for the same reason.

    (Both RAISE paths above are silent-degradation guards new in this
    update. Neither is the same failure mode as a `@workflow`/`@step`
    call reaching a registry whose `DBOS()` was never constructed at all
    — that already fails loud on its own: dbos/_core.py's
    `workflow_wrapper` raises `DBOSException("... invoked before DBOS
    initialized")` (`dbos/_core.py:1369-1372`, verified against
    dbos==2.28.0) the instant such a call is made, surfaced as a 502 via
    routes/documents.py's exception handling. That was the actual state of
    every decorated call before #154 shipped this function — a
    deterministic exception on every call, not a no-op; see ADR 0011's
    #154 update.)

    When durable, this is the ONE place the `DBOS` singleton is
    constructed and `DBOS.launch()` is called:

      - Config: verified against dbos==2.28.0's `DBOSConfig` TypedDict
        (`dbos/_dbos_config.py`). `name` is the only required key
        (`translate_dbos_config_to_config_file` raises
        `DBOSInitializationError` without it). We set `system_database_url`
        to DBOS_DATABASE_URL — that is the checkpoint store our
        `@workflow`/`@step` decorators read/write. We deliberately do NOT
        set `database_url` (DEPRECATED — of the two, that is the ONLY one
        `DBOSConfig`'s own docstring marks that way) or
        `application_database_url` (current, NOT deprecated, but
        provisions a SEPARATE "application database" used only by
        `@DBOS.transaction`-decorated functions, which Sapling doesn't
        use): `dbos/_dbos_config.py::get_system_database_url` reads
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

    ANY exception while constructing/launching (below) is logged and
    RE-RAISED — the second of the two RAISE paths described above.
    """
    if not _ENABLED:
        logger.info("durable execution off — passthrough decorators")
        return False

    if not is_durable():
        # DBOS_ENABLED=true but a precondition already failed at import
        # time (see the module-level check above) — name exactly which one,
        # rather than degrading to the flag-off no-op. Fixes the silent-
        # degrade gap: previously this returned False here too, so an
        # explicit opt-in with a typo'd/missing DBOS_DATABASE_URL (or an
        # uninstalled `dbos`) would boot and serve requests looking durable
        # in the source while running with zero durability.
        if not _DATABASE_URL:
            raise RuntimeError(
                "DBOS_ENABLED=true but DBOS_DATABASE_URL is not set. Set "
                "DBOS_DATABASE_URL to a Postgres connection string, or "
                "unset DBOS_ENABLED to run without durability (see "
                "docs/decisions/0011-durable-execution-dbos.md)."
            )
        raise RuntimeError(
            f"DBOS_ENABLED=true but the `dbos` package could not be "
            f"imported ({_IMPORT_ERROR}). Install "
            f"backend/requirements-durable.txt, or unset DBOS_ENABLED to "
            f"run without durability."
        )

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
