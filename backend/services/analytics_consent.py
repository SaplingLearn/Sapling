"""Who third-party analytics may name: the one consent check the PostHog
worker (ADR 0028) runs before a user id reaches PostHog.

Called ONLY from the PostHog send worker thread (``posthog_client``), never on
a request path — so it may block on its read, and no event-loop thread ever
waits on it.

A user id may be sent only when ALL of these hold:

* it has the shape of an id this app issues (``users.id`` is TEXT —
  ``user_<google id>`` in production, ``seed-user-demo`` / ``rich-*`` in the
  seeded lanes, not a UUID) and is not a placeholder a caller passes when it
  has no actor (``anonymous``, ``backfill``, ...). Those are
  :data:`Consent.NO_USER` — "there is no actor here", not "this actor said no";
* a ``users`` row exists for it and is not soft-deleted (``deleted_at``) —
  PostHog creates a person for any unseen ``distinct_id``, so an event after
  account deletion would re-create the person the deletion just removed;
* the student has not opted out (``user_settings.analytics_opt_out``). A
  missing ``user_settings`` row is the column default: not opted out.

**Fail closed.** A lookup that errors, a row that does not answer the
question, or an answer invalidated while it was being read, is a "no".

**Caching.** One read per user per :data:`_TTL_S` per process, not one per
event. Not ``functools.lru_cache``: an lru entry never expires, and a toggle
flipped through ANOTHER process (a second replica) must still take effect in
bounded time. The invalidation story (CLAUDE.md's rule) is two-part:

* :func:`clear_analytics_consent_cache` — every mutator in this process calls
  it: the settings PATCH (``analytics_opt_out``) and account deletion. Any
  clear bumps one counter, and a read that was in flight across a clear does
  not store its (possibly stale) answer; it is re-read;
* the TTL bounds how long any OTHER process can act on a stale "yes".

The autouse ``_clear_lru_caches`` fixture in ``tests/conftest.py`` clears it
between tests.
"""

from __future__ import annotations

import logging
import re
import threading
import time
from enum import Enum

logger = logging.getLogger("sapling.analytics_consent")


class Consent(Enum):
    ALLOWED = "allowed"   # a real, live user who has not opted out
    DENIED = "denied"     # opted out, deleted, unknown, or unreadable
    NO_USER = "no_user"   # no actor (None or a placeholder id)


#: Placeholder ids callers pass when there is no real actor. Compared
#: case-insensitively. Not exhaustive by design: anything else that is not a
#: live ``users`` row is DENIED by the lookup, which is the safe direction.
_PLACEHOLDER_IDS = frozenset({
    "anonymous", "anon", "backfill", "system", "unknown", "none", "null",
    "undefined", "guest",
})

#: The shape of a ``users.id`` this app issues. Deliberately loose (a
#: pre-filter that saves a lookup, not the gate — the lookup is the gate).
_ID_SHAPE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_\-]{0,127}$")

_TTL_S = 60.0
#: A failed lookup is retried sooner than a real answer expires, but not on
#: every event (a DB outage must not turn every event into a round trip).
_FAILURE_TTL_S = 10.0
_MAX_ENTRIES = 10_000

# uid -> (expires_at, answer)
_cache: dict[str, tuple[float, Consent]] = {}
# Bumped by every clear; a read stores its answer only if unchanged.
_clears = 0
_lock = threading.Lock()


def is_placeholder(user_id: object) -> bool:
    """True for None and for ids that cannot be a real ``users.id``."""
    if not isinstance(user_id, str):
        return True
    uid = user_id.strip()
    return not uid or uid.lower() in _PLACEHOLDER_IDS or not _ID_SHAPE.match(uid)


def consent_for(user_id: object) -> Consent:
    """Whether ``user_id`` may be named to third-party analytics.

    May block on a DB read — call it only from the PostHog worker thread.
    Never raises.
    """
    if is_placeholder(user_id):
        return Consent.NO_USER
    uid = str(user_id).strip()
    with _lock:
        hit = _cache.get(uid)
    if hit is not None and hit[0] > time.monotonic():
        return hit[1]
    # A clear that lands mid-read means the answer may be stale: read again
    # (once); if it is still racing, fail closed.
    for _ in range(2):
        with _lock:
            started = _clears
        try:
            answer, ttl = _lookup(uid), _TTL_S
        except Exception as exc:
            logger.warning(
                "analytics consent lookup failed (%s); not sending", type(exc).__name__,
            )
            answer, ttl = Consent.DENIED, _FAILURE_TTL_S
        with _lock:
            if _clears != started:
                continue
            if len(_cache) >= _MAX_ENTRIES and uid not in _cache:
                _cache.pop(next(iter(_cache)))
            _cache[uid] = (time.monotonic() + ttl, answer)
        return answer
    return Consent.DENIED


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
    """Drop one user's cached answer (or all), and invalidate any read in
    flight. Called by every mutator."""
    global _clears
    with _lock:
        _clears += 1
        if user_id is None:
            _cache.clear()
        else:
            _cache.pop(str(user_id).strip(), None)
