"""Shared request-resource guards: per-key rate limiting and upload size bounds.

Factored for reuse across CPU/cost-heavy endpoints (OCR extraction, LLM). The
flashcard import service has an older copy of the same sliding-window limiter
(`services/flashcard_import_service.check_rate_limit`) that can migrate here.
"""
import math
import time
from typing import NamedTuple

from fastapi import HTTPException, UploadFile

# In-memory sliding-window state, keyed by an arbitrary string (e.g.
# "ocr:<user_id>"). Process-local — fine for a single-instance deployment; a
# multi-instance rollout would move this to Redis.
_rate_state: dict[str, list[float]] = {}


class RateLimitClaim(NamedTuple):
    """One call's outcome at the gate.

    `retry_after` is None when the call was allowed; `slot` is then the exact
    timestamp recorded for it — the handle `refund_rate_limit` needs to give
    back THIS call's slot rather than whichever was recorded last.
    """

    retry_after: int | None
    slot: float | None = None


def claim_rate_limit(key: str, *, limit: int, window_sec: int) -> RateLimitClaim:
    """Sliding-window per-key limiter that returns a refundable slot."""
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


def check_rate_limit(key: str, *, limit: int, window_sec: int) -> int | None:
    """Sliding-window per-key limiter.

    Returns None if the call is allowed (and records it), else the number of
    seconds until the next call would be allowed.
    """
    return claim_rate_limit(key, limit=limit, window_sec=window_sec).retry_after


def refund_rate_limit(key: str, slot: float | None) -> None:
    """Give back the slot `claim_rate_limit` recorded for one call.

    For guards that must claim BEFORE doing the expensive work (so a
    concurrent burst can't slip past the gate) but shouldn't charge the
    caller when that work fails for reasons they didn't cause.

    Removes THAT call's timestamp (#760). Popping the newest instead refunded
    a concurrent request's slot — one still running, which then stayed
    uncharged — while the failed call's own stamp kept counting. A slot that
    has already aged out of the window (or was never recorded) is a no-op;
    two equal timestamps are interchangeable, so removing either is exact.
    """
    if slot is None:
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
