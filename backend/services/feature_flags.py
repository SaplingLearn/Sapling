"""Feature flags (#620, ADR 0029): declared in code, configured in the DB.

A flag is a registry entry here (key, variants, description, client_visible).
Its CONFIGURATION — default, percentage rollout, user/role rules — lives in
`feature_flags` / `feature_flag_targets` and is edited from /admin.

Resolution, first match wins (see `explain`): env override → fail-closed →
user rule → role rule (highest roles.display_priority, then lowest role id)
→ percentage rollout (stable sha256 bucket) → default. Anything unreadable or
invalid resolves to variants[0] ("off"). Reads come from a 30 s per-process
snapshot; admin writes call `clear_feature_flags_cache()` (#98).
"""
from __future__ import annotations

import hashlib
import logging
import os
import threading
import time
from dataclasses import dataclass

from fastapi import HTTPException, Request

from db.connection import table

logger = logging.getLogger("sapling.feature_flags")


@dataclass(frozen=True)
class FlagDef:
    key: str
    variants: tuple[str, ...]  # variants[0] is the OFF variant (fail-closed answer)
    description: str
    client_visible: bool


REGISTRY: dict[str, FlagDef] = {f.key: f for f in (
    FlagDef("decision_router", ("off", "jev", "jev_shadow"),
            "Tutor turn router on the Jev decision seam (ADR 0027). jev_shadow "
            "also runs flash-lite to measure agreement.", False),
    FlagDef("learning_loop", ("off", "on"),
            "AI learning loop (#673).", True),
    FlagDef("product_analytics", ("off", "on"),
            "PostHog product analytics, frontend + backend (ADR 0028).", True),
)}

STEPS = ("env_override", "fail_closed", "user", "role", "rollout", "default")


@dataclass(frozen=True)
class Resolution:
    variant: str
    step: str
    detail: str = ""


@dataclass(frozen=True)
class Snapshot:
    flags: dict[str, dict]           # key -> feature_flags row
    targets: dict[str, list[dict]]   # key -> feature_flag_targets rows


SNAPSHOT_TTL_S = 30.0
ROLES_TTL_S = 60.0
_PAGE = 1000  # PostgREST max_rows; page so a large table never truncates

_lock = threading.Lock()
_snapshot: tuple[float, Snapshot] | None = None
_roles: dict[str, tuple[float, tuple[tuple[str, int], ...]]] = {}
_warned: set[str] = set()


def _warn_once(key: str, msg: str, *args, **kwargs) -> None:
    if key not in _warned:
        _warned.add(key)
        logger.warning(msg, *args, **kwargs)


def clear_feature_flags_cache() -> None:
    global _snapshot
    with _lock:
        _snapshot = None


def clear_user_roles_cache(user_id: str | None = None) -> None:
    with _lock:
        if user_id is None:
            _roles.clear()
        else:
            _roles.pop(user_id, None)


def _select_all(name: str, columns: str) -> list[dict]:
    rows: list[dict] = []
    offset = 0
    while True:
        page = table(name).select(columns, limit=_PAGE, offset=offset) or []
        rows.extend(page)
        if len(page) < _PAGE:
            return rows
        offset += _PAGE


def read_config() -> Snapshot:
    """Uncached read of every flag row and rule (admin API + cache fill)."""
    flags = _select_all(
        "feature_flags",
        "key,default_variant,rollout_percent,rollout_variant,updated_at,updated_by",
    )
    targets = _select_all(
        "feature_flag_targets",
        "flag_key,target_type,target_id,variant,created_at,created_by",
    )
    by_key: dict[str, list[dict]] = {}
    for t in targets:
        by_key.setdefault(t["flag_key"], []).append(t)
    return Snapshot(flags={f["key"]: f for f in flags}, targets=by_key)


def _get_snapshot(fresh: bool = False) -> Snapshot:
    global _snapshot
    if not fresh:
        with _lock:
            if _snapshot and time.monotonic() - _snapshot[0] < SNAPSHOT_TTL_S:
                return _snapshot[1]
    snap = read_config()  # raises on failure: callers fail closed, nothing cached
    with _lock:
        _snapshot = (time.monotonic(), snap)
    return snap


def _user_roles(user_id: str) -> tuple[tuple[str, int], ...]:
    now = time.monotonic()
    with _lock:
        hit = _roles.get(user_id)
        if hit and now - hit[0] < ROLES_TTL_S:
            return hit[1]
    rows = table("user_roles").select(
        "role_id,roles!inner(display_priority)", filters={"user_id": f"eq.{user_id}"},
    ) or []
    out = tuple(
        (str(r["role_id"]), int(((r.get("roles") or {}).get("display_priority")) or 0))
        for r in rows
    )
    with _lock:
        _roles[user_id] = (time.monotonic(), out)
    return out


def rollout_bucket(key: str, user_id: str) -> float:
    """Stable 0.00–99.99 bucket per (flag, user). Raising the percentage only
    ever adds users: membership at p is a subset of membership at any p' > p."""
    digest = hashlib.sha256(f"{key}:{user_id}".encode()).hexdigest()
    return int(digest[:8], 16) % 10000 / 100


def explain(key: str, user_id: str | None, *, fresh: bool = False) -> Resolution:
    fd = REGISTRY.get(key)
    if fd is None:
        _warn_once(f"unregistered:{key}", "feature flag %r is not registered; off", key)
        return Resolution("off", "fail_closed", "unregistered flag")
    off = fd.variants[0]

    env = (os.getenv(f"SAPLING_FLAG_{key.upper()}") or "").strip().lower()
    if env:
        if env in fd.variants:
            return Resolution(env, "env_override", f"SAPLING_FLAG_{key.upper()}")
        _warn_once(f"env:{key}:{env}", "SAPLING_FLAG_%s=%r is not a variant of %s; ignored",
                   key.upper(), env, fd.variants)

    def valid(v, step: str, detail: str) -> Resolution:
        if v in fd.variants:
            return Resolution(v, step, detail)
        return Resolution(off, "fail_closed", f"invalid stored variant {v!r} ({step})")

    try:
        snap = _get_snapshot(fresh)
        row = snap.flags.get(key)
        if user_id:
            rules = snap.targets.get(key, [])
            for t in rules:
                if t["target_type"] == "user" and t["target_id"] == user_id:
                    return valid(t["variant"], "user", user_id)
            role_rules = {t["target_id"]: t for t in rules if t["target_type"] == "role"}
            if role_rules:
                held = [(p, rid) for rid, p in _user_roles(user_id) if rid in role_rules]
                if held:
                    held.sort(key=lambda pr: (-pr[0], pr[1]))
                    rid = held[0][1]
                    return valid(role_rules[rid]["variant"], "role", rid)
            if row and (row.get("rollout_percent") or 0) > 0 and row.get("rollout_variant"):
                if rollout_bucket(key, user_id) < row["rollout_percent"]:
                    return valid(row["rollout_variant"], "rollout", f"{row['rollout_percent']}%")
        if row:
            return valid(row["default_variant"], "default", "stored default")
        return Resolution(off, "default", "no stored configuration")
    except Exception:
        _warn_once(f"store:{key}", "feature flag store unreadable; %r fails closed", key,
                   exc_info=True)
        return Resolution(off, "fail_closed", "flag store unreadable")


def flag_variant(key: str, user_id: str | None) -> str:
    return explain(key, user_id).variant


def flag_on(key: str, user_id: str | None) -> bool:
    fd = REGISTRY.get(key)
    return fd is not None and flag_variant(key, user_id) != fd.variants[0]


def resolved_client_flags(user_id: str | None) -> dict[str, str]:
    return {k: flag_variant(k, user_id) for k, fd in REGISTRY.items() if fd.client_visible}


def require_flag(key: str):
    """Route dependency: 404 when `key` is off for the session user."""
    def _dependency(request: Request) -> None:
        from services.auth_guard import get_session_user_id
        try:
            uid = get_session_user_id(request)
        except HTTPException:
            uid = None
        if not flag_on(key, uid):
            raise HTTPException(status_code=404, detail="Not found")
    return _dependency
