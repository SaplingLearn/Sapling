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

import httpx
from fastapi import HTTPException, Request

from db.connection import page_all, table

logger = logging.getLogger("sapling.feature_flags")


@dataclass(frozen=True)
class FlagDef:
    key: str
    variants: tuple[str, ...]  # variants[0] is the OFF variant (fail-closed answer)
    description: str
    client_visible: bool


#: Main-nav features an admin can hide (sidebar + top nav, and the route
#: redirects to /dashboard). "on" HIDES, so the fail-closed "off" leaves the
#: feature visible. Frontend twin: frontend/src/lib/navFeatures.ts.
NAV_FEATURES: tuple[tuple[str, str], ...] = (
    ("tutor", "Tutor"), ("quiz", "Quiz"), ("tree", "Tree"), ("study", "Study"),
    ("library", "Library"), ("calendar", "Calendar"),
    ("social", "Social"), ("achievements", "Achievements"),
    ("grades", "Grades"), ("notetaker", "Notetaker"),
    ("course_planner", "Course Planner"),
)

REGISTRY: dict[str, FlagDef] = {f.key: f for f in (
    *(FlagDef(f"hide_{slug}", ("off", "on"),
              f"Hide {label} from the nav; its pages redirect to /dashboard.", True)
      for slug, label in NAV_FEATURES),
    # #672 (ADR 0027): which decision-seam backends the observe-only tutor
    # router runs for a student. Server-only: the router acts on nothing, so
    # the client has no use for it. SAPLING_FLAG_DECISION_ROUTER is its env
    # kill switch like any flag's; under SAPLING_MODEL_MODE=function an on
    # variant runs the scripted backend (`decisions.router_backends`).
    FlagDef("decision_router", ("off", "jev", "jev_shadow"),
            "Tutor turn router on the Jev decision seam (ADR 0027). jev_shadow "
            "also runs flash-lite to measure agreement.", False),
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


#: Every resolver read of the flag store (the snapshot, a user's roles) is
#: bounded by this — not the connection's 30 s default — and a failed
#: SNAPSHOT read marks the store unreadable for STORE_UNREADABLE_TTL_S, during
#: which resolution fails closed WITHOUT another read (a failed roles read
#: fails only that user's resolution). An outage therefore costs
#: each process one bounded wait per window, not one hung read per call (the
#: tutor router and the PostHog worker resolve per item).
STORE_TIMEOUT_S = 2.5
STORE_UNREADABLE_TTL_S = 30.0
#: Resolution.detail when the store could not be read — the one signal a
#: caller may key on to tell "unreadable" from a real or invalid answer.
STORE_UNREADABLE = "flag store unreadable"


class StoreUnreadable(RuntimeError):
    """The flag store is (still) unreadable; raised by the snapshot/roles
    reads inside the negative-cache window."""


#: What counts as "the store did not answer": the negative-cache marker, and
#: any httpx error (transport, timeout, or a PostgREST error status). Any
#: other exception is a data/config bug and is reported as one.
_STORE_ERRORS: tuple[type[BaseException], ...] = (StoreUnreadable, httpx.HTTPError)


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
#: monotonic time until which the store counts as unreadable (0 = readable).
_store_down_until = 0.0


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
    global _snapshot, _generation, _store_down_until
    with _lock:
        _snapshot = None
        _generation += 1
        _store_down_until = 0.0  # a write just went through: read again


def clear_user_roles_cache(user_id: str | None = None) -> None:
    with _lock:
        if user_id is None:
            _roles.clear()
        else:
            _roles.pop(user_id, None)


def read_config(*, timeout: float | None = None) -> Snapshot:
    """Uncached read of every flag row and rule (admin API + cache fill).
    Paged in a total order: offset paging over an unordered select can skip
    or repeat a row at a page boundary. ``timeout`` bounds each page read
    (the resolver passes STORE_TIMEOUT_S; the admin API keeps the default)."""
    flags = list(page_all(
        table("feature_flags"),
        "key,default_variant,rollout_percent,rollout_variant,updated_at,updated_by",
        order="key", timeout=timeout,
    ))
    targets = list(page_all(
        table("feature_flag_targets"),
        "flag_key,target_type,target_id,variant,created_at,created_by",
        order="flag_key,target_type,target_id", timeout=timeout,
    ))
    by_key: dict[str, list[dict]] = {}
    for t in targets:
        by_key.setdefault(t["flag_key"], []).append(t)
    return Snapshot(flags={f["key"]: f for f in flags}, targets=by_key)


def _get_snapshot(fresh: bool = False) -> Snapshot:
    global _snapshot
    ttl = snapshot_ttl_s()
    global _store_down_until
    with _lock:
        generation = _generation
        if not fresh and _snapshot and time.monotonic() - _snapshot[0] < ttl:
            return _snapshot[1]
        if not fresh and time.monotonic() < _store_down_until:
            raise StoreUnreadable("flag store unreadable (cached)")
    if fresh:
        # The admin path (ADR 0029): the connection's normal timeout, and an
        # admin read never marks the store down — it only clears the mark
        # when it succeeds.
        snap = read_config()
    else:
        try:
            snap = read_config(timeout=STORE_TIMEOUT_S)
        except _STORE_ERRORS:
            _mark_store_down()  # callers fail closed; nothing re-reads for a while
            raise
    with _lock:
        _store_down_until = 0.0  # the store answered
        if generation == _generation:  # no clear landed while we were reading
            _snapshot = (time.monotonic(), snap)
    # The store answered: a later outage is news again, so let it warn.
    for key in REGISTRY:
        _warned.discard(f"store:{key}")
    return snap


def _mark_store_down() -> None:
    global _store_down_until
    with _lock:
        _store_down_until = time.monotonic() + STORE_UNREADABLE_TTL_S


def _roles_peek(user_id: str) -> tuple[tuple[str, int], ...] | None:
    """This user's cached roles if still fresh, else None. Never reads."""
    with _lock:
        hit = _roles.get(user_id)
        return hit[1] if hit and time.monotonic() - hit[0] < roles_ttl_s() else None


def _user_roles(user_id: str) -> tuple[tuple[str, int], ...]:
    now = time.monotonic()
    with _lock:
        hit = _roles.get(user_id)
        if hit and now - hit[0] < roles_ttl_s():
            return hit[1]
        if now < _store_down_until:
            raise StoreUnreadable("flag store unreadable (cached)")
    # A failed read raises into explain(), which fails closed for THIS
    # user's resolution only: one user's roles read does not mark the whole
    # store down (only a snapshot read does).
    rows = table("user_roles").select(
        "role_id,roles!inner(display_priority)", filters={"user_id": f"eq.{user_id}"},
        timeout=STORE_TIMEOUT_S,
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


def explain(key: str, user_id: str | None, *, fresh: bool = False,
            _snapshot: Snapshot | Exception | None = None,
            _roles_known: tuple[tuple[str, int], ...] | None = None) -> Resolution:
    """`_snapshot`: a snapshot (or the error reading it) already taken by a
    caller resolving many flags at once, so one outage costs one store read,
    not one per flag. The env override still wins over it. `_roles_known`:
    the user's roles, already resolved by a caller that must not do I/O
    (:func:`cached_explain`)."""
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
        if isinstance(_snapshot, Exception):
            raise _snapshot
        snap = _snapshot if _snapshot is not None else _get_snapshot(fresh)
        row = snap.flags.get(key)
        if user_id:
            rules = snap.targets.get(key, [])
            for t in rules:
                if t["target_type"] == "user" and t["target_id"] == user_id:
                    return valid(t["variant"], "user", user_id)
            role_rules = {t["target_id"]: t for t in rules if t["target_type"] == "role"}
            if role_rules:
                roles = _roles_known if _roles_known is not None else _user_roles(user_id)
                held = [(p, rid) for rid, p in roles if rid in role_rules]
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
    except _STORE_ERRORS:
        _warn_once(f"store:{key}", "feature flag store unreadable; %r fails closed", key,
                   exc_info=True)
        return Resolution(off, "fail_closed", STORE_UNREADABLE)
    except Exception as exc:
        # A data/config bug (a malformed target row, ...), not an outage:
        # say what it is, and fail closed for this flag only.
        logger.error("feature flag %r failed to resolve (%s: %s); fails closed",
                     key, type(exc).__name__, exc)
        return Resolution(off, "fail_closed", f"resolution error: {type(exc).__name__}")


def cached_explain(key: str, user_id: str | None) -> Resolution | None:
    """:func:`explain` without any I/O, or None when answering would need a
    store read (a cold snapshot, or a role lookup this user has no fresh
    cache entry for). Safe on an event loop. Inside the unreadable window it
    answers — fail closed — without a read."""
    fd = REGISTRY.get(key)
    if fd is None:
        return explain(key, user_id)  # unregistered: answered without I/O
    env = (os.getenv(f"SAPLING_FLAG_{key.upper()}") or "").strip().lower()
    if env in fd.variants:
        return explain(key, user_id)  # the env override wins before any read
    with _lock:
        cached = _snapshot
        down = time.monotonic() < _store_down_until
    if cached is not None and time.monotonic() - cached[0] < snapshot_ttl_s():
        snap = cached[1]
        roles = None
        if user_id and any(t["target_type"] == "role" for t in snap.targets.get(key, [])):
            # Resolved ONCE here and handed to explain(), so a roles entry
            # that expires between the check and the use cannot turn this
            # into a blocking read.
            roles = _roles_peek(user_id)
            if roles is None:
                return None  # would need this user's roles
        return explain(key, user_id, _snapshot=snap, _roles_known=roles)
    if down:
        return Resolution(fd.variants[0], "fail_closed", STORE_UNREADABLE)
    return None


def flag_variant(key: str, user_id: str | None) -> str:
    return explain(key, user_id).variant


def flag_on(key: str, user_id: str | None) -> bool:
    fd = REGISTRY.get(key)
    return fd is not None and flag_variant(key, user_id) != fd.variants[0]


def resolved_client_flags(user_id: str | None) -> dict[str, str]:
    """Every client-visible flag from ONE snapshot read. Resolving them one by
    one would retry the store per flag during an outage — 11 timeouts in a
    row on GET /api/flags, while NavFeatureGate keeps flagged pages veiled."""
    try:
        snap: Snapshot | Exception = _get_snapshot()
    except Exception as exc:
        snap = exc
    return {k: explain(k, user_id, _snapshot=snap).variant
            for k, fd in REGISTRY.items() if fd.client_visible}


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
