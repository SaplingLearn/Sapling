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

from db.connection import MAX_ROWS, page_all, table
from services.growth import stage_for_level, xp_into_level

# Every read in this module pages through `db.connection.page_all`, which
# carries the rationale: PostgREST caps a response at `max_rows` and reports
# the cut with a 206, a 2xx that raise_for_status() ignores, so an unpaged
# read truncates silently. `events_since` backs the leaderboard's weekly-XP
# aggregation (and /me and /activity), so a truncated read here corrupts
# totals and rank order rather than merely under-reporting one card.
XP_EVENTS_PAGE = MAX_ROWS


def events_since(user_id: str | None, since: datetime) -> list[dict]:
    """All xp_events at/after `since`, optionally scoped to one user."""
    filters = {"created_at": f"gte.{since.isoformat()}"}
    if user_id:
        filters["user_id"] = f"eq.{user_id}"
    return list(page_all(
        table("xp_events"),
        "user_id,amount,created_at",
        filters=filters,
        order="created_at.asc,id.asc",
        page=XP_EVENTS_PAGE,
    ))


@dataclass(frozen=True)
class MeInputs:
    """The cheap reads behind the hero card — and `/me`'s ETag inputs.

    Carries the `user_id` it was read for so `me_payload` needs no second
    opinion about whose card it is building. It used to take the id
    separately, which type-checked a transposition —
    `me_payload("userB", read_me_inputs("userA"))` returned userA's totals
    spliced with userB's `today_xp` — with nothing to catch it.
    """

    user_id: str
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

    # Both halves of "N of M" filter to live, or N can exceed M. Migration
    # 20260731194102 demoted ten legacy seeds to draft and deliberately kept
    # the rows people had already earned ("nobody loses a badge"), so counting
    # every user_achievements row against a live-only catalog puts badges in
    # the numerator that are absent from the denominator. `achievements!inner`
    # is what lets the `achievements.status` filter reach the embedded table
    # at all — the same form routes/profile.py's showcase uses, and without
    # the `!inner` PostgREST silently excludes nothing.
    earned = page_all(
        table("user_achievements"),
        "achievement_id,achievements!inner(id)",
        filters={"user_id": f"eq.{user_id}", "achievements.status": "eq.live"},
        # user_id is fixed, so achievement_id alone is the rest of the PK and
        # therefore a total order.
        order="achievement_id.asc",
    )
    catalog = page_all(
        table("achievements"), "id",
        filters={"status": "eq.live"},
        order="id.asc",
    )

    return MeInputs(
        user_id=user_id,
        total_xp=int(u.get("total_xp") or 0),
        level=int(u.get("level") or 1),
        streak=int(u.get("streak_count") or 0),
        longest_streak=int(u.get("longest_streak") or 0),
        daily_goal_xp=int(u.get("daily_goal_xp") or 50),
        earned_count=sum(1 for _ in earned),
        total_count=sum(1 for _ in catalog),
    )


def me_payload(inputs: MeInputs) -> dict:
    """The hero-card payload. `GET /api/gamification/me` returns this verbatim."""
    today = datetime.now(timezone.utc).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    today_xp = sum(
        int(e.get("amount") or 0) for e in events_since(inputs.user_id, today)
    )

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
    return me_payload(read_me_inputs(user_id))
