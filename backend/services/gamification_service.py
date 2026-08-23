"""The hero-card snapshot — one implementation, every caller.

`GET /api/gamification/me` renders the XP/level/streak card, and since G8
(#537) `POST /api/quiz/submit` returns the same numbers inline so the results
screen does not have to race a second request for the line it just earned.

Those two must never be able to disagree, which is the whole reason this lives
in a service rather than in the route: two hand-rolled payloads drift the
moment one of them gains a field. `/me` is a thin caching wrapper over
`read_me_inputs` + `me_payload`; the quiz calls `me_snapshot`, which is the
same two calls in a row.

The read is split in two because `/me` needs the cheap half BEFORE it decides
whether to build the payload at all: `total_xp`, `level` and the earned-badge
count are its ETag inputs, and a 304 must not pay for the `xp_events` scan
that `today_xp` costs.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from db.connection import table
from services.growth import stage_for_level, xp_into_level

# supabase/config.toml sets PostgREST's `max_rows = 1000`. A page past that
# cap doesn't error — PostgREST returns 206 Partial Content, which is a 2xx,
# so db/connection.py's raise_for_status() never fires; the truncation is
# silent by construction. `events_since` backs the leaderboard's weekly-XP
# aggregation (and /me and /activity), so an unbounded single call here would
# silently corrupt totals and rank order once platform-wide weekly events
# cross this cap. Keep this at or below max_rows and page to completion.
XP_EVENTS_PAGE = 1000


def events_since(user_id: str | None, since: datetime) -> list[dict]:
    """All xp_events at/after `since`, optionally scoped to one user.

    Pages to completion via select_with_count rather than a single unbounded
    select — see XP_EVENTS_PAGE. The `created_at,id` order is required for
    offset paging to be correct: without a stable sort, Postgres/PostgREST
    can return rows in a different order across pages, silently skipping or
    duplicating rows across the page boundary.
    """
    filters = {"created_at": f"gte.{since.isoformat()}"}
    if user_id:
        filters["user_id"] = f"eq.{user_id}"
    out: list[dict] = []
    offset = 0
    while True:
        rows, total = table("xp_events").select_with_count(
            "user_id,amount,created_at",
            filters=filters,
            order="created_at.asc,id.asc",
            limit=XP_EVENTS_PAGE,
            offset=offset,
        )
        out.extend(rows or [])
        if not rows or len(out) >= total:
            break
        offset += XP_EVENTS_PAGE
    return out


@dataclass(frozen=True)
class MeInputs:
    """The cheap reads behind the hero card — and `/me`'s ETag inputs."""

    total_xp: int
    level: int
    streak: int
    longest_streak: int
    daily_goal_xp: int
    earned_count: int
    total_count: int


def read_me_inputs(user_id: str) -> MeInputs:
    rows = table("users").select(
        "total_xp,level,streak_count,longest_streak,daily_goal_xp",
        filters={"id": f"eq.{user_id}"},
    )
    u = rows[0] if rows else {}

    earned = table("user_achievements").select(
        "achievement_id", filters={"user_id": f"eq.{user_id}"}
    ) or []
    # Live only — a work-in-progress badge must not inflate "12 of 30".
    catalog = table("achievements").select("id", filters={"status": "eq.live"}) or []

    return MeInputs(
        total_xp=int(u.get("total_xp") or 0),
        level=int(u.get("level") or 1),
        streak=int(u.get("streak_count") or 0),
        longest_streak=int(u.get("longest_streak") or 0),
        daily_goal_xp=int(u.get("daily_goal_xp") or 50),
        earned_count=len(earned),
        total_count=len(catalog),
    )


def me_payload(user_id: str, inputs: MeInputs) -> dict:
    """The hero-card payload. `GET /api/gamification/me` returns this verbatim."""
    today = datetime.now(timezone.utc).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    today_xp = sum(int(e.get("amount") or 0) for e in events_since(user_id, today))

    into, for_level = xp_into_level(inputs.total_xp)
    stage = stage_for_level(inputs.level)
    return {
        "level": inputs.level,
        "next_level": inputs.level + 1,
        "stage": {"slug": stage.get("slug"), "name": stage.get("name"),
                  "blurb": stage.get("blurb")},
        "total_xp": inputs.total_xp,
        "xp_into_level": into,
        "xp_for_level": for_level,
        "level_pct": round(into / for_level * 100) if for_level else 100,
        "streak": inputs.streak,
        "longest_streak": inputs.longest_streak,
        "daily_goal_xp": inputs.daily_goal_xp,
        "today_xp": today_xp,
        "earned_count": inputs.earned_count,
        "total_count": inputs.total_count,
    }


def me_snapshot(user_id: str) -> dict:
    """`me_payload` with its own reads — for callers with no ETag to serve."""
    return me_payload(user_id, read_me_inputs(user_id))
