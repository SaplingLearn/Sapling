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
vouch for EVERY number in the body it answers 5xx — never zeros, never a
partial body. Canopy would quietly drop a single bad key and keep the rest;
refusing the whole response instead puts the failure in THIS app's logs, where
the person who can fix it will see it.

Privacy: the response is aggregate integers — distinct-user counts for the
whole app, event/row counts, sums of tokens and cents. No ids, no emails, no
per-user rows, no distinct-users-per-feature (in a small org "1 user used notes
today" names them), no averages, no free text. A future need is a NEW aggregate
with its own line in the contract, never a list of people.
"""

from __future__ import annotations

import hmac
import logging
import re

from fastapi import APIRouter, Header, HTTPException

from config import canopy_metrics_token
from db.connection import rpc

logger = logging.getLogger("sapling.internal_metrics")

router = APIRouter()

# The Postgres function behind the whole body (migration
# 20260921044914_canopy_metrics.sql). Takes no arguments and returns ONE JSONB
# document, which PostgREST hands back as a bare JSON object.
METRICS_RPC = "canopy_metrics"

# The three sections of contract v2, and the only top-level keys allowed out.
_SECTIONS = ("active_users", "counts", "totals")

# Wire order of a windowed entry. Every entry has exactly these three.
_WINDOWS = ("24h", "7d", "30d")

# Canopy's own limits (its spec, section 3), checked here first so a refusal shows up in
# THIS app's logs instead of as a silent drop on the other side.
_MAX_ACTIVE_USERS = 10_000_000
_MAX_VALUE = 1_000_000_000_000
_MAX_KEYS = {"counts": 48, "totals": 24}
_KEY_RE = re.compile(r"[a-z][a-z0-9_]{0,39}")

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


def _integer(value: object, ceiling: int, where: str) -> int:
    """`value` as a real non-negative integer no larger than `ceiling`, or raise.

    `type(...) is int`, not isinstance: bool is an int in Python (True would go
    out as the JSON literal `true`), and a string or a float here means the wire
    format changed under us. Error messages name the KEY, never the value.
    """
    if type(value) is not int or not 0 <= value <= ceiling:
        raise ValueError(f"{METRICS_RPC}: {where} is not an integer in range")
    return value


def _windows(entry: object, ceiling: int, where: str) -> dict[str, int]:
    """One `{24h, 7d, 30d}` entry: exactly those keys, in range, nested."""
    if not isinstance(entry, dict) or set(entry) != set(_WINDOWS):
        raise ValueError(f"{METRICS_RPC}: {where} is not exactly the three windows")
    # Rebuilt, in wire order — never the object the database handed over.
    out = {w: _integer(entry[w], ceiling, f"{where}.{w}") for w in _WINDOWS}
    if not out["24h"] <= out["7d"] <= out["30d"]:
        raise ValueError(f"{METRICS_RPC}: {where} windows do not nest")
    return out


def _keyed(section: object, name: str) -> dict:
    """A `counts` / `totals` object with contract-legal keys, within the cap."""
    if not isinstance(section, dict):
        raise ValueError(f"{METRICS_RPC}: {name} is not an object")
    if len(section) > _MAX_KEYS[name]:
        raise ValueError(f"{METRICS_RPC}: {name} has more than {_MAX_KEYS[name]} keys")
    for key in section:
        if not isinstance(key, str) or not _KEY_RE.fullmatch(key):
            # repr + a cut: a hostile key must not get to write the log line.
            raise ValueError(f"{METRICS_RPC}: {name} has an illegal key {key!r:.48}")
    return section


def _metrics_document() -> dict:
    """The whole response from ONE database round trip, or raise.

    Validates everything Canopy will validate — and refuses the WHOLE document
    where Canopy would drop one key — then rebuilds it value by value, so
    nothing the database returned reaches the wire unchecked.
    """
    doc = rpc(METRICS_RPC, {})
    # PostgREST answers a scalar-returning function with the bare value. A
    # one-element list is the same document from a server that wrapped it.
    if isinstance(doc, list) and len(doc) == 1:
        doc = doc[0]
    if not isinstance(doc, dict) or set(doc) != set(_SECTIONS):
        raise ValueError(f"{METRICS_RPC} did not return exactly {', '.join(_SECTIONS)}")

    return {
        "active_users": _windows(doc["active_users"], _MAX_ACTIVE_USERS, "active_users"),
        "counts": {
            key: _windows(entry, _MAX_VALUE, f"counts.{key}")
            for key, entry in _keyed(doc["counts"], "counts").items()
        },
        "totals": {
            key: _integer(value, _MAX_VALUE, f"totals.{key}")
            for key, value in _keyed(doc["totals"], "totals").items()
        },
    }


# No trailing slash and include_in_schema=False: Canopy never follows a
# redirect (it will not carry the token to a second URL), and the route stays
# out of /docs and /openapi.json.
@router.get("/metrics", include_in_schema=False)
def internal_metrics(authorization: str | None = Header(default=None)) -> dict:
    """Aggregate usage numbers for the Canopy dashboard (its contract v2).

        {"active_users": {"24h": 74, "7d": 318, "30d": 402},
         "counts": {"signups": {"24h": 3, "7d": 21, "30d": 96}, ...},
         "totals": {"users": 1204, "users_pending": 7, ...}}

    `counts` are WINDOWED — how many of something happened in the trailing 24
    hours / 7 days / 30 days. `totals` are POINT-IN-TIME — how many exist right
    now. Every value is a non-negative JSON integer. Which keys exist, their
    exact source column and what a deleted row does to each are documented ONCE,
    next to the SQL that computes them: migration
    `20260921044914_canopy_metrics.sql`. Three rules from there matter to a
    caller:

    - **A key is absent rather than approximated.** Absent reads "not reported"
      on the dashboard; 0 reads as a measured zero. So the keys counted from the
      `events` table (tutor_sessions, chat_messages, documents_uploaded, logins,
      errors_*, the *_failed signals) appear only when `events` holds a row from
      the last 30 days, and the llm_* keys only when `llm_usage` does — both
      tables go silent under the `EVENTS_LOGGING_ENABLED=false` kill switch.
      `study_guides` is never sent: that table is a cache.
    - **`llm_cost_cents` is a LOWER bound.** It is `ROUND(SUM(cost_usd) * 100)`
      — integer cents, half-up — and `cost_usd` is NULL for a model
      `services/llm_pricing.py` has no price for; those calls add tokens but no
      cents. With no priced call in 30 days the key is absent.
    - **`counts` say what happened, `totals` what exists.** A soft-deleted
      document, note, account or room message still counts in its window; it is
      gone from the totals.

    **What "active" means.** A user is active in a window when the `events`
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

    **Nesting and consistency are by construction.** The whole body is ONE SQL
    statement — one snapshot, one `now()` — and every windowed entry is one
    30-day row set with each narrower window a FILTER on the wider one, so
    `24h <= 7d <= 30d` always and no two numbers can contradict each other.
    There is deliberately no row-scan fallback: `admin_analytics` pages rows
    into Python and stops at a 100k-row cap with `truncated: true`, and a
    truncated scan UNDERCOUNTS. Aggregates in Postgres cannot truncate.

    Status codes: 404 when `CANOPY_METRICS_TOKEN` is unset or blank (feature
    off); 401, identical for every kind of wrong credential; 503 with a generic
    body when the document cannot be produced or ANY part of it does not
    validate — including code deployed before the migration is applied
    (PostgREST 404s the RPC), which was the v1 behaviour too.
    """
    _authorize(authorization)
    try:
        document = _metrics_document()
    except Exception:
        # Includes the function not existing yet (code deployed before the
        # migration: PostgREST 404s the RPC). The traceback names the Supabase
        # URL and status, never a credential — the token is not in scope here.
        logger.exception("canopy metrics: document unavailable")
        raise HTTPException(status_code=503, detail=_UNAVAILABLE)
    return document
