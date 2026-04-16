"""
Achievement checker service.
Called synchronously after events to grant achievements when thresholds are met.
"""

from datetime import datetime, timezone
from db.connection import table


def _count_rows(table_name: str, filters: dict) -> int:
    rows = table(table_name).select("id", filters=filters)
    return len(rows) if rows else 0


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

    return 0


def check_achievements(user_id: str, event_type: str, event_data: dict = None) -> list:
    """
    Check and grant achievements for a user after an event.
    Returns list of newly granted achievement slugs.
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

        # Grant the achievement
        table("user_achievements").insert({
            "user_id": user_id,
            "achievement_id": achievement_id,
            "earned_at": datetime.now(timezone.utc).isoformat(),
            "is_featured": False,
        })

        # Look up achievement slug for return value
        achievement = table("achievements").select(
            "slug", filters={"id": f"eq.{achievement_id}"}
        )
        if achievement:
            newly_earned.append(achievement[0]["slug"])

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
