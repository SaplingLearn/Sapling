"""Feature flags (#620, ADR 0029): declared in code, configured in the DB.

A flag is a registry entry here (key, variants, description, client_visible).
Its CONFIGURATION — default, percentage rollout, user/role rules — lives in
`feature_flags` / `feature_flag_targets` and is edited from /admin.

Resolution, first match wins (see `explain`): env override → fail-closed →
user rule → role rule (highest roles.display_priority, then lowest role id)
→ percentage rollout (stable sha256 bucket) → default. Anything unreadable or
invalid resolves to variants[0] ("off"). Reads come from a per-process
snapshot (30 s, `FEATURE_FLAGS_SNAPSHOT_TTL_S`); admin writes call
`clear_feature_flags_cache()` (#98), which clears only THIS process. Other
replicas see the write through `feature_flags_version` (#117): a trigger bumps
it on every flag write, and a process serving flag reads re-reads it at most
every `FEATURE_FLAGS_VERSION_CHECK_S` (5 s) and drops its snapshot when it
moved. Convergence across replicas is therefore ~5 s while requests flow (and
never worse than the snapshot TTL: a missing version table leaves exactly the
TTL behaviour; a version read that finds the store unreachable marks it
unreadable like a failed snapshot read, so an outage costs one bounded read
per window). The check only validates a WARM snapshot: a reload files the new
snapshot under the version already known (older or equal, so at worst one
extra reload), and reads the row only when none is known yet. It is off when
either interval is 0. A user's roles are cached 60 s
(`FEATURE_FLAGS_ROLES_TTL_S`). Both TTLs are read at call time; 0 means
"always read fresh" (the E2E stack exports 0 so a per-test DB reset is seen
immediately).
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
import math
import os
import re
import threading
import time
from dataclasses import dataclass
from typing import Callable, TypeVar

import httpx
from fastapi import HTTPException, Request

from db.connection import page_all, table
from db.scope import service_scope

logger = logging.getLogger("sapling.feature_flags")

T = TypeVar("T")


@dataclass(frozen=True)
class FlagDef:
    key: str
    variants: tuple[str, ...]  # variants[0] is the OFF variant (fail-closed answer)
    description: str
    client_visible: bool


#: Main-nav features an admin can hide (sidebar + top nav, and the route
#: redirects to /dashboard). "on" HIDES, so the fail-closed "off" leaves the
#: feature visible. Frontend twin: frontend/src/lib/navFeatures.ts. The API
#: side is NAV_FEATURE_API at the bottom of this module (#771).
NAV_FEATURES: tuple[tuple[str, str], ...] = (
    ("tutor", "Tutor"), ("quiz", "Quiz"), ("tree", "Tree"), ("study", "Study"),
    ("library", "Library"), ("calendar", "Calendar"),
    ("social", "Social"), ("achievements", "Achievements"),
    ("grades", "Grades"), ("notetaker", "Notetaker"),
    ("course_planner", "Course Planner"),
)

#: Features that are no longer their own nav row but keep a hide flag: Quiz
#: is a tab under Study since #753 (frontend twin: NESTED_NAV_FEATURES).
_NESTED_NAV_DESCRIPTIONS: dict[str, str] = {
    "quiz": "Hide Quiz (a tab under Study); its pages redirect to /dashboard.",
}

REGISTRY: dict[str, FlagDef] = {f.key: f for f in (
    *(FlagDef(f"hide_{slug}", ("off", "on"),
              _NESTED_NAV_DESCRIPTIONS.get(
                  slug, f"Hide {label} from the nav; its pages redirect to /dashboard."),
              True)
      for slug, label in NAV_FEATURES),
    # #672 (ADR 0027): which decision-seam backends the observe-only tutor
    # router runs for a student. Server-only: the router acts on nothing, so
    # the client has no use for it. SAPLING_FLAG_DECISION_ROUTER is its env
    # kill switch like any flag's; under SAPLING_MODEL_MODE=function an on
    # variant runs the scripted backend (`decisions.router_backends`).
    FlagDef("decision_router", ("off", "jev", "jev_shadow"),
            "Tutor turn router on the Jev decision seam (ADR 0027). jev_shadow "
            "also runs flash-lite to measure agreement.", False),
    # #677 (ADR 0028): PostHog product analytics, end to end — the backend
    # worker drops every capture for a student it resolves "off" for, and the
    # frontend (#675) never starts posthog-js. The #620 migration seeds it
    # "on", so analytics stays on wherever it already was.
    FlagDef("product_analytics", ("off", "on"),
            "PostHog product analytics, frontend + backend (ADR 0028).", True),
    # #119: cross-provider LLM fallback (agents/_providers.py). Resolved
    # GLOBALLY (user_id=None — the model layer never sees a student), so only
    # the stored default and SAPLING_FLAG_LLM_FALLBACK (the kill switch)
    # apply; per-user/role rules and rollouts are ignored. Server-only.
    FlagDef("llm_fallback", ("off", "on"),
            "When an agent's LLM provider is down (retries exhausted or its "
            "circuit breaker open), retry the call on the other provider's "
            "model. Global: per-user rules and rollouts do not apply.", False),
    # #119: per-user daily LLM token budget (services/llm_budget.py), checked
    # at the model chokepoint before an agent run starts. Per user, so role
    # rules and rollouts apply. Budgets live in `llm_budgets` (/api/admin/llm).
    # Server-only. Kill switch: SAPLING_FLAG_LLM_BUDGET=off.
    FlagDef("llm_budget", ("off", "on"),
            "Refuse new AI runs (429) for a student who has used today's LLM "
            "token budget (llm_budgets: default, role and user overrides).", False),
    # #119: the forced provider-outage drill (agents/_resilience.py,
    # docs/ops/llm-outage-drill.md): every request to the named provider(s)
    # fails with a retryable 503 before it is sent. Resolved GLOBALLY
    # (user_id=None) like llm_fallback; server-only. Usually armed for one
    # deploy with SAPLING_FLAG_LLM_OUTAGE_DRILL=anthropic. Refused in
    # APP_ENV=production unless SAPLING_LLM_FORCE_OUTAGE_ALLOW_PRODUCTION=yes.
    # A flag-store outage fails closed to "off", so it can never arm a drill.
    FlagDef("llm_outage_drill", ("off", "anthropic", "google", "both"),
            "Outage drill: fail every LLM request to the chosen provider(s) with "
            "a retryable 503 (exercises retries, the breaker and llm_fallback). "
            "Global. Refused in production without "
            "SAPLING_LLM_FORCE_OUTAGE_ALLOW_PRODUCTION=yes.", False),
    # #116: move background work onto the Postgres job queue. Server-only.
    # Resolved for the student whose action triggered the work. It covers
    # course-context aggregation (course_context_service.
    # refresh_course_context), the upload's first indexing attempt
    # (document_indexing.schedule_document_index) and the upload pipeline
    # itself (services/document_jobs.py). On WITHOUT a running `python -m
    # worker`, aggregation and indexing only queue (class aggregates go stale;
    # the index sweeper still recovers unindexed documents in production) and
    # uploads wait PICKUP_GRACE_SECONDS, then run inline. Hence default off.
    FlagDef("jobs_queue", ("off", "on"),
            "Run course-context aggregation, document indexing, the upload "
            "pipeline (extraction + document agents) and the Gradescope sync on "
            "the job queue instead of in the request. Needs a running `python -m "
            "worker`; without one aggregation and indexing only queue, and "
            "uploads and Gradescope syncs fall back to inline after a short "
            "wait.", False),
    # #115 (RLS step 2, docs/security/rls-step2-plan.md §4.4): whether a
    # request's PostgREST calls run as the student (a backend-minted JWT, RLS
    # applies) instead of the service role. shadow = service answers, a
    # sampled share of reads is re-run as the student and divergence logged
    # (db.rls_shadow_divergence); enforce = the student's token, fail closed.
    # Per user, so per-user/role rules and rollouts work ("admins on enforce").
    # Resolved once per request, as service (db/scope.py). Server-only. Kill
    # switch: SAPLING_FLAG_DB_USER_SCOPE=off. NB the ADR 0029 fail-closed
    # answer ("off") is the LESS secure side for this flag: a flag-store
    # outage downgrades everyone to service role (accepted during rollout;
    # graduate the flag once prod has run enforce at 100%).
    FlagDef("db_user_scope", ("off", "shadow", "enforce"),
            "Run each request's database calls as the student (RLS) instead of "
            "the service role. shadow compares a sample of reads; enforce "
            "applies RLS and fails closed.", False),
    # #115 RLS step 2e (docs/security/realtime-jwt-bridge-design.md): the
    # study-room live chat authenticates Supabase Realtime with a
    # backend-minted token (GET /api/auth/realtime-token, iss
    # sapling-realtime) instead of the public anon key, so it keeps working
    # once RLS is on for room_messages. Client-visible: Social.tsx reads it.
    # Off = today's anon subscription. Turn on only where
    # SUPABASE_JWT_SIGNING_KEY is set and trusted by that project's Realtime
    # (else the endpoint 503s and the room falls back to REST-only).
    FlagDef("realtime_rls", ("off", "on"),
            "Study-room live chat authenticates Supabase Realtime with a "
            "backend-minted, member-scoped token instead of the anon key "
            "(RLS step 2e). Needs SUPABASE_JWT_SIGNING_KEY.", True),
    # #117 (docs/design/async-db-client.md §3): whether the `a*` twins of
    # table()'s verbs use the native httpx.AsyncClient ("on") or run the sync
    # verb on a worker thread ("off": today's client and limiter, reached from
    # an async def without blocking the loop). Per user; resolved once per
    # request and memoized beside db_user_scope. Server-only. Kill switch:
    # SAPLING_FLAG_ASYNC_DB_CLIENT=off. Graduate after one release at 100%.
    FlagDef("async_db_client", ("off", "on"),
            "Serve async handlers' database calls from the native async HTTP "
            "client instead of a worker thread.", False),
    # #117 (design §5): the per-key rate limiter as a Postgres counter
    # (`claim_rate_limit()` SQL function) instead of per-process memory, so
    # two replicas share one budget. Resolved GLOBALLY (user_id=None): the
    # limiter keys are not always a user. Off = today's in-memory limiter; a
    # failing DB call falls back to it. Server-only.
    FlagDef("stateless_rate_limit", ("off", "on"),
            "Keep rate-limit counters in Postgres so every replica shares one "
            "budget. Global: per-user rules and rollouts do not apply.", False),
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
VERSION_CHECK_ENV = "FEATURE_FLAGS_VERSION_CHECK_S"
DEFAULT_SNAPSHOT_TTL_S = 30.0
DEFAULT_ROLES_TTL_S = 60.0
DEFAULT_VERSION_CHECK_S = 5.0

_lock = threading.Lock()
_snapshot: tuple[float, Snapshot] | None = None
#: Bumped by every clear. A snapshot read that began before a clear must not
#: store its (pre-write) result after it, or the write stays invisible for a
#: whole TTL.
_generation = 0
_roles: dict[str, tuple[float, tuple[tuple[str, int], ...]]] = {}
_warned: set[str] = set()
#: #117: `feature_flags_version.version` as of the snapshot in hand (None =
#: unknown: no version checks, the TTL alone governs), and when it was last
#: confirmed. One thread checks at a time; the rest keep serving the snapshot.
_version: int | None = None
_version_checked = 0.0
_version_lock = threading.Lock()
#: Bounds on the two per-process maps keyed by caller input (#771): one entry
#: per student ever resolved (roles) and one per distinct warning. Past the
#: cap the oldest role entry goes (a re-read costs one bounded query); the
#: warned set is reset (a warning may then repeat once).
ROLES_CACHE_MAX = 10_000
WARNED_MAX = 1_000


class _Flight:
    """One in-flight snapshot read that concurrent cold callers wait on
    instead of each reading the store (#771: single-flight)."""

    __slots__ = ("done", "generation", "result", "error")

    def __init__(self, generation: int) -> None:
        self.done = threading.Event()
        self.generation = generation
        self.result: Snapshot | None = None
        self.error: BaseException | None = None


_flight: _Flight | None = None
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


def version_check_s() -> float:
    """How often a serving process re-reads `feature_flags_version`; 0 turns
    the cross-replica check off (the snapshot TTL alone then bounds it)."""
    return _ttl(VERSION_CHECK_ENV, DEFAULT_VERSION_CHECK_S)


def _warn_once(key: str, msg: str, *args, **kwargs) -> None:
    if key not in _warned:
        if len(_warned) >= WARNED_MAX:
            _warned.clear()
        _warned.add(key)
        logger.warning(msg, *args, **kwargs)


def clear_feature_flags_cache() -> None:
    _clear()


def _clear(version: int | None = None) -> None:
    """Drop the snapshot. `version`: the version the next snapshot may be
    filed under (one just read, so not newer than that snapshot); None = the
    next load reads it again."""
    global _snapshot, _generation, _store_down_until, _version
    with _lock:
        _snapshot = None
        _generation += 1
        _store_down_until = 0.0  # a write just went through: read again
        _version = version


def _version_checks_on() -> bool:
    """FEATURE_FLAGS_VERSION_CHECK_S=0, or a snapshot TTL of 0 (every read is
    fresh anyway), turns the version row off entirely: never read."""
    return version_check_s() > 0 and snapshot_ttl_s() > 0


def _is_outage(exc: BaseException) -> bool:
    """The store did not answer (transport, timeout, 5xx). A 4xx is an
    answer -- e.g. the version table not migrated yet -- not an outage."""
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code >= 500
    return isinstance(exc, httpx.HTTPError)


def _read_version(*, mark_down: bool = True) -> int | None:
    """`feature_flags_version.version`, or None when it cannot be known (no
    table yet, an empty or odd answer, a failed read). Never raises. An
    unreachable store is marked unreadable (`mark_down`; not on the admin
    path), so nothing re-reads it -- version or config -- inside the window."""
    try:
        with service_scope():  # #115: part of the flag store
            rows = table("feature_flags_version").select(
                "version", filters={"id": "eq.true"}, timeout=STORE_TIMEOUT_S,
            )
    except Exception as exc:
        if mark_down and _is_outage(exc):
            _mark_store_down()
        _warn_once("version", "feature_flags_version unreadable (%s); flag changes "
                   "reach this process within the snapshot TTL only", type(exc).__name__)
        return None
    if not isinstance(rows, list) or not rows or not isinstance(rows[0], dict):
        return None
    v = rows[0].get("version")
    return v if isinstance(v, int) and not isinstance(v, bool) else None


def _version_due() -> bool:
    """Whether the snapshot in hand should be re-validated against the
    version row before it is served. Never inside the unreadable window.
    Caller holds no lock."""
    if not _version_checks_on():
        return False
    interval = version_check_s()
    with _lock:
        if _version is None or _snapshot is None:
            return False
        now = time.monotonic()
        return now >= _store_down_until and now - _version_checked >= interval


def _baseline_version(*, mark_down: bool = True) -> int | None:
    """The version to file a newly read snapshot under: the one already
    known when there is one (it is not newer than the new snapshot, so a
    write in between costs one extra reload, never a missed write), else a
    read of the row -- once per process, and after a local clear."""
    if not _version_checks_on():
        return None
    with _lock:
        known = _version
    if known is not None:
        return known
    return _read_version(mark_down=mark_down)


def _maybe_check_version() -> None:
    """#117: drop the snapshot when another process changed the flag store
    (the trigger moved `feature_flags_version`). One checker at a time; a
    concurrent caller keeps serving the snapshot instead of waiting."""
    global _version_checked
    if not _version_due() or not _version_lock.acquire(blocking=False):
        return
    try:
        with _lock:
            seen = _version
        current = _read_version()
        with _lock:
            _version_checked = time.monotonic()
        if current is not None and current != seen:
            # Read before the reload, so it is a safe baseline for it: the
            # reload does not read the version row again.
            _clear(current)
    finally:
        _version_lock.release()


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
    # Service role (#115): the flag store is service-only, it is read before
    # a request's identity is settled, and `db_user_scope` itself is decided
    # from it — a scoped read would recurse into its own answer.
    with service_scope():
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
    global _snapshot, _flight
    ttl = snapshot_ttl_s()
    global _store_down_until
    if fresh:
        with _lock:
            generation = _generation
        # The admin path (ADR 0029): the connection's normal timeout, and an
        # admin read never marks the store down — it only clears the mark
        # when it succeeds.
        version = _baseline_version(mark_down=False)
        snap = read_config()
        return _store_snapshot(snap, generation, version)
    _maybe_check_version()
    with _lock:
        generation = _generation
        if _snapshot and time.monotonic() - _snapshot[0] < ttl:
            return _snapshot[1]
        if time.monotonic() < _store_down_until:
            raise StoreUnreadable("flag store unreadable (cached)")
        # Single-flight (#771): a cold cache used to send every concurrent
        # caller to the store. Join a read already in flight for this
        # generation (one begun before a clear would serve a pre-write view);
        # otherwise lead one.
        flight = _flight
        leader = flight is None or flight.generation != generation
        if leader:
            flight = _flight = _Flight(generation)
    if not leader:
        # The leader's read is bounded per page by STORE_TIMEOUT_S; wait a
        # little longer than a two-page read, then fail closed.
        if not flight.done.wait(STORE_TIMEOUT_S * 3):
            raise StoreUnreadable("flag store read still in flight")
        if flight.error is not None:
            raise flight.error
        assert flight.result is not None
        return flight.result
    try:
        # The version BEFORE the config: the snapshot is then at least as new
        # as the version it is filed under (a write in between only causes
        # one extra reload on the next check). Usually no read at all (a
        # version is already known); when it read and found the store
        # unreachable, fail closed now rather than wait on the config too.
        version = _baseline_version()
        if version is None and store_unreadable():
            raise StoreUnreadable("flag store unreadable (version read)")
        try:
            snap = read_config(timeout=STORE_TIMEOUT_S)
        except _STORE_ERRORS:
            _mark_store_down()  # callers fail closed; nothing re-reads for a while
            raise
        flight.result = snap
        return _store_snapshot(snap, generation, version)
    except BaseException as exc:
        flight.error = exc
        raise
    finally:
        with _lock:
            if _flight is flight:
                _flight = None
        flight.done.set()


def _store_snapshot(snap: Snapshot, generation: int, version: int | None = None) -> Snapshot:
    global _snapshot, _store_down_until, _version, _version_checked
    with _lock:
        _store_down_until = 0.0  # the store answered
        if generation == _generation:  # no clear landed while we were reading
            _snapshot = (time.monotonic(), snap)
            _version, _version_checked = version, time.monotonic()
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
    with service_scope():  # #115: part of the flag store (see read_config)
        rows = table("user_roles").select(
            "role_id,roles!inner(display_priority)", filters={"user_id": f"eq.{user_id}"},
            timeout=STORE_TIMEOUT_S,
        ) or []
    out = tuple(
        (str(r["role_id"]), int(((r.get("roles") or {}).get("display_priority")) or 0))
        for r in rows
    )
    with _lock:
        _roles.pop(user_id, None)  # re-inserted last: insertion order = age
        _roles[user_id] = (time.monotonic(), out)
        while len(_roles) > ROLES_CACHE_MAX:
            _roles.pop(next(iter(_roles)))
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
        if _version_due():
            return None  # re-validating against feature_flags_version is a read
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


async def resolve_off_loop(cached: Callable[[], T | None], read: Callable[[], T]) -> T:
    """The one way event-loop code reads a flag: ``cached()`` (must do no
    I/O) when it answers, else ``read()`` — which may hit the store, bounded
    by STORE_TIMEOUT_S — in a worker thread. Raises whatever ``read`` or the
    thread hop raises (an executor shut down at teardown): each caller keeps
    its own failure semantics — llm_budget, llm_fallback and the outage
    drill read a failure as off, the tutor router skips the turn."""
    hit = cached()
    if hit is not None:
        return hit
    return await asyncio.to_thread(read)


async def explain_off_loop(key: str, user_id: str | None) -> Resolution:
    """:func:`explain` for code on the event loop (:func:`resolve_off_loop`)."""
    return await resolve_off_loop(
        lambda: cached_explain(key, user_id), lambda: explain(key, user_id),
    )


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


def store_unreadable() -> bool:
    """Whether the flag store is inside its unreadable window right now — so
    a fail-closed answer just given was an outage, not configuration. GET
    /api/flags reports it (``degraded``) so the client keeps its last-known
    nav flags instead of un-hiding every hidden feature (#771)."""
    with _lock:
        return time.monotonic() < _store_down_until


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


#: The backend half of the ``hide_<feature>`` flags (#771): the API routers a
#: hidden feature's pages use, mounted in main.py with
#: ``require_feature_visible``. A hidden feature used to stay fully callable —
#: the flags were enforced only by the frontend nav. Each router is listed
#: under the ONE flag that hides it; ``exempt`` names the (method, path regex)
#: pairs another visible surface still calls, so hiding one feature never
#: breaks another. A ``hide_*`` flag absent here is deliberately not enforced
#: on the API (``NAV_FEATURES_NOT_ENFORCED`` says why).
NAV_FEATURE_API: dict[str, dict[str, tuple[tuple[str, str], ...]]] = {
    "hide_quiz": {
        # Tree shows the student's recent attempts.
        "/api/quiz": (("GET", r"/attempts"),),
    },
    # /api/study is the Study hub's own (daily goal + minutes).
    "hide_study": {"/api/flashcards": (), "/api/study-guide": (), "/api/study": ()},
    # Only the Library's own folders router: /api/documents stays open — it
    # backs the shared upload modal (Calendar) and Study's document list.
    "hide_library": {"/api/library": ()},
    "hide_calendar": {
        # The dashboard's upcoming-deadlines card.
        "/api/calendar": (("GET", r"/upcoming/[^/]+"),),
    },
    "hide_social": {
        # Friends are on every profile page (ProfileView), not just Social.
        "/api/social": (("*", r"/friends(/.*)?"),),
    },
    "hide_achievements": {
        # The quiz results screen shows the XP/streak delta.
        "/api/gamification": (("GET", r"/me"),),
    },
    # /api/gradescope stays: Settings > Connected accounts manages it.
    "hide_grades": {"/api/gradebook": ()},
    "hide_notetaker": {"/api/notes": ()},
}

NAV_FEATURES_NOT_ENFORCED: dict[str, str] = {
    "hide_tutor": "the quiz Ask panel streams through the tutor's chat/session "
                  "endpoints and the dashboard/tree list sessions",
    "hide_tree": "/api/graph backs the course list every page loads",
    "hide_course_planner": "the page is static; it calls no API",
}


def require_feature_visible(flag: str, prefix: str):
    """Router dependency for a ``hide_<feature>`` flag: 404 when the flag hides
    the feature for the session user, except on the ``NAV_FEATURE_API``
    exemptions for ``prefix``. Fail-closed "off" (an unreadable store) means
    visible, exactly as the nav reads it."""
    exempt = tuple(
        (method, re.compile(re.escape(prefix) + pattern + r"/?$"))
        for method, pattern in NAV_FEATURE_API[flag][prefix]
    )

    def _dependency(request: Request) -> None:
        path = request.url.path
        if any((m == "*" or m == request.method) and rx.match(path) for m, rx in exempt):
            return
        from services.auth_guard import get_session_user_id
        try:
            uid = get_session_user_id(request)
        except HTTPException:
            uid = None
        if flag_variant(flag, uid) == "on":
            raise HTTPException(status_code=404, detail="Not found")
    return _dependency


def nav_feature_gate(prefix: str) -> list:
    """``include_router(dependencies=...)`` for the router mounted at
    ``prefix``: the ``require_feature_visible`` gate of the ``hide_*`` flag
    that lists it in NAV_FEATURE_API."""
    from fastapi import Depends

    flag = next(f for f, routers in NAV_FEATURE_API.items() if prefix in routers)
    return [Depends(require_feature_visible(flag, prefix))]
