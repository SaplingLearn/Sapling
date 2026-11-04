"""Copies the rich sample dataset onto local Google accounts (#715).

On a developer's own stack, a fresh Google sign-in lands on an empty account.
`python -m db.seed_local_rich --owner-user-id` fills it, but only if someone
remembers to run it between signing in and looking around. This loop runs that
same seed (`seed_local_rich.seed_owner`) for them, one account at a time in a
worker thread, for every account that is:

- a real Google sign-in: `users.id` is `user_<google id>` (fixture accounts are
  rich-*/seed-*/it-* and are never touched) and `google_id` is set (an
  ensure_user_exists stub is not a sign-in yet);
- live: `deleted_at` is null;
- not yet onboarded: `onboarding_completed` is false.

The seed completes onboarding as its LAST write, so that one column is the
whole "already seeded" story: a finished seed is never redone (a sample course
the developer dropped stays dropped across restarts), an account whose seed
stopped midway is still a candidate and is finished on a later pass (the seed
is idempotent), and an account that was already onboarded — a developer's own
account with their own data — is left alone; the CLI is its way in.

LOCAL ONLY. It starts only when `seed_helpers.is_local_backend()` holds (APP_ENV
local|test AND a loopback SUPABASE_URL) — the exact check the seed CLI's guard
uses — so staging and production never run it, and GET /api/auth/local-seed
404s there.

The loop idles on a slow poll (LOCAL_SEED_WATCH_INTERVAL_SECONDS, default
30s): sign-in is picked up at once regardless, because every `pending` answer
from the status route — the post-sign-in routing asks, then the hold screen
polls every 2s — `nudge()`s the sleeping loop awake.

A failing account is recorded (the status route reports it) and retried on an
exponential backoff; it never stops the others or the loop.
"""
from __future__ import annotations

import asyncio
import contextlib
import logging
import math
import os
import threading
import time
from dataclasses import dataclass

from db.connection import table
from db.seed_helpers import is_local_backend

logger = logging.getLogger(__name__)

DEFAULT_WATCH_INTERVAL_SECONDS = 30.0


def _interval_from_env() -> float:
    """LOCAL_SEED_WATCH_INTERVAL_SECONDS, or the default (with a warning) when it
    is not a positive finite number. Never raises: main.py imports this module
    in every environment, so a typo must not stop a backend from booting."""
    raw = (os.getenv("LOCAL_SEED_WATCH_INTERVAL_SECONDS") or "").strip()
    if not raw:
        return DEFAULT_WATCH_INTERVAL_SECONDS
    try:
        value = float(raw)
    except ValueError:
        value = math.nan
    if not math.isfinite(value) or value <= 0:
        logger.warning(
            "[local-seed] ignoring LOCAL_SEED_WATCH_INTERVAL_SECONDS=%r (not a positive "
            "number of seconds); using %ss", raw, DEFAULT_WATCH_INTERVAL_SECONDS,
        )
        return DEFAULT_WATCH_INTERVAL_SECONDS
    return value


WATCH_INTERVAL_SECONDS = _interval_from_env()
#: First retry delay after a failed seed; doubles per failure up to the cap.
BACKOFF_BASE_SECONDS = 10.0
BACKOFF_MAX_SECONDS = 300.0
#: Google OAuth accounts only (routes/auth.py builds `user_<google id>`).
OAUTH_ID_PREFIX = "user_"
_MAX_ERROR_CHARS = 500


@dataclass
class _Failure:
    error: str
    attempts: int
    retry_at: float


_task: asyncio.Task | None = None
_wake: asyncio.Event | None = None
#: One scan at a time: the seed shares h.counts and is built for one writer.
_scan_lock = threading.Lock()
#: Guards the state below, which the status route reads from another thread.
_state_lock = threading.Lock()
_seeding: str | None = None
_failures: dict[str, _Failure] = {}


def _reset() -> None:
    """Forget all in-process state (tests; equivalent to a restart)."""
    global _seeding
    with _state_lock:
        _failures.clear()
        _seeding = None


def watcher_enabled() -> bool:
    """Only on a developer's local stack; read live, per call."""
    return is_local_backend()


def is_oauth_account(user_id: object) -> bool:
    return isinstance(user_id, str) and user_id.startswith(OAUTH_ID_PREFIX)


#: The candidate rule, as PostgREST filters (see the module docstring). The
#: `like` is only a pre-filter — `_` is a LIKE wildcard — so is_oauth_account
#: re-checks the prefix in Python.
_CANDIDATE_FILTERS = {
    "id": f"like.{OAUTH_ID_PREFIX}*",
    "google_id": "not.is.null",
    "deleted_at": "is.null",
    "onboarding_completed": "eq.false",
}


def _seed_one(owner: dict, now: float) -> bool:
    global _seeding
    from db import seed_local_rich

    user_id = owner["id"]
    with _state_lock:
        _seeding = user_id
    try:
        created = seed_local_rich.seed_owner(owner, report=False)
    except Exception as exc:
        with _state_lock:
            previous = _failures.get(user_id)
            attempts = (previous.attempts if previous else 0) + 1
            delay = min(BACKOFF_BASE_SECONDS * 2 ** (attempts - 1), BACKOFF_MAX_SECONDS)
            _failures[user_id] = _Failure(
                error=f"{type(exc).__name__}: {exc}"[:_MAX_ERROR_CHARS],
                attempts=attempts,
                retry_at=now + delay,
            )
        logger.exception(
            "[local-seed] could not seed sample data onto %s (attempt %d; retrying in %.0fs)",
            user_id, attempts, delay,
        )
        return False
    finally:
        with _state_lock:
            _seeding = None
    with _state_lock:
        _failures.pop(user_id, None)
    logger.info("[local-seed] seeded sample data onto %s (%d rows created)", user_id, created)
    return True


def scan_once(now: float | None = None) -> int:
    """Seed every unseeded local Google account. Returns how many were seeded.

    Synchronous — PostgREST calls are — so the loop runs it in a thread. Never
    raises: a failed listing ends the pass with a warning, and one account's
    failure never costs the rest. A scan already running makes this a no-op.
    """
    if not watcher_enabled():
        return 0
    if not _scan_lock.acquire(blocking=False):
        return 0
    try:
        now = time.monotonic() if now is None else now
        try:
            users = table("users").select(
                "id,onboarding_completed", filters=_CANDIDATE_FILTERS,
            ) or []
        except Exception:
            logger.warning("[local-seed] could not list local accounts", exc_info=True)
            return 0
        with _state_lock:
            due = [
                u for u in users
                if is_oauth_account(u.get("id"))
                and (u["id"] not in _failures or _failures[u["id"]].retry_at <= now)
            ]
        return sum(_seed_one(u, now) for u in due)
    finally:
        _scan_lock.release()


def status_for(user_id: str) -> dict | None:
    """{"state": pending|seeding|ready|failed, "error"?} for one account, or
    None when it is not a live Google account (missing, an ensure_user_exists
    stub, soft-deleted): nothing the watcher would ever seed, so nothing to
    wait for. `ready` is simply "onboarded" — by the seed, or by hand — and it
    outranks a recorded failure, which "Continue anyway" can leave behind.
    """
    with _state_lock:
        if _seeding == user_id:
            return {"state": "seeding"}
    rows = table("users").select(
        "id,google_id,deleted_at,onboarding_completed",
        filters={"id": f"eq.{user_id}"}, limit=1,
    ) or []
    if not rows or rows[0].get("google_id") is None or rows[0].get("deleted_at") is not None:
        return None
    if rows[0].get("onboarding_completed"):
        return {"state": "ready"}
    with _state_lock:
        failure = _failures.get(user_id)
    if failure is not None:
        return {"state": "failed", "error": failure.error}
    return {"state": "pending"}


def nudge() -> None:
    """Wake the loop now rather than at the next interval. Event-loop thread only."""
    if _wake is not None:
        _wake.set()


async def _loop(wake: asyncio.Event) -> None:
    while True:
        # Sleep first, as the index sweeper does; a nudge cuts the wait short.
        with contextlib.suppress(asyncio.TimeoutError, TimeoutError):
            await asyncio.wait_for(wake.wait(), timeout=WATCH_INTERVAL_SECONDS)
        wake.clear()
        try:
            await asyncio.to_thread(scan_once)
        except Exception:
            # scan_once does not raise by contract; this is the backstop that
            # keeps one surprise from ending the watcher for the process's life.
            logger.exception("[local-seed] scan raised; the loop continues")


def start_watcher() -> None:
    """Start the loop on the running event loop. Called from the app lifespan."""
    global _task, _wake
    if not watcher_enabled():
        logger.info("[local-seed] watcher not started (not a local backend)")
        return
    if _task is None or _task.done():
        _wake = asyncio.Event()
        _task = asyncio.get_running_loop().create_task(_loop(_wake), name="local-seed-watcher")
        logger.info(
            "[local-seed] watcher started: new local Google accounts get the sample "
            "dataset (every %ss)", WATCH_INTERVAL_SECONDS,
        )


async def stop_watcher() -> None:
    """Cancel the loop. Safe when it never started."""
    global _task, _wake
    task, _task = _task, None
    _wake = None
    if task is None:
        return
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task
