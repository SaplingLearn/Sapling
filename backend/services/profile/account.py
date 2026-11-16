"""The account data export (#118, moved from ``routes/profile.py``)."""
from db.connection import table
from services.profile.users import (
    _get_or_create_settings,
    _get_user_or_404,
    _get_user_roles,
)


def export_account_data(user_id: str) -> dict:
    """Everything the user's own export carries. Raises
    :class:`UserNotFound` for a missing or deleted account."""
    user = _get_user_or_404(user_id)
    settings = _get_or_create_settings(user_id)
    roles = _get_user_roles(user_id)

    # Deliberately NOT filtered to status = live, unlike the showcase and the
    # badge grid: this is the user's own data export of what they actually
    # earned. If a badge they hold was later unpublished, omitting it here
    # would make the export a lie about their own history.
    earned = table("user_achievements").select(
        "achievement_id,earned_at,is_featured,achievements(name,slug)",
        filters={"user_id": f"eq.{user_id}"},
    )

    owned_cosmetics = table("user_cosmetics").select(
        "cosmetic_id,unlocked_at,cosmetics(name,slug,type)",
        filters={"user_id": f"eq.{user_id}"},
    )

    return {
        "user": user,
        "settings": settings,
        "roles": roles,
        "achievements": earned or [],
        "cosmetics": owned_cosmetics or [],
    }
