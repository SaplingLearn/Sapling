"""Shared request-resource guards: per-key rate limiting and upload size bounds.

Factored for reuse across CPU/cost-heavy endpoints (OCR extraction, LLM). The
flashcard import service has an older copy of the same sliding-window limiter
(`services/flashcard_import_service.check_rate_limit`) that can migrate here.
"""
import time

from fastapi import HTTPException, UploadFile

# In-memory sliding-window state, keyed by an arbitrary string (e.g.
# "ocr:<user_id>"). Process-local — fine for a single-instance deployment; a
# multi-instance rollout would move this to Redis.
_rate_state: dict[str, list[float]] = {}


def check_rate_limit(key: str, *, limit: int, window_sec: int) -> int | None:
    """Sliding-window per-key limiter.

    Returns None if the call is allowed (and records it), else the number of
    seconds until the next call would be allowed.
    """
    now = time.time()
    bucket = [t for t in _rate_state.get(key, []) if now - t < window_sec]
    if len(bucket) >= limit:
        retry = int(window_sec - (now - bucket[0])) + 1
        _rate_state[key] = bucket
        return retry
    bucket.append(now)
    _rate_state[key] = bucket
    return None


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
