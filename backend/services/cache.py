"""Optional cross-worker cache backed by Redis (#97).

Design goals:
- **Off by default.** With no ``REDIS_URL`` set, every call is a cheap no-op and
  the app behaves exactly as before. Provision Redis + set ``REDIS_URL`` to turn
  it on — no code change.
- **Never fails the request.** Any connection/redis error logs a warning and
  callers get a clean miss (``None``) and fall through to the real computation.
  A failed connect is retried after a capped exponential backoff (#771), so a
  Redis that was down at boot is picked up once it is back.
- **Mockable** like ``db/connection.py`` — tests patch ``services.cache.enabled``
  / ``get_str`` / ``set_str`` (or set ``REDIS_URL`` against a fake).

Scope: currently the OCR/extraction content-cache. The Gemini-response cache the
original #97 described became obsolete with the agent migration (every LLM call
is now a Pydantic AI agent; the raw-call seam it would have fronted was deleted
in ADR 0024); this wrapper is the reusable seam if that need returns.
"""

from __future__ import annotations

import logging
import os
import threading
import time

logger = logging.getLogger(__name__)

_client = None            # lazily-built redis client, or None when disabled
_initialized = False      # settled: a live client, or no REDIS_URL (off by default)
#: A failed connect is NOT settled (#771): it used to latch the cache off for
#: the life of the process. It is retried after a backoff that doubles per
#: consecutive failure, up to _RETRY_MAX_S; until then callers get a clean miss
#: without re-trying the connect on the request path.
_retry_at = 0.0
_failures = 0
_RETRY_BASE_S = 5.0
_RETRY_MAX_S = 300.0
#: One caller builds the client; concurrent first callers wait for its answer
#: instead of each seeing a half-initialized "disabled" state.
_init_lock = threading.Lock()


def _redis_url() -> str:
    return os.getenv("REDIS_URL", "").strip()


def _get_client():
    """Lazily build (and memoize) the redis client, or None if unavailable.

    Read at call time so tests can set REDIS_URL then call reset(). No
    REDIS_URL settles the cache off. A failed connect (missing dep,
    unreachable server) is a miss now and a retry after a backoff — never a
    permanent off (#771). Thread-safe: the first callers wait for one build."""
    global _client, _initialized, _retry_at, _failures
    if _initialized:
        return _client
    with _init_lock:
        if _initialized:
            return _client
        if time.monotonic() < _retry_at:
            return None
        url = _redis_url()
        if not url:
            _client = None
            _initialized = True
            return None
        try:
            import redis  # optional dependency — only imported when REDIS_URL is set
            client = redis.Redis.from_url(
                url, socket_connect_timeout=2, socket_timeout=2
            )
            client.ping()
        except Exception as e:  # missing redis dep, bad URL, unreachable server, …
            _failures += 1
            backoff = min(_RETRY_BASE_S * 2 ** (_failures - 1), _RETRY_MAX_S)
            _retry_at = time.monotonic() + backoff
            logger.warning(
                "Redis cache unavailable (%s); continuing without it, retrying in %.0fs",
                e, backoff,
            )
            return None
        _client = client
        _failures = 0
        _initialized = True
        logger.info("Redis cache enabled")
        return _client


def reset() -> None:
    """Drop the memoized client so the next call re-reads REDIS_URL. For tests."""
    global _client, _initialized, _retry_at, _failures
    _client = None
    _initialized = False
    _retry_at = 0.0
    _failures = 0


def enabled() -> bool:
    """True only when a Redis client is configured and reachable. Callers use
    this to skip building a cache key (e.g. hashing a large file) when the cache
    is off, so there's zero overhead in the no-Redis default."""
    return _get_client() is not None


def get_str(key: str) -> str | None:
    client = _get_client()
    if client is None:
        return None
    try:
        raw = client.get(key)
    except Exception as e:
        logger.warning("cache get failed (%s): %s", key, e)
        return None
    if raw is None:
        return None
    return raw.decode("utf-8") if isinstance(raw, bytes) else str(raw)


def set_str(key: str, value: str, ttl_seconds: int | None = None) -> None:
    client = _get_client()
    if client is None:
        return
    try:
        client.set(key, value.encode("utf-8"), ex=ttl_seconds)
    except Exception as e:
        logger.warning("cache set failed (%s): %s", key, e)
