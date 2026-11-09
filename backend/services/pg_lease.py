"""Cross-replica leases in Postgres, behind the ``stateless_locks`` flag (#117).

Some guards in this app are per-process: the study-guide single-flight
(``routes/study_guide.py``), the admin account-operation slot
(``services/account_ops_lock.py``) and the consumed-OAuth-nonce set
(``routes/auth.py``). With two API replicas each process only sees its own
half. This module is the one primitive that closes the gap: a lease row in
``app_leases``, claimed, renewed and released through the atomic
``claim_lease`` / ``renew_lease`` / ``release_lease`` SQL functions (migration
``*_app_leases.sql``).

The callers keep their in-process lock as the FIRST layer and take a lease
here as the second, so with the flag off nothing changes at all:

* ``off`` (default) -- no DB call; every lease is granted at once (the
  caller's in-process lock is the whole guard, exactly as before).
* ``on`` -- one bounded ``claim_lease`` round trip (``CLAIM_TIMEOUT_S``, not
  the client's 30 s). A lease is held for ``ttl_s`` and, while a ``with``
  body runs, renewed every ``ttl_s / 3`` so a slow body never loses it; a
  crashed process's lease simply expires. A renewal only extends a row this
  acquisition still holds (it never inserts one), and the body's exit stops
  and joins the renewer before releasing, so a release can never be undone
  by a renewal still in flight. Release deletes the row only while this
  acquisition still holds it.
* DB failure (or a pre-migration 404) -- the lease is GRANTED (fail open to
  the in-process layer: these guard double-submits, they are not
  authorization) and the store is marked down for ``DB_DOWN_S``: inside that
  window no lease call tries the DB, so an outage costs each process one
  bounded wait per window. One warning per outage; the first answer after it
  re-arms the warning. Same pattern as ``services/request_limits.py``.

Keys are caller-chosen strings of at most 300 characters. A key derived from
secret or user-supplied data must go through :func:`hashed_key` (never store a
raw OAuth nonce).

The API is sync (:func:`lease`, :func:`consume_once`, :func:`try_claim`):
every caller runs in the threadpool. There are no async twins; an
``async def`` caller would have to add them.
"""
from __future__ import annotations

import contextlib
import hashlib
import logging
import os
import socket
import threading
import time
import uuid
from collections.abc import Iterator
from typing import Optional


logger = logging.getLogger("sapling.pg_lease")

FLAG_KEY = "stateless_locks"
#: The SQL functions the migration adds.
CLAIM_FN = "claim_lease"
RENEW_FN = "renew_lease"
RELEASE_FN = "release_lease"

#: Bound on one lease round trip.
CLAIM_TIMEOUT_S = 1.5
#: After a failed call, how long every lease skips the DB.
DB_DOWN_S = 30.0
#: The SQL function refuses TTLs outside [1, 86400] seconds.
MAX_TTL_S = 86_400
#: Floor on the renewal interval (ttl/3); tests shrink it.
RENEW_MIN_S = 1.0
#: How long the body's exit waits for an in-flight renewal before releasing:
#: one bounded round trip, plus slack.
RENEW_JOIN_S = CLAIM_TIMEOUT_S + 0.5

_HOST = f"{socket.gethostname()[:60]}:{os.getpid()}"

_state_lock = threading.Lock()
_db_down_until = 0.0
_warned = False


def hashed_key(prefix: str, *parts: object) -> str:
    """``<prefix>:<sha256 of the parts>``: a bounded key that never stores the
    parts themselves (an OAuth nonce, a long id tuple)."""
    digest = hashlib.sha256("\x1f".join(str(p) for p in parts).encode()).hexdigest()
    return f"{prefix}:{digest}"


def new_holder() -> str:
    """An opaque token naming ONE acquisition (host:pid:random)."""
    return f"{_HOST}:{uuid.uuid4().hex[:16]}"


def _ttl(ttl_s: float) -> int:
    return max(1, min(MAX_TTL_S, int(round(ttl_s))))


# ── down-state (one warning per outage) ─────────────────────────────────────


def _db_down() -> bool:
    with _state_lock:
        return time.monotonic() < _db_down_until


def _db_failed(exc: BaseException) -> None:
    global _db_down_until, _warned
    with _state_lock:
        _db_down_until = time.monotonic() + DB_DOWN_S
        warn = not _warned
        _warned = True
    if warn:
        logger.warning("stateless_locks: %s() failed (%s: %s); using the in-process locks "
                       "alone for %.0f s at a time until it answers",
                       CLAIM_FN, type(exc).__name__, exc, DB_DOWN_S)


def _db_answered() -> None:
    global _db_down_until, _warned
    with _state_lock:
        recovered = _warned
        _db_down_until = 0.0
        _warned = False
    if recovered:
        logger.info("stateless_locks: %s() answers again; back on Postgres leases", CLAIM_FN)


def reset_db_state() -> None:
    """Forget any down mark and warning (tests)."""
    global _db_down_until, _warned
    with _state_lock:
        _db_down_until = 0.0
        _warned = False


# ── flag ────────────────────────────────────────────────────────────────────


def _enabled() -> bool:
    try:
        from services.feature_flags import flag_on

        return flag_on(FLAG_KEY, None)
    except Exception:
        return False


# ── the two round trips ─────────────────────────────────────────────────────


def _as_bool(answer) -> Optional[bool]:
    """PostgREST returns a scalar function's value bare (``true``); accept a
    one-row/one-column shape too. None = not an answer."""
    if isinstance(answer, list):
        answer = answer[0] if answer else None
    if isinstance(answer, dict) and len(answer) == 1:
        answer = next(iter(answer.values()))
    return answer if isinstance(answer, bool) else None


def _settle(answer) -> Optional[bool]:
    got = _as_bool(answer)
    if got is None:
        _db_failed(ValueError(f"unexpected answer {type(answer).__name__}"))
    else:
        _db_answered()
    return got


def _claim_params(key: str, holder: str, ttl_s: float) -> dict:
    return {"p_key": key, "p_holder": holder, "p_ttl_sec": _ttl(ttl_s)}


def _claim_db(key: str, holder: str, ttl_s: float) -> Optional[bool]:
    """True = held, False = someone else holds it, None = no answer."""
    from db.connection import rpc
    from db.scope import service_scope

    try:
        with service_scope():  # app_leases + its functions are service-only
            answer = rpc(CLAIM_FN, _claim_params(key, holder, ttl_s), timeout=CLAIM_TIMEOUT_S)
    except Exception as exc:
        _db_failed(exc)
        return None
    return _settle(answer)


def _renew_db(key: str, holder: str, ttl_s: float) -> Optional[bool]:
    """True = extended, False = this holder no longer holds it (released,
    expired and taken over), None = no answer. Never creates a row."""
    from db.connection import rpc
    from db.scope import service_scope

    try:
        with service_scope():
            answer = rpc(RENEW_FN, _claim_params(key, holder, ttl_s), timeout=CLAIM_TIMEOUT_S)
    except Exception as exc:
        _db_failed(exc)
        return None
    return _settle(answer)


def _release_db(key: str, holder: str) -> None:
    """Best effort: a release that fails leaves the lease to expire."""
    from db.connection import rpc
    from db.scope import service_scope

    try:
        with service_scope():
            rpc(RELEASE_FN, {"p_key": key, "p_holder": holder}, timeout=CLAIM_TIMEOUT_S)
    except Exception:
        logger.warning("stateless_locks: release of %s failed; it expires on its own",
                       key.split(":", 1)[0], exc_info=True)


# ── public API ──────────────────────────────────────────────────────────────


def try_claim(key: str, ttl_s: float, holder: str) -> Optional[bool]:
    """One claim (or renewal, for the same ``holder``). True = held, False =
    another holder's lease is live, None = the store is off or unavailable
    (the caller's in-process lock is then the whole guard)."""
    if _db_down() or not _enabled():
        return None
    return _claim_db(key, holder, ttl_s)


def _wait_for(claim, deadline: float, poll_s: float, sleep) -> Optional[bool]:
    got = claim()
    while got is False and time.monotonic() < deadline:
        sleep(min(poll_s, max(0.0, deadline - time.monotonic())))
        got = claim()
    return got


class _Renewer:
    """Extends a held lease every ttl/3 on a daemon thread until stopped."""

    def __init__(self, key: str, ttl_s: float, holder: str):
        self._key, self._ttl, self._holder = key, ttl_s, holder
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True,
                                        name="pg-lease-renew")
        self._thread.start()

    def _run(self) -> None:
        while not self._stop.wait(max(RENEW_MIN_S, self._ttl / 3)):
            if _renew_db(self._key, self._holder, self._ttl) is False:
                if self._stop.is_set():
                    return  # the body finished while this renewal ran
                logger.warning("stateless_locks: lost the lease on %s mid-run",
                               self._key.split(":", 1)[0])
                return

    def stop(self) -> None:
        """Stop renewing and wait (bounded) for a renewal already in flight,
        so the release that follows is the last word on the row."""
        self._stop.set()
        self._thread.join(RENEW_JOIN_S)


@contextlib.contextmanager
def lease(key: str, ttl_s: float, *, wait_s: float = 0.0, poll_s: float = 0.5,
          renew: bool = True) -> Iterator[bool]:
    """Hold the lease on ``key`` for the ``with`` body.

    Yields True when this caller may proceed as the holder: the lease was
    claimed, or the store is off / unavailable (the in-process layer stands
    alone). Yields False when another holder kept it for ``wait_s`` (polled
    every ``poll_s``); the caller decides what that means (409, read the
    cache, proceed anyway). Released on exit however the body ends.
    """
    holder = new_holder()
    got = _wait_for(lambda: try_claim(key, ttl_s, holder),
                    time.monotonic() + max(0.0, wait_s), poll_s, time.sleep)
    if not got:
        yield got is None
        return
    renewer = _Renewer(key, ttl_s, holder) if renew else None
    try:
        yield True
    finally:
        if renewer is not None:
            renewer.stop()
        _release_db(key, holder)


def consume_once(key: str, ttl_s: float) -> Optional[bool]:
    """Mark ``key`` used for ``ttl_s`` across replicas: a lease that is never
    released. True the first time, False when it was already consumed (and
    has not expired), None when the store is off or unavailable."""
    return try_claim(key, ttl_s, new_holder())
