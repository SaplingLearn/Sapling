"""Optional cross-worker cache backed by Redis (#97).

Design goals:
- **Off by default.** With no ``REDIS_URL`` set, every call is a cheap no-op and
  the app behaves exactly as before. Provision Redis + set ``REDIS_URL`` to turn
  it on — no code change.
- **Never fails the request.** Any connection/redis error disables the cache and
  logs a warning; callers always get a clean miss (``None``) and fall through to
  the real computation.
- **Mockable** like ``db/connection.py`` — tests patch ``services.cache.enabled``
  / ``get_str`` / ``set_str`` (or set ``REDIS_URL`` against a fake).

Scope: currently the OCR/extraction content-cache. The Gemini-response cache the
original #97 described is mostly obsolete post agent-migration (agents bypass
``gemini_service.call_gemini``); this wrapper is the reusable seam if that need
returns.
"""

from __future__ import annotations

import logging
import os

logger = logging.getLogger(__name__)

_client = None            # lazily-built redis client, or None when disabled
_initialized = False      # have we attempted to build the client yet?


def _redis_url() -> str:
    return os.getenv("REDIS_URL", "").strip()


def _get_client():
    """Lazily build (and memoize) the redis client, or None if unavailable.

    Read at call time so tests can set REDIS_URL then call reset(). Any failure
    (missing dep, unreachable server) disables the cache for the process."""
    global _client, _initialized
    if _initialized:
        return _client
    _initialized = True
    url = _redis_url()
    if not url:
        _client = None
        return None
    try:
        import redis  # optional dependency — only imported when REDIS_URL is set
        client = redis.Redis.from_url(
            url, socket_connect_timeout=2, socket_timeout=2
        )
        client.ping()
        _client = client
        logger.info("Redis cache enabled")
    except Exception as e:  # missing redis dep, bad URL, unreachable server, …
        logger.warning("Redis cache disabled (%s); continuing without it", e)
        _client = None
    return _client


def reset() -> None:
    """Drop the memoized client so the next call re-reads REDIS_URL. For tests."""
    global _client, _initialized
    _client = None
    _initialized = False


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
