"""Equipped and owned cosmetics behind the profile routes (#118, moved from
``routes/profile.py``)."""
from db.connection import table


def _get_equipped_cosmetics(settings: dict) -> dict:
    equipped = {}
    slot_map = {
        "avatar_frame": "equipped_avatar_frame_id",
        "banner": "equipped_banner_id",
        "name_color": "equipped_name_color_id",
        "title": "equipped_title_id",
    }
    for slot, col in slot_map.items():
        cosmetic_id = settings.get(col)
        if cosmetic_id:
            rows = table("cosmetics").select(
                "id,type,name,slug,asset_url,css_value,rarity",
                filters={"id": f"eq.{cosmetic_id}"},
            )
            if rows:
                equipped[slot] = rows[0]
    # Featured role
    featured_role_id = settings.get("featured_role_id")
    if featured_role_id:
        rows = table("roles").select(
            "id,name,slug,color,icon,description,is_staff_assigned,is_earnable,display_priority",
            filters={"id": f"eq.{featured_role_id}"},
        )
        if rows:
            equipped["featured_role"] = rows[0]
    return equipped


def _strip_role_cosmetics(equipped: dict) -> dict:
    """`equipped` minus anything that reveals a role, for anonymous viewers
    (#115): the featured role itself, and every equipped cosmetic a role grants
    (`role_cosmetics`). Conservative: a cosmetic granted by ANY role goes, staff
    or earnable, since the slot alone cannot say which."""
    out = {k: v for k, v in equipped.items() if k != "featured_role"}
    ids = [c["id"] for c in out.values() if isinstance(c, dict) and c.get("id")]
    if not ids:
        return out
    granted = {
        r["cosmetic_id"]
        for r in table("role_cosmetics").select(
            "cosmetic_id", filters={"cosmetic_id": f"in.({','.join(ids)})"}
        ) or []
    }
    return {k: v for k, v in out.items() if v.get("id") not in granted}


def owned_cosmetics_by_type(user_id: str) -> dict:
    """The cosmetics ``user_id`` owns, grouped by slot type."""
    owned = table("user_cosmetics").select(
        "unlocked_at,cosmetics(id,type,name,slug,asset_url,css_value,rarity)",
        filters={"user_id": f"eq.{user_id}"},
    )

    grouped = {"avatar_frame": [], "banner": [], "name_color": [], "title": []}
    if owned:
        for row in owned:
            cosmetic = row.get("cosmetics", {})
            if cosmetic and cosmetic.get("type") in grouped:
                grouped[cosmetic["type"]].append({
                    "cosmetic": cosmetic,
                    "unlocked_at": row["unlocked_at"],
                })
    return grouped


def cosmetics_catalog(user_id: str) -> dict:
    """All cosmetics grouped by type with an `owned` flag per item."""
    all_cosmetics = table("cosmetics").select("id,type,name,slug,asset_url,css_value,rarity,unlock_source")
    owned_rows = table("user_cosmetics").select(
        "cosmetic_id",
        filters={"user_id": f"eq.{user_id}"},
    )
    owned_ids = {r["cosmetic_id"] for r in (owned_rows or [])}

    grouped: dict = {"avatar_frame": [], "banner": [], "name_color": [], "title": []}
    for c in all_cosmetics or []:
        if c.get("type") not in grouped:
            continue
        grouped[c["type"]].append({**c, "owned": c["id"] in owned_ids})
    return grouped
