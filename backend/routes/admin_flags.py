"""Admin feature-flag API (#620, ADR 0029). All routes require admin."""
from datetime import datetime, timezone
from typing import Literal, Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from db.connection import table
from services import feature_flags
from services.admin_audit import log_admin_action
from services.auth_guard import get_session_user_id, require_admin
from services.events_service import log_event
from services.profiles import get_display_names

router = APIRouter()


class FlagPatch(BaseModel):
    default_variant: Optional[str] = None
    rollout_percent: Optional[int] = Field(default=None, ge=0, le=100)
    rollout_variant: Optional[str] = None


class TargetBody(BaseModel):
    target_type: Literal["user", "role"]
    target_id: str = Field(min_length=1, max_length=200)
    variant: str


def _def(key: str) -> feature_flags.FlagDef:
    fd = feature_flags.REGISTRY.get(key)
    if fd is None:
        raise HTTPException(status_code=404, detail="Unknown flag")
    return fd


def _check(fd: feature_flags.FlagDef, value: Optional[str], field: str) -> None:
    if value is not None and value not in fd.variants:
        raise HTTPException(status_code=422, detail=f"{field} must be one of {list(fd.variants)}")


def _view(fd: feature_flags.FlagDef, snap: feature_flags.Snapshot) -> dict:
    row = snap.flags.get(fd.key) or {}
    rules = snap.targets.get(fd.key, [])
    user_ids = [t["target_id"] for t in rules if t["target_type"] == "user"]
    if row.get("updated_by"):
        user_ids.append(row["updated_by"])
    names = get_display_names(user_ids) if user_ids else {}
    role_names = {r["id"]: r["name"] for r in (table("roles").select("id,name") or [])} \
        if any(t["target_type"] == "role" for t in rules) else {}
    return {
        "key": fd.key,
        "description": fd.description,
        "variants": list(fd.variants),
        "client_visible": fd.client_visible,
        "default_variant": row.get("default_variant") or fd.variants[0],
        "rollout_percent": row.get("rollout_percent") or 0,
        "rollout_variant": row.get("rollout_variant"),
        "updated_at": row.get("updated_at"),
        "updated_by": row.get("updated_by"),
        "updated_by_name": names.get(row.get("updated_by")) if row.get("updated_by") else None,
        "targets": [
            {"target_type": t["target_type"], "target_id": t["target_id"],
             "label": (names.get(t["target_id"]) if t["target_type"] == "user"
                       else role_names.get(t["target_id"])) or t["target_id"],
             "variant": t["variant"]}
            for t in sorted(rules, key=lambda t: (t["target_type"], t["target_id"]))
        ],
    }


def _changed(actor: str, key: str, field: str, before, after) -> None:
    payload = {"key": key, "field": field, "before": before, "after": after}
    log_admin_action(actor_id=actor, action="flag.update", target_type="feature_flag",
                     target_id=key, payload=payload)
    log_event("flag.changed", category="audit", user_id=actor, payload=payload)
    feature_flags.clear_feature_flags_cache()


def _ensure_row(fd: feature_flags.FlagDef, actor: str) -> None:
    table("feature_flags").upsert(
        {"key": fd.key, "default_variant": fd.variants[0], "updated_by": actor},
        on_conflict="key", ignore_duplicates=True,
    )


@router.get("")
def list_flags(request: Request):
    require_admin(request)
    snap = feature_flags.read_config()
    return {"flags": [_view(fd, snap) for fd in feature_flags.REGISTRY.values()]}


@router.patch("/{key}")
def update_flag(key: str, body: FlagPatch, request: Request):
    require_admin(request)
    actor = get_session_user_id(request)
    fd = _def(key)
    _check(fd, body.default_variant, "default_variant")
    _check(fd, body.rollout_variant, "rollout_variant")
    current = feature_flags.read_config().flags.get(key) or {}
    merged = {
        "default_variant": body.default_variant or current.get("default_variant") or fd.variants[0],
        "rollout_percent": body.rollout_percent if body.rollout_percent is not None
        else (current.get("rollout_percent") or 0),
        "rollout_variant": body.rollout_variant if body.rollout_variant is not None
        else current.get("rollout_variant"),
    }
    if merged["rollout_percent"] > 0 and not merged["rollout_variant"]:
        raise HTTPException(status_code=422, detail="rollout_variant is required when rollout_percent > 0")
    table("feature_flags").upsert(
        {"key": key, **merged, "updated_by": actor,
         "updated_at": datetime.now(timezone.utc).isoformat()},
        on_conflict="key",
    )
    for field in ("default_variant", "rollout_percent", "rollout_variant"):
        if current.get(field) != merged[field]:
            _changed(actor, key, field, current.get(field), merged[field])
    feature_flags.clear_feature_flags_cache()
    return {"flag": _view(fd, feature_flags.read_config())}


@router.put("/{key}/targets")
def upsert_target(key: str, body: TargetBody, request: Request):
    require_admin(request)
    actor = get_session_user_id(request)
    fd = _def(key)
    _check(fd, body.variant, "variant")
    if body.target_type == "user":
        exists = table("users").select("id", filters={"id": f"eq.{body.target_id}"})
    else:
        exists = table("roles").select("id", filters={"id": f"eq.{body.target_id}"})
    if not exists:
        raise HTTPException(status_code=404, detail=f"Unknown {body.target_type}")
    _ensure_row(fd, actor)
    before = next((t["variant"] for t in feature_flags.read_config().targets.get(key, [])
                   if t["target_type"] == body.target_type and t["target_id"] == body.target_id), None)
    table("feature_flag_targets").upsert(
        {"flag_key": key, "target_type": body.target_type, "target_id": body.target_id,
         "variant": body.variant, "created_by": actor},
        on_conflict="flag_key,target_type,target_id",
    )
    _changed(actor, key, f"{body.target_type}:{body.target_id}", before, body.variant)
    return {"flag": _view(fd, feature_flags.read_config())}


@router.delete("/{key}/targets/{target_type}/{target_id}")
def delete_target(key: str, target_type: Literal["user", "role"], target_id: str, request: Request):
    require_admin(request)
    actor = get_session_user_id(request)
    fd = _def(key)
    removed = table("feature_flag_targets").delete(filters={
        "flag_key": f"eq.{key}", "target_type": f"eq.{target_type}", "target_id": f"eq.{target_id}",
    })
    if removed:
        _changed(actor, key, f"{target_type}:{target_id}", removed[0].get("variant"), None)
    return {"flag": _view(fd, feature_flags.read_config())}


@router.get("/{key}/explain")
def explain_flag(key: str, request: Request, user_id: Optional[str] = None):
    require_admin(request)
    _def(key)
    r = feature_flags.explain(key, user_id or None, fresh=True)
    return {"variant": r.variant, "step": r.step, "detail": r.detail}
