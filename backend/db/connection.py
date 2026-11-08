import logging
import os
import threading
from concurrent.futures import ThreadPoolExecutor
from typing import Iterator, Optional

import httpx
from dotenv import load_dotenv

from db import scope as _scope

load_dotenv()

logger = logging.getLogger("sapling.db")

SUPABASE_URL = os.getenv("SUPABASE_URL", "").strip().rstrip("/")
SUPABASE_KEY = os.getenv("SUPABASE_SERVICE_KEY", "").strip()
REST_URL = f"{SUPABASE_URL}/rest/v1"

_HEADERS = {
    "apikey": SUPABASE_KEY,
    "Authorization": f"Bearer {SUPABASE_KEY}",
    "Content-Type": "application/json",
    "Prefer": "return=representation",
}

# Persistent client — reuses TCP connections across requests (much faster)
_client = httpx.Client(headers=_HEADERS, timeout=30.0)


# ── Who the call runs as (#115, RLS step 2; db/scope.py) ────────────────────
#
# The client's default headers above are the service role. Every verb asks
# `_scope_headers()` right before it sends: `None` means "send exactly what
# was sent before the user-scoped client existed" (no `headers=` argument is
# added at all, so flag `off` is byte-identical), and a dict is the
# user-scoped `apikey` + `Authorization` pair httpx merges over the defaults
# for that one request. One function for every verb (and, later, the async
# twin): it never awaits.


def _scope_headers(target: Optional[str] = None) -> Optional[dict]:
    """The per-request header override for the current scope, or None for
    service role. Raises (enforce only) rather than ever falling back."""
    return _scope.resolve_headers(target)


def _merge(headers: Optional[dict], scoped: Optional[dict]) -> Optional[dict]:
    if scoped is None:
        return headers
    return {**(headers or {}), **scoped}


def _raise_for_status(r, scoped: Optional[dict], target: str) -> None:
    """`raise_for_status()`, plus the enforce-only mapping of PostgREST's two
    user-scope refusals: 401 (the minted token was rejected: key/kid mismatch)
    -> ScopeUnavailable (503), 403 (RLS WITH CHECK / missing grant, 42501) ->
    ScopedAccessDenied (404). A service-role call is unchanged."""
    if scoped is not None:
        status = r.status_code
        if status == 401:
            logger.error("db_user_scope=enforce: PostgREST rejected the user-scoped token "
                         "for %s (401); refusing rather than retrying as service role", target)
            raise _scope.ScopeUnavailable(f"PostgREST rejected the user-scoped token ({target})")
        if status == 403:
            _scope.report_denied(target, status)
            raise _scope.ScopedAccessDenied(
                f"user-scoped call on {target} refused (403)",
                request=r.request, response=r,
            )
    r.raise_for_status()


# ── Shadow reads (db_user_scope = shadow) ────────────────────────────────────
#
# A sampled service-role READ is re-run user-scoped on a small background pool
# and the two answers compared (row count + set of ids, never content). Off
# the request thread so it never delays the response; bounded so a slow
# PostgREST cannot pile them up (a full pool skips the comparison). Writes and
# rpc() are never shadowed: running a mutation twice is not an observation.

SHADOW_TIMEOUT_S = 3.0
_SHADOW_IN_FLIGHT_MAX = 4
_shadow_slots = threading.BoundedSemaphore(_SHADOW_IN_FLIGHT_MAX)
_shadow_pool: Optional[ThreadPoolExecutor] = None
_shadow_pool_lock = threading.Lock()


def _submit_shadow(fn, *args) -> None:
    """Run `fn(*args)` on the shadow pool. A seam: tests run it inline."""
    global _shadow_pool
    with _shadow_pool_lock:
        if _shadow_pool is None:
            _shadow_pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="rls-shadow")
        pool = _shadow_pool
    pool.submit(fn, *args)


def _row_ids(rows) -> set:
    return {str(r["id"]) for r in rows if isinstance(r, dict) and "id" in r}


def _maybe_shadow(name: str, url: str, params: dict, headers: Optional[dict],
                  timeout: Optional[float], rows) -> None:
    scoped = _scope.shadow_headers()
    if scoped is None or not isinstance(rows, list):
        return
    if not _shadow_slots.acquire(blocking=False):
        return
    from services.request_context import current_request_id, current_route_template

    args = (name, url, dict(params), _merge(headers, scoped),
            min(timeout, SHADOW_TIMEOUT_S) if timeout else SHADOW_TIMEOUT_S,
            len(rows), _row_ids(rows), current_route_template(),
            _scope.current_db_subject(), current_request_id())
    try:
        _submit_shadow(_shadow_compare, *args)
    except Exception:
        _shadow_slots.release()
        logger.debug("shadow read not submitted", exc_info=True)


def _shadow_compare(name, url, params, headers, timeout, service_count, service_ids,
                    route, subject, request_id) -> None:
    try:
        try:
            r = _client.get(url, params=params, headers=headers, timeout=timeout)
        except Exception:
            # Transport trouble says nothing about RLS; never report it as a
            # divergence.
            logger.debug("shadow read of %s failed in transport", name, exc_info=True)
            return
        if r.status_code >= 400:
            _scope.report_shadow_divergence(
                table=name, route=route, subject=subject, request_id=request_id,
                service_count=service_count, scoped_count=-1, error=str(r.status_code),
            )
            return
        rows = r.json()
        rows = rows if isinstance(rows, list) else []
        scoped_ids = _row_ids(rows)
        if len(rows) != service_count or (
            (service_ids or scoped_ids) and scoped_ids != service_ids
        ):
            _scope.report_shadow_divergence(
                table=name, route=route, subject=subject, request_id=request_id,
                service_count=service_count, scoped_count=len(rows),
            )
    except Exception:
        logger.debug("shadow comparison of %s failed", name, exc_info=True)
    finally:
        _shadow_slots.release()


class SupabaseTable:
    """Thin synchronous wrapper around Supabase PostgREST REST API."""

    def __init__(self, name: str):
        self.name = name
        self.url = f"{REST_URL}/{name}"

    def select(
        self,
        columns: str = "*",
        filters: Optional[dict] = None,
        order: Optional[str] = None,
        limit: Optional[int] = None,
        offset: Optional[int] = None,
        timeout: Optional[float] = None,
    ) -> list:
        """Read rows. Pass `limit`/`offset` to page — PostgREST caps a
        response at `max_rows` (1000) and answers 206 Partial Content,
        which is a 2xx, so an unpaged read over that many rows truncates
        silently.

        `timeout` (seconds) overrides the client-wide 30 s for this one read,
        for a caller that would rather fail fast than wait."""
        params: dict = {"select": columns}
        if filters:
            params.update(filters)
        if order:
            params["order"] = order
        if limit:
            params["limit"] = str(limit)
        if offset is not None:
            params["offset"] = str(offset)
        kw = {"timeout": timeout} if timeout is not None else {}
        scoped = _scope_headers(self.name)
        if scoped is not None:
            kw["headers"] = scoped
        r = _client.get(self.url, params=params, **kw)
        _raise_for_status(r, scoped, self.name)
        rows = r.json()
        if scoped is None:
            _maybe_shadow(self.name, self.url, params, None, timeout, rows)
        return rows

    def select_with_count(
        self,
        columns: str = "*",
        filters: Optional[dict] = None,
        order: Optional[str] = None,
        limit: Optional[int] = None,
        offset: Optional[int] = None,
        timeout: Optional[float] = None,
    ) -> tuple[list, int]:
        """Like select(), but also returns total row count via Content-Range.
        `timeout` as in select()."""
        params: dict = {"select": columns}
        if filters:
            params.update(filters)
        if order:
            params["order"] = order
        if limit is not None:
            params["limit"] = str(limit)
        if offset is not None:
            params["offset"] = str(offset)
        headers = {"Prefer": "count=exact"}
        kw = {"timeout": timeout} if timeout is not None else {}
        scoped = _scope_headers(self.name)
        r = _client.get(self.url, params=params, headers=_merge(headers, scoped), **kw)
        _raise_for_status(r, scoped, self.name)
        rows = r.json()
        if scoped is None:
            _maybe_shadow(self.name, self.url, params, headers, timeout, rows)
        total = 0
        cr = r.headers.get("Content-Range") or r.headers.get("content-range")
        if cr and "/" in cr:
            try:
                total = int(cr.rsplit("/", 1)[1])
            except ValueError:
                total = 0
        return rows, total

    def insert(self, data) -> list:
        scoped = _scope_headers(self.name)
        if scoped is None:
            r = _client.post(self.url, json=data)
        else:
            r = _client.post(self.url, json=data, headers=scoped)
        _raise_for_status(r, scoped, self.name)
        return r.json()

    def update(self, data: dict, filters: dict, *, prefer_return_minimal: bool = False) -> list:
        """PATCH matching rows; returns the updated rows.

        `prefer_return_minimal=True` overrides the client-wide
        `Prefer: return=representation` for writes whose result nobody
        reads — a background sweep over many rows would otherwise drag
        every updated row (including large encrypted columns) back over
        the wire. Returns [] in that mode.
        """
        headers = {"Prefer": "return=minimal"} if prefer_return_minimal else None
        scoped = _scope_headers(self.name)
        r = _client.patch(self.url, params=filters, json=data, headers=_merge(headers, scoped))
        _raise_for_status(r, scoped, self.name)
        if prefer_return_minimal:
            return []
        return r.json()

    def upsert(
        self,
        data,
        on_conflict: str = "id",
        *,
        ignore_duplicates: bool = False,
        columns: Optional[str] = None,
    ) -> list:
        """INSERT … ON CONFLICT (on_conflict) DO UPDATE, or DO NOTHING when
        `ignore_duplicates=True`. Use the latter to make sure a row EXISTS
        (lazy get-or-create, #674): DO UPDATE on a race loser would still fire
        BEFORE UPDATE triggers such as `updated_at`, which moves ETags. A
        DO NOTHING conflict returns no representation for the skipped row.

        `columns` projects the returned representation (PostgREST `select=`),
        the same column list a select() takes; omitted, every column comes back."""
        resolution = "ignore-duplicates" if ignore_duplicates else "merge-duplicates"
        headers = {"Prefer": f"return=representation,resolution={resolution}"}
        params = {"on_conflict": on_conflict}
        if columns:
            params["select"] = columns
        scoped = _scope_headers(self.name)
        r = _client.post(self.url, headers=_merge(headers, scoped), params=params, json=data)
        _raise_for_status(r, scoped, self.name)
        return r.json()

    def delete(self, filters: dict) -> list:
        scoped = _scope_headers(self.name)
        if scoped is None:
            r = _client.delete(self.url, params=filters)
        else:
            r = _client.delete(self.url, params=filters, headers=scoped)
        _raise_for_status(r, scoped, self.name)
        return r.json()


def pg_quote_value(value: str) -> str:
    """Double-quote a value for a PostgREST logic tree (``or=(…)``/``and=(…)``).

    Inside a logic tree a bare value ends at the first comma or paren, so a
    course named ``Ethics, Law and Society`` parses as two broken operands and
    a search for ``a)b`` closes the tree early. Quoting fixes that; ``"`` and
    ``\\`` inside the value are backslash-escaped, as PostgREST's grammar
    specifies.

    Lives here rather than in the feature that first needed it because this is
    PostgREST grammar, not domain logic: every caller that interpolates a
    user- or catalog-supplied value into a filter needs the same rule, and one
    of them (`routes/onboarding.py`'s course search) shipped without it.
    """
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


#: LIKE's own metacharacters, plus its default escape character. Applied
#: BEFORE `pg_quote_value`, which then doubles the backslashes this introduces
#: for PostgREST's grammar — the other order emits a bare ``\%`` that PostgREST
#: unescapes to ``%`` and hands to LIKE as a live wildcard.
_LIKE_SPECIALS = str.maketrans({"\\": "\\\\", "%": "\\%", "_": "\\_"})


def like_literal(value: str) -> str:
    """Escape a value so ``like``/``ilike`` matches it verbatim.

    ``topic.ilike."Math_101"`` would otherwise match ``Math-101`` and
    ``Math 101`` too (``_`` is LIKE's any-single-character wildcard), and a
    value containing ``%`` would match a great deal more than it names. Add
    your own surrounding ``%`` for a substring match — the point of this is
    that the *value* stops being a pattern, not that the match stops being one.

    One gap it cannot close: PostgREST rewrites ``*`` to ``%`` in like/ilike
    values itself, before Postgres ever sees the pattern, and offers no escape
    for it.
    """
    return value.translate(_LIKE_SPECIALS)


def table(name: str) -> SupabaseTable:
    return SupabaseTable(name)


#: `supabase/config.toml` sets PostgREST's `max_rows`. A response past that cap
#: does not error — PostgREST answers 206 Partial Content, which is a 2xx, so
#: `raise_for_status()` never fires and the truncation is silent by
#: construction. Every unbounded read of a table that can grow past this has to
#: page; `page_all` below is how.
MAX_ROWS = 1000


def page_all(
    handle: SupabaseTable,
    columns: str = "*",
    *,
    filters: Optional[dict] = None,
    order: str,
    page: int = MAX_ROWS,
    timeout: Optional[float] = None,
) -> Iterator[dict]:
    """Yield EVERY row matching `filters`, paging past `MAX_ROWS`.

    Lives here rather than in the feature that first needed it, for the same
    reason `pg_quote_value` does: this is PostgREST's paging contract, not
    domain logic. It replaced three hand-rolled copies (the XP ledger sum, the
    per-day XP totals, and the hero card's `events_since`), each of which
    carried its own constant, its own copy of the rationale above, and — the
    reason they are one function now — the same termination bug.

    Takes the RESOLVED handle, not a table name, so `table(...)` still
    resolves in the calling module. That keeps each service's own `table` the
    single patch point its tests already use, rather than silently relocating
    the seam here.

    **A full page is never evidence of the end; only a short page is.**
    `select_with_count` reports `total = 0` whenever the Content-Range header
    is missing or unparseable, so a `seen >= total` guard alone stops after
    page one *with a completely full page in hand* — performing exactly the
    silent truncation the loop exists to prevent. `total` is therefore only an
    optimisation here: a trustworthy one saves the extra round trip that would
    otherwise be needed to prove the end.

    `order` is REQUIRED and must be a total order (append a unique tiebreaker
    such as `id`). Offset paging over a non-deterministic sort lets Postgres
    return rows in a different order for page N and N+1, silently skipping or
    duplicating rows across the boundary.

    `timeout` bounds each page's read (see `SupabaseTable.select`); omitted,
    the handle's call is unchanged (fakes need not accept it).
    """
    if page > MAX_ROWS:
        # Above the cap every page comes back short by construction, so the
        # short-page terminator would end the read after MAX_ROWS rows and
        # report it as the complete set. Refuse rather than truncate quietly.
        raise ValueError(
            f"page={page} exceeds PostgREST max_rows ({MAX_ROWS}); "
            "every page would come back short and the read would stop early"
        )
    seen = 0
    offset = 0
    extra = {"timeout": timeout} if timeout is not None else {}
    while True:
        rows, total = handle.select_with_count(
            columns, filters=filters, order=order, limit=page, offset=offset, **extra,
        )
        rows = rows or []
        yield from rows
        seen += len(rows)
        # A SHORT page is the only proof of the end. `total` is a pure
        # optimisation on top of it, and only when it is credible: `total = 0`
        # is what an unparseable Content-Range reports, and `seen >= 0` holds
        # trivially — so testing `seen >= total` on its own (or as one more
        # `or` beside the short-page test) re-introduces the very truncation
        # this guards, because a full page satisfies it too.
        if len(rows) < page or (total > 0 and seen >= total):
            return
        offset += page


def rpc(function_name: str, params: dict) -> list:
    """Call a Supabase Postgres function via /rest/v1/rpc/{function_name}."""
    url = f"{REST_URL}/rpc/{function_name}"
    target = f"rpc/{function_name}"
    scoped = _scope_headers(target)
    if scoped is None:
        r = _client.post(url, json=params)
    else:
        r = _client.post(url, json=params, headers=scoped)
    _raise_for_status(r, scoped, target)
    return r.json()
