"""Gamification read endpoints — hero card, leaderboards, activity charts.

Everything here derives from the xp_events ledger. Responses carry
app-decrypted display names, so Cache-Control is always `private` (#99).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, HTTPException, Request

from db.connection import table
from services import academics
from services.growth import stage_for_level, xp_into_level
from services.http_cache import cached_json, conditional, make_etag
from services.profiles import get_display_names

router = APIRouter()

SCOPES = ("everyone", "friends", "school")

# supabase/config.toml sets PostgREST's `max_rows = 1000`. A page past that
# cap doesn't error — PostgREST returns 206 Partial Content, which is a 2xx,
# so db/connection.py's raise_for_status() never fires; the truncation is
# silent by construction. _events_since backs the leaderboard's weekly-XP
# aggregation (and /me and /activity), so an unbounded single call here would
# silently corrupt totals and rank order once platform-wide weekly events
# cross this cap. Keep this at or below max_rows and page to completion.
_XP_EVENTS_PAGE = 1000


def _parse_ts(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _events_since(user_id: str | None, since: datetime) -> list[dict]:
    """All xp_events at/after `since`, optionally scoped to one user.

    Pages to completion via select_with_count rather than a single unbounded
    select — see _XP_EVENTS_PAGE. The `created_at,id` order is required for
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
            limit=_XP_EVENTS_PAGE,
            offset=offset,
        )
        out.extend(rows or [])
        if not rows or len(out) >= total:
            break
        offset += _XP_EVENTS_PAGE
    return out


def _week_start(now: datetime) -> datetime:
    """Monday 00:00 UTC of the current week — the leaderboard reset boundary."""
    monday = now - timedelta(days=now.weekday())
    return monday.replace(hour=0, minute=0, second=0, microsecond=0)


@router.get("/me")
def get_me(user_id: str, request: Request):
    rows = table("users").select(
        "total_xp,level,streak_count,longest_streak,daily_goal_xp",
        filters={"id": f"eq.{user_id}"},
    )
    u = rows[0] if rows else {}
    total_xp = int(u.get("total_xp") or 0)
    level = int(u.get("level") or 1)

    earned = table("user_achievements").select(
        "achievement_id", filters={"user_id": f"eq.{user_id}"}
    ) or []
    # Live only — a work-in-progress badge must not inflate "12 of 30".
    catalog = table("achievements").select("id", filters={"status": "eq.live"}) or []

    # NOTE: daily_goal_xp is echoed in this payload below but is not one of
    # the etag inputs. It's inert today — nothing writes users.daily_goal_xp
    # yet. If a settings path starts writing it, add it to make_etag's args
    # here or clients will keep serving a stale 304 after it changes.
    etag = make_etag(user_id, total_xp, level, len(earned))
    not_mod = conditional(request, etag)
    if not_mod:
        return not_mod

    today = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    today_xp = sum(int(e.get("amount") or 0) for e in _events_since(user_id, today))

    into, for_level = xp_into_level(total_xp)
    stage = stage_for_level(level)
    return cached_json({
        "level": level,
        "next_level": level + 1,
        "stage": {"slug": stage.get("slug"), "name": stage.get("name"),
                  "blurb": stage.get("blurb")},
        "total_xp": total_xp,
        "xp_into_level": into,
        "xp_for_level": for_level,
        "level_pct": round(into / for_level * 100) if for_level else 100,
        "streak": int(u.get("streak_count") or 0),
        "longest_streak": int(u.get("longest_streak") or 0),
        "daily_goal_xp": int(u.get("daily_goal_xp") or 50),
        "today_xp": today_xp,
        "earned_count": len(earned),
        "total_count": len(catalog),
    }, etag)


def _scope_ids(user_id: str, scope: str) -> set[str] | None:
    """Candidate user ids for a scope. None means 'no restriction'."""
    if scope == "friends":
        rows = table("friendships").select(
            "friend_id", filters={"user_id": f"eq.{user_id}"}
        ) or []
        return {r["friend_id"] for r in rows} | {user_id}
    if scope == "school":
        # `school` is NOT a column on user_profiles after the 0024 identity
        # split — it resolves through the enrollment chain. Reuse the same
        # fail-closed resolver GET /api/social/students uses (#342) rather than
        # reinventing it: an unenrolled viewer sees only themselves.
        peers = academics.school_peer_user_ids(user_id)
        return set(peers) | {user_id} if peers else {user_id}
    return None


def _private_ids() -> set[str]:
    rows = table("user_settings").select(
        "user_id,profile_visibility", filters={"profile_visibility": "eq.private"}
    ) or []
    return {r["user_id"] for r in rows}


@router.get("/leaderboard")
def get_leaderboard(user_id: str, request: Request, scope: str = "everyone"):
    if scope not in SCOPES:
        raise HTTPException(status_code=400, detail=f"scope must be one of {SCOPES}")

    now = datetime.now(timezone.utc)
    start = _week_start(now)
    events = _events_since(None, start)

    weekly: dict[str, int] = {}
    for e in events:
        uid = e.get("user_id")
        if uid:
            weekly[uid] = weekly.get(uid, 0) + int(e.get("amount") or 0)

    allowed = _scope_ids(user_id, scope)
    if allowed is not None:
        weekly = {k: v for k, v in weekly.items() if k in allowed}

    # The viewer always sees their own row, even at zero and even when private.
    weekly.setdefault(user_id, 0)

    hidden = _private_ids() - {user_id} if scope in ("everyone", "school") else set()

    ids = [k for k in weekly if k not in hidden]
    etag = make_etag(user_id, scope, len(ids), sum(weekly.get(i, 0) for i in ids))
    not_mod = conditional(request, etag)
    if not_mod:
        return not_mod

    users = table("users").select(
        "id,level,total_xp,streak_count", filters={"id": f"in.({','.join(ids)})"}
    ) if ids else []
    names = get_display_names(ids) if ids else {}
    by_id = {u["id"]: u for u in users or []}

    ranked = sorted(ids, key=lambda i: (-weekly.get(i, 0), i))
    rows, you = [], None
    for rank, uid in enumerate(ranked, start=1):
        u = by_id.get(uid, {})
        level = int(u.get("level") or 1)
        row = {
            "rank": rank,
            "user_id": uid,
            "name": names.get(uid, "Someone"),
            "level": level,
            "stage": stage_for_level(level).get("name"),
            "total_xp": int(u.get("total_xp") or 0),
            "week_xp": weekly.get(uid, 0),
            "streak": int(u.get("streak_count") or 0),
            "is_you": uid == user_id,
        }
        rows.append(row)
        if row["is_you"]:
            you = row

    return cached_json({
        "rows": rows,
        "you": you,
        "resets_at": (start + timedelta(days=7)).isoformat(),
    }, etag)


@router.get("/activity")
def get_activity(user_id: str, request: Request):
    now = datetime.now(timezone.utc)
    today = now.replace(hour=0, minute=0, second=0, microsecond=0)
    since = today - timedelta(days=55)          # 8 weeks back
    events = _events_since(user_id, since)

    # NOTE: daily_goal_xp is echoed in this payload below but is not one of
    # the etag inputs. It's inert today — nothing writes users.daily_goal_xp
    # yet. If a settings path starts writing it, add it to make_etag's args
    # here or clients will keep serving a stale 304 after it changes.
    etag = make_etag(user_id, len(events),
                     sum(int(e.get("amount") or 0) for e in events))
    not_mod = conditional(request, etag)
    if not_mod:
        return not_mod

    daily: dict[str, int] = {}
    for e in events:
        ts = _parse_ts(e.get("created_at"))
        if ts:
            key = ts.date().isoformat()
            daily[key] = daily.get(key, 0) + int(e.get("amount") or 0)

    week = []
    for offset in range(6, -1, -1):
        day = (today - timedelta(days=offset)).date()
        week.append({"day": day.strftime("%a"), "date": day.isoformat(),
                     "xp": daily.get(day.isoformat(), 0)})

    trend = []
    for w in range(7, -1, -1):
        start = today - timedelta(days=now.weekday() + 7 * w)
        total = sum(
            daily.get((start + timedelta(days=d)).date().isoformat(), 0)
            for d in range(7)
        )
        # %-d is POSIX-only and raises on Windows; build the label manually.
        label = "This" if w == 0 else f"{start.strftime('%b')} {start.day}"
        trend.append({"label": label, "xp": total})

    urow = table("users").select(
        "streak_count,daily_goal_xp", filters={"id": f"eq.{user_id}"}
    )
    u = urow[0] if urow else {}
    week_total = sum(d["xp"] for d in week)
    active = [d for d in week if d["xp"] > 0]
    best = max(week, key=lambda d: d["xp"]) if week else {"xp": 0, "day": ""}

    return cached_json({
        "week": week,
        "trend": trend,
        "daily_goal_xp": int(u.get("daily_goal_xp") or 50),
        "tiles": {
            "week_total": week_total,
            "daily_avg": round(week_total / len(active)) if active else 0,
            "best_day": best["xp"],
            "best_day_label": best["day"],
            "streak": int(u.get("streak_count") or 0),
        },
    }, etag)
