"""
backend/services/admin/cosmetics.py

Admin cosmetic catalog CRUD.

Moved verbatim out of ``routes/admin.py`` (#118); the route keeps the
auth checks and maps ``services.admin.errors`` to HTTP statuses.
"""
from __future__ import annotations

from db.connection import table
from models import CreateCosmeticBody
from services.admin.errors import InvalidRequest
from services.admin_audit import log_admin_action


def list_cosmetics():
    rows = table("cosmetics").select("*", order="type.asc")
    return {"cosmetics": rows or []}


def create_cosmetic(body: CreateCosmeticBody, actor: str | None):
    result = table("cosmetics").insert({
        "type": body.type,
        "name": body.name,
        "slug": body.slug,
        "asset_url": body.asset_url,
        "css_value": body.css_value,
        "rarity": body.rarity,
        "unlock_source": body.unlock_source,
    })
    log_admin_action(
        actor_id=actor, action="cosmetic.create",
        target_type="cosmetic", target_id=result[0]["id"] if result else None,
        payload={"slug": body.slug, "name": body.name, "type": body.type},
    )
    return {"cosmetic": result[0] if result else None}


def update_cosmetic(cosmetic_id: str, body: dict, actor: str | None):
    allowed = {"name", "asset_url", "css_value", "rarity", "unlock_source"}
    updates = {k: v for k, v in body.items() if k in allowed}
    if not updates:
        raise InvalidRequest("No valid fields to update")
    table("cosmetics").update(updates, filters={"id": f"eq.{cosmetic_id}"})
    log_admin_action(
        actor_id=actor, action="cosmetic.update",
        target_type="cosmetic", target_id=cosmetic_id, payload=updates,
    )
    return {"updated": True}


def delete_cosmetic(cosmetic_id: str, actor: str | None):
    table("cosmetics").delete(filters={"id": f"eq.{cosmetic_id}"})
    log_admin_action(
        actor_id=actor, action="cosmetic.delete",
        target_type="cosmetic", target_id=cosmetic_id,
    )
    return {"deleted": True}
