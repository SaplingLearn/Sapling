"""
Achievement checker service.
Called synchronously after events to grant achievements when thresholds are met.
"""

from datetime import datetime, timedelta, timezone
from db.connection import table
from services.xp_service import award_xp_safe


def _count_rows(table_name: str, filters: dict) -> int:
    rows = table(table_name).select("id", filters=filters)
    return len(rows) if rows else 0


def get_user_stat(user_id: str, trigger_type: str) -> int:
    """Public wrapper around the internal stat lookup."""
    return _get_user_stat(user_id, trigger_type)


def _get_user_stat(user_id: str, trigger_type: str) -> int:
    """Evaluate the current value for a trigger type."""
    if trigger_type == "login_streak":
        user = table("users").select("streak_count", filters={"id": f"eq.{user_id}"})
        if user:
            return user[0].get("streak_count", 0) or 0
        return 0

    if trigger_type == "session_count":
        return _count_rows("sessions", {"user_id": f"eq.{user_id}"})

    if trigger_type == "documents_uploaded":
        return _count_rows("documents", {"user_id": f"eq.{user_id}"})

    if trigger_type == "quizzes_completed":
        return _count_rows("quiz_attempts", {"user_id": f"eq.{user_id}"})

    if trigger_type == "rooms_joined":
        return _count_rows("room_members", {"user_id": f"eq.{user_id}"})

    if trigger_type == "flashcards_created":
        return _count_rows("flashcards", {"user_id": f"eq.{user_id}"})

    if trigger_type == "post_count":
        return _count_rows("room_messages", {"user_id": f"eq.{user_id}"})

    if trigger_type == "account_age_days":
        user = table("users").select("created_at", filters={"id": f"eq.{user_id}"})
        if user and user[0].get("created_at"):
            created = datetime.fromisoformat(user[0]["created_at"].replace("Z", "+00:00"))
            delta = datetime.now(timezone.utc) - created
            return delta.days
        return 0

    if trigger_type == "manual_admin_grant":
        return 0  # Handled directly by admin endpoint

    if trigger_type == "flashcards_reviewed":
        rows = table("flashcards").select(
            "times_reviewed", filters={"user_id": f"eq.{user_id}"}
        )
        return sum(int(r.get("times_reviewed") or 0) for r in rows or [])

    if trigger_type == "concepts_mastered":
        return _count_rows("graph_nodes", {
            "user_id": f"eq.{user_id}", "mastery_tier": "eq.mastered",
        })

    if trigger_type == "courses_with_mastery":
        rows = table("graph_nodes").select(
            "course_id",
            filters={"user_id": f"eq.{user_id}", "mastery_tier": "eq.mastered"},
        )
        return len({r["course_id"] for r in rows or [] if r.get("course_id")})

    if trigger_type == "graph_nodes_count":
        return _count_rows("graph_nodes", {"user_id": f"eq.{user_id}"})

    if trigger_type == "friends_count":
        return _count_rows("friendships", {"user_id": f"eq.{user_id}"})

    if trigger_type == "level":
        rows = table("users").select("level", filters={"id": f"eq.{user_id}"})
        return int(rows[0].get("level") or 1) if rows else 1

    if trigger_type in ("session_minutes", "session_before_hour", "session_after_midnight"):
        return _session_stat(user_id, trigger_type)

    if trigger_type == "xp_in_day":
        return _best_day_xp(user_id)

    if trigger_type == "goal_streak":
        return _goal_streak(user_id)

    if trigger_type == "owned_room_members":
        rooms = table("rooms").select("id", filters={"created_by": f"eq.{user_id}"})
        best = 0
        for room in rooms or []:
            best = max(best, _count_rows("room_members", {"room_id": f"eq.{room['id']}"}))
        return best

    if trigger_type == "rooms_active":
        rows = table("room_messages").select(
            "room_id", filters={"user_id": f"eq.{user_id}"}
        )
        return len({r["room_id"] for r in rows or [] if r.get("room_id")})

    if trigger_type == "room_replies":
        owned = {
            r["id"] for r in
            (table("rooms").select("id", filters={"created_by": f"eq.{user_id}"}) or [])
        }
        rows = table("room_messages").select(
            "room_id", filters={"user_id": f"eq.{user_id}"}
        )
        return sum(1 for r in rows or [] if r.get("room_id") not in owned)

    return 0


def _parse_ts(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _session_stat(user_id: str, trigger_type: str) -> int:
    """Longest session in minutes, or whether one ended in a given window.

    Timestamps are UTC — sessions carry no timezone, so 'before 7am' means
    07:00 UTC. Documented rather than guessed at per-user.
    """
    rows = table("sessions").select(
        "started_at,ended_at", filters={"user_id": f"eq.{user_id}"}
    ) or []
    best = 0
    for r in rows:
        started, ended = _parse_ts(r.get("started_at")), _parse_ts(r.get("ended_at"))
        if not ended:
            continue
        if trigger_type == "session_minutes":
            if started:
                best = max(best, int((ended - started).total_seconds() // 60))
        elif trigger_type == "session_before_hour":
            # Report the earliest finish as "hours before 24" so a plain
            # `value >= threshold` comparison still works for an "earlier is
            # better" stat: finishing at 05:00 yields 19, which clears 7.
            best = max(best, 24 - ended.hour if ended.hour < 12 else 0)
        elif trigger_type == "session_after_midnight":
            best = max(best, 1 if 0 <= ended.hour < 4 else 0)
    return best


def _daily_totals(user_id: str) -> dict:
    rows = table("xp_events").select(
        "amount,created_at", filters={"user_id": f"eq.{user_id}"}
    ) or []
    totals: dict = {}
    for r in rows:
        ts = _parse_ts(r.get("created_at"))
        if not ts:
            continue
        day = ts.date().isoformat()
        totals[day] = totals.get(day, 0) + int(r.get("amount") or 0)
    return totals


def _best_day_xp(user_id: str) -> int:
    totals = _daily_totals(user_id)
    return max(totals.values()) if totals else 0


def _goal_streak(user_id: str) -> int:
    """Consecutive days, counting back from today, that met the daily goal."""
    rows = table("users").select("daily_goal_xp", filters={"id": f"eq.{user_id}"})
    goal = int(rows[0].get("daily_goal_xp") or 50) if rows else 50
    totals = _daily_totals(user_id)
    streak, day = 0, datetime.now(timezone.utc).date()
    while totals.get(day.isoformat(), 0) >= goal:
        streak += 1
        day -= timedelta(days=1)
    return streak


def check_achievements(user_id: str, event_type: str, event_data: dict = None) -> list:
    """
    Check and grant achievements for a user after an event.
    Returns list of newly granted achievements as {"slug", "name", "xp"} dicts.
    """
    if event_data is None:
        event_data = {}

    newly_earned = []

    # Find triggers matching the event type
    triggers = table("achievement_triggers").select(
        "id,achievement_id,trigger_type,trigger_threshold",
        filters={"trigger_type": f"eq.{event_type}"},
    )
    if not triggers:
        return newly_earned

    # Get user's existing achievements to avoid re-granting
    existing = table("user_achievements").select(
        "achievement_id",
        filters={"user_id": f"eq.{user_id}"},
    )
    existing_ids = {row["achievement_id"] for row in existing} if existing else set()

    # Get the current stat value for this event type
    current_value = _get_user_stat(user_id, event_type)

    for trigger in triggers:
        achievement_id = trigger["achievement_id"]

        # Skip if already earned
        if achievement_id in existing_ids:
            continue

        # Check threshold
        if current_value < trigger["trigger_threshold"]:
            continue

        # Resolve the badge BEFORE granting: a 'draft' achievement is
        # work-in-progress in the admin wiki and must never reach a user.
        achievement = table("achievements").select(
            "slug,name,xp_reward,status", filters={"id": f"eq.{achievement_id}"}
        )
        if not achievement:
            continue
        row = achievement[0]
        if row.get("status") != "live":
            continue

        table("user_achievements").insert({
            "user_id": user_id,
            "achievement_id": achievement_id,
            "earned_at": datetime.now(timezone.utc).isoformat(),
            "is_featured": False,
        })

        reward = int(row.get("xp_reward") or 0)
        if reward:
            award_xp_safe(
                user_id, "achievement_unlocked",
                source_type="achievement", source_id=achievement_id,
                amount=reward,
            )
        newly_earned.append({"slug": row["slug"], "name": row["name"], "xp": reward})

        # Grant linked cosmetics
        linked_cosmetics = table("achievement_cosmetics").select(
            "cosmetic_id", filters={"achievement_id": f"eq.{achievement_id}"}
        )
        if linked_cosmetics:
            for lc in linked_cosmetics:
                table("user_cosmetics").insert({
                    "user_id": user_id,
                    "cosmetic_id": lc["cosmetic_id"],
                    "unlocked_at": datetime.now(timezone.utc).isoformat(),
                })

    return newly_earned
