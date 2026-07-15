"""HTTP conditional-GET helpers: ETag + If-None-Match → 304 (#99).

Usage in a sync route:

    from services.http_cache import make_etag, conditional

    rows = table("study_guides").select(...)          # the primary read
    etag = make_etag(user_id, len(rows), _max(rows, "generated_at"))
    not_mod = conditional(request, etag)
    if not_mod:
        return not_mod                                # 304, skips enrichment+serialize
    ... build payload ...
    return cached_json(payload, etag)

Correctness: derive the ETag from the data you just read (ids / updated_at /
existing hashes), NOT from the fully-built payload — so a 304 skips the
downstream enrichment and JSON serialization while the tag still reflects
exactly the current data. Always `private` — these routes carry user-scoped,
app-decrypted data that must never be cached at a shared proxy/CDN.
"""

from __future__ import annotations

import hashlib

from fastapi import Request, Response
from fastapi.responses import JSONResponse

# private: user-scoped + app-decrypted, never shared-cacheable (see CLAUDE.md).
# max-age: short freshness window; stale-while-revalidate: serve stale briefly
# while revalidating in the background.
CACHE_CONTROL = "private, max-age=30, stale-while-revalidate=60"


def make_etag(*parts: object) -> str:
    """Build a strong ETag from cheap, change-sensitive parts (ids, timestamps,
    counts, existing content hashes). Joins with the ASCII unit separator so
    values containing commas/spaces can't collide."""
    raw = "\x1f".join("" if p is None else str(p) for p in parts)
    return '"' + hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16] + '"'


def _if_none_match(request: Request, etag: str) -> bool:
    header = request.headers.get("if-none-match")
    if not header:
        return False
    if header.strip() == "*":
        return True
    # RFC 7232: comma-separated list of entity-tags; compare ignoring the
    # optional weak "W/" prefix.
    supplied = {t.strip().removeprefix("W/") for t in header.split(",")}
    return etag.removeprefix("W/") in supplied


def conditional(request: Request, etag: str) -> Response | None:
    """Return a 304 Response (with ETag + Cache-Control) when the client's
    If-None-Match matches `etag`; otherwise None (caller builds the 200)."""
    if _if_none_match(request, etag):
        return Response(
            status_code=304,
            headers={"ETag": etag, "Cache-Control": CACHE_CONTROL},
        )
    return None


def cached_json(payload: object, etag: str) -> JSONResponse:
    """Build a 200 JSONResponse carrying the ETag + private Cache-Control."""
    return JSONResponse(
        content=payload,
        headers={"ETag": etag, "Cache-Control": CACHE_CONTROL},
    )
