"""
backend/services/admin/achievements.py

Admin achievement management: the catalog CRUD, icon upload, manual
grant (XP + linked cosmetics, like the earned path), triggers and
achievement↔cosmetic links.

Moved verbatim out of ``routes/admin.py`` (#118); the route keeps the
auth checks and maps ``services.admin.errors`` to HTTP statuses.
"""
from __future__ import annotations

import base64
import logging
from datetime import datetime, timezone

from db.connection import table
from models import (
    AchievementIconBody,
    CreateAchievementBody,
    CreateAchievementTriggerBody,
    GrantAchievementBody,
    LinkAchievementCosmeticBody,
    UpdateAchievementTriggerBody,
)
from services.achievement_service import check_achievements, grant_linked_cosmetics
from services.admin.errors import Conflict, InvalidRequest, NotFound, Unprocessable
from services.admin_audit import log_admin_action
from services.storage_service import upload_achievement_icon
from services.xp_service import award_xp_safe

logger = logging.getLogger(__name__)


def list_achievements():
    rows = table("achievements").select("*", order="created_at.desc")
    return {"achievements": rows or []}


def create_achievement(body: CreateAchievementBody, actor: str | None):
    result = table("achievements").insert({
        "name": body.name,
        "slug": body.slug,
        "description": body.description,
        "icon": body.icon,
        "category": body.category,
        "rarity": body.rarity,
        "is_secret": body.is_secret,
    })
    log_admin_action(
        actor_id=actor, action="achievement.create", target_type="achievement",
        target_id=result[0]["id"] if result else None,
        payload={"slug": body.slug, "name": body.name},
    )
    return {"achievement": result[0] if result else None}


def update_achievement(achievement_id: str, body: dict, actor: str | None):
    allowed = {"name", "description", "icon", "icon_url", "category", "rarity",
               "is_secret", "xp_reward", "sort_order", "status"}
    updates = {k: v for k, v in body.items() if k in allowed}
    if not updates:
        raise InvalidRequest("No valid fields to update")
    # Mirror achievements_status_check (20260731193214) so a bad value is a
    # 422 here, not a CHECK violation surfacing as a 500 (#767).
    #
    # live → draft is UNPUBLISH, not revoke: existing user_achievements rows
    # (and the XP/cosmetics they paid) are kept, but every user-facing read
    # filters to live (profile list + showcase, the hero card's N of M), so the
    # badge disappears for everyone, and check_achievements neither grants it
    # nor heals it while it is a draft. Publishing it again restores it as it
    # was — the same contract 20260731194102 used to demote legacy seeds.
    if "status" in updates and updates["status"] not in ("draft", "live"):
        raise Unprocessable("status must be 'draft' or 'live'")
    table("achievements").update(updates, filters={"id": f"eq.{achievement_id}"})
    log_admin_action(
        actor_id=actor, action="achievement.update", target_type="achievement",
        target_id=achievement_id, payload=updates,
    )
    return {"updated": True}


def upload_icon(achievement_id: str, body: AchievementIconBody, actor: str | None):
    try:
        file_bytes = base64.b64decode(body.file_base64, validate=True)
    except Exception:
        raise InvalidRequest("file_base64 is not valid base64")
    icon_url = upload_achievement_icon(achievement_id, file_bytes, body.content_type)
    table("achievements").update(
        {"icon_url": icon_url}, filters={"id": f"eq.{achievement_id}"}
    )
    log_admin_action(
        actor_id=actor, action="achievement.icon", target_type="achievement",
        target_id=achievement_id, payload={"icon_url": icon_url},
    )
    return {"icon_url": icon_url}


def unlink_achievement_cosmetic(body: LinkAchievementCosmeticBody, actor: str | None):
    table("achievement_cosmetics").delete(filters={
        "achievement_id": f"eq.{body.achievement_id}",
        "cosmetic_id": f"eq.{body.cosmetic_id}",
    })
    log_admin_action(
        actor_id=actor, action="achievement_cosmetic.unlink",
        target_type="achievement_cosmetic", target_id=body.achievement_id,
        payload={"cosmetic_id": body.cosmetic_id},
    )
    return {"unlinked": True}


def delete_achievement(achievement_id: str, actor: str | None):
    table("achievements").delete(filters={"id": f"eq.{achievement_id}"})
    log_admin_action(
        actor_id=actor, action="achievement.delete", target_type="achievement",
        target_id=achievement_id,
    )
    return {"deleted": True}


def grant_achievement(body: GrantAchievementBody, actor: str | None):

    # Resolve the badge BEFORE granting: a 'draft' achievement is
    # work-in-progress in the admin wiki and must never reach a user.
    achievement = table("achievements").select(
        "id,slug,status,xp_reward", filters={"id": f"eq.{body.achievement_id}"},
    )
    if not achievement:
        raise NotFound("Achievement not found")
    achievement_row = achievement[0]
    if achievement_row.get("status") != "live":
        raise Conflict(
            f"Achievement '{achievement_row.get('slug')}' is a draft — "
            f"publish it before granting.",
        )

    # Check if already earned
    existing = table("user_achievements").select(
        "achievement_id",
        filters={"user_id": f"eq.{body.user_id}", "achievement_id": f"eq.{body.achievement_id}"},
    )
    if existing:
        raise Conflict("User already has this achievement")

    table("user_achievements").insert({
        "user_id": body.user_id,
        "achievement_id": body.achievement_id,
        "earned_at": datetime.now(timezone.utc).isoformat(),
        "is_featured": False,
    })
    log_admin_action(
        actor_id=actor, action="achievement.grant", target_type="achievement",
        target_id=body.achievement_id, payload={"user_id": body.user_id},
    )

    # Pay the badge's xp_reward, exactly as achievement_service.check_achievements
    # does on the earned path. `mentor`, `comeback`, `secret` and `methuselah`
    # are manual-grant-only, so without this they paid 0 and two users with
    # identical badge sets ended up with different XP totals. Same rule_key +
    # source_id as the earned path, so the xp_events idempotency key makes a
    # re-grant (or an earned-then-granted badge) a clean no-op rather than a
    # double payout. _safe: XP must never fail the grant that earned it.
    reward = int(achievement_row.get("xp_reward") or 0)
    if reward:
        award_xp_safe(
            body.user_id, "achievement_unlocked",
            source_type="achievement", source_id=body.achievement_id,
            amount=reward,
        )

    # Unlock the badge's linked cosmetics, exactly as the earned path does.
    # This must be the direct call, NOT check_achievements: _get_user_stat
    # returns a hard-coded 0 for `manual_admin_grant` and every such trigger
    # in the catalog has a threshold of 1, so the dispatch below skips every
    # trigger and grants nothing. `mentor`, `comeback`, `secret` and
    # `methuselah` are manual-grant-only, so their cosmetics were unreachable.
    # Post-commit: the badge row and its XP are already written, so a failure
    # here must not 500 a grant that did succeed.
    try:
        grant_linked_cosmetics(body.user_id, body.achievement_id)
    except Exception:
        logger.exception(
            "linked cosmetics failed after admin grant user=%s achievement=%s",
            body.user_id, body.achievement_id,
        )

    # Kept for the cosmetics linked to OTHER achievements this grant may now
    # qualify the user for (check_achievements re-evaluates every
    # manual_admin_grant trigger they haven't earned).
    check_achievements(body.user_id, "manual_admin_grant", {})

    return {"granted": True}


def create_trigger(body: CreateAchievementTriggerBody, actor: str | None):
    result = table("achievement_triggers").insert({
        "achievement_id": body.achievement_id,
        "trigger_type": body.trigger_type,
        "trigger_threshold": body.trigger_threshold,
    })
    log_admin_action(
        actor_id=actor, action="trigger.create", target_type="trigger",
        target_id=result[0]["id"] if result else None,
        payload={
            "achievement_id": body.achievement_id,
            "trigger_type": body.trigger_type,
            "trigger_threshold": body.trigger_threshold,
        },
    )
    return {"trigger": result[0] if result else None}


def list_triggers(achievement_id: str):
    rows = table("achievement_triggers").select(
        "id,achievement_id,trigger_type,trigger_threshold",
        filters={"achievement_id": f"eq.{achievement_id}"},
    )
    return {"triggers": rows or []}


def update_trigger(trigger_id: str, body: UpdateAchievementTriggerBody, actor: str | None):
    updates = {k: v for k, v in body.model_dump(exclude_unset=True).items() if v is not None}
    if not updates:
        raise InvalidRequest("No valid fields to update")
    table("achievement_triggers").update(updates, filters={"id": f"eq.{trigger_id}"})
    log_admin_action(actor_id=actor, action="trigger.update", target_type="trigger", target_id=trigger_id, payload=updates)
    return {"updated": True}


def delete_trigger(trigger_id: str, actor: str | None):
    table("achievement_triggers").delete(filters={"id": f"eq.{trigger_id}"})
    log_admin_action(actor_id=actor, action="trigger.delete", target_type="trigger", target_id=trigger_id)
    return {"deleted": True}


def list_achievement_cosmetics(achievement_id: str):
    rows = table("achievement_cosmetics").select(
        "achievement_id,cosmetic_id",
        filters={"achievement_id": f"eq.{achievement_id}"},
    )
    return {"links": rows or []}


def link_achievement_cosmetic(body: LinkAchievementCosmeticBody, actor: str | None):
    table("achievement_cosmetics").upsert(
        {"achievement_id": body.achievement_id, "cosmetic_id": body.cosmetic_id},
        on_conflict="achievement_id,cosmetic_id",
    )
    log_admin_action(
        actor_id=actor, action="achievement_cosmetic.link",
        target_type="achievement_cosmetic", target_id=body.achievement_id,
        payload={"cosmetic_id": body.cosmetic_id},
    )
    return {"linked": True}
