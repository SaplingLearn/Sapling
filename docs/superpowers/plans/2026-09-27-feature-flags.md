# Feature Flags (#620) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Admin-controlled feature flags (a user, role, percentage or global default; no redeploy; audited; fail-closed), wired to the Jev decision router, the learning loop (#673) and PostHog analytics.

**Architecture:**
- Flags are declared in a code registry (`backend/services/feature_flags.py`), and their configuration lives in two Postgres tables.
- One resolver answers `flag_variant(key, user_id)` from a 30s per-process snapshot cache. Admin writes clear the cache and are audited.
- Admins configure flags in a new tab in `/admin`.
- The frontend reads client-visible flags once per page load through `GET /api/flags` and a `useFlag` hook, which returns the off variant until loaded.

**Tech Stack:** FastAPI + PostgREST via `db/connection.py::table()`, pytest, Next.js / React (vitest, Playwright).

**Spec:** `docs/superpowers/specs/2026-09-27-feature-flags-design.md`. Read it first; this plan implements it.

## Global Constraints

- **Worktree:** everything is on branch `feat/620-feature-flags` in `/home/andresl/Projects/sapling-wt-flags`, stacked on `feat/posthog-frontend`. Never touch the primary checkout's git state.
- **Supabase access:** only through `db/connection.py::table()`. No new httpx clients.
- **Migration:** exactly ONE new file. Name it with `date -u +%Y%m%d%H%M%S` followed by `_feature_flags.sql` in `backend/db/migrations/`. It must be idempotent (`IF NOT EXISTS`, `ON CONFLICT DO NOTHING`).
- **Registry:** `variants[0]` of every flag is `"off"`, and the fail-closed answer is always `variants[0]`.
- **Caches:** they follow the #98 rule. Each has a `clear_*` hook that every mutator calls, and the autouse `_clear_lru_caches` fixture in `backend/tests/conftest.py` calls them too.
- **Client API:** `Cache-Control: private, no-store` on `GET /api/flags`, never `public`.
- **Events and audit:** `flag.changed` must be registered in `services/events_service.py::EVENT_TAXONOMY` and in the pin in `backend/tests/test_event_capture_seams.py`. Every admin write also calls `services.admin_audit.log_admin_action`.
- **Backend tests:** run from `backend/` with `/home/andresl/Projects/sapling/backend/venv/bin/python -m pytest tests/ -q`. Symlink `backend/.env` from the primary checkout (`ln -sf /home/andresl/Projects/sapling/backend/.env backend/.env`) and remove it afterwards. The baseline is 0 failures with `.env` linked.
- **Frontend:** COPY `node_modules` from `/home/andresl/Projects/sapling/frontend/node_modules`, then run `npm install --engine-strict=false --no-save --no-audit --no-fund posthog-js@1.434.15`. Revert `package.json` and `package-lock.json` if npm touched them, and remove `node_modules` when done.
- **Shell:** use `/usr/bin/grep`, since bare `grep`/`find` are shadowed and truncate. The shell is fish, so wrap bash syntax in `bash -c '...'`.
- **Commits:** `git commit -- <paths>` only, never `git add -A`. Every message ends with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

## Review Focus

1. **The flag store is unreadable** (DB down, table missing before the migration): every flag returns `"off"`, the failure is NOT cached, and routes still answer.
2. **A student holds two roles with conflicting rules:** the higher `roles.display_priority` wins deterministically, and ties go to the lowest role id.
3. **An admin raises the rollout from 10% to 20%:** every student who had the rollout variant at 10% still has it. Membership only grows.
4. **An admin sets a rule for a user or role that doesn't exist, or a variant not in the registry:** 422 or 404, and nothing is written.
5. **`product_analytics` is flipped off:** the backend PostHog worker stops sending, and the frontend never starts posthog-js, within the cache window.

---

### Task 1: Migration, registry and resolver

**Files:**
- Create: `backend/db/migrations/<UTC-ts>_feature_flags.sql`
- Create: `backend/services/feature_flags.py`
- Modify: `backend/tests/conftest.py` (the `_clear_lru_caches` fixture, around lines 64-76)
- Test: `backend/tests/test_feature_flags.py`

**Interfaces produced:**
- `FlagDef(key: str, variants: tuple[str, ...], description: str, client_visible: bool)`
- `REGISTRY: dict[str, FlagDef]`
- `Resolution(variant: str, step: str, detail: str)`, where `step` is one of `env_override` / `fail_closed` / `user` / `role` / `rollout` / `default`
- `explain(key: str, user_id: str | None, *, fresh: bool = False) -> Resolution`
- `flag_variant(key: str, user_id: str | None) -> str`
- `flag_on(key: str, user_id: str | None) -> bool`
- `resolved_client_flags(user_id: str | None) -> dict[str, str]`
- `require_flag(key: str)`, a FastAPI dependency factory
- `read_config() -> Snapshot`, an uncached read used by the admin API
- `clear_feature_flags_cache() -> None`
- `clear_user_roles_cache(user_id: str | None = None) -> None`
- `rollout_bucket(key: str, user_id: str) -> float`

- [ ] **Step 1: Write the migration**

Run `date -u +%Y%m%d%H%M%S` and create `backend/db/migrations/<that>_feature_flags.sql`:

```sql
-- #620 feature flags (ADR 0029). Flags are DECLARED in code
-- (backend/services/feature_flags.py::REGISTRY); these tables hold only their
-- configuration. Variant validity is enforced by the app, not the DB.
CREATE TABLE IF NOT EXISTS feature_flags (
    key              TEXT PRIMARY KEY CHECK (key ~ '^[a-z][a-z0-9_]{1,62}$'),
    default_variant  TEXT NOT NULL,
    rollout_percent  SMALLINT NOT NULL DEFAULT 0 CHECK (rollout_percent BETWEEN 0 AND 100),
    rollout_variant  TEXT,
    updated_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_by       TEXT REFERENCES users(id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS feature_flag_targets (
    flag_key     TEXT NOT NULL REFERENCES feature_flags(key) ON DELETE CASCADE,
    target_type  TEXT NOT NULL CHECK (target_type IN ('user', 'role')),
    target_id    TEXT NOT NULL,
    variant      TEXT NOT NULL,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    created_by   TEXT REFERENCES users(id) ON DELETE SET NULL,
    PRIMARY KEY (flag_key, target_type, target_id)
);

-- PostHog analytics stays ON once keys are set; admins can switch it off.
INSERT INTO feature_flags (key, default_variant) VALUES ('product_analytics', 'on')
ON CONFLICT (key) DO NOTHING;
```

- [ ] **Step 2: Write the failing resolver tests**

Create `backend/tests/test_feature_flags.py`:

```python
"""#620 resolver: precedence, fail-closed, caching, rollout stability."""
from unittest.mock import MagicMock, patch

import pytest

from services import feature_flags as ff

KEY = "learning_loop"  # registry: ("off", "on"), client_visible


def _tables(flags=None, targets=None, roles=None, fail=False):
    """table() factory: feature_flags / feature_flag_targets / user_roles."""
    def factory(name):
        m = MagicMock()
        if fail:
            m.select.side_effect = RuntimeError("db down")
        elif name == "feature_flags":
            m.select.side_effect = lambda *a, **k: (flags or []) if not k.get("offset") else []
        elif name == "feature_flag_targets":
            m.select.side_effect = lambda *a, **k: (targets or []) if not k.get("offset") else []
        elif name == "user_roles":
            m.select.return_value = roles or []
        else:
            m.select.return_value = []
        return m
    return factory


def _row(default="off", pct=0, rv=None):
    return {"key": KEY, "default_variant": default, "rollout_percent": pct,
            "rollout_variant": rv, "updated_at": None, "updated_by": None}


def test_registry_variants_start_with_off():
    for fd in ff.REGISTRY.values():
        assert fd.variants[0] == "off"


def test_no_row_is_off_default():
    with patch("services.feature_flags.table", side_effect=_tables()):
        r = ff.explain(KEY, "u1")
    assert (r.variant, r.step) == ("off", "default")


def test_default_row():
    with patch("services.feature_flags.table", side_effect=_tables(flags=[_row("on")])):
        assert ff.flag_variant(KEY, "u1") == "on"
        assert ff.flag_on(KEY, "u1") is True


def test_user_rule_beats_role_rollout_default():
    targets = [
        {"flag_key": KEY, "target_type": "user", "target_id": "u1", "variant": "off"},
        {"flag_key": KEY, "target_type": "role", "target_id": "r1", "variant": "on"},
    ]
    roles = [{"role_id": "r1", "roles": {"display_priority": 100}}]
    with patch("services.feature_flags.table",
               side_effect=_tables(flags=[_row("on", 100, "on")], targets=targets, roles=roles)):
        r = ff.explain(KEY, "u1")
    assert (r.variant, r.step) == ("off", "user")


def test_role_priority_then_lowest_id():
    targets = [
        {"flag_key": KEY, "target_type": "role", "target_id": "r-low", "variant": "off"},
        {"flag_key": KEY, "target_type": "role", "target_id": "r-high", "variant": "on"},
    ]
    roles = [{"role_id": "r-low", "roles": {"display_priority": 10}},
             {"role_id": "r-high", "roles": {"display_priority": 80}}]
    with patch("services.feature_flags.table",
               side_effect=_tables(flags=[_row()], targets=targets, roles=roles)):
        assert ff.explain(KEY, "u1").variant == "on"
    ff.clear_feature_flags_cache(); ff.clear_user_roles_cache()
    tie = [{"role_id": "b", "roles": {"display_priority": 50}},
           {"role_id": "a", "roles": {"display_priority": 50}}]
    t2 = [{"flag_key": KEY, "target_type": "role", "target_id": "a", "variant": "on"},
          {"flag_key": KEY, "target_type": "role", "target_id": "b", "variant": "off"}]
    with patch("services.feature_flags.table",
               side_effect=_tables(flags=[_row()], targets=t2, roles=tie)):
        r = ff.explain(KEY, "u1")
    assert (r.variant, r.step, r.detail) == ("on", "role", "a")


def test_rollout_membership_only_grows():
    users = [f"user_{i}" for i in range(400)]
    at10 = {u for u in users if ff.rollout_bucket(KEY, u) < 10}
    at20 = {u for u in users if ff.rollout_bucket(KEY, u) < 20}
    assert at10 and at10 <= at20 and len(at20) > len(at10)
    assert ff.rollout_bucket(KEY, "user_7") == ff.rollout_bucket(KEY, "user_7")


def test_rollout_applies_to_bucket():
    inside = next(u for u in (f"u{i}" for i in range(1000)) if ff.rollout_bucket(KEY, u) < 30)
    outside = next(u for u in (f"u{i}" for i in range(1000)) if ff.rollout_bucket(KEY, u) >= 30)
    with patch("services.feature_flags.table", side_effect=_tables(flags=[_row("off", 30, "on")])):
        assert ff.explain(KEY, inside).step == "rollout"
        assert ff.flag_variant(KEY, inside) == "on"
        assert ff.flag_variant(KEY, outside) == "off"


def test_anonymous_skips_user_role_rollout():
    with patch("services.feature_flags.table", side_effect=_tables(flags=[_row("off", 100, "on")])):
        r = ff.explain(KEY, None)
    assert (r.variant, r.step) == ("off", "default")


def test_invalid_stored_variant_is_off():
    with patch("services.feature_flags.table", side_effect=_tables(flags=[_row("banana")])):
        r = ff.explain(KEY, "u1")
    assert (r.variant, r.step) == ("off", "fail_closed")


def test_unregistered_key_is_off():
    assert ff.flag_variant("no_such_flag", "u1") == "off"
    assert ff.flag_on("no_such_flag", "u1") is False


def test_store_failure_fails_closed_and_is_not_cached():
    with patch("services.feature_flags.table", side_effect=_tables(fail=True)):
        r = ff.explain(KEY, "u1")
    assert (r.variant, r.step) == ("off", "fail_closed")
    with patch("services.feature_flags.table", side_effect=_tables(flags=[_row("on")])):
        assert ff.flag_variant(KEY, "u1") == "on"  # retried, not a cached failure


def test_snapshot_is_cached_until_cleared():
    calls = {"n": 0}
    base = _tables(flags=[_row("on")])

    def counting(name):
        if name == "feature_flags":
            calls["n"] += 1
        return base(name)

    with patch("services.feature_flags.table", side_effect=counting):
        ff.flag_variant(KEY, "u1"); ff.flag_variant(KEY, "u2")
        assert calls["n"] == 1
        ff.clear_feature_flags_cache()
        ff.flag_variant(KEY, "u1")
        assert calls["n"] == 2


def test_env_override(monkeypatch):
    monkeypatch.setenv("SAPLING_FLAG_LEARNING_LOOP", "on")
    with patch("services.feature_flags.table", side_effect=_tables(fail=True)):
        r = ff.explain(KEY, "u1")
    assert (r.variant, r.step) == ("on", "env_override")
    monkeypatch.setenv("SAPLING_FLAG_LEARNING_LOOP", "banana")
    with patch("services.feature_flags.table", side_effect=_tables(flags=[_row("off")])):
        assert ff.flag_variant(KEY, "u1") == "off"


def test_resolved_client_flags_only_client_visible():
    with patch("services.feature_flags.table", side_effect=_tables()):
        out = ff.resolved_client_flags("u1")
    visible = {k for k, fd in ff.REGISTRY.items() if fd.client_visible}
    assert set(out) == visible
    assert "decision_router" not in out


def test_require_flag_404_when_off():
    from fastapi import HTTPException
    dep = ff.require_flag(KEY)
    req = MagicMock()
    with patch("services.feature_flags.table", side_effect=_tables()), \
         patch("services.auth_guard.get_session_user_id", return_value="u1"):
        with pytest.raises(HTTPException) as e:
            dep(req)
    assert e.value.status_code == 404
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `cd backend && /home/andresl/Projects/sapling/backend/venv/bin/python -m pytest tests/test_feature_flags.py -q`

Expected: FAIL with `ImportError: cannot import name 'feature_flags'`.

- [ ] **Step 4: Implement `backend/services/feature_flags.py`**

```python
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


def _warn_once(key: str, msg: str, *args) -> None:
    if key not in _warned:
        _warned.add(key)
        logger.warning(msg, *args)


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
```

Note: `_warn_once` with `exc_info=True` goes through `logger.warning(msg, *args)`. Make its signature `_warn_once(key, msg, *args, **kwargs)` and pass `**kwargs` through to `logger.warning`.

- [ ] **Step 5: Register the caches in the conftest fixture**

In `backend/tests/conftest.py`, `_clear_lru_caches`, add to the import and to both the before and after blocks:

```python
    from services import academics, analytics_consent, course_context_service, feature_flags, growth
    ...
    feature_flags.clear_feature_flags_cache()
    feature_flags.clear_user_roles_cache()
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `/home/andresl/Projects/sapling/backend/venv/bin/python -m pytest tests/test_feature_flags.py -q`

Expected: PASS, 15 tests.

- [ ] **Step 7: Commit**

```bash
git commit -m "feat(flags): registry, resolver and migration (#620)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>" -- backend/db/migrations backend/services/feature_flags.py backend/tests/test_feature_flags.py backend/tests/conftest.py
```

(`git add` the new files first: `git add backend/db/migrations/*_feature_flags.sql backend/services/feature_flags.py backend/tests/test_feature_flags.py`.)

---

### Task 2: Admin API

**Files:**
- Create: `backend/routes/admin_flags.py`
- Modify: `backend/main.py` (the router block, ~line 314: mount `/api/admin/flags` before `admin_router`'s generic routes; add it next to `admin_analytics_router`)
- Modify: `backend/routes/admin.py`, the `assign_role` and `revoke_role` routes: call `feature_flags.clear_user_roles_cache(body.user_id)` after the write
- Modify: `backend/services/events_service.py`: add `"flag.changed"` to `EVENT_TAXONOMY`, plus a docstring table row: `flag.changed  audit  key, field, before, after`
- Modify: `backend/tests/test_event_capture_seams.py` (the taxonomy pin, ~line 87): add `"flag.changed"`
- Test: `backend/tests/test_admin_flags_routes.py`

**Interfaces:**
- Consumes: Task 1's `REGISTRY`, `read_config`, `explain(..., fresh=True)`, `clear_feature_flags_cache`, `clear_user_roles_cache`.
- Produces these HTTP endpoints, all `require_admin`:
  - `GET /api/admin/flags` returns `{"flags": [FlagView]}`, where `FlagView` = `{key, description, variants, client_visible, default_variant, rollout_percent, rollout_variant, updated_at, updated_by, updated_by_name, targets: [{target_type, target_id, label, variant}]}`
  - `PATCH /api/admin/flags/{key}` with body `{default_variant?, rollout_percent?, rollout_variant?}` returns `{"flag": FlagView}`
  - `PUT /api/admin/flags/{key}/targets` with body `{target_type, target_id, variant}` returns `{"flag": FlagView}`
  - `DELETE /api/admin/flags/{key}/targets/{target_type}/{target_id}` returns `{"flag": FlagView}`
  - `GET /api/admin/flags/{key}/explain?user_id=` returns `{variant, step, detail}`

- [ ] **Step 1: Write the failing route tests**

Create `backend/tests/test_admin_flags_routes.py`:

```python
"""#620 admin flags API: auth, validation, audit + event, cache clear."""
from unittest.mock import MagicMock, patch

from fastapi import HTTPException
from fastapi.testclient import TestClient

from main import app

client = TestClient(app)
ADMIN = "admin_1"


class _DB:
    """In-memory feature_flags / feature_flag_targets / users / roles."""

    def __init__(self):
        self.flags: dict[str, dict] = {}
        self.targets: dict[tuple, dict] = {}
        self.users = {"u1"}
        self.roles = {"r-admin": {"id": "r-admin", "name": "Admin", "display_priority": 100}}

    def table(self, name):
        db = self
        m = MagicMock()
        if name == "feature_flags":
            m.select.side_effect = lambda *a, **k: (
                [] if k.get("offset") else
                [dict(v) for v in db.flags.values()
                 if not (k.get("filters") or {}).get("key")
                 or v["key"] == k["filters"]["key"].removeprefix("eq.")])

            def upsert(row, on_conflict="id", ignore_duplicates=False):
                if ignore_duplicates and row["key"] in db.flags:
                    return []
                cur = db.flags.get(row["key"], {"rollout_percent": 0, "rollout_variant": None,
                                               "updated_at": None, "updated_by": None})
                db.flags[row["key"]] = {**cur, **row}
                return [db.flags[row["key"]]]
            m.upsert.side_effect = upsert
        elif name == "feature_flag_targets":
            m.select.side_effect = lambda *a, **k: [] if k.get("offset") else [dict(v) for v in db.targets.values()]
            m.upsert.side_effect = lambda row, **k: db.targets.__setitem__(
                (row["flag_key"], row["target_type"], row["target_id"]), row) or [row]

            def delete(filters):
                key = (filters["flag_key"].removeprefix("eq."), filters["target_type"].removeprefix("eq."),
                       filters["target_id"].removeprefix("eq."))
                return [db.targets.pop(key)] if key in db.targets else []
            m.delete.side_effect = delete
        elif name == "users":
            m.select.side_effect = lambda *a, **k: (
                [{"id": k["filters"]["id"].removeprefix("eq.")}]
                if k["filters"]["id"].removeprefix("eq.") in db.users else [])
        elif name == "roles":
            m.select.side_effect = lambda *a, **k: (
                [r for r in db.roles.values()
                 if not (k.get("filters") or {}).get("id") or r["id"] == k["filters"]["id"].removeprefix("eq.")])
        elif name == "user_roles":
            m.select.return_value = []
        return m


def _admin(db):
    return [
        patch("routes.admin_flags.require_admin", return_value=None),
        patch("routes.admin_flags.get_session_user_id", return_value=ADMIN),
        patch("routes.admin_flags.table", side_effect=db.table),
        patch("services.feature_flags.table", side_effect=db.table),
        patch("routes.admin_flags.get_display_names", return_value={"u1": "Student One"}),
        patch("routes.admin_flags.log_admin_action"),
        patch("routes.admin_flags.log_event"),
    ]


def _run(db, fn):
    ps = _admin(db)
    mocks = [p.start() for p in ps]
    try:
        return fn(), mocks
    finally:
        for p in ps:
            p.stop()


def test_non_admin_forbidden():
    with patch("routes.admin_flags.require_admin",
               side_effect=HTTPException(status_code=403, detail="Forbidden")):
        assert client.get("/api/admin/flags").status_code == 403


def test_list_includes_every_registered_flag():
    db = _DB()
    r, _ = _run(db, lambda: client.get("/api/admin/flags"))
    assert r.status_code == 200
    keys = {f["key"] for f in r.json()["flags"]}
    assert keys == {"decision_router", "learning_loop", "product_analytics"}
    ll = next(f for f in r.json()["flags"] if f["key"] == "learning_loop")
    assert ll["default_variant"] == "off" and ll["variants"] == ["off", "on"]


def test_patch_validates_and_audits():
    db = _DB()
    r, mocks = _run(db, lambda: client.patch("/api/admin/flags/learning_loop",
                                            json={"default_variant": "banana"}))
    assert r.status_code == 422 and "learning_loop" not in db.flags
    r, mocks = _run(db, lambda: client.patch("/api/admin/flags/learning_loop",
                                            json={"rollout_percent": 20}))
    assert r.status_code == 422  # rollout_variant required when percent > 0
    r, mocks = _run(db, lambda: client.patch("/api/admin/flags/learning_loop",
                                            json={"rollout_percent": 20, "rollout_variant": "on"}))
    assert r.status_code == 200
    assert db.flags["learning_loop"]["rollout_percent"] == 20
    assert db.flags["learning_loop"]["updated_by"] == ADMIN
    audit, event = mocks[5], mocks[6]
    assert audit.call_args.kwargs["action"] == "flag.update"
    assert event.call_args.args[0] == "flag.changed"
    assert event.call_args.kwargs["category"] == "audit"


def test_unknown_flag_404():
    db = _DB()
    r, _ = _run(db, lambda: client.patch("/api/admin/flags/nope", json={"default_variant": "on"}))
    assert r.status_code == 404


def test_target_upsert_requires_existing_user_and_valid_variant():
    db = _DB()
    r, _ = _run(db, lambda: client.put("/api/admin/flags/learning_loop/targets",
                                      json={"target_type": "user", "target_id": "ghost", "variant": "on"}))
    assert r.status_code == 404 and not db.targets
    r, _ = _run(db, lambda: client.put("/api/admin/flags/learning_loop/targets",
                                      json={"target_type": "user", "target_id": "u1", "variant": "maybe"}))
    assert r.status_code == 422 and not db.targets
    r, _ = _run(db, lambda: client.put("/api/admin/flags/learning_loop/targets",
                                      json={"target_type": "user", "target_id": "u1", "variant": "on"}))
    assert r.status_code == 200
    assert "learning_loop" in db.flags  # parent row created for the FK, default off
    assert db.flags["learning_loop"]["default_variant"] == "off"
    view = r.json()["flag"]
    assert view["targets"] == [{"target_type": "user", "target_id": "u1",
                                "label": "Student One", "variant": "on"}]


def test_target_delete_and_explain():
    db = _DB()
    _run(db, lambda: client.put("/api/admin/flags/learning_loop/targets",
                               json={"target_type": "role", "target_id": "r-admin", "variant": "on"}))
    r, _ = _run(db, lambda: client.get("/api/admin/flags/learning_loop/explain?user_id=u1"))
    assert r.json() == {"variant": "off", "step": "default", "detail": "stored default"}
    r, _ = _run(db, lambda: client.delete("/api/admin/flags/learning_loop/targets/role/r-admin"))
    assert r.status_code == 200 and not db.targets


def test_writes_clear_the_resolver_cache():
    db = _DB()
    with patch("services.feature_flags.clear_feature_flags_cache") as clear:
        _run(db, lambda: client.patch("/api/admin/flags/learning_loop", json={"default_variant": "on"}))
    assert clear.called
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `/home/andresl/Projects/sapling/backend/venv/bin/python -m pytest tests/test_admin_flags_routes.py -q`

Expected: FAIL with 404s, because the router isn't mounted yet.

- [ ] **Step 3: Implement `backend/routes/admin_flags.py`**

```python
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
```

- [ ] **Step 4: Mount the router, add the taxonomy entry, clear the roles cache**

In `backend/main.py`:
- Import: `from routes.admin_flags import router as admin_flags_router`.
- Mount it BEFORE `app.include_router(admin_router, prefix="/api/admin")`, so a generic admin path can't shadow it: `app.include_router(admin_flags_router, prefix="/api/admin/flags")`.

In `backend/services/events_service.py`:
- Add `"flag.changed",` inside `EVENT_TAXONOMY` with the comment `# #620: admin feature-flag change (audit).`
- Add a docstring table row: `flag.changed                  audit     key, field, before, after`.

In `backend/tests/test_event_capture_seams.py`, add `"flag.changed",` to the pinned set.

In `backend/routes/admin.py`, add after the `table("user_roles").upsert(...)` in `assign_role`, and after the delete in `revoke_role`:

```python
    from services.feature_flags import clear_user_roles_cache
    clear_user_roles_cache(body.user_id)
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `/home/andresl/Projects/sapling/backend/venv/bin/python -m pytest tests/test_admin_flags_routes.py tests/test_event_capture_seams.py tests/test_feature_flags.py -q`

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/routes/admin_flags.py backend/tests/test_admin_flags_routes.py
git commit -m "feat(flags): admin API with audit, events and explain (#620)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>" -- backend/routes/admin_flags.py backend/routes/admin.py backend/main.py backend/services/events_service.py backend/tests/test_admin_flags_routes.py backend/tests/test_event_capture_seams.py
```

---

### Task 3: Client API `GET /api/flags`

**Files:**
- Create: `backend/routes/flags.py`
- Modify: `backend/main.py` (mount at `/api/flags`)
- Test: `backend/tests/test_flags_route.py`

**Interfaces:**
- Consumes: `feature_flags.resolved_client_flags(user_id)`.
- Produces: `GET /api/flags` returns `{"flags": {key: variant}}` with `Cache-Control: private, no-store`.

- [ ] **Step 1: Write the failing test**

```python
"""#620 GET /api/flags: client-visible only, signed-out defaults, no caching."""
from unittest.mock import patch

from fastapi import HTTPException
from fastapi.testclient import TestClient

from main import app

client = TestClient(app)


def test_signed_in_gets_client_visible_flags():
    with patch("routes.flags.get_session_user_id", return_value="u1"), \
         patch("routes.flags.feature_flags.resolved_client_flags",
               return_value={"learning_loop": "on", "product_analytics": "on"}) as res:
        r = client.get("/api/flags")
    assert r.status_code == 200
    assert r.json() == {"flags": {"learning_loop": "on", "product_analytics": "on"}}
    res.assert_called_once_with("u1")
    assert r.headers["cache-control"] == "private, no-store"


def test_signed_out_resolves_anonymously():
    with patch("routes.flags.get_session_user_id",
               side_effect=HTTPException(status_code=401, detail="no session")), \
         patch("routes.flags.feature_flags.resolved_client_flags", return_value={}) as res:
        r = client.get("/api/flags")
    assert r.status_code == 200
    res.assert_called_once_with(None)


def test_server_only_flags_never_leak():
    with patch("routes.flags.get_session_user_id", return_value="u1"):
        r = client.get("/api/flags")
    assert "decision_router" not in r.json()["flags"]
```

- [ ] **Step 2: Run to verify it fails**

Run: `/home/andresl/Projects/sapling/backend/venv/bin/python -m pytest tests/test_flags_route.py -q`

Expected: FAIL (404).

- [ ] **Step 3: Implement `backend/routes/flags.py`**

```python
"""GET /api/flags — the signed-in student's client-visible flags (#620)."""
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse

from services import feature_flags
from services.auth_guard import get_session_user_id

router = APIRouter()


@router.get("")
def get_flags(request: Request):
    try:
        user_id = get_session_user_id(request)
    except HTTPException:
        user_id = None
    return JSONResponse(
        {"flags": feature_flags.resolved_client_flags(user_id)},
        headers={"Cache-Control": "private, no-store"},
    )
```

In `backend/main.py`: import `from routes.flags import router as flags_router` and mount `app.include_router(flags_router, prefix="/api/flags")`.

- [ ] **Step 4: Run to verify it passes**

Same command as Step 2. Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/routes/flags.py backend/tests/test_flags_route.py
git commit -m "feat(flags): GET /api/flags for client-visible flags (#620)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>" -- backend/routes/flags.py backend/main.py backend/tests/test_flags_route.py
```

---

### Task 4: Consumer — the `decision_router` flag drives the tutor router

**Files:**
- Modify: `backend/services/decisions.py`
  - `decide()` (~line 955): add keyword-only overrides.
  - Add `router_backends(user_id)` near `configured_backend` (~line 139).
- Modify: `backend/services/tutor_router.py`
  - `observe_tutor_turn` (~line 225): replace `if not decisions.enabled()`.
  - `_route` (~line 156): pass the overrides.
- Test: `backend/tests/test_decision_router_flag.py`

**Interfaces:**
- Consumes: `feature_flags.flag_variant("decision_router", user_id)`.
- Produces:
  - `decisions.router_backends(user_id: str | None) -> tuple[str, str]` returns `(primary, shadow)`, each one of `OFF`/`JEV`/`FLASH_LITE`/`FUNCTION`.
  - `decisions.decide(..., backend: str | None = None, shadow: str | None = None)`.

- [ ] **Step 1: Write the failing tests**

```python
"""#620: the decision_router flag picks the tutor router's backends."""
from unittest.mock import patch

import pytest

from services import decisions


@pytest.fixture(autouse=True)
def _real_mode(monkeypatch):
    monkeypatch.delenv("SAPLING_MODEL_MODE", raising=False)
    monkeypatch.delenv("SAPLING_DECISIONS_BACKEND", raising=False)
    monkeypatch.delenv("SAPLING_DECISIONS_SHADOW", raising=False)


@pytest.mark.parametrize("variant,expected", [
    ("off", (decisions.OFF, decisions.OFF)),
    ("jev", (decisions.JEV, decisions.OFF)),
    ("jev_shadow", (decisions.JEV, decisions.FLASH_LITE)),
])
def test_flag_variant_maps_to_backends(variant, expected):
    with patch("services.feature_flags.flag_variant", return_value=variant):
        assert decisions.router_backends("u1") == expected


def test_explicit_env_backend_wins_over_flag(monkeypatch):
    monkeypatch.setenv("SAPLING_DECISIONS_BACKEND", "flash_lite")
    with patch("services.feature_flags.flag_variant", return_value="jev") as fv:
        assert decisions.router_backends("u1") == (decisions.FLASH_LITE, decisions.OFF)
    fv.assert_not_called()


def test_function_mode_ignores_flag(monkeypatch):
    monkeypatch.setenv("SAPLING_MODEL_MODE", "function")
    with patch("services.feature_flags.flag_variant", return_value="off") as fv:
        assert decisions.router_backends("u1")[0] == decisions.FUNCTION
    fv.assert_not_called()


def test_router_skips_everything_when_flag_off():
    from services import tutor_router
    with patch("services.feature_flags.flag_variant", return_value="off"), \
         patch("services.tutor_router.build_state") as build:
        out = tutor_router.observe_tutor_turn(
            user_id="u1", session_id="s1", message="hi", history=[],
            request_id="r1", model_pref_requested=None, model_tier="default", tutor_model="m",
        )
    assert out is None and not build.called


def test_decide_uses_explicit_overrides():
    import asyncio
    q = [decisions.YesNo(key="k", instructions="?", default=False)]
    with patch("services.decisions._answer_with") as aw:
        aw.side_effect = Exception("stop")  # we only assert which backend was requested
        asyncio.run(decisions.decide("s", q, feature="t", backend=decisions.JEV, shadow=decisions.OFF))
    assert aw.call_args.args[0] == decisions.JEV  # decide() never raises (fails soft)
```

Before running, check `observe_tutor_turn`'s real keyword parameters with `/usr/bin/grep -n "def observe_tutor_turn" -A14 services/tutor_router.py`. Make the call in `test_router_skips_everything_when_flag_off` match them exactly. Check the `YesNo` constructor fields with `/usr/bin/grep -n "class YesNo" -A10 services/decisions.py` and adjust the test's arguments to match. Also check that `_answer_with`'s first positional argument is the backend name.

- [ ] **Step 2: Run to verify they fail**

Run: `/home/andresl/Projects/sapling/backend/venv/bin/python -m pytest tests/test_decision_router_flag.py -q`

Expected: FAIL (no `router_backends`, unknown kwargs).

- [ ] **Step 3: Implement**

In `backend/services/decisions.py`, add after `enabled()`:

```python
#: decision_router flag variant -> (primary, shadow) backends (#620).
_FLAG_BACKENDS = {
    "off": (OFF, OFF),
    "jev": (JEV, OFF),
    "jev_shadow": (JEV, FLASH_LITE),
}


def router_backends(user_id: str | None) -> tuple[str, str]:
    """The tutor router's (primary, shadow) backends for this student.

    Function mode and an explicitly-set SAPLING_DECISIONS_BACKEND keep the
    env-driven behaviour (the E2E lane and the operator emergency override);
    otherwise the `decision_router` feature flag decides (ADR 0029).
    """
    if _model_mode() == "function" or (os.getenv(BACKEND_ENV) or "").strip():
        return configured_backend(), shadow_backend()
    from services.feature_flags import flag_variant
    return _FLAG_BACKENDS.get(flag_variant("decision_router", user_id), (OFF, OFF))
```

In `decide()`, add keyword-only parameters `backend: str | None = None, shadow: str | None = None` to the signature. Where it currently does `primary_backend = configured_backend()` and `shadow_name = shadow_backend()`, use:

```python
    primary_backend = backend if backend is not None else configured_backend()
    shadow_name = shadow if shadow is not None else shadow_backend()
    if shadow_name == primary_backend:
        shadow_name = OFF
```

In `backend/services/tutor_router.py`:
- Replace `if not decisions.enabled(): return None` with:

```python
        primary, shadow = decisions.router_backends(user_id)
        if primary == decisions.OFF:
            return None
```

- Thread `primary`/`shadow` into `_route(...)` as new keyword arguments, and pass them to `decisions.decide(..., backend=primary, shadow=shadow)`.

- [ ] **Step 4: Run the new tests and the existing decision/router suites**

Run: `/home/andresl/Projects/sapling/backend/venv/bin/python -m pytest tests/test_decision_router_flag.py tests/test_decisions.py tests/test_tutor_router.py -q`

Expected: PASS. If an existing router test assumed env-only enabling, give it `SAPLING_DECISIONS_BACKEND` explicitly (that path is unchanged), or patch `services.feature_flags.flag_variant`.

- [ ] **Step 5: Commit**

```bash
git add backend/tests/test_decision_router_flag.py
git commit -m "feat(flags): decision_router flag drives the tutor router (#620)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>" -- backend/services/decisions.py backend/services/tutor_router.py backend/tests/test_decision_router_flag.py backend/tests/test_decisions.py backend/tests/test_tutor_router.py
```

---

### Task 5: Consumer — `product_analytics` gates the PostHog worker

**Files:**
- Modify: `backend/services/posthog_client.py`, `_deliver` (~line 329)
- Test: `backend/tests/test_posthog_seam.py` (append a class)

**Interfaces:**
- Consumes: `feature_flags.flag_on("product_analytics", actor)`.
- Produces: no new API.

- [ ] **Step 1: Write the failing test** (append to `backend/tests/test_posthog_seam.py`)

```python
class TestProductAnalyticsFlag:
    def test_worker_drops_when_flag_off(self, monkeypatch):
        from services import posthog_client as pc
        sent = []

        class _C:
            def capture(self, *a, **k):
                sent.append(a)

        monkeypatch.setattr(pc, "_client", _C())
        monkeypatch.setattr(pc, "disabled_reason", lambda **k: None)
        monkeypatch.setattr(pc, "_distinct_id_for", lambda actor: actor)
        item = pc._Item(name="x", properties={}, actor="u1", captured_at=0.0)
        monkeypatch.setattr("services.feature_flags.flag_on", lambda k, u: False)
        pc._deliver(item)
        assert sent == []
        monkeypatch.setattr("services.feature_flags.flag_on", lambda k, u: True)
        pc._deliver(item)
        assert len(sent) == 1
```

Check `_Item`'s real fields first with `/usr/bin/grep -n "class _Item" -A8 services/posthog_client.py` and match the constructor.

- [ ] **Step 2: Run to verify it fails**

Run: `/home/andresl/Projects/sapling/backend/venv/bin/python -m pytest tests/test_posthog_seam.py -q -k ProductAnalyticsFlag`

Expected: FAIL (sent once while the flag is off).

- [ ] **Step 3: Implement.** In `_deliver`, right after the `disabled_reason()` re-check:

```python
        from services.feature_flags import flag_on
        if not flag_on("product_analytics", item.actor):  # #620: admin switch
            return
```

- [ ] **Step 4: Run the full PostHog seam suite**

Run: `/home/andresl/Projects/sapling/backend/venv/bin/python -m pytest tests/test_posthog_seam.py -q`

Expected: PASS. If earlier tests now drop events because no flag row exists (off by default in the mocked DB), make the existing autouse setup in that file patch `services.feature_flags.flag_on` to return `True`. Keep the new class overriding it.

- [ ] **Step 5: Commit**

```bash
git commit -m "feat(flags): product_analytics flag gates the PostHog worker (#620)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>" -- backend/services/posthog_client.py backend/tests/test_posthog_seam.py
```

---

### Task 6: Frontend flags provider, `useFlag`, and the analytics wiring

**Files:**
- Create: `frontend/src/lib/flags.ts`
- Create: `frontend/src/context/FlagsContext.tsx`
- Modify: the file that renders `<UserProvider>`. Find it with `bash -c 'grep -rln "<UserProvider" frontend/src'` and nest `<FlagsProvider>` directly inside `<UserProvider>`.
- Modify: `frontend/src/lib/analytics.ts`: add `setProductAnalyticsFlag`, and require it in `captureAllowed()` and wherever posthog-js is started (`ensureStarted`).
- Test: `frontend/src/context/FlagsContext.test.tsx`, plus one case added to `frontend/src/lib/analytics.test.ts`

**Interfaces:**
- Consumes: `GET /api/flags` (Task 3), `useUser()` from `@/context/UserContext`, `isAppShellRoute` from `@/lib/appRoutes`, and `fetchJSON` from `@/lib/api`.
- Produces:
  - `useFlag(key: string): string`, which returns `"off"` until loaded, on error, and off-shell;
  - `FlagsProvider`;
  - `fetchFlags(): Promise<Record<string, string>>`;
  - `setProductAnalyticsFlag(on: boolean): void` in `analytics.ts`.

- [ ] **Step 1: Write the failing tests** (`frontend/src/context/FlagsContext.test.tsx`)

```tsx
import { render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const fetchFlags = vi.fn();
vi.mock("@/lib/flags", () => ({ fetchFlags: () => fetchFlags() }));
const setProductAnalyticsFlag = vi.fn();
vi.mock("@/lib/analytics", () => ({ setProductAnalyticsFlag: (on: boolean) => setProductAnalyticsFlag(on) }));
let pathname = "/dashboard";
vi.mock("next/navigation", () => ({ usePathname: () => pathname }));
let user = { userId: "u1", isAuthenticated: true, userReady: true };
vi.mock("@/context/UserContext", () => ({ useUser: () => user }));

import { FlagsProvider, useFlag } from "./FlagsContext";

function Probe() {
  return <span data-testid="v">{useFlag("learning_loop")}</span>;
}

describe("FlagsProvider/useFlag", () => {
  beforeEach(() => {
    fetchFlags.mockReset(); setProductAnalyticsFlag.mockReset();
    pathname = "/dashboard"; user = { userId: "u1", isAuthenticated: true, userReady: true };
  });

  it("is off until loaded, then the fetched variant", async () => {
    let resolve!: (v: Record<string, string>) => void;
    fetchFlags.mockReturnValue(new Promise((r) => { resolve = r; }));
    render(<FlagsProvider><Probe /></FlagsProvider>);
    expect(screen.getByTestId("v").textContent).toBe("off");
    resolve({ learning_loop: "on", product_analytics: "on" });
    await waitFor(() => expect(screen.getByTestId("v").textContent).toBe("on"));
    expect(setProductAnalyticsFlag).toHaveBeenLastCalledWith(true);
  });

  it("fails closed on error and turns analytics off", async () => {
    fetchFlags.mockRejectedValue(new Error("down"));
    render(<FlagsProvider><Probe /></FlagsProvider>);
    await waitFor(() => expect(setProductAnalyticsFlag).toHaveBeenCalledWith(false));
    expect(screen.getByTestId("v").textContent).toBe("off");
  });

  it("does not fetch off the app shell and reads off", () => {
    pathname = "/privacy";
    render(<FlagsProvider><Probe /></FlagsProvider>);
    expect(fetchFlags).not.toHaveBeenCalled();
    expect(screen.getByTestId("v").textContent).toBe("off");
  });

  it("ignores a stale response after a user switch", async () => {
    let first!: (v: Record<string, string>) => void;
    fetchFlags.mockReturnValueOnce(new Promise((r) => { first = r; }))
      .mockResolvedValueOnce({ learning_loop: "off" });
    const { rerender } = render(<FlagsProvider><Probe /></FlagsProvider>);
    user = { userId: "u2", isAuthenticated: true, userReady: true };
    rerender(<FlagsProvider><Probe /></FlagsProvider>);
    first({ learning_loop: "on" });
    await waitFor(() => expect(fetchFlags).toHaveBeenCalledTimes(2));
    expect(screen.getByTestId("v").textContent).toBe("off");
  });
});
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd frontend && npx vitest run src/context/FlagsContext.test.tsx`

Expected: FAIL (module not found).

- [ ] **Step 3: Implement**

`frontend/src/lib/flags.ts`:

```ts
import { fetchJSON } from "@/lib/api";

export type FlagMap = Record<string, string>;

/** The signed-in student's client-visible flags (#620). */
export async function fetchFlags(): Promise<FlagMap> {
  const res = await fetchJSON<{ flags?: FlagMap }>("/api/flags");
  return res.flags ?? {};
}
```

`frontend/src/context/FlagsContext.tsx`:

```tsx
"use client";
import React, { createContext, useContext, useEffect, useRef, useState } from "react";
import { usePathname } from "next/navigation";

import { useUser } from "@/context/UserContext";
import { isAppShellRoute } from "@/lib/appRoutes";
import { fetchFlags, type FlagMap } from "@/lib/flags";
import { setProductAnalyticsFlag } from "@/lib/analytics";

/** Every registered flag's variants[0] is "off" (backend REGISTRY). */
const OFF = "off";

const FlagsContext = createContext<{ flags: FlagMap | null; onAppRoute: boolean }>({
  flags: null,
  onAppRoute: false,
});

export function FlagsProvider({ children }: { children: React.ReactNode }) {
  const { userId, isAuthenticated, userReady } = useUser();
  const onAppRoute = isAppShellRoute(usePathname());
  const [flags, setFlags] = useState<FlagMap | null>(null);
  const [loadedFor, setLoadedFor] = useState<string | null>(null);
  const generation = useRef(0);

  useEffect(() => {
    if (!userReady) return;
    const who = isAuthenticated && userId ? userId : null;
    if (!who) {
      generation.current += 1;
      setFlags(null);
      setLoadedFor(null);
      setProductAnalyticsFlag(false);
      return;
    }
    if (!onAppRoute || loadedFor === who) return;
    const gen = ++generation.current;
    setFlags(null);
    fetchFlags().then(
      (f) => {
        if (gen !== generation.current) return;
        setFlags(f);
        setLoadedFor(who);
        setProductAnalyticsFlag(f.product_analytics === "on");
      },
      () => {
        if (gen !== generation.current) return;
        setFlags({});
        setLoadedFor(who);
        setProductAnalyticsFlag(false);
      },
    );
  }, [userReady, isAuthenticated, userId, onAppRoute, loadedFor]);

  return <FlagsContext.Provider value={{ flags, onAppRoute }}>{children}</FlagsContext.Provider>;
}

/** The variant of `key` for this student; "off" until loaded, on error, off-shell. */
export function useFlag(key: string): string {
  const { flags, onAppRoute } = useContext(FlagsContext);
  if (!onAppRoute || !flags) return OFF;
  return flags[key] ?? OFF;
}
```

In `frontend/src/lib/analytics.ts`, add a module-level flag. It defaults to `false`, so analytics fails closed until flags load:

```ts
/** #620: the admin `product_analytics` switch. Off until /api/flags answers. */
let productAnalyticsFlag = false;

export function setProductAnalyticsFlag(on: boolean): void {
  productAnalyticsFlag = on;
  if (on) ensureStarted();
  notify();
}
```

Then:
- Add `productAnalyticsFlag &&` as the first condition inside `captureAllowed()`.
- Add it at the top of `ensureStarted()`'s start condition (`if (!productAnalyticsFlag) return;`).
- Reset it to `false` in the module's test-reset helper, if one exists (search: `bash -c 'grep -n "resetForTests\|__reset" frontend/src/lib/analytics.ts'`).

Add to `frontend/src/lib/analytics.test.ts`:

```ts
it("never starts posthog-js while the product_analytics flag is off (#620)", async () => {
  // Arrange the same "signed in, allowed" state the existing start test uses, then:
  setProductAnalyticsFlag(false);
  // assert: no posthog-js load/init and getAnalyticsState() !== "on"
  setProductAnalyticsFlag(true);
  // assert: posthog-js init happens exactly once
});
```

Fill the arrange and assert lines by copying the setup and assertions from the existing test in that file that proves "signed-in, not opted out ⇒ init" (search for `beginAccountRead` in `analytics.test.ts`). The only difference is the flag toggle.

Nest the provider: in the file found above, change `<UserProvider>{children}</UserProvider>` to `<UserProvider><FlagsProvider>{children}</FlagsProvider></UserProvider>` and import `FlagsProvider` from `@/context/FlagsContext`.

- [ ] **Step 4: Run the tests and type check**

Run: `cd frontend && npx vitest run src/context/FlagsContext.test.tsx src/lib/analytics.test.ts && npx tsc --noEmit && npx eslint src/context src/lib`

Expected: PASS, 0 type errors, and no new lint errors. If lint reports "suppressions left", run `npx eslint . --prune-suppressions` and commit `frontend/eslint-suppressions.json`.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/lib/flags.ts frontend/src/context/FlagsContext.tsx frontend/src/context/FlagsContext.test.tsx
git commit -m "feat(flags): FlagsProvider/useFlag; product_analytics gates posthog-js (#620)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>" -- frontend/src/lib/flags.ts frontend/src/context/FlagsContext.tsx frontend/src/context/FlagsContext.test.tsx frontend/src/lib/analytics.ts frontend/src/lib/analytics.test.ts <provider-file-path>
```

---

### Task 7: Admin UI — the "Feature flags" tab

**Files:**
- Create: `frontend/src/components/screens/admin/FeatureFlags.tsx`
- Create: `frontend/src/components/screens/admin/FeatureFlags.test.tsx`
- Modify: `frontend/src/components/screens/Admin.tsx`
  - `type Tab` (line 26): add `"flags"`.
  - The `tabs` array (line 57): add `"flags"` after `"roles"`.
  - The tab switch (lines 87-94): add `{tab === "flags" && <FeatureFlagsTab />}`.
- Modify: `frontend/src/lib/api.ts`: add the admin flag helpers next to `adminListRoles` (~line 1127).
- Modify: `docs/frontend-testids.md`: add the new testids under the admin surface.

**Interfaces:**
- Consumes: the Task 2 endpoints, plus the existing `adminFetchUsers`, `adminListRoles`, `useConfirm` and `useToast`.
- Produces: the `adminListFlags`, `adminUpdateFlag`, `adminUpsertFlagTarget`, `adminDeleteFlagTarget` and `adminExplainFlag` helpers, and the `FeatureFlagsTab` component.
- Test ids:
  - `admin-tab-flags`
  - `flag-row-{key}`
  - `flag-default-{key}`
  - `flag-rollout-{key}`
  - `flag-rollout-variant-{key}`
  - `flag-save-{key}`
  - `flag-target-add-{key}`
  - `flag-target-row-{key}-{type}-{id}`
  - `flag-target-remove-{key}-{type}-{id}`
  - `flag-explain-input-{key}`
  - `flag-explain-result-{key}`

- [ ] **Step 1: Add the API helpers** to `frontend/src/lib/api.ts`

```ts
export type AdminFlagTarget = { target_type: 'user' | 'role'; target_id: string; label: string; variant: string };
export type AdminFlag = {
  key: string; description: string; variants: string[]; client_visible: boolean;
  default_variant: string; rollout_percent: number; rollout_variant: string | null;
  updated_at: string | null; updated_by: string | null; updated_by_name: string | null;
  targets: AdminFlagTarget[];
};

export const adminListFlags = () => fetchJSON<{ flags: AdminFlag[] }>('/api/admin/flags');
export const adminUpdateFlag = (key: string, body: { default_variant?: string; rollout_percent?: number; rollout_variant?: string | null }) =>
  fetchJSON<{ flag: AdminFlag }>(`/api/admin/flags/${encodeURIComponent(key)}`, {
    method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
  });
export const adminUpsertFlagTarget = (key: string, body: { target_type: 'user' | 'role'; target_id: string; variant: string }) =>
  fetchJSON<{ flag: AdminFlag }>(`/api/admin/flags/${encodeURIComponent(key)}/targets`, {
    method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
  });
export const adminDeleteFlagTarget = (key: string, type: 'user' | 'role', id: string) =>
  fetchJSON<{ flag: AdminFlag }>(
    `/api/admin/flags/${encodeURIComponent(key)}/targets/${type}/${encodeURIComponent(id)}`, { method: 'DELETE' });
export const adminExplainFlag = (key: string, userId: string) =>
  fetchJSON<{ variant: string; step: string; detail: string }>(
    `/api/admin/flags/${encodeURIComponent(key)}/explain?user_id=${encodeURIComponent(userId)}`);
```

Check how the existing admin POST/PATCH helpers set headers (look at `adminAssignRole`, ~line 1115) and match that style exactly. `fetchJSON` may already set the JSON content-type.

- [ ] **Step 2: Write the failing component test** (`FeatureFlags.test.tsx`)

```tsx
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const api = vi.hoisted(() => ({
  adminListFlags: vi.fn(), adminUpdateFlag: vi.fn(), adminUpsertFlagTarget: vi.fn(),
  adminDeleteFlagTarget: vi.fn(), adminExplainFlag: vi.fn(),
  adminListRoles: vi.fn(), adminFetchUsers: vi.fn(),
}));
vi.mock("@/lib/api", () => api);
const confirm = vi.fn();
vi.mock("@/lib/useConfirm", () => ({ useConfirm: () => confirm }));
vi.mock("../../ToastProvider", () => ({ useToast: () => ({ show: vi.fn() }) }));

import { FeatureFlagsTab } from "./FeatureFlags";

const FLAG = {
  key: "learning_loop", description: "AI learning loop (#673).", variants: ["off", "on"],
  client_visible: true, default_variant: "off", rollout_percent: 0, rollout_variant: null,
  updated_at: null, updated_by: null, updated_by_name: null, targets: [],
};

describe("FeatureFlagsTab", () => {
  beforeEach(() => {
    Object.values(api).forEach((f) => f.mockReset());
    confirm.mockReset();
    api.adminListFlags.mockResolvedValue({ flags: [FLAG] });
    api.adminListRoles.mockResolvedValue({ roles: [{ id: "r-admin", name: "Admin" }] });
    api.adminFetchUsers.mockResolvedValue({ users: [], total: 0 });
  });

  it("lists flags", async () => {
    render(<FeatureFlagsTab />);
    expect(await screen.findByTestId("flag-row-learning_loop")).toBeTruthy();
  });

  it("asks for confirmation before a default change and saves on yes", async () => {
    confirm.mockResolvedValue(true);
    api.adminUpdateFlag.mockResolvedValue({ flag: { ...FLAG, default_variant: "on" } });
    render(<FeatureFlagsTab />);
    fireEvent.click(await screen.findByTestId("flag-row-learning_loop"));
    fireEvent.change(screen.getByTestId("flag-default-learning_loop"), { target: { value: "on" } });
    fireEvent.click(screen.getByTestId("flag-save-learning_loop"));
    await waitFor(() => expect(api.adminUpdateFlag).toHaveBeenCalledWith(
      "learning_loop", { default_variant: "on", rollout_percent: 0, rollout_variant: null }));
    expect(confirm).toHaveBeenCalled();
  });

  it("does not save when the confirm is declined", async () => {
    confirm.mockResolvedValue(false);
    render(<FeatureFlagsTab />);
    fireEvent.click(await screen.findByTestId("flag-row-learning_loop"));
    fireEvent.change(screen.getByTestId("flag-default-learning_loop"), { target: { value: "on" } });
    fireEvent.click(screen.getByTestId("flag-save-learning_loop"));
    await waitFor(() => expect(confirm).toHaveBeenCalled());
    expect(api.adminUpdateFlag).not.toHaveBeenCalled();
  });

  it("explains a student's variant", async () => {
    api.adminExplainFlag.mockResolvedValue({ variant: "on", step: "role", detail: "r-admin" });
    render(<FeatureFlagsTab />);
    fireEvent.click(await screen.findByTestId("flag-row-learning_loop"));
    fireEvent.change(screen.getByTestId("flag-explain-input-learning_loop"), { target: { value: "u1" } });
    fireEvent.keyDown(screen.getByTestId("flag-explain-input-learning_loop"), { key: "Enter" });
    expect((await screen.findByTestId("flag-explain-result-learning_loop")).textContent)
      .toContain("on");
  });
});
```

Check `useConfirm`'s real call signature (`frontend/src/lib/useConfirm.ts`) and `useToast`'s API (`ToastProvider`), and match the mocks and the component to them.

- [ ] **Step 3: Run to verify it fails**

Run: `cd frontend && npx vitest run src/components/screens/admin/FeatureFlags.test.tsx`

Expected: FAIL (module not found).

- [ ] **Step 4: Implement `FeatureFlags.tsx`.** Follow the inline-style conventions of `RolesTab` in `Admin.tsx`: `var(--text)`, `var(--text-dim)`, `var(--accent)`, 13px tables, and `AdminTableSkeleton` while loading.

```tsx
"use client";
import React from "react";

import { AdminTableSkeleton } from "../../Skeleton";
import { useToast } from "../../ToastProvider";
import { useConfirm } from "@/lib/useConfirm";
import {
  adminListFlags, adminUpdateFlag, adminUpsertFlagTarget, adminDeleteFlagTarget,
  adminExplainFlag, adminListRoles, adminFetchUsers, type AdminFlag,
} from "@/lib/api";

export function FeatureFlagsTab() {
  const [flags, setFlags] = React.useState<AdminFlag[] | null>(null);
  const [open, setOpen] = React.useState<string | null>(null);
  const [roles, setRoles] = React.useState<{ id: string; name: string }[]>([]);

  React.useEffect(() => {
    adminListFlags().then((r) => setFlags(r.flags), () => setFlags([]));
    adminListRoles().then((r) => setRoles(r.roles), () => setRoles([]));
  }, []);

  if (!flags) return <AdminTableSkeleton />;
  const replace = (f: AdminFlag) => setFlags((all) => (all ?? []).map((x) => (x.key === f.key ? f : x)));

  return (
    <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
      <thead>
        <tr style={{ textAlign: "left", color: "var(--text-dim)" }}>
          <th>Flag</th><th>Default</th><th>Rollout</th><th>Rules</th><th>Last change</th>
        </tr>
      </thead>
      <tbody>
        {flags.map((f) => (
          <React.Fragment key={f.key}>
            <tr data-testid={`flag-row-${f.key}`} onClick={() => setOpen(open === f.key ? null : f.key)}
                style={{ cursor: "pointer", borderTop: "1px solid var(--border)" }}>
              <td><strong>{f.key}</strong><div style={{ color: "var(--text-dim)" }}>{f.description}</div></td>
              <td>{f.default_variant}</td>
              <td>{f.rollout_percent > 0 ? `${f.rollout_percent}% → ${f.rollout_variant}` : "—"}</td>
              <td>{f.targets.length}</td>
              <td>{f.updated_at ? `${f.updated_by_name ?? f.updated_by ?? ""} · ${new Date(f.updated_at).toLocaleString()}` : "—"}</td>
            </tr>
            {open === f.key && (
              <tr><td colSpan={5}><FlagEditor flag={f} roles={roles} onSaved={replace} /></td></tr>
            )}
          </React.Fragment>
        ))}
      </tbody>
    </table>
  );
}

function FlagEditor({ flag, roles, onSaved }: {
  flag: AdminFlag; roles: { id: string; name: string }[]; onSaved: (f: AdminFlag) => void;
}) {
  const toast = useToast();
  const confirm = useConfirm();
  const [def, setDef] = React.useState(flag.default_variant);
  const [pct, setPct] = React.useState(flag.rollout_percent);
  const [rv, setRv] = React.useState<string | null>(flag.rollout_variant);
  const [ruleType, setRuleType] = React.useState<"user" | "role">("role");
  const [ruleId, setRuleId] = React.useState("");
  const [ruleVariant, setRuleVariant] = React.useState(flag.variants[flag.variants.length - 1]);
  const [userQuery, setUserQuery] = React.useState("");
  const [userHits, setUserHits] = React.useState<{ id: string; name?: string; email?: string }[]>([]);
  const [explainId, setExplainId] = React.useState("");
  const [explained, setExplained] = React.useState<string | null>(null);

  const save = async () => {
    const ok = await confirm({
      title: `Change ${flag.key} for everyone?`,
      message: `Default → ${def}; rollout ${pct}%${pct > 0 ? ` → ${rv}` : ""}. Affects every student without a user or role rule.`,
    });
    if (!ok) return;
    try {
      const r = await adminUpdateFlag(flag.key, { default_variant: def, rollout_percent: pct, rollout_variant: pct > 0 ? rv : null });
      onSaved(r.flag);
      toast.show("Flag saved");
    } catch (e) {
      toast.show(`Couldn't save: ${(e as Error).message}`);
    }
  };

  const addRule = async () => {
    if (!ruleId) return;
    try {
      onSaved((await adminUpsertFlagTarget(flag.key, { target_type: ruleType, target_id: ruleId, variant: ruleVariant })).flag);
      setRuleId(""); setUserQuery(""); setUserHits([]);
    } catch (e) {
      toast.show(`Couldn't add rule: ${(e as Error).message}`);
    }
  };

  const searchUsers = async (q: string) => {
    setUserQuery(q);
    if (q.trim().length < 2) return setUserHits([]);
    const r = await adminFetchUsers({ q, page_size: 8 });
    setUserHits((r as unknown as { users: { id: string; name?: string; email?: string }[] }).users ?? []);
  };

  const explain = async () => {
    if (!explainId) return;
    const r = await adminExplainFlag(flag.key, explainId);
    setExplained(`${r.variant} (${r.step}${r.detail ? `: ${r.detail}` : ""})`);
  };

  return (
    <div style={{ display: "grid", gap: 12, padding: "12px 0" }}>
      <div style={{ display: "flex", gap: 12, alignItems: "center" }}>
        <label>Default{" "}
          <select data-testid={`flag-default-${flag.key}`} value={def} onChange={(e) => setDef(e.target.value)}>
            {flag.variants.map((v) => <option key={v} value={v}>{v}</option>)}
          </select>
        </label>
        <label>Rollout{" "}
          <input data-testid={`flag-rollout-${flag.key}`} type="range" min={0} max={100} value={pct}
                 onChange={(e) => setPct(Number(e.target.value))} /> {pct}%
        </label>
        <select data-testid={`flag-rollout-variant-${flag.key}`} value={rv ?? ""} disabled={pct === 0}
                onChange={(e) => setRv(e.target.value || null)}>
          <option value="">variant…</option>
          {flag.variants.slice(1).map((v) => <option key={v} value={v}>{v}</option>)}
        </select>
        <button data-testid={`flag-save-${flag.key}`} onClick={save}>Save</button>
      </div>

      <div>
        <strong>Rules</strong>
        <table style={{ width: "100%", fontSize: 13 }}>
          <tbody>
            {flag.targets.map((t) => (
              <tr key={`${t.target_type}-${t.target_id}`} data-testid={`flag-target-row-${flag.key}-${t.target_type}-${t.target_id}`}>
                <td>{t.target_type}</td><td>{t.label}</td><td>{t.variant}</td>
                <td>
                  <button data-testid={`flag-target-remove-${flag.key}-${t.target_type}-${t.target_id}`}
                          onClick={async () => onSaved((await adminDeleteFlagTarget(flag.key, t.target_type, t.target_id)).flag)}>
                    Remove
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
          <select value={ruleType} onChange={(e) => { setRuleType(e.target.value as "user" | "role"); setRuleId(""); }}>
            <option value="role">role</option><option value="user">user</option>
          </select>
          {ruleType === "role" ? (
            <select value={ruleId} onChange={(e) => setRuleId(e.target.value)}>
              <option value="">pick a role…</option>
              {roles.map((r) => <option key={r.id} value={r.id}>{r.name}</option>)}
            </select>
          ) : (
            <span style={{ position: "relative" }}>
              <input placeholder="search students…" value={userQuery} onChange={(e) => searchUsers(e.target.value)} />
              {userHits.length > 0 && (
                <ul style={{ position: "absolute", background: "var(--bg)", zIndex: 10, listStyle: "none", padding: 4, margin: 0 }}>
                  {userHits.map((u) => (
                    <li key={u.id}><button onClick={() => { setRuleId(u.id); setUserQuery(u.name || u.email || u.id); setUserHits([]); }}>
                      {u.name || u.email || u.id}
                    </button></li>
                  ))}
                </ul>
              )}
            </span>
          )}
          <select value={ruleVariant} onChange={(e) => setRuleVariant(e.target.value)}>
            {flag.variants.map((v) => <option key={v} value={v}>{v}</option>)}
          </select>
          <button data-testid={`flag-target-add-${flag.key}`} onClick={addRule} disabled={!ruleId}>Add rule</button>
        </div>
      </div>

      <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
        <input data-testid={`flag-explain-input-${flag.key}`} placeholder="check a student (user id)…"
               value={explainId} onChange={(e) => setExplainId(e.target.value)}
               onKeyDown={(e) => { if (e.key === "Enter") explain(); }} />
        <button onClick={explain}>Check</button>
        {explained && <span data-testid={`flag-explain-result-${flag.key}`}>{explained}</span>}
      </div>
    </div>
  );
}
```

Match `adminFetchUsers`'s real return shape: check the `PaginatedUsers` type in `frontend/src/lib/types.ts` or `api.ts`, and remove the `as unknown as` cast once it's typed. Also match the `useConfirm` and `useToast` call signatures found in Step 2.

- [ ] **Step 5: Wire the tab into `Admin.tsx`**

- Add `"flags"` to `type Tab` and to the `tabs` array after `"roles"`.
- Add `{tab === "flags" && <FeatureFlagsTab />}`.
- Import `FeatureFlagsTab` from `"./admin/FeatureFlags"`.
- Give the tab button for `"flags"` `data-testid="admin-tab-flags"`. If the tab buttons have no testids yet, add ``data-testid={`admin-tab-${t}`}`` to the mapped button.
- Update `docs/frontend-testids.md` with every testid listed under Interfaces.

- [ ] **Step 6: Run the tests, type check and lint**

Run: `cd frontend && npx vitest run src/components/screens/admin/FeatureFlags.test.tsx && npx tsc --noEmit && npx eslint src/components/screens`

Expected: PASS, and no "suppressions left" (prune and commit the suppressions file if it appears).

- [ ] **Step 7: Commit**

```bash
git add frontend/src/components/screens/admin/FeatureFlags.tsx frontend/src/components/screens/admin/FeatureFlags.test.tsx
git commit -m "feat(flags): admin Feature flags tab (#620)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>" -- frontend/src/components/screens/admin/FeatureFlags.tsx frontend/src/components/screens/admin/FeatureFlags.test.tsx frontend/src/components/screens/Admin.tsx frontend/src/lib/api.ts docs/frontend-testids.md
```

---

### Task 8: E2E seed, journey and oracle

**Files:**
- Modify: `backend/db/seed_local_rich.py`: add `seed_feature_flags()` and call it from the main sequence (~line 864, after `seed_users()` runs; place it with the others).
- Create: `frontend/e2e/feature-flags.spec.ts`
- Modify: `backend/e2e_oracles/gather.py` (add `run_flags`) and `backend/e2e_oracles/__main__.py` (add `"flags"` to `CHECKS`)
- Test: `backend/tests/test_e2e_oracles_flags.py`

**Interfaces:**
- Consumes: the Task 2 admin API, `REGISTRY`, and the E2E support helpers `mintStorageState` and `queryRaw`.

- [ ] **Step 1: Seed.** The flag tables are NOT in `TRUNCATE_DENYLIST`, so journeys start clean. Re-seed the migration's row so the baseline matches prod. In `seed_local_rich.py`:

```python
def seed_feature_flags() -> None:
    """#620: the migration seeds product_analytics=on; the per-test TRUNCATE
    wipes it, so restore the prod-like baseline. No other flag rows: every
    other flag is off (its variants[0]) until a journey configures it."""
    table("feature_flags").upsert(
        {"key": "product_analytics", "default_variant": "on"}, on_conflict="key",
    )
```

Call `seed_feature_flags()` in the main seed sequence.

- [ ] **Step 2: Oracle, test first.** Create `backend/tests/test_e2e_oracles_flags.py`:

```python
from e2e_oracles import gather


def test_flags_oracle_flags_invalid_variants():
    rows_flags = [{"key": "learning_loop", "default_variant": "banana", "rollout_variant": None}]
    rows_targets = [{"flag_key": "decision_router", "target_type": "user",
                     "target_id": "u1", "variant": "on"}]
    findings = gather.flag_findings(rows_flags, rows_targets)
    assert {f.evidence["key"] for f in findings} == {"learning_loop", "decision_router"}
    assert gather.flag_findings(
        [{"key": "learning_loop", "default_variant": "on", "rollout_variant": None}], []) == []
```

Implement in `gather.py`:

```python
def flag_findings(flags: list[dict], targets: list[dict]) -> list[Finding]:
    """#620: every stored variant must be one of its registry flag's variants."""
    from services.feature_flags import REGISTRY
    out: list[Finding] = []
    for f in flags:
        fd = REGISTRY.get(f["key"])
        for field in ("default_variant", "rollout_variant"):
            v = f.get(field)
            if fd and v is not None and v not in fd.variants:
                out.append(Finding("flags", f"{f['key']}.{field}={v!r} is not a registered variant",
                                   {"key": f["key"], "field": field, "value": v}))
    for t in targets:
        fd = REGISTRY.get(t["flag_key"])
        if fd and t["variant"] not in fd.variants:
            out.append(Finding("flags", f"{t['flag_key']} rule {t['target_type']}:{t['target_id']} "
                                        f"has unregistered variant {t['variant']!r}",
                               {"key": t["flag_key"], "target": f"{t['target_type']}:{t['target_id']}",
                                "value": t["variant"]}))
    return out


def run_flags(args: argparse.Namespace) -> tuple[list[Finding], int]:
    """`flags`: no stored flag variant falls outside the registry (#620)."""
    conn = _db_conn()
    flags = conn.execute("select key, default_variant, rollout_variant from feature_flags").fetchall()
    targets = conn.execute(
        "select flag_key, target_type, target_id, variant from feature_flag_targets").fetchall()
    return flag_findings([dict(r) for r in flags], [dict(r) for r in targets]), 0
```

Add `"flags": lambda args: gather.run_flags(args),` to `CHECKS` in `__main__.py`, and add `"flags"` to the `Finding.oracle` comment in `findings.py`.

Run: `/home/andresl/Projects/sapling/backend/venv/bin/python -m pytest tests/test_e2e_oracles_flags.py -q`

Expected: PASS.

- [ ] **Step 3: Journey.** Create `frontend/e2e/feature-flags.spec.ts`:

```ts
/**
 * Journey (#620): an admin gives one student a flag from /admin, and that
 * student's GET /api/flags reflects it; the rule is a real DB row.
 */
import { queryRaw } from "./support/db";
import { expect, test } from "./support/fixtures";
import { mintStorageState } from "./support/session";
import { FRONTEND_URL, USER_ACTIVE } from "./support/stack";

const USER_ADMIN = "rich-user-admin"; // seeded with the admin role

test("admin sets a user rule on learning_loop and the student gets it (#620)", async ({ browser, page }) => {
  // Baseline: the student sees learning_loop off.
  const before = await page.request.get(`${FRONTEND_URL}/api/flags`);
  expect((await before.json()).flags.learning_loop).toBe("off");

  const adminCtx = await browser.newContext({ storageState: await mintStorageState(USER_ADMIN) });
  const admin = await adminCtx.newPage();
  await admin.goto(`${FRONTEND_URL}/admin`);
  await admin.getByTestId("admin-tab-flags").click();
  await admin.getByTestId("flag-row-learning_loop").click();

  // Add a user rule through the API the tab uses (user search needs names
  // that the seed does not guarantee; the rules table is what we assert).
  const res = await admin.request.put(`${FRONTEND_URL}/api/admin/flags/learning_loop/targets`, {
    data: { target_type: "user", target_id: USER_ACTIVE, variant: "on" },
  });
  expect(res.ok()).toBeTruthy();
  await admin.reload();
  await admin.getByTestId("admin-tab-flags").click();
  await admin.getByTestId("flag-row-learning_loop").click();
  await expect(admin.getByTestId(`flag-target-row-learning_loop-user-${USER_ACTIVE}`)).toBeVisible();

  const rows = await queryRaw(
    "select variant from feature_flag_targets where flag_key = $1 and target_type = 'user' and target_id = $2",
    ["learning_loop", USER_ACTIVE],
  );
  expect(rows).toEqual([{ variant: "on" }]);

  // The cache is cleared on write in the same backend process.
  const after = await page.request.get(`${FRONTEND_URL}/api/flags`);
  expect((await after.json()).flags.learning_loop).toBe("on");

  // The explain box names the rule.
  await admin.getByTestId("flag-explain-input-learning_loop").fill(USER_ACTIVE);
  await admin.getByTestId("flag-explain-input-learning_loop").press("Enter");
  await expect(admin.getByTestId("flag-explain-result-learning_loop")).toContainText("on (user");
  await adminCtx.close();
});
```

Check `mintStorageState`'s real signature in `frontend/e2e/support/session.ts` and how `admin-analytics.spec.ts` uses it, and match exactly.

- [ ] **Step 4: Run the full E2E cycle.** Run all of this in ONE `flock /tmp/claude-1000/sapling-e2e-stack.lock bash -c '...'`:
  1. `make e2e-up`
  2. `cd frontend && npx playwright test`
  3. `cd backend && <venv>/bin/python -m e2e_oracles`
  4. `make e2e-down`, always.

Export `SAPLING_MODEL_MODE=function`, `SAPLING_FUNCTION_HANDLERS=agents.function_handlers_e2e`, `FRONTEND_PORT=3100`, `E2E_FRONTEND_URL=http://localhost:3100`, and `E2E_SEED_PYTHON=/home/andresl/Projects/sapling/backend/venv/bin/python` inside the cycle only. Symlink `backend/venv` and `backend/.env`, and copy `frontend/node_modules` and `frontend/.env.local`, as in the Global Constraints; clean up after.

Expected: all journeys pass, including `feature-flags.spec.ts`. Oracles report 0 findings, including the new `flags` check.

- [ ] **Step 5: Commit**

```bash
git add frontend/e2e/feature-flags.spec.ts backend/tests/test_e2e_oracles_flags.py
git commit -m "test(flags): e2e journey, seed baseline and flags oracle (#620)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>" -- backend/db/seed_local_rich.py frontend/e2e/feature-flags.spec.ts backend/e2e_oracles/gather.py backend/e2e_oracles/__main__.py backend/e2e_oracles/findings.py backend/tests/test_e2e_oracles_flags.py
```

---

### Task 9: Docs, env docs, full verification, PR, #673 note

**Files:**
- Create: `docs/decisions/0029-feature-flags.md`. Use the next free number; check `ls docs/decisions | tail -3` first, since open PRs may have claimed numbers.
- Modify: `CLAUDE.md`: a repo-map line for `services/feature_flags.py` + `routes/admin_flags.py`, and a Conventions line.
- Modify: `docs/architecture.md`: a flags paragraph.
- Modify: `backend/.env.example`: document `SAPLING_FLAG_<KEY>`, and note that `SAPLING_DECISIONS_BACKEND` is now an override of the `decision_router` flag.

- [ ] **Step 1: Write the ADR** with these sections:
  - **Context:** #620; env-var gating needs redeploys; #673's hand-set column.
  - **Decision:**
    - a code registry plus DB configuration;
    - the resolution order (spec §4);
    - fail-closed;
    - a 30s snapshot cache with clear-on-write;
    - no PostHog flags, for privacy and decoupling;
    - no Canopy in v1;
    - the three first flags.
  - **Consequences:**
    - up to 30s staleness on other replicas;
    - new flags need a registry line;
    - `SAPLING_DECISIONS_*` becomes an optional override;
    - analytics now needs `product_analytics=on`, which is seeded.

- [ ] **Step 2: Update `CLAUDE.md`.** Repo map:

```
- backend/services/feature_flags.py — #620 flags: REGISTRY (declared in code) + `flag_variant`/`flag_on`/`require_flag`; config in `feature_flags`/`feature_flag_targets`, edited via `routes/admin_flags.py` (`/api/admin/flags`); client-visible flags at `GET /api/flags` → frontend `useFlag`.
```

Conventions:

```
- **Gate unfinished or risky features with a flag** (`flag_on(key, user_id)` / `require_flag(key)` on the backend, `useFlag(key)` on the frontend). Declare the flag in `services/feature_flags.py::REGISTRY` (variants[0] must be `"off"`); never gate with a new env var or a per-feature `user_settings` column.
```

- [ ] **Step 3: Full verification.**
  - Backend: `python -m pytest tests/ -q` gives exact counts with 0 failures; `ruff check .` is clean.
  - Frontend: `npx tsc --noEmit`, `npx eslint .`, `npx vitest run` and `next build` all pass.
  - The Task 8 E2E cycle is green.

- [ ] **Step 4: Commit, push and open the PR.**

```bash
git commit -m "docs(flags): ADR 0029, CLAUDE.md, architecture, env docs (#620)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>" -- docs/decisions CLAUDE.md docs/architecture.md backend/.env.example
git push -u origin feat/620-feature-flags
gh pr create --base feat/posthog-frontend --head feat/620-feature-flags \
  --title "feat(flags): feature-flag system with admin UI (#620)" --body-file <prepared body>
```

The PR body must:
- summarise the spec;
- list the three consumers and the migration;
- state the rollout steps: Railway only needs `TYPESAFE_API_KEY`; set `decision_router` in `/admin`;
- give the verification counts;
- end with `🤖 Generated with [Claude Code](https://claude.com/claude-code)`.

- [ ] **Step 5: Leave the #673 note, as a comment only; do not edit that branch.**

```bash
gh pr comment 673 --body-file <prepared body>
```

The body proposes:
- that `learning/gate.py::learning_loop_active` becomes `LEARNING_LOOP_ENABLED and flag_on("learning_loop", user_id)` (import from `services.feature_flags`);
- dropping the `user_settings.learning_loop_beta` column from #673's migration, which has never been applied outside local dev;
- `useFlag("learning_loop")` for any UI gating;
- that the rollout to staff happens via a role rule in `/admin`.

End it with the Claude Code footer.
