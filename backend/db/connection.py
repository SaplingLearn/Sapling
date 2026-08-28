import os
from typing import Optional

import httpx
from dotenv import load_dotenv

load_dotenv()

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
    ) -> list:
        """Read rows. Pass `limit`/`offset` to page — PostgREST caps a
        response at `max_rows` (1000) and answers 206 Partial Content,
        which is a 2xx, so an unpaged read over that many rows truncates
        silently."""
        params: dict = {"select": columns}
        if filters:
            params.update(filters)
        if order:
            params["order"] = order
        if limit:
            params["limit"] = str(limit)
        if offset is not None:
            params["offset"] = str(offset)
        r = _client.get(self.url, params=params)
        r.raise_for_status()
        return r.json()

    def select_with_count(
        self,
        columns: str = "*",
        filters: Optional[dict] = None,
        order: Optional[str] = None,
        limit: Optional[int] = None,
        offset: Optional[int] = None,
    ) -> tuple[list, int]:
        """Like select(), but also returns total row count via Content-Range."""
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
        r = _client.get(self.url, params=params, headers=headers)
        r.raise_for_status()
        rows = r.json()
        total = 0
        cr = r.headers.get("Content-Range") or r.headers.get("content-range")
        if cr and "/" in cr:
            try:
                total = int(cr.rsplit("/", 1)[1])
            except ValueError:
                total = 0
        return rows, total

    def insert(self, data) -> list:
        r = _client.post(self.url, json=data)
        r.raise_for_status()
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
        r = _client.patch(self.url, params=filters, json=data, headers=headers)
        r.raise_for_status()
        if prefer_return_minimal:
            return []
        return r.json()

    def upsert(self, data, on_conflict: str = "id") -> list:
        headers = {"Prefer": "return=representation,resolution=merge-duplicates"}
        r = _client.post(self.url, headers=headers, params={"on_conflict": on_conflict}, json=data)
        r.raise_for_status()
        return r.json()

    def delete(self, filters: dict) -> list:
        r = _client.delete(self.url, params=filters)
        r.raise_for_status()
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


def rpc(function_name: str, params: dict) -> list:
    """Call a Supabase Postgres function via /rest/v1/rpc/{function_name}."""
    url = f"{REST_URL}/rpc/{function_name}"
    r = _client.post(url, json=params)
    r.raise_for_status()
    return r.json()
