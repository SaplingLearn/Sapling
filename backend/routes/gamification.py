"""Gamification read endpoints — hero card, leaderboards, activity charts.

Everything here derives from the xp_events ledger. Responses carry
app-decrypted display names, so Cache-Control is always `private` (#99).

Every endpoint here takes `user_id` as a query parameter, which is a claim,
never an identity — so each one opens with `require_self(user_id, request)`,
the same guard routes/social.py and routes/profile.py use. There is no global
auth middleware and the router is mounted without `dependencies=`, so the
in-handler call IS the authorization. Without it `?user_id=<victim>` reads
another user's XP/streaks and `leaderboard?scope=friends` reads their whole
friends list, both with app-decrypted display names and no cookie.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, HTTPException, Request

from db.connection import table
from services import academics
from services.auth_guard import require_self
from services.gamification_service import events_since, me_payload, read_me_inputs
from services.growth import stage_for_level
from services.http_cache import (
    REVALIDATE_CACHE_CONTROL,
    cached_json,
    conditional,
    make_etag,
)
from services.profiles import get_display_names

router = APIRouter()

SCOPES = ("everyone", "friends", "school")


def _parse_ts(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _week_start(now: datetime) -> datetime:
    """Monday 00:00 UTC of the current week — the leaderboard reset boundary."""
    monday = now - timedelta(days=now.weekday())
    return monday.replace(hour=0, minute=0, second=0, microsecond=0)


@router.get("/me")
def get_me(user_id: str, request: Request):
    """The hero card. The payload itself is built by
    `services/gamification_service.py` — POST /api/quiz/submit returns the same
    snapshot inline (G8), and the two must never be able to disagree."""
    require_self(user_id, request)
    inputs = read_me_inputs(user_id)

    # NOTE: daily_goal_xp is echoed in this payload below but is not one of
    # the etag inputs. It's inert today — nothing writes users.daily_goal_xp
    # yet. If a settings path starts writing it, add it to make_etag's args
    # here or clients will keep serving a stale 304 after it changes.
    etag = make_etag(user_id, inputs.total_xp, inputs.level, inputs.earned_count)
    not_mod = conditional(request, etag, REVALIDATE_CACHE_CONTROL)
    if not_mod:
        return not_mod

    return cached_json(me_payload(user_id, inputs), etag, REVALIDATE_CACHE_CONTROL)


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
    require_self(user_id, request)
    if scope not in SCOPES:
        raise HTTPException(status_code=400, detail=f"scope must be one of {SCOPES}")

    now = datetime.now(timezone.utc)
    start = _week_start(now)
    events = events_since(None, start)

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
    ranked = sorted(ids, key=lambda i: (-weekly.get(i, 0), i))

    # The ETag has to key on the ranking ITSELF, not on (count, total). Those
    # two summary numbers are preserved by any reshuffle that keeps the same
    # people and the same overall XP — u1:100/u2:200 becoming u1:150/u2:150
    # scores identically — so first and second place could swap and every
    # viewer would keep getting a 304 for the stale order until someone's
    # award happened to move the total. Ranked (id, xp) pairs change whenever
    # the board does.
    #
    # Still NOT covered, same caveat as daily_goal_xp on /me above: level,
    # streak_count and display name are rendered here but aren't etag inputs,
    # so a rename alone won't bust the cache. `no-cache` keeps that to one
    # stale revalidation rather than a 30s blind window.
    etag = make_etag(user_id, scope, *[f"{i}:{weekly.get(i, 0)}" for i in ranked])
    not_mod = conditional(request, etag, REVALIDATE_CACHE_CONTROL)
    if not_mod:
        return not_mod

    users = table("users").select(
        "id,level,total_xp,streak_count", filters={"id": f"in.({','.join(ids)})"}
    ) if ids else []
    names = get_display_names(ids) if ids else {}
    by_id = {u["id"]: u for u in users or []}
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
    }, etag, REVALIDATE_CACHE_CONTROL)


@router.get("/activity")
def get_activity(user_id: str, request: Request):
    require_self(user_id, request)
    now = datetime.now(timezone.utc)
    today = now.replace(hour=0, minute=0, second=0, microsecond=0)
    since = today - timedelta(days=55)          # 8 weeks back
    events = events_since(user_id, since)

    # NOTE: daily_goal_xp is echoed in this payload below but is not one of
    # the etag inputs. It's inert today — nothing writes users.daily_goal_xp
    # yet. If a settings path starts writing it, add it to make_etag's args
    # here or clients will keep serving a stale 304 after it changes.
    etag = make_etag(user_id, len(events),
                     sum(int(e.get("amount") or 0) for e in events))
    not_mod = conditional(request, etag, REVALIDATE_CACHE_CONTROL)
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
    }, etag, REVALIDATE_CACHE_CONTROL)
