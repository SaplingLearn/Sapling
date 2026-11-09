"""Achievement reads behind the profile routes (#118, moved from
``routes/profile.py``): the badge grid with progress, and the showcase."""
from datetime import datetime, timezone

from db.connection import table
from services.achievement_service import LOWER_IS_BETTER, get_user_stat
from services.profile.users import _get_or_create_settings


def _get_featured_achievements(user_id: str) -> list:
    # `achievements!inner(...)` + the `achievements.status` filter is the
    # embed-side equivalent of the `status = live` filter every top-level
    # achievements read carries. Without the !inner the filter can't apply to
    # the embedded table at all, and a badge the wiki has since unpublished
    # (or one of the ten legacy seeds 0044 demotes to draft) stays pinned on
    # the showcase — visible to other users, while absent from the grid and
    # the "N of M" count. This showcase is served by GET /api/profile/{id},
    # which other users can read subject to visibility, so a draft leaking
    # here leaks work-in-progress off-team.
    rows = table("user_achievements").select(
        "earned_at,is_featured,"
        "achievements!inner(id,name,slug,description,icon,category,rarity,"
        "is_secret,xp_reward,icon_url,sort_order,status)",
        filters={
            "user_id": f"eq.{user_id}",
            "is_featured": "eq.true",
            "achievements.status": "eq.live",
        },
    )
    if not rows:
        return []
    result = []
    for r in rows:
        ach = r.get("achievements", {})
        if ach:
            result.append({
                "achievement": ach,
                "earned_at": r.get("earned_at"),
                "is_featured": True,
            })
    return result


def achievements_view(user_id: str) -> dict:
    """``{"earned": [...], "available": [...]}`` for ``user_id``: live badges
    only, secret unearned ones masked, unearned ones with progress."""
    # The select must carry every field frontend/src/lib/types.ts::Achievement
    # declares required — the response is cast, never validated, so a missing
    # column surfaces as `+undefined XP` and, worse, `iconUrl={undefined}`,
    # which makes every admin-uploaded icon invisible to users (the admin wiki
    # reads a different endpoint that selects `*`, so admins never see it).
    all_achs = table("achievements").select(
        "id,name,slug,description,icon,category,rarity,is_secret,"
        "xp_reward,icon_url,sort_order,status",
        filters={"status": "eq.live"},
    )
    if not all_achs:
        return {"earned": [], "available": []}

    earned_rows = table("user_achievements").select(
        "achievement_id,earned_at,is_featured",
        filters={"user_id": f"eq.{user_id}"},
    )
    earned_ids = {}
    if earned_rows:
        for r in earned_rows:
            earned_ids[r["achievement_id"]] = r

    # Fetch triggers once and group by achievement_id so we can surface progress.
    trigger_rows = table("achievement_triggers").select(
        "achievement_id,trigger_type,trigger_threshold",
    )
    triggers_by_ach: dict = {}
    for t in trigger_rows or []:
        triggers_by_ach.setdefault(t["achievement_id"], []).append(t)

    # Cache stat lookups per trigger_type — most achievements share a handful of counters.
    stat_cache: dict = {}

    def _progress_for(ach_id: str) -> dict | None:
        ts = triggers_by_ach.get(ach_id)
        if not ts:
            return None
        # Pick the tightest gap (lowest current/target ratio) so the UI tracks the leading edge.
        best = None
        for t in ts:
            tt = t["trigger_type"]
            if tt == "manual_admin_grant":
                continue
            # LOWER_IS_BETTER stats (session_before_hour) count DOWN to their
            # threshold — it's a wall-clock hour, not a target to accumulate
            # towards. "5 of 7" would be nonsense, and the `min(stat, target)`
            # clamp below would render the unearned badge as 100% complete.
            # These badges are pass/fail, so they carry no progress bar.
            if tt in LOWER_IS_BETTER:
                continue
            target = int(t.get("trigger_threshold") or 0)
            if target <= 0:
                continue
            if tt not in stat_cache:
                try:
                    stat_cache[tt] = get_user_stat(user_id, tt)
                except Exception:
                    stat_cache[tt] = 0
            current = min(stat_cache[tt], target)
            ratio = current / target
            if best is None or ratio < best["ratio"]:
                best = {"current": current, "target": target, "ratio": ratio}
        if best is None:
            return None
        return {"current": best["current"], "target": best["target"]}

    earned = []
    available = []

    for ach in all_achs:
        if ach["id"] in earned_ids:
            earned.append({
                "achievement": ach,
                "earned_at": earned_ids[ach["id"]]["earned_at"],
                "is_featured": earned_ids[ach["id"]]["is_featured"],
            })
        else:
            if ach.get("is_secret"):
                # Hand-built rather than a row spread so the masked entry can
                # never leak the real name/description/icon. It still has to
                # carry every field the Achievement type declares required —
                # xp_reward is the honest reward (the UI shows what it pays,
                # which is not a spoiler), icon_url is nulled alongside icon.
                entry = {
                    "id": ach["id"],
                    "name": "Secret Achievement",
                    "slug": ach["slug"],
                    "description": "Keep exploring to discover this achievement",
                    "icon": None,
                    "icon_url": None,
                    "category": ach["category"],
                    "rarity": ach["rarity"],
                    "is_secret": True,
                    "xp_reward": ach.get("xp_reward") or 0,
                    "sort_order": ach.get("sort_order") or 0,
                    "status": ach.get("status") or "live",
                    "progress": None,
                }
            else:
                entry = {**ach, "progress": _progress_for(ach["id"])}
            available.append(entry)

    return {"earned": earned, "available": available}


def replace_featured_achievements(user_id: str, achievement_ids: list) -> None:
    """Make ``achievement_ids`` (already checked as earned) the user's whole
    showcase, on ``user_achievements`` and in ``user_settings``. Raises
    :class:`UserNotFound` if the settings row cannot be had."""
    # Clear old featured flags
    existing = table("user_achievements").select(
        "achievement_id,is_featured",
        filters={"user_id": f"eq.{user_id}", "is_featured": "eq.true"},
    )
    if existing:
        for row in existing:
            table("user_achievements").update(
                {"is_featured": False},
                filters={"user_id": f"eq.{user_id}", "achievement_id": f"eq.{row['achievement_id']}"},
            )

    # Set new featured
    for aid in achievement_ids:
        table("user_achievements").update(
            {"is_featured": True},
            filters={"user_id": f"eq.{user_id}", "achievement_id": f"eq.{aid}"},
        )

    # Also store in settings
    _get_or_create_settings(user_id)
    table("user_settings").update(
        {"featured_achievement_ids": achievement_ids, "updated_at": datetime.now(timezone.utc).isoformat()},
        filters={"user_id": f"eq.{user_id}"},
    )
