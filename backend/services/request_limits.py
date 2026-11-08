"""Shared request-resource guards: per-key rate limiting and upload size bounds.

Factored for reuse across CPU/cost-heavy endpoints (OCR extraction, LLM).

Two stores for the same sliding-window limiter, chosen by the
``stateless_rate_limit`` flag (#117, resolved globally):

* ``off`` (default) -- per-process memory (``_rate_state``). Fine for one
  replica; with two, each one grants the full budget, so a student gets 2x.
* ``on`` -- the ``rate_limit_hits`` table, through the atomic
  ``claim_rate_limit(p_key, p_limit, p_window_sec)`` SQL function (migration
  ``*_stateless_rate_limit.sql``): one round trip that serializes on the key,
  counts the window, inserts the hit when under the limit and returns its id
  (the refund handle) or how long to wait. Every replica shares one budget.
  The call is bounded by ``CLAIM_TIMEOUT_S`` (not the client's 30 s). Any DB
  failure falls back to the in-memory store (a cost guard must not deny
  every student because the limiter's own table blipped) and marks the DB
  down for ``DB_DOWN_S``: inside that window every claim goes straight to
  memory without trying the DB, so an outage costs each process one bounded
  wait per window, not one per request. One warning per outage: the first
  answer after it re-arms the warning.

Sync callers (threadpool handlers) use :func:`claim_rate_limit` /
:func:`check_rate_limit`; an ``async def`` uses :func:`aclaim_rate_limit` /
:func:`acheck_rate_limit`, which never block the loop. :func:`refund_rate_limit`
is safe from either: a DB refund is handed to a background thread.
"""
import logging
import math
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from typing import NamedTuple, Optional, Union

import anyio
from fastapi import HTTPException, UploadFile

logger = logging.getLogger("sapling.request_limits")

FLAG_KEY = "stateless_rate_limit"
#: The SQL function the migration adds.
CLAIM_FN = "claim_rate_limit"
HITS_TABLE = "rate_limit_hits"

# In-memory sliding-window state, keyed by an arbitrary string (e.g.
# "ocr:<user_id>"). Process-local: the `stateless_rate_limit` flag moves it
# to Postgres for multi-replica deployments.
_rate_state: dict[str, list[float]] = {}


class DbSlot(NamedTuple):
    """A hit recorded in ``rate_limit_hits``: its row id is the refund handle."""

    hit_id: int


class RateLimitClaim(NamedTuple):
    """One call's outcome at the gate.

    `retry_after` is None when the call was allowed; `slot` is then the handle
    `refund_rate_limit` needs to give back THIS call's slot rather than
    whichever was recorded last: the exact timestamp recorded in memory, or a
    :class:`DbSlot` naming the recorded row.
    """

    retry_after: int | None
    slot: Union[float, DbSlot, None] = None


# ── In-memory store (flag off, and the fallback) ────────────────────────────


def _claim_memory(key: str, limit: int, window_sec: int) -> RateLimitClaim:
    now = time.time()
    bucket = [t for t in _rate_state.get(key, []) if now - t < window_sec]
    if len(bucket) >= limit:
        # Ceiling of the remaining window, capped at window_sec: on coarse
        # timers (Windows, ~15.6ms tick) `now` can equal `bucket[0]` exactly,
        # and int(remaining) + 1 would overshoot to window_sec + 1 (#346).
        # The min() cap additionally pins the ceiling when `now` reads BEFORE
        # bucket[0] (NTP backward step) — ceil alone would exceed the window.
        retry = min(window_sec, math.ceil(window_sec - (now - bucket[0])))
        _rate_state[key] = bucket
        return RateLimitClaim(retry_after=retry)
    bucket.append(now)
    _rate_state[key] = bucket
    return RateLimitClaim(retry_after=None, slot=now)


# ── Postgres store (flag on) ────────────────────────────────────────────────

#: Bound on one claim round trip. The limiter sits in front of the request it
#: guards, so a slow DB must cost that request at most this, not 30 s.
CLAIM_TIMEOUT_S = 1.5
#: After a failed claim, how long every claim skips the DB and uses memory.
DB_DOWN_S = 30.0

_state_lock = threading.Lock()
#: monotonic time until which the DB store counts as down (0 = try it).
_db_down_until = 0.0
#: Whether this outage has been logged; re-armed by the next DB answer.
_warned_fallback = False


def _db_down() -> bool:
    with _state_lock:
        return time.monotonic() < _db_down_until


def _db_failed(exc: BaseException) -> None:
    """Mark the DB store down for DB_DOWN_S and warn once per outage."""
    global _db_down_until, _warned_fallback
    with _state_lock:
        _db_down_until = time.monotonic() + DB_DOWN_S
        warn = not _warned_fallback
        _warned_fallback = True
    if warn:
        logger.warning("stateless_rate_limit: %s() failed (%s: %s); using the per-process "
                       "limiter for %.0f s at a time until it answers",
                       CLAIM_FN, type(exc).__name__, exc, DB_DOWN_S)


def _db_answered() -> None:
    """The DB store answered: clear the mark, and let the next outage warn."""
    global _db_down_until, _warned_fallback
    with _state_lock:
        recovered = _warned_fallback
        _db_down_until = 0.0
        _warned_fallback = False
    if recovered:
        logger.info("stateless_rate_limit: %s() answers again; back on the shared limiter",
                    CLAIM_FN)


def reset_db_state() -> None:
    """Forget any down mark and warning (tests)."""
    global _db_down_until, _warned_fallback
    with _state_lock:
        _db_down_until = 0.0
        _warned_fallback = False


def _parse_claim(rows, window_sec: int) -> Optional[RateLimitClaim]:
    row = rows[0] if isinstance(rows, list) and rows else rows
    if not isinstance(row, dict):
        return None
    hit_id = row.get("hit_id")
    if hit_id is not None:
        return RateLimitClaim(retry_after=None, slot=DbSlot(int(hit_id)))
    retry = row.get("retry_after")
    if retry is None:
        return None
    return RateLimitClaim(retry_after=max(1, min(window_sec, int(retry))))


def _params(key: str, limit: int, window_sec: int) -> dict:
    return {"p_key": key, "p_limit": int(limit), "p_window_sec": int(window_sec)}


def _settle(claim: Optional[RateLimitClaim]) -> Optional[RateLimitClaim]:
    if claim is None:
        _db_failed(ValueError("unexpected answer"))
    else:
        _db_answered()
    return claim


def _claim_db(key: str, limit: int, window_sec: int) -> Optional[RateLimitClaim]:
    from db.connection import rpc
    from db.scope import service_scope

    try:
        with service_scope():  # rate_limit_hits + its function are service-only
            rows = rpc(CLAIM_FN, _params(key, limit, window_sec), timeout=CLAIM_TIMEOUT_S)
        claim = _parse_claim(rows, window_sec)
    except Exception as exc:
        _db_failed(exc)
        return None
    return _settle(claim)


async def _aclaim_db(key: str, limit: int, window_sec: int) -> Optional[RateLimitClaim]:
    from db.async_connection import arpc
    from db.scope import service_scope

    try:
        with service_scope():  # one coroutine, no yield: reset in the same context
            rows = await arpc(CLAIM_FN, _params(key, limit, window_sec),
                              timeout=CLAIM_TIMEOUT_S)
        claim = _parse_claim(rows, window_sec)
    except Exception as exc:
        _db_failed(exc)
        return None
    return _settle(claim)


def _stateless() -> bool:
    try:
        from services.feature_flags import flag_on

        return flag_on(FLAG_KEY, None)
    except Exception:
        return False


async def _astateless() -> bool:
    """The flag without a blocking read on the loop: the cached snapshot when
    it can answer, else one hop to a worker thread."""
    try:
        from services.feature_flags import cached_explain

        res = cached_explain(FLAG_KEY, None)
    except Exception:
        res = None
    if res is not None:
        return res.variant == "on"
    return await anyio.to_thread.run_sync(_stateless)


# ── Public API ──────────────────────────────────────────────────────────────


def claim_rate_limit(key: str, *, limit: int, window_sec: int) -> RateLimitClaim:
    """Sliding-window per-key limiter that returns a refundable slot. Sync:
    with the flag on it is a PostgREST call, so never call it from an
    ``async def`` (use :func:`aclaim_rate_limit`)."""
    if not _db_down() and _stateless():
        claim = _claim_db(key, limit, window_sec)
        if claim is not None:
            return claim
    return _claim_memory(key, limit, window_sec)


async def aclaim_rate_limit(key: str, *, limit: int, window_sec: int) -> RateLimitClaim:
    """:func:`claim_rate_limit` for an ``async def``: never blocks the loop."""
    if not _db_down() and await _astateless():
        claim = await _aclaim_db(key, limit, window_sec)
        if claim is not None:
            return claim
    return _claim_memory(key, limit, window_sec)


def check_rate_limit(key: str, *, limit: int, window_sec: int) -> int | None:
    """Sliding-window per-key limiter.

    Returns None if the call is allowed (and records it), else the number of
    seconds until the next call would be allowed.
    """
    return claim_rate_limit(key, limit=limit, window_sec=window_sec).retry_after


async def acheck_rate_limit(key: str, *, limit: int, window_sec: int) -> int | None:
    return (await aclaim_rate_limit(key, limit=limit, window_sec=window_sec)).retry_after


_refund_pool: Optional[ThreadPoolExecutor] = None
_refund_pool_lock = threading.Lock()


def _refund_db(key: str, hit_id: int) -> None:
    from db.connection import table
    from db.scope import service_scope

    try:
        with service_scope():
            table(HITS_TABLE).delete(filters={"id": f"eq.{hit_id}", "key": f"eq.{key}"})
    except Exception:
        logger.warning("stateless_rate_limit: refund of hit %s failed", hit_id, exc_info=True)


def _submit_refund(key: str, hit_id: int) -> None:
    """Run the DB refund on a small background pool, so a refund from an
    ``async def`` never blocks the loop. A seam: tests run it inline."""
    global _refund_pool
    with _refund_pool_lock:
        if _refund_pool is None:
            _refund_pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="rate-refund")
        pool = _refund_pool
    pool.submit(_refund_db, key, hit_id)


def refund_rate_limit(key: str, slot) -> None:
    """Give back the slot `claim_rate_limit` recorded for one call.

    For guards that must claim BEFORE doing the expensive work (so a
    concurrent burst can't slip past the gate) but shouldn't charge the
    caller when that work fails for reasons they didn't cause.

    Removes THAT call's slot (#760). Popping the newest instead refunded
    a concurrent request's slot — one still running, which then stayed
    uncharged — while the failed call's own stamp kept counting. A slot that
    has already aged out of the window (or was never recorded) is a no-op;
    two equal timestamps are interchangeable, so removing either is exact.
    A :class:`DbSlot` deletes its own row, off the calling thread.
    """
    if slot is None:
        return
    if isinstance(slot, DbSlot):
        try:
            _submit_refund(key, slot.hit_id)
        except Exception:
            logger.warning("stateless_rate_limit: refund not submitted", exc_info=True)
        return
    bucket = _rate_state.get(key)
    if not bucket:
        return
    try:
        bucket.remove(slot)
    except ValueError:
        pass


async def read_within_limit(upload: UploadFile, max_bytes: int) -> bytes:
    """Read at most ``max_bytes`` (+1 to detect overflow) from an UploadFile so
    an oversize upload can't be pulled fully into memory before we reject it.

    Raises 413 if the upload exceeds ``max_bytes``.
    """
    data = await upload.read(max_bytes + 1)
    if len(data) > max_bytes:
        raise HTTPException(
            status_code=413,
            detail=f"File too large. Maximum size is {max_bytes // (1024 * 1024)} MB.",
        )
    return data
