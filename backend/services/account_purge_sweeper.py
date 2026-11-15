"""The daily account purge (owner decision 2026-11-14), as a lifespan task.

Once a day each API process runs one pass (`run_pass`). It first removes the
credentials any soft-deleted account still holds (`sweep_leftover_credentials`:
the self-delete removes them at once, so a row is left only when that delete
and its after-response retries failed); that runs whatever `account_purge`
says, since the credentials were due at the delete itself, behind its own
`credential_sweep` flag (seeded on; SAPLING_FLAG_CREDENTIAL_SWEEP=off is the
kill switch), on one replica at a time (a `services/pg_lease.py` lease, under
`stateless_locks`). Then, when the
`account_purge` flag is
on (resolved globally, at the start of every pass, so turning it off stops
the next pass without a restart) it claims accounts deleted more than
`account_purge.GRACE_DAYS` ago through `claim_accounts_for_purge` — an atomic
`UPDATE ... RETURNING` over `FOR UPDATE SKIP LOCKED` with a lease
(20261114192918_account_purge.sql) — and purges each one
(`services/account_purge.py::purge_account`). Several workers or replicas
can run passes at once: the claim hands each account to one of them, and the
purge itself is idempotent, so a pass that dies mid-account leaves it to be
claimed again once the lease runs out.

The first pass runs `FIRST_PASS_DELAY_SECONDS` after boot (not a day later:
deploys restart every process, and a 24 h first sleep could postpone the
purge indefinitely), then every `PASS_INTERVAL_SECONDS`.

Like services/index_sweeper.py it is never started under pytest or outside
real model mode (the E2E/function-mode stacks), and a pass never raises.
Each purge is recorded as an `account.purge` audit event with counts only —
no account id, no content.
"""
from __future__ import annotations

import asyncio
import contextlib
import logging
import sys
import threading

from db.connection import rpc
from services import account_credentials, account_purge, events_service, pg_lease
from services.feature_flags import flag_on

logger = logging.getLogger(__name__)

FLAG_KEY = "account_purge"
#: The leftover-credential sweep's own switch (seeded "on" by
#: 20261115005314_credential_sweep_flag.sql): it deletes rows and revokes tokens
#: at Google every pass, so it can be stopped without a deploy.
CREDENTIAL_SWEEP_FLAG = "credential_sweep"
CLAIM_RPC = "claim_accounts_for_purge"
FIRST_PASS_DELAY_SECONDS = 15 * 60
PASS_INTERVAL_SECONDS = 24 * 60 * 60
#: A claim outlives a crashed pass by this long before another may take it.
LEASE_SECONDS = 60 * 60
#: Most accounts one pass purges (one claim each, so a lease starts when its
#: account's purge does).
BATCH_SIZE = 50
#: The cross-replica lease one credential sweep holds (services/pg_lease.py),
#: renewed while it runs and released when it ends: another replica's pass
#: that starts meanwhile skips its sweep.
CREDENTIAL_SWEEP_LEASE_KEY = "account_purge:credential_sweep"
CREDENTIAL_SWEEP_LEASE_SECONDS = 10 * 60

_task: asyncio.Task | None = None
_stop: threading.Event | None = None


def sweeper_enabled() -> bool:
    """Whether this process runs passes at all (the flag is read per pass)."""
    if "pytest" in sys.modules:
        return False
    from agents._providers import model_mode  # lazy: pulls in pydantic-ai

    return model_mode() == "real"


def _claim_one() -> str | None:
    claimed = rpc(CLAIM_RPC, {
        "grace_days": account_purge.GRACE_DAYS,
        "lease_seconds": LEASE_SECONDS,
        "batch_size": 1,
    })
    return claimed[0]["id"] if claimed else None


def _failed(exc: Exception) -> None:
    logger.error("[account-purge] a purge stopped (%s); it is retried on a later pass",
                 type(exc).__name__, exc_info=True)
    events_service.log_event(
        "account.purge", category="audit",
        payload={"outcome": "incomplete", "error": type(exc).__name__},
    )


def purge_once(stop: threading.Event | None = None) -> int:
    """One pass: purge up to BATCH_SIZE due accounts. Returns how many were
    purged. A no-op while the flag is off. Never raises."""
    try:
        if not flag_on(FLAG_KEY, None):
            return 0
    except Exception:
        logger.warning("[account-purge] could not read the %s flag; pass skipped", FLAG_KEY)
        return 0
    purged = 0
    for _ in range(BATCH_SIZE):
        if stop is not None and stop.is_set():
            break
        try:
            user_id = _claim_one()
        except Exception:
            logger.warning("[account-purge] could not claim an account", exc_info=True)
            break
        if user_id is None:
            break
        try:
            account_purge.purge_account(user_id)
            purged += 1
        except Exception as exc:  # PurgeRefused, AccountPurgeIncomplete, anything
            _failed(exc)
    if purged:
        logger.info("[account-purge] pass purged %d account(s)", purged)
    return purged


def sweep_leftover_credentials(stop: threading.Event | None = None) -> int:
    """Remove (and revoke at Google) the credentials of every soft-deleted
    account that still holds some, at any age. Returns how many accounts were
    cleaned. A failure is logged with the account id and retried on the next
    pass. A stop request (shutdown) ends it before the next account. Never
    raises.

    One replica sweeps at a time: the sweep holds the
    CREDENTIAL_SWEEP_LEASE_KEY lease (`stateless_locks`), and a pass that
    finds it held elsewhere skips its sweep. With that flag off, or the lease
    store unreachable, every replica sweeps, as before: the sweep is
    idempotent, so that costs duplicate work, never harm.

    A no-op (nothing read, no lease taken) while the `credential_sweep` flag
    is off, or cannot be read."""
    try:
        if not flag_on(CREDENTIAL_SWEEP_FLAG, None):
            return 0
    except Exception:
        logger.warning("[account-purge] could not read the %s flag; sweep skipped", CREDENTIAL_SWEEP_FLAG)
        return 0
    try:
        with pg_lease.lease(CREDENTIAL_SWEEP_LEASE_KEY, CREDENTIAL_SWEEP_LEASE_SECONDS) as held:
            if not held:
                logger.info("[account-purge] another replica is sweeping leftover credentials; skipped")
                return 0
            return _sweep_leftover_credentials(stop)
    except Exception:  # the lease's own release is best effort; belt and braces
        logger.warning("[account-purge] the leftover-credential sweep stopped", exc_info=True)
        return 0


def _sweep_leftover_credentials(stop: threading.Event | None) -> int:
    try:
        owners = account_credentials.deleted_accounts_with_credentials()
    except Exception:
        logger.warning("[account-purge] could not look for leftover credentials", exc_info=True)
        return 0
    cleaned = 0
    for user_id in owners:
        if stop is not None and stop.is_set():
            break
        try:
            account_credentials.revoke_google_tokens(account_credentials.remove_credentials(user_id))
            cleaned += 1
        except Exception as exc:
            logger.error("[account-purge] could not remove the leftover credentials of deleted"
                         " account %s (%s); retried on the next pass", user_id, type(exc).__name__)
    if cleaned:
        logger.info("[account-purge] removed the leftover credentials of %d deleted account(s)", cleaned)
    return cleaned


def run_pass(stop: threading.Event | None = None) -> int:
    """One daily pass: the leftover credentials, then the purge (flag-gated).
    Returns how many accounts were purged. Stops early on a stop request.
    Never raises."""
    if stop is not None and stop.is_set():
        return 0
    sweep_leftover_credentials(stop)
    return purge_once(stop)


async def _loop(stop: threading.Event) -> None:
    delay = FIRST_PASS_DELAY_SECONDS
    while True:
        await asyncio.sleep(delay)
        delay = PASS_INTERVAL_SECONDS
        try:
            await asyncio.to_thread(run_pass, stop)
        except Exception:
            logger.exception("[account-purge] pass raised; the loop continues")


def start_purge_sweeper() -> None:
    """Start the daily loop on the running event loop (app lifespan)."""
    global _task, _stop
    if not sweeper_enabled():
        logger.info("[account-purge] sweeper not started (pytest, or not real model mode)")
        return
    if _task is None or _task.done():
        _stop = threading.Event()
        _task = asyncio.get_running_loop().create_task(_loop(_stop), name="account-purge")
        logger.info("[account-purge] sweeper started (first pass in %ss, then daily)",
                    FIRST_PASS_DELAY_SECONDS)


async def stop_purge_sweeper() -> None:
    """Stop claiming, then cancel the loop. Safe when it never started."""
    global _task, _stop
    if _stop is not None:
        _stop.set()
    _stop = None
    task, _task = _task, None
    if task is None:
        return
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task
