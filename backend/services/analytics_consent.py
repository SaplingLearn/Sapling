"""Who third-party analytics may name: the one consent check the PostHog seam
(ADR 0028) runs before a user id reaches PostHog, as an event's
``distinct_id`` or an AI span's ``posthog.distinct_id``.

A user id may be sent only when ALL of these hold:

* it has the shape of an id this app issues (``users.id`` is TEXT —
  ``user_<google id>`` in production, ``seed-user-demo`` / ``rich-*`` in the
  seeded lanes, not a UUID) and is not a placeholder a caller passes when it
  has no actor (``anonymous``, ``backfill``, ...). Those are reported as
  :data:`NO_USER` — "there is no actor here", not "this actor said no";
* a ``users`` row exists for it and is not soft-deleted (``deleted_at``) —
  PostHog creates a person for any unseen ``distinct_id``, so an event after
  account deletion would re-create the person the deletion just removed;
* the student has not opted out (``user_settings.analytics_opt_out``). A
  missing ``user_settings`` row is the column default: not opted out.

**Fail closed.** A lookup that errors, a row that does not answer the
question, an answer not yet known, or one invalidated while it was being
read, is a "no". Analytics is the thing that may be lost, never consent.

**Never blocks an event loop.** The read is a synchronous PostgREST call. On a
thread running an asyncio loop (async routes, the async 500 handler,
RequestIDMiddleware, agent runs) a cache miss does NOT read: it answers
DENIED now and warms the entry on a small worker pool, so the next event is
answered from cache. Threads without a loop (sync handlers in the threadpool,
the index sweeper, scripts) may block, and read inline. :func:`warm` lets a
caller start the read before it needs the answer (the agent-run boundary does,
so the answer is ready by the time the run's spans end).

**Caching.** Mirroring runs on every ``log_event``; a DB read per event is not
acceptable. Answers are cached per process for :data:`_TTL_S` seconds, keyed
on the user id, and an entry used past half its life is refreshed in the
background, so an active user's entry never goes cold. This is not
``functools.lru_cache`` because an lru entry never expires, and a toggle
flipped through ANOTHER process (a second replica) must still take effect in
bounded time — CLAUDE.md's rule is "never cache without a clear invalidation
story", and here that story is two-part:

* :func:`clear_analytics_consent_cache` — every mutator in this process calls
  it: the settings PATCH (``analytics_opt_out``) and account deletion. It
  bumps a per-user generation, and a read that began before the bump never
  stores its (possibly stale) answer;
* the TTL bounds how long any OTHER process can act on a stale "yes".

The autouse ``_clear_lru_caches`` fixture in ``tests/conftest.py`` clears it
between tests.
"""

from __future__ import annotations

import asyncio
import logging
import re
import threading
import time
from concurrent.futures import Future, ThreadPoolExecutor, wait
from enum import Enum

logger = logging.getLogger("sapling.analytics_consent")


class Consent(Enum):
    ALLOWED = "allowed"   # a real, live user who has not opted out
    DENIED = "denied"     # opted out, deleted, unknown, unreadable, or not yet known
    NO_USER = "no_user"   # no actor (None or a placeholder id)


#: Placeholder ids callers pass when there is no real actor. Compared
#: case-insensitively. Not exhaustive by design: anything else that is not a
#: live ``users`` row is DENIED by the lookup, which is the safe direction.
_PLACEHOLDER_IDS = frozenset({
    "anonymous", "anon", "backfill", "system", "unknown", "none", "null",
    "undefined", "guest",
})

#: The shape of a ``users.id`` this app issues. Deliberately loose (it is a
#: pre-filter that saves a lookup, not the gate — the lookup is the gate).
_ID_SHAPE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_\-]{0,127}$")

#: Public: account deletion schedules its second person delete after this
#: (plus a margin), because another process may act on a "yes" this old.
TTL_S = 60.0
_TTL_S = TTL_S
#: A failed lookup is retried sooner than a real answer expires, but not on
#: every event (a DB outage must not turn every log_event into a round trip).
_FAILURE_TTL_S = 10.0
_MAX_ENTRIES = 10_000

# uid -> (stored_at, expires_at, answer)
_cache: dict[str, tuple[float, float, Consent]] = {}
# Invalidation generations: per user, plus an epoch for clear-all.
_generation: dict[str, int] = {}
_epoch = 0
_in_flight: dict[str, Future] = {}
_lock = threading.Lock()
_pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="analytics-consent")


def is_placeholder(user_id: object) -> bool:
    """True for None and for ids that cannot be a real ``users.id``."""
    if not isinstance(user_id, str):
        return True
    uid = user_id.strip()
    return not uid or uid.lower() in _PLACEHOLDER_IDS or not _ID_SHAPE.match(uid)


def _on_event_loop() -> bool:
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return False
    return True


def consent_for(user_id: object) -> Consent:
    """Whether ``user_id`` may be named to third-party analytics.

    Never raises, and never blocks a thread that is running an event loop
    (a miss there is DENIED now + a background read).
    """
    if is_placeholder(user_id):
        return Consent.NO_USER
    uid = str(user_id).strip()
    now = time.monotonic()
    with _lock:
        hit = _cache.get(uid)
    if hit is not None and hit[1] > now:
        stored_at, expires_at, answer = hit
        if now - stored_at > (expires_at - stored_at) / 2:
            _refresh_in_background(uid)  # keep an active user's entry warm
        return answer
    if _on_event_loop():
        _refresh_in_background(uid)
        return Consent.DENIED
    return _read_and_store(uid)


def warm(user_id: object) -> None:
    """Start reading ``user_id``'s answer in the background if it is not
    cached. Non-blocking; a no-op for placeholders."""
    if is_placeholder(user_id):
        return
    uid = str(user_id).strip()
    with _lock:
        hit = _cache.get(uid)
    if hit is None or hit[1] <= time.monotonic():
        _refresh_in_background(uid)


def _refresh_in_background(uid: str) -> None:
    with _lock:
        if uid in _in_flight:
            return
        try:
            future = _pool.submit(_read_and_store, uid)
        except RuntimeError:  # pragma: no cover - interpreter shutdown
            return
        _in_flight[uid] = future
    future.add_done_callback(lambda _f, uid=uid: _forget_in_flight(uid, _f))


def _forget_in_flight(uid: str, future: Future) -> None:
    with _lock:
        if _in_flight.get(uid) is future:
            _in_flight.pop(uid, None)


def _read_and_store(uid: str) -> Consent:
    """The blocking read. Stores the answer only if no invalidation landed
    while it was in flight; if one did, the answer may be stale — DENIED."""
    with _lock:
        started = (_epoch, _generation.get(uid, 0))
    try:
        answer = _lookup(uid)
        ttl = _TTL_S
    except Exception as exc:
        logger.warning(
            "analytics consent lookup failed (%s); not sending", type(exc).__name__,
        )
        answer, ttl = Consent.DENIED, _FAILURE_TTL_S
    now = time.monotonic()
    with _lock:
        if (_epoch, _generation.get(uid, 0)) != started:
            return Consent.DENIED
        if len(_cache) >= _MAX_ENTRIES and uid not in _cache:
            _cache.pop(next(iter(_cache)))
        _cache[uid] = (now, now + ttl, answer)
    return answer


def _lookup(user_id: str) -> Consent:
    """One PostgREST round trip: the users row with its settings embedded
    (``user_settings.user_id`` is a FK to ``users.id``)."""
    from db.connection import table

    rows = table("users").select(
        "id,deleted_at,user_settings(analytics_opt_out)",
        filters={"id": f"eq.{user_id}"},
        limit=1,
    )
    if not rows:
        return Consent.DENIED  # not a user this app knows
    row = rows[0]
    if row.get("deleted_at"):
        return Consent.DENIED
    settings = row.get("user_settings")
    if isinstance(settings, list):  # PostgREST may embed 1:1 as a list
        settings = settings[0] if settings else None
    if settings is None:
        return Consent.ALLOWED  # no settings row = the column default (false)
    # NOT NULL in the schema; anything but an explicit False fails closed.
    return Consent.ALLOWED if settings.get("analytics_opt_out") is False else Consent.DENIED


def clear_analytics_consent_cache(user_id: str | None = None) -> None:
    """Drop one user's cached answer (or all), and invalidate any read of it
    already in flight. Called by every mutator."""
    global _epoch
    with _lock:
        if user_id is None:
            _epoch += 1
            _cache.clear()
        else:
            uid = str(user_id).strip()
            _generation[uid] = _generation.get(uid, 0) + 1
            _cache.pop(uid, None)


def drain_for_tests(timeout: float = 5.0) -> None:
    """Wait for background reads to finish. Test-only."""
    with _lock:
        futures = list(_in_flight.values())
    if futures:
        wait(futures, timeout=timeout)
