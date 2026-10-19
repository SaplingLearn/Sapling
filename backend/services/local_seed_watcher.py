"""Copies the rich sample dataset onto local Google accounts (#715).

On a developer's own stack, a fresh Google sign-in lands on an empty account.
`python -m db.seed_local_rich --owner-user-id` fills it, but only if someone
remembers to run it between signing in and looking around. This loop runs that
same seed (`seed_local_rich.seed_owner`) for them: every few seconds it lists
the real Google accounts — `users.id` is `user_<google id>`; fixture accounts
are rich-*/seed-*/it-* and are never touched — and seeds each one that does
not have the sample data yet, one at a time, in a worker thread.

LOCAL ONLY. It starts only when `seed_helpers.is_local_backend()` holds (APP_ENV
local|test AND a loopback SUPABASE_URL) — the exact check the seed CLI's guard
uses — so staging and production never run it, and GET /api/auth/local-seed
404s there.

"Already seeded" is read off the data, not a new column: the owner seed's copy
of one sample enrollment (`owner_seed_marker_id`, deterministic) exists AND
`users.onboarding_completed` is true. The enrollment is written early and
onboarding is completed last, so an account whose seed stopped midway reads as
unseeded and is finished on a later pass. In-process, an account seeded by this
process is remembered by (id, created_at): the marker can be absent for good
(a pre-existing enrollment in the sample offering keeps its own id), and that
must cost one idempotent re-run per restart, never one every pass — while an
account deleted and re-created under the same Google id is a new account.

A failing account is recorded (the status route reports it) and retried on an
exponential backoff; it never stops the others or the loop.
"""
from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import threading
import time
from dataclasses import dataclass

from db.connection import table
from db.seed_helpers import is_local_backend

logger = logging.getLogger(__name__)

WATCH_INTERVAL_SECONDS = float(os.getenv("LOCAL_SEED_WATCH_INTERVAL_SECONDS", "2"))
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
_seeded: dict[str, str | None] = {}      # user id -> created_at it was seeded at
_seeding: str | None = None
_failures: dict[str, _Failure] = {}


def _reset() -> None:
    """Forget all in-process state (tests; equivalent to a restart)."""
    global _seeding
    with _state_lock:
        _seeded.clear()
        _failures.clear()
        _seeding = None


def watcher_enabled() -> bool:
    """Only on a developer's local stack; read live, per call."""
    return is_local_backend()


def is_oauth_account(user_id: object) -> bool:
    return isinstance(user_id, str) and user_id.startswith(OAUTH_ID_PREFIX)


def _seeded_in_db(users: list[dict]) -> set[str]:
    """Which of these accounts already hold a completed owner seed."""
    from db.seed_local_rich import owner_seed_marker_id

    markers = {
        owner_seed_marker_id(u["id"]): u["id"] for u in users if u.get("onboarding_completed")
    }
    if not markers:
        return set()
    rows = table("enrollments").select("id", filters={"id": f"in.({','.join(markers)})"}) or []
    return {markers[row["id"]] for row in rows if row.get("id") in markers}


def _remember_seeded(users: list[dict]) -> None:
    with _state_lock:
        for user in users:
            _seeded[user["id"]] = user.get("created_at")
            _failures.pop(user["id"], None)


def _known_seeded(user: dict) -> bool:
    return user["id"] in _seeded and _seeded[user["id"]] == user.get("created_at")


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
    _remember_seeded([owner])
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
                "id,onboarding_completed,created_at",
                filters={"id": f"like.{OAUTH_ID_PREFIX}*"},
            ) or []
        except Exception:
            logger.warning("[local-seed] could not list local accounts", exc_info=True)
            return 0
        with _state_lock:
            due = [
                u for u in users
                if is_oauth_account(u.get("id"))
                and not _known_seeded(u)
                and (u["id"] not in _failures or _failures[u["id"]].retry_at <= now)
            ]
            # A failed account is re-seeded outright: its marker may predate the failure.
            fresh = [u for u in due if u["id"] not in _failures]
        if not due:
            return 0
        try:
            done = _seeded_in_db(fresh)
        except Exception:
            logger.warning("[local-seed] could not check which accounts are seeded", exc_info=True)
            return 0
        _remember_seeded([u for u in fresh if u["id"] in done])
        return sum(_seed_one(u, now) for u in due if u["id"] not in done)
    finally:
        _scan_lock.release()


def status_for(user_id: str) -> dict:
    """{"state": pending|seeding|ready|failed, "error"?} for one account."""
    with _state_lock:
        if _seeding == user_id:
            return {"state": "seeding"}
        failure = _failures.get(user_id)
        if failure is not None:
            return {"state": "failed", "error": failure.error}
    rows = table("users").select(
        "id,onboarding_completed,created_at", filters={"id": f"eq.{user_id}"}, limit=1,
    ) or []
    if not rows:
        return {"state": "pending"}
    with _state_lock:
        if _known_seeded(rows[0]):
            return {"state": "ready"}
    if _seeded_in_db(rows):
        _remember_seeded(rows)
        return {"state": "ready"}
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
