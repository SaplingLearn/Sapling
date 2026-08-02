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

# For reads that must reflect the user's OWN action on the very next request.
#
# `no-cache` does not mean "don't cache" — it means "cache, but revalidate
# before every reuse". So the ETag still does its job and an unchanged read is
# still a cheap 304; what goes away is the window where the browser answers
# from its own cache WITHOUT asking us, during which no ETag can help.
#
# CACHE_CONTROL's 30s freshness is right for data the user does not
# immediately cause to change. It is wrong for a live counter: the E2E journey
# (frontend/e2e/gamification.spec.ts) caught the hero card still reading
# "0 XP total" after XP was earned and the page reloaded, because the browser
# reused its fresh copy and never re-asked. Under-30s feedback is the entire
# point of the XP surface, so these routes trade a revalidation round-trip for
# never showing a number the user just disproved.
REVALIDATE_CACHE_CONTROL = "private, no-cache"


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


def conditional(
    request: Request, etag: str, cache_control: str = CACHE_CONTROL
) -> Response | None:
    """Return a 304 Response (with ETag + Cache-Control) when the client's
    If-None-Match matches `etag`; otherwise None (caller builds the 200).

    Pass `REVALIDATE_CACHE_CONTROL` for a route whose value the user changes
    directly and expects to see change immediately. The 304 must carry the
    SAME directive as the 200 — it refreshes the stored response's headers,
    so returning the default here would silently re-grant a 30s no-ask window
    on the next revalidation.
    """
    if _if_none_match(request, etag):
        return Response(
            status_code=304,
            headers={"ETag": etag, "Cache-Control": cache_control},
        )
    return None


def cached_json(
    payload: object, etag: str, cache_control: str = CACHE_CONTROL
) -> JSONResponse:
    """Build a 200 JSONResponse carrying the ETag + private Cache-Control."""
    return JSONResponse(
        content=payload,
        headers={"ETag": etag, "Cache-Control": cache_control},
    )
