"""Feature flags (#620, ADR 0029): declared in code, configured in the DB.

A flag is a registry entry here (key, variants, description, client_visible).
Its CONFIGURATION — default, percentage rollout, user/role rules — lives in
`feature_flags` / `feature_flag_targets` and is edited from /admin.

Resolution, first match wins (see `explain`): env override → fail-closed →
user rule → role rule (highest roles.display_priority, then lowest role id)
→ percentage rollout (stable sha256 bucket) → default. Anything unreadable or
invalid resolves to variants[0] ("off"). Reads come from a per-process
snapshot (30 s, `FEATURE_FLAGS_SNAPSHOT_TTL_S`); admin writes call
`clear_feature_flags_cache()` (#98). A user's roles are cached 60 s
(`FEATURE_FLAGS_ROLES_TTL_S`). Both TTLs are read at call time; 0 means
"always read fresh" (the E2E stack exports 0 so a per-test DB reset is seen
immediately).
"""
from __future__ import annotations

import hashlib
import logging
import math
import os
import threading
import time
from dataclasses import dataclass

from fastapi import HTTPException, Request

from db.connection import page_all, table

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


SNAPSHOT_TTL_ENV = "FEATURE_FLAGS_SNAPSHOT_TTL_S"
ROLES_TTL_ENV = "FEATURE_FLAGS_ROLES_TTL_S"
DEFAULT_SNAPSHOT_TTL_S = 30.0
DEFAULT_ROLES_TTL_S = 60.0

_lock = threading.Lock()
_snapshot: tuple[float, Snapshot] | None = None
#: Bumped by every clear. A snapshot read that began before a clear must not
#: store its (pre-write) result after it, or the write stays invisible for a
#: whole TTL.
_generation = 0
_roles: dict[str, tuple[float, tuple[tuple[str, int], ...]]] = {}
_warned: set[str] = set()


def _ttl(env: str, default: float) -> float:
    try:
        value = float(os.getenv(env) or default)
    except ValueError:
        return default
    return value if math.isfinite(value) and value >= 0 else default


def snapshot_ttl_s() -> float:
    return _ttl(SNAPSHOT_TTL_ENV, DEFAULT_SNAPSHOT_TTL_S)


def roles_ttl_s() -> float:
    return _ttl(ROLES_TTL_ENV, DEFAULT_ROLES_TTL_S)


def _warn_once(key: str, msg: str, *args, **kwargs) -> None:
    if key not in _warned:
        _warned.add(key)
        logger.warning(msg, *args, **kwargs)


def clear_feature_flags_cache() -> None:
    global _snapshot, _generation
    with _lock:
        _snapshot = None
        _generation += 1


def clear_user_roles_cache(user_id: str | None = None) -> None:
    with _lock:
        if user_id is None:
            _roles.clear()
        else:
            _roles.pop(user_id, None)


def read_config() -> Snapshot:
    """Uncached read of every flag row and rule (admin API + cache fill).
    Paged in a total order: offset paging over an unordered select can skip
    or repeat a row at a page boundary."""
    flags = list(page_all(
        table("feature_flags"),
        "key,default_variant,rollout_percent,rollout_variant,updated_at,updated_by",
        order="key",
    ))
    targets = list(page_all(
        table("feature_flag_targets"),
        "flag_key,target_type,target_id,variant,created_at,created_by",
        order="flag_key,target_type,target_id",
    ))
    by_key: dict[str, list[dict]] = {}
    for t in targets:
        by_key.setdefault(t["flag_key"], []).append(t)
    return Snapshot(flags={f["key"]: f for f in flags}, targets=by_key)


def _get_snapshot(fresh: bool = False) -> Snapshot:
    global _snapshot
    ttl = snapshot_ttl_s()
    with _lock:
        generation = _generation
        if not fresh and _snapshot and time.monotonic() - _snapshot[0] < ttl:
            return _snapshot[1]
    snap = read_config()  # raises on failure: callers fail closed, nothing cached
    with _lock:
        if generation == _generation:  # no clear landed while we were reading
            _snapshot = (time.monotonic(), snap)
    # The store answered: a later outage is news again, so let it warn.
    for key in REGISTRY:
        _warned.discard(f"store:{key}")
    return snap


def _user_roles(user_id: str) -> tuple[tuple[str, int], ...]:
    now = time.monotonic()
    with _lock:
        hit = _roles.get(user_id)
        if hit and now - hit[0] < roles_ttl_s():
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


#: (primary, shadow) backends -> the decision_router variant that runs them.
_ROUTER_VARIANTS = {
    ("off", "off"): "off",
    ("jev", "off"): "jev",
    ("jev", "flash_lite"): "jev_shadow",
}


def _legacy_router_override() -> Resolution | None:
    """Spec §4 step 1, legacy half: function mode or an explicit
    SAPLING_DECISIONS_BACKEND makes `decisions.router_backends` ignore the
    flag, so report the variant the router will ACTUALLY run. A backend pair
    no variant names (flash_lite, function) reads as "off" with the pair in
    the detail."""
    from services import decisions  # decisions imports this module lazily too

    if decisions._model_mode() == "function":
        detail = "SAPLING_MODEL_MODE=function"
    elif (os.getenv(decisions.BACKEND_ENV) or "").strip():
        detail = f"{decisions.BACKEND_ENV} (legacy)"
    else:
        return None
    backends = (decisions.configured_backend(), decisions.shadow_backend())
    variant = _ROUTER_VARIANTS.get(backends)
    if variant is None:
        return Resolution("off", "env_override",
                          f"{detail}: router runs {backends[0]!r}"
                          + (f" + shadow {backends[1]!r}" if backends[1] != "off" else ""))
    return Resolution(variant, "env_override", detail)


def explain(key: str, user_id: str | None, *, fresh: bool = False) -> Resolution:
    fd = REGISTRY.get(key)
    if fd is None:
        _warn_once(f"unregistered:{key}", "feature flag %r is not registered; off", key)
        return Resolution("off", "fail_closed", "unregistered flag")
    off = fd.variants[0]

    if key == "decision_router":
        legacy = _legacy_router_override()
        if legacy is not None:
            return legacy

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
