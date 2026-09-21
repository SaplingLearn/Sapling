"""Server-to-server aggregate metrics for the Canopy team dashboard.

One route, `GET /api/internal/metrics`, polled once an hour per environment by
Canopy's Worker (user-agent `canopy-metrics`). It is NOT a user-facing route and
NOT an admin one: there is no `sapling_session` on the other end, only a shared
bearer token (`CANOPY_METRICS_TOKEN`, see `config.canopy_metrics_token`). This
app has no global auth middleware — every route guards itself — so nothing had
to be exempted; this route simply never calls `auth_guard`.

The consumer keeps what it is told FOREVER (its store is append-only and
first-write-wins per hour), and treats anything but a valid 200 as "write
nothing this hour". That asymmetry sets every rule here: when this route cannot
vouch for all three numbers it answers 5xx — never zeros, never a partial body.

Privacy: the response is three integers. No ids, no emails, no per-user rows,
no per-route breakdown. A future need is a NEW aggregate count with its own
line in the contract, never a list of people.
"""

from __future__ import annotations

import hmac
import logging

from fastapi import APIRouter, Header, HTTPException

from config import canopy_metrics_token
from db.connection import rpc

logger = logging.getLogger("sapling.internal_metrics")

router = APIRouter()

# The Postgres function behind the counts (migration
# 20260921041555_canopy_active_users.sql). Takes no arguments, returns one row.
ACTIVE_USERS_RPC = "canopy_active_users"

# function column -> wire key. The response is PROJECTED through this map, so a
# column added to the function later cannot reach the wire by accident.
_WINDOWS = (("d1", "24h"), ("d7", "7d"), ("d30", "30d"))

# Canopy refuses a window outside 0..10,000,000. Checked here too so a refusal
# shows up in THIS app's logs instead of as a silent drop on the other side.
_MAX_COUNT = 10_000_000

# One body for every failure, saying nothing about which.
_UNAVAILABLE = "Metrics temporarily unavailable"


def _authorize(authorization: str | None) -> None:
    """404 when the feature is off, one generic 401 for every bad credential."""
    expected = canopy_metrics_token()
    if not expected:
        # Unset/blank -> DISABLED, indistinguishable from an unrouted path (the
        # stock detail, same as /api/auth/test-login outside local). This MUST
        # come before the compare: against an empty expected token, the header
        # "Bearer " would match.
        raise HTTPException(status_code=404)

    # Constant-time, on bytes (compare_digest rejects non-ASCII str), over the
    # WHOLE header value: no early return on a missing "Bearer " prefix and no
    # length check first, so timing says nothing about how far a guess got.
    presented = (authorization or "").encode("utf-8")
    if not hmac.compare_digest(presented, f"Bearer {expected}".encode("utf-8")):
        # Missing header, wrong scheme, wrong token: the same bare answer. No
        # WWW-Authenticate either — nothing here should describe how to get in.
        # Deliberately not logged beyond the middleware's own status line.
        raise HTTPException(status_code=401, detail="Unauthorized")


def _active_user_counts() -> dict[str, int]:
    """All three windows from ONE database round trip, or raise.

    Validates everything Canopy will validate — one row, three real integers in
    range, 24h <= 7d <= 30d — because a bad window must refuse the other two.
    """
    rows = rpc(ACTIVE_USERS_RPC, {})
    if not isinstance(rows, list) or len(rows) != 1 or not isinstance(rows[0], dict):
        raise ValueError(f"{ACTIVE_USERS_RPC} did not return exactly one row")
    row = rows[0]

    counts: dict[str, int] = {}
    for column, window in _WINDOWS:
        value = row.get(column)
        # `type(...) is int`, not isinstance: bool is an int in Python, and a
        # string or float here means the wire format changed under us.
        if type(value) is not int or not 0 <= value <= _MAX_COUNT:
            raise ValueError(f"{ACTIVE_USERS_RPC}.{column} is not an integer in range")
        counts[window] = value

    if not counts["24h"] <= counts["7d"] <= counts["30d"]:
        raise ValueError(f"{ACTIVE_USERS_RPC} windows do not nest")
    return counts


# No trailing slash and include_in_schema=False: Canopy never follows a
# redirect (it will not carry the token to a second URL), and the route stays
# out of /docs and /openapi.json.
@router.get("/metrics", include_in_schema=False)
def internal_metrics(authorization: str | None = Header(default=None)) -> dict:
    """Distinct active users over the trailing 24 hours / 7 days / 30 days.

        {"active_users": {"24h": 74, "7d": 318, "30d": 318}}

    **What "active" means here.** A user is active in a window when the `events`
    table holds at least one row attributed to them (`user_id` set) with
    `created_at` inside it. That is the same source, and the same "has a
    user_id" rule, as the admin dashboard's `distinct_active_users`
    (`routes/admin_analytics.py::usage_summary`), so the two agree: this route's
    `30d` is that endpoint's default-range number (while that endpoint's scan
    stays under its row cap).

    Why `events`: it is the only table that timestamps activity across features
    and only ever attributes a row to a user AFTER authentication — emit sites
    sit behind `require_self`/the session decode, and the HTTP error rows take
    theirs from `request.state.user_id`, which `auth_guard` stamps on a
    successful session decode. `users.last_active_date` was the alternative and is worse on both
    counts: it is a DATE (a trailing 24h window cannot be cut from it) and only
    the tutor/graph XP hook advances it. `llm_usage` sees AI features only.

    **Known blind spots — this undercounts, it never overcounts.** `events` is a
    curated taxonomy, not a request log; successful (2xx) requests are
    deliberately not recorded. A user is counted when they sign in
    (`auth.login`), start/end a tutor session, send a chat message, start or
    finish a quiz, upload a document, create a note, or hit any 4xx/5xx while
    signed in. A user who only browses — or only uses a surface that emits
    nothing (flashcards, gradebook, calendar, study guides, rooms) — on an
    already-valid session is NOT counted, and sessions last 30 days, so
    `auth.login` alone does not catch them. `24h` and `7d` are the windows this
    hurts most. `EVENTS_LOGGING_ENABLED=false` (the events kill switch) or a
    dropped events batch also reads as inactivity.

    **Nesting is by construction.** All three counts come from one SQL statement
    over one 30-day row set with one `now()`, each narrower window a FILTER on
    the wider one — so `24h <= 7d <= 30d` always, which Canopy checks. There is
    deliberately no row-scan fallback: `admin_analytics` pages `events` into
    Python and stops at a 100k-row cap with `truncated: true`, and a truncated
    scan UNDERCOUNTS. `COUNT(DISTINCT ...)` in Postgres cannot truncate.

    Status codes: 404 when `CANOPY_METRICS_TOKEN` is unset or blank (feature
    off); 401, identical for every kind of wrong credential; 503 with a generic
    body when the counts cannot be produced or do not validate.
    """
    _authorize(authorization)
    try:
        counts = _active_user_counts()
    except Exception:
        # Includes the function not existing yet (code deployed before the
        # migration: PostgREST 404s the RPC). The traceback names the Supabase
        # URL and status, never a credential — the token is not in scope here.
        logger.exception("canopy metrics: active-user counts unavailable")
        raise HTTPException(status_code=503, detail=_UNAVAILABLE)
    return {"active_users": counts}
