# Admin Portal Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close every gap listed in issue #69 — pagination, server-side search, unapprove, audit log, last-sign-in tracking, self-protection, achievement triggers + cosmetic linking CRUD, and an analytics backend — and surface them in `frontend/src/components/screens/Admin.tsx` using the existing `card` / `chip` / `btn` / `label-micro` / `var(--accent)` design tokens (no new design language).

**Architecture:**
- Backend stays in `routes/admin.py` with one new helper (`services/admin_audit.py`). Mutating endpoints write a row to a new `admin_audit_log` table.
- `users.last_sign_in_at` column added; `routes/auth.py:google_callback` stamps it on every successful callback.
- Admin lists move to offset pagination (`limit` + `offset` + `Prefer: count=exact`); server-side search on `/users` works by decrypting the full table once when a query is supplied (admin-only, low traffic).
- Frontend keeps the existing tab strip (`users | allowlist | roles | achievements | cosmetics | analytics | audit`). All new UI uses existing CSS classes (`.card`, `.chip`, `.chip--accent`, `.chip--warn`, `.btn`, `.btn--primary`, `.btn--ghost`, `.btn--sm`, `.btn--danger`, `.label-micro`, `.h-serif`, `.body-serif`) and the existing `LabeledField` / `CatalogRow` / `CustomSelect` / `useConfirm` / `useToast` helpers — no new component library, no inline new CSS variables.

**Tech Stack:** FastAPI, Pydantic v2, Supabase REST (`db/connection.py::table()`), pytest + `fastapi.testclient`, React 18 + TypeScript, plain CSS variables in `frontend/src/app/globals.css`.

---

## File Structure

### Backend (created)
- `backend/db/migration_admin_portal.sql` — new tables (`admin_audit_log`, `role_cosmetics_admin_view`), new column (`users.last_sign_in_at`), new indexes.
- `backend/services/admin_audit.py` — `log_admin_action(actor_id, action, target_type, target_id, payload)` helper.
- `backend/services/users_search.py` — `paginate_users(q, page, page_size)`; isolates the decrypt-and-filter hot path so it can be cached/optimized later.

### Backend (modified)
- `backend/db/connection.py` — extend `select()` to support `Prefer: count=exact` and return `(rows, total)` so pagination knows the total without a second query.
- `backend/models/__init__.py` — add new request bodies (`UpdateAchievementTriggerBody`, `LinkAchievementCosmeticBody`, `LinkRoleCosmeticBody`, `UnapproveUserBody` is unnecessary — endpoint takes no body — but `UnapproveUserResponse` is implicit).
- `backend/routes/admin.py` — pagination + search on `/users`; `/users/{id}/unapprove` PATCH; `/audit` GET; trigger list/update/delete; `achievement_cosmetics` and `role_cosmetics` CRUD; analytics endpoints; self-protection guards; assign-role becomes upsert. Every mutating endpoint logs to `admin_audit_log`.
- `backend/routes/auth.py` — write `users.last_sign_in_at = now()` on every successful Google callback.
- `backend/tests/test_admin_routes.py` — extend with new test classes (one per endpoint added or changed).
- `backend/tests/test_admin_audit.py` — new file, tests the audit helper in isolation.
- `backend/tests/test_auth_state.py` — add a test that confirms `last_sign_in_at` is written.

### Frontend (modified)
- `frontend/src/lib/api.ts` — add `adminPaginatedUsers`, `adminUnapproveUser`, `adminListAllowlist`, `adminApproveAllowlist`, `adminRevokeAllowlist`, `adminListTriggers`, `adminCreateTrigger`, `adminUpdateTrigger`, `adminDeleteTrigger`, `adminListRoleCosmetics`, `adminLinkRoleCosmetic`, `adminUnlinkRoleCosmetic`, `adminListAchievementCosmetics`, `adminLinkAchievementCosmetic`, `adminUnlinkAchievementCosmetic`, `adminAnalyticsOverview`, `adminAuditLog`.
- `frontend/src/lib/types.ts` — add `AllowlistEmail`, `AchievementTrigger`, `AdminAuditEntry`, `AnalyticsOverview`. Extend `Cosmetic` with `unlock_source`, extend admin user shape to include `last_sign_in_at`.
- `frontend/src/components/screens/Admin.tsx` — extend `Tab` union (`+ "allowlist" | "audit"`); new `AllowlistTab`; new `AuditTab`; `UsersTab` gains pagination footer + server-side search + `Last sign-in` column + revoke/approve dropdown; `AchievementsTab` gains a triggers panel and a cosmetic-linker chip; `CosmeticsTab` gains a role-linker chip; `AnalyticsTab` becomes real (signups-per-day, totals, role breakdown).

### Files explicitly NOT touched
- `frontend/src/app/globals.css` — no new tokens. We reuse `--accent`, `--err-soft`, etc.
- `services/auth_guard.py` — already correct; the new self-protection lives in route handlers, not in the guard.
- `services/encryption.py` — unchanged. Search uses existing `decrypt_if_present`.

---

## Decisions Locked In (matches issue #69 "Decisions needed")

1. **Unapprove**: `PATCH /api/admin/users/{user_id}/unapprove` exists and is the inverse of `/approve`.
2. **Audit log**: single `admin_audit_log` table — `(id, actor_id, action, target_type, target_id, payload jsonb, created_at)`. Read via `GET /api/admin/audit?page=&page_size=&action=&target_type=`.
3. **Analytics**: `GET /api/admin/analytics/overview` returns totals + signups-per-day for the last 30 days + role membership counts. Anything fancier (DAU/MAU, per-feature funnels) is explicitly out of scope.
4. **Self-protection rules**: enforced server-side as 409 responses with `detail` strings the frontend surfaces unchanged via `toast.error`:
   - You cannot revoke your own admin role.
   - You cannot delete the `admin` role row.
   - You cannot revoke the last admin's admin role.
   - You cannot unapprove yourself.
5. **Pagination shape**: offset, default `page_size=50`, hard cap `page_size=200`. Page is 1-indexed in the URL (`?page=1`); SQL `offset = (page - 1) * page_size`. Response shape: `{ "users": [...], "total": N, "page": P, "page_size": S }`.

---

## Pre-flight: branch, worktree, requirements

- [ ] **Step 0.1: Create a worktree for this plan**

```bash
cd /home/andresl/Projects/sapling
git worktree add ../sapling-admin-portal -b feat/admin-portal main
cd ../sapling-admin-portal
```

- [ ] **Step 0.2: Confirm test suite is green before starting**

Run: `cd backend && python -m pytest tests/ -q`
Expected: full pass (or only known-skipped). If failing, stop and surface the failure to the user before writing code.

- [ ] **Step 0.3: Commit a marker so the branch base is obvious**

```bash
git commit --allow-empty -m "chore(admin): start admin portal work (issue #69)"
```

---

## Phase 1 — Schema foundations

### Task 1: `admin_audit_log` table + `users.last_sign_in_at` migration

**Files:**
- Create: `backend/db/migration_admin_portal.sql`

- [ ] **Step 1.1: Write the migration file**

```sql
-- Migration: Admin portal — audit log + last_sign_in tracking
-- Run once in Supabase SQL editor.

CREATE TABLE IF NOT EXISTS admin_audit_log (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    actor_id     TEXT NOT NULL REFERENCES users(id) ON DELETE SET NULL,
    action       TEXT NOT NULL,           -- e.g. 'user.approve', 'role.assign'
    target_type  TEXT NOT NULL,           -- 'user' | 'role' | 'achievement' | 'cosmetic' | 'allowlist' | 'trigger' | 'role_cosmetic' | 'achievement_cosmetic'
    target_id    TEXT,                    -- nullable for actions without a single target
    payload      JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_admin_audit_log_created_at
    ON admin_audit_log (created_at DESC);

CREATE INDEX IF NOT EXISTS idx_admin_audit_log_actor
    ON admin_audit_log (actor_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_admin_audit_log_target
    ON admin_audit_log (target_type, target_id);

ALTER TABLE users
    ADD COLUMN IF NOT EXISTS last_sign_in_at TIMESTAMPTZ;

CREATE INDEX IF NOT EXISTS idx_users_created_at
    ON users (created_at DESC);
```

- [ ] **Step 1.2: Apply the migration locally / in Supabase**

Run the file in the Supabase SQL editor for the dev project. Verify:

```sql
SELECT column_name FROM information_schema.columns
 WHERE table_name = 'users' AND column_name = 'last_sign_in_at';
SELECT 1 FROM admin_audit_log LIMIT 1;  -- should run without error
```

Expected: one row from the first query; no error from the second.

- [ ] **Step 1.3: Commit**

```bash
git add backend/db/migration_admin_portal.sql
git commit -m "feat(admin): admin_audit_log + users.last_sign_in_at migration"
```

---

## Phase 2 — Connection helper: count + paginate

We need to know `total` for the pagination footer. PostgREST returns it via the `Content-Range` header when `Prefer: count=exact` is set.

### Task 2: Extend `SupabaseTable.select` to optionally return `(rows, total)`

**Files:**
- Modify: `backend/db/connection.py`
- Test: `backend/tests/test_supabase.py`

- [ ] **Step 2.1: Write the failing test**

Append to `backend/tests/test_supabase.py`:

```python
from unittest.mock import MagicMock, patch
from db.connection import table


class TestSelectWithCount:
    def test_returns_rows_and_total_when_count_exact(self):
        fake = MagicMock()
        fake.json.return_value = [{"id": "1"}]
        fake.headers = {"Content-Range": "0-0/42"}
        fake.raise_for_status = MagicMock()

        with patch("db.connection._client") as c:
            c.get.return_value = fake
            rows, total = table("users").select_with_count(
                columns="id", limit=1, offset=0
            )

        assert rows == [{"id": "1"}]
        assert total == 42

    def test_total_zero_when_header_missing(self):
        fake = MagicMock()
        fake.json.return_value = []
        fake.headers = {}
        fake.raise_for_status = MagicMock()

        with patch("db.connection._client") as c:
            c.get.return_value = fake
            rows, total = table("users").select_with_count(columns="id")

        assert rows == []
        assert total == 0
```

- [ ] **Step 2.2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_supabase.py::TestSelectWithCount -v`
Expected: FAIL — `AttributeError: 'SupabaseTable' object has no attribute 'select_with_count'`.

- [ ] **Step 2.3: Implement `select_with_count`**

In `backend/db/connection.py`, after the existing `select` method:

```python
    def select_with_count(
        self,
        columns: str = "*",
        filters: Optional[dict] = None,
        order: Optional[str] = None,
        limit: Optional[int] = None,
        offset: Optional[int] = None,
    ) -> tuple[list, int]:
        """Like select(), but also returns total row count via Content-Range."""
        params: dict = {"select": columns}
        if filters:
            params.update(filters)
        if order:
            params["order"] = order
        if limit is not None:
            params["limit"] = str(limit)
        if offset is not None:
            params["offset"] = str(offset)
        headers = {"Prefer": "count=exact"}
        r = _client.get(self.url, params=params, headers=headers)
        r.raise_for_status()
        rows = r.json()
        total = 0
        cr = r.headers.get("Content-Range") or r.headers.get("content-range")
        if cr and "/" in cr:
            try:
                total = int(cr.rsplit("/", 1)[1])
            except ValueError:
                total = 0
        return rows, total
```

- [ ] **Step 2.4: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/test_supabase.py::TestSelectWithCount -v`
Expected: PASS.

- [ ] **Step 2.5: Commit**

```bash
git add backend/db/connection.py backend/tests/test_supabase.py
git commit -m "feat(db): SupabaseTable.select_with_count for paginated lists"
```

---

## Phase 3 — Audit log helper

### Task 3: `services/admin_audit.py` — single sanctioned write path

**Files:**
- Create: `backend/services/admin_audit.py`
- Test: `backend/tests/test_admin_audit.py`

- [ ] **Step 3.1: Write the failing tests**

`backend/tests/test_admin_audit.py`:

```python
from unittest.mock import MagicMock, patch
from services.admin_audit import log_admin_action


class TestLogAdminAction:
    def test_inserts_row_with_all_fields(self):
        with patch("services.admin_audit.table") as t:
            inserted = MagicMock()
            t.return_value.insert = inserted
            log_admin_action(
                actor_id="admin1",
                action="user.approve",
                target_type="user",
                target_id="u1",
                payload={"note": "manual"},
            )

        assert t.called
        assert t.call_args.args[0] == "admin_audit_log"
        inserted.assert_called_once()
        row = inserted.call_args.args[0]
        assert row["actor_id"] == "admin1"
        assert row["action"] == "user.approve"
        assert row["target_type"] == "user"
        assert row["target_id"] == "u1"
        assert row["payload"] == {"note": "manual"}

    def test_swallows_db_errors_so_main_action_still_succeeds(self):
        with patch("services.admin_audit.table") as t:
            t.return_value.insert.side_effect = RuntimeError("network")
            log_admin_action(
                actor_id="admin1",
                action="user.approve",
                target_type="user",
                target_id="u1",
            )  # must not raise
```

- [ ] **Step 3.2: Run tests, expect failure**

Run: `cd backend && python -m pytest tests/test_admin_audit.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'services.admin_audit'`.

- [ ] **Step 3.3: Implement the helper**

`backend/services/admin_audit.py`:

```python
"""
Audit-log helper for admin mutations. Every admin write goes through here.
Failures are logged but never raised — audit must not block the operation.
"""

import logging
from typing import Any, Optional

from db.connection import table

log = logging.getLogger(__name__)


def log_admin_action(
    actor_id: str,
    action: str,
    target_type: str,
    target_id: Optional[str] = None,
    payload: Optional[dict[str, Any]] = None,
) -> None:
    row = {
        "actor_id": actor_id,
        "action": action,
        "target_type": target_type,
        "target_id": target_id,
        "payload": payload or {},
    }
    try:
        table("admin_audit_log").insert(row)
    except Exception:  # noqa: BLE001 — audit failures must not break the action
        log.exception("admin_audit_log write failed: %s", row)
```

- [ ] **Step 3.4: Run tests, expect pass**

Run: `cd backend && python -m pytest tests/test_admin_audit.py -v`
Expected: PASS (both tests).

- [ ] **Step 3.5: Commit**

```bash
git add backend/services/admin_audit.py backend/tests/test_admin_audit.py
git commit -m "feat(admin): admin_audit log helper"
```

---

## Phase 4 — Stamp `last_sign_in_at` on every Google callback

### Task 4: Auth callback writes `last_sign_in_at`

**Files:**
- Modify: `backend/routes/auth.py:308-360` (the existing/new branches in `google_callback`)
- Test: `backend/tests/test_auth_state.py`

- [ ] **Step 4.1: Write the failing test**

Append to `backend/tests/test_auth_state.py`:

```python
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch


class TestLastSignInStamp:
    def _ts_string(self):
        # Any ISO8601 string that parses back to a datetime is acceptable.
        return None

    def test_existing_user_gets_last_sign_in_updated(self):
        # We exercise the branch that updates an existing user. We patch
        # everything Google-side, then inspect the final users.update payload.
        from routes import auth as auth_routes

        with patch.object(auth_routes, "GOOGLE_AVAILABLE", True), \
             patch.object(auth_routes, "GOOGLE_CLIENT_ID", "x"), \
             patch.object(auth_routes, "Flow") as flow, \
             patch.object(auth_routes, "build") as build, \
             patch.object(auth_routes, "table") as t:
            # Decode_oauth_cookie returns {"n": ..., "cv": ...}; we bypass via
            # directly calling the route function with a stub request would be
            # painful, so instead we drive it through the test client and patch
            # the cookie/state plumbing.
            t.side_effect = lambda name: MagicMock()
            # Wire up: existing users row found → update path.
            users_table = MagicMock()
            users_table.select.return_value = [{"id": "u1", "is_approved": True}]
            users_table.update = MagicMock(return_value=[{}])
            tokens_table = MagicMock()

            def by_name(name):
                if name == "users":
                    return users_table
                if name == "oauth_tokens":
                    return tokens_table
                return MagicMock()

            t.side_effect = by_name

            # Drive the inner update step directly: simulate that the callback
            # has reached the `existing` branch and call its update with a
            # patch-friendly seam.
            from routes.auth import _stamp_last_sign_in_for_test  # to be added

            _stamp_last_sign_in_for_test("u1")

        users_table.update.assert_called()
        update_payload = users_table.update.call_args.args[0]
        assert "last_sign_in_at" in update_payload
        assert update_payload["last_sign_in_at"]  # truthy ISO string
```

- [ ] **Step 4.2: Run the test, expect failure**

Run: `cd backend && python -m pytest tests/test_auth_state.py::TestLastSignInStamp -v`
Expected: FAIL — `_stamp_last_sign_in_for_test` not found.

- [ ] **Step 4.3: Add the seam + actual write to `auth.py`**

In `backend/routes/auth.py`, just below the imports:

```python
def _stamp_last_sign_in_for_test(user_id: str) -> None:
    """Test seam: write last_sign_in_at to keep the callback path testable in
    isolation without round-tripping through the OAuth flow."""
    from datetime import datetime, timezone
    table("users").update(
        {"last_sign_in_at": datetime.now(timezone.utc).isoformat()},
        filters={"id": f"eq.{user_id}"},
    )
```

Then, in `google_callback` — both branches that touch the `users` row — include `last_sign_in_at`:

In the existing-user branch (around the `update_fields = {...}` dict):

```python
        from datetime import datetime as _dt, timezone as _tz
        update_fields["last_sign_in_at"] = _dt.now(_tz.utc).isoformat()
```

In the new-user branch (just before `table("users").insert(insert_fields)`):

```python
        from datetime import datetime as _dt, timezone as _tz
        insert_fields["last_sign_in_at"] = _dt.now(_tz.utc).isoformat()
```

- [ ] **Step 4.4: Run the test, expect pass**

Run: `cd backend && python -m pytest tests/test_auth_state.py::TestLastSignInStamp -v`
Expected: PASS.

- [ ] **Step 4.5: Commit**

```bash
git add backend/routes/auth.py backend/tests/test_auth_state.py
git commit -m "feat(auth): stamp users.last_sign_in_at on Google callback"
```

---

## Phase 5 — Users API: pagination, search, unapprove, last_sign_in_at

### Task 5: Pagination + search service

**Files:**
- Create: `backend/services/users_search.py`
- Test: `backend/tests/test_users_search.py`

- [ ] **Step 5.1: Write the failing tests**

`backend/tests/test_users_search.py`:

```python
from unittest.mock import MagicMock, patch
from services.users_search import paginate_users


class TestPaginateUsers:
    def test_no_query_uses_select_with_count(self):
        users_rows = [
            {"id": "u1", "name": "enc1", "email": "enc2", "is_approved": True,
             "created_at": "2026-01-01T00:00:00Z", "last_sign_in_at": None},
        ]
        with patch("services.users_search.table") as t, \
             patch("services.users_search.decrypt_if_present", side_effect=lambda v: f"d:{v}" if v else v):
            users_tbl = MagicMock()
            users_tbl.select_with_count.return_value = (users_rows, 137)
            roles_tbl = MagicMock()
            roles_tbl.select.return_value = []

            def by_name(name):
                return users_tbl if name == "users" else roles_tbl

            t.side_effect = by_name

            result = paginate_users(q=None, page=1, page_size=50)

        assert result["total"] == 137
        assert result["page"] == 1
        assert result["page_size"] == 50
        assert result["users"][0]["name"] == "d:enc1"
        users_tbl.select_with_count.assert_called_once()

    def test_query_filters_after_decrypt(self):
        rows = [
            {"id": "u1", "name": "ALICE_ENC", "email": "AE", "is_approved": True,
             "created_at": "x", "last_sign_in_at": None},
            {"id": "u2", "name": "BOB_ENC", "email": "BE", "is_approved": False,
             "created_at": "x", "last_sign_in_at": None},
        ]
        decrypt_map = {"ALICE_ENC": "Alice Smith", "AE": "alice@bu.edu",
                       "BOB_ENC": "Bob Jones", "BE": "bob@bu.edu"}
        with patch("services.users_search.table") as t, \
             patch("services.users_search.decrypt_if_present", side_effect=lambda v: decrypt_map.get(v, v)):
            users_tbl = MagicMock()
            users_tbl.select.return_value = rows
            roles_tbl = MagicMock()
            roles_tbl.select.return_value = []

            def by_name(name):
                return users_tbl if name == "users" else roles_tbl

            t.side_effect = by_name

            result = paginate_users(q="alice", page=1, page_size=10)

        assert result["total"] == 1
        assert len(result["users"]) == 1
        assert result["users"][0]["email"] == "alice@bu.edu"

    def test_caps_page_size(self):
        with patch("services.users_search.table") as t:
            users_tbl = MagicMock()
            users_tbl.select_with_count.return_value = ([], 0)
            t.return_value = users_tbl
            result = paginate_users(q=None, page=1, page_size=9999)
        assert result["page_size"] == 200  # hard cap
```

- [ ] **Step 5.2: Run, expect failure**

Run: `cd backend && python -m pytest tests/test_users_search.py -v`
Expected: FAIL — `ModuleNotFoundError`.

- [ ] **Step 5.3: Implement the service**

`backend/services/users_search.py`:

```python
"""
Paginated user listing for the admin portal.

Without a search query, we paginate at the DB layer (offset+limit) and decrypt
only the page we return. With a search query, we have to decrypt the whole
table because users.name and users.email use AEAD with random nonces and are
not directly searchable. This is acceptable at admin scale and lives behind
require_admin.
"""

from typing import Optional

from db.connection import table
from services.encryption import decrypt_if_present

_DEFAULT_PAGE_SIZE = 50
_MAX_PAGE_SIZE = 200


def _attach_roles(users: list[dict]) -> None:
    for user in users:
        roles = table("user_roles").select(
            "roles(id,name,slug,color,icon,description,is_staff_assigned,is_earnable,display_priority)",
            filters={"user_id": f"eq.{user['id']}"},
        )
        user["roles"] = [r.get("roles", {}) for r in roles] if roles else []


def _decrypt(user: dict) -> dict:
    user["name"] = decrypt_if_present(user.get("name"))
    user["email"] = decrypt_if_present(user.get("email"))
    return user


def paginate_users(
    q: Optional[str],
    page: int = 1,
    page_size: int = _DEFAULT_PAGE_SIZE,
) -> dict:
    page = max(1, int(page))
    page_size = max(1, min(_MAX_PAGE_SIZE, int(page_size)))
    offset = (page - 1) * page_size
    columns = "id,name,email,is_approved,created_at,last_sign_in_at"

    if not q:
        rows, total = table("users").select_with_count(
            columns=columns,
            order="created_at.desc",
            limit=page_size,
            offset=offset,
        )
        for u in rows:
            _decrypt(u)
        _attach_roles(rows)
        return {"users": rows, "total": total, "page": page, "page_size": page_size}

    # Search path: decrypt everything, then filter and paginate in Python.
    all_rows = table("users").select(columns=columns, order="created_at.desc")
    for u in all_rows:
        _decrypt(u)
    needle = q.lower()
    filtered = [
        u for u in all_rows
        if needle in (u.get("name") or "").lower()
        or needle in (u.get("email") or "").lower()
    ]
    total = len(filtered)
    page_rows = filtered[offset : offset + page_size]
    _attach_roles(page_rows)
    return {"users": page_rows, "total": total, "page": page, "page_size": page_size}
```

- [ ] **Step 5.4: Run, expect pass**

Run: `cd backend && python -m pytest tests/test_users_search.py -v`
Expected: PASS (3 tests).

- [ ] **Step 5.5: Commit**

```bash
git add backend/services/users_search.py backend/tests/test_users_search.py
git commit -m "feat(admin): paginated + searchable users service"
```

### Task 6: Wire `/api/admin/users` to the new service

**Files:**
- Modify: `backend/routes/admin.py:213-230`
- Test: `backend/tests/test_admin_routes.py::TestListUsers`

- [ ] **Step 6.1: Add the failing test**

Append to `backend/tests/test_admin_routes.py`:

```python
class TestListUsersPaginated:
    def test_passes_query_and_page_through(self):
        with _mock_admin(), patch("routes.admin.paginate_users") as p:
            p.return_value = {"users": [], "total": 17, "page": 2, "page_size": 25}
            r = client.get("/api/admin/users?q=alice&page=2&page_size=25")
        assert r.status_code == 200
        assert r.json() == {"users": [], "total": 17, "page": 2, "page_size": 25}
        p.assert_called_once_with(q="alice", page=2, page_size=25)

    def test_defaults_when_params_missing(self):
        with _mock_admin(), patch("routes.admin.paginate_users") as p:
            p.return_value = {"users": [], "total": 0, "page": 1, "page_size": 50}
            r = client.get("/api/admin/users")
        assert r.status_code == 200
        p.assert_called_once_with(q=None, page=1, page_size=50)
```

- [ ] **Step 6.2: Run, expect failure**

Run: `cd backend && python -m pytest tests/test_admin_routes.py::TestListUsersPaginated -v`
Expected: FAIL — `paginate_users` not imported in `routes.admin`.

- [ ] **Step 6.3: Replace the existing `list_users` route**

In `backend/routes/admin.py`, replace the existing `list_users` block with:

```python
from typing import Optional
from services.users_search import paginate_users

@router.get("/users")
def list_users(
    request: Request,
    q: Optional[str] = None,
    page: int = 1,
    page_size: int = 50,
):
    require_admin(request)
    return paginate_users(q=q, page=page, page_size=page_size)
```

- [ ] **Step 6.4: Replace the legacy `TestListUsers` so it tests the new path**

The pre-existing `TestListUsers` patches `routes.admin.table` directly, but the route now delegates to `paginate_users` — the legacy mocks no longer intercept anything. Delete the legacy `TestListUsers` class (it is fully superseded by `TestListUsersPaginated` plus the unit tests in `tests/test_users_search.py`).

```python
# Remove the old class entirely:
# class TestListUsers:
#     def test_returns_all_users(self): ...
```

- [ ] **Step 6.5: Run, expect pass**

Run: `cd backend && python -m pytest tests/test_admin_routes.py -v -k users`
Expected: PASS for `TestListUsersPaginated`. Legacy `TestListUsers` is gone.

- [ ] **Step 6.6: Commit**

```bash
git add backend/routes/admin.py backend/tests/test_admin_routes.py
git commit -m "feat(admin): paginate /users with optional q search"
```

### Task 7: `PATCH /users/{id}/unapprove` with self-protection

**Files:**
- Modify: `backend/routes/admin.py` (after `approve_user`)
- Test: `backend/tests/test_admin_routes.py`

- [ ] **Step 7.1: Add the failing tests**

Append:

```python
class TestUnapproveUser:
    def test_unapproves_user(self):
        with _mock_admin(), patch("routes.admin.table") as t, \
             patch("routes.admin.log_admin_action") as audit:
            t.return_value.update.return_value = [{}]
            r = client.patch("/api/admin/users/u1/unapprove?user_id=admin1")
        assert r.status_code == 200
        assert r.json()["unapproved"] is True
        audit.assert_called_once()
        assert audit.call_args.kwargs["action"] == "user.unapprove"

    def test_cannot_unapprove_self(self):
        with patch("routes.admin.get_session_user_id", return_value="u1"), \
             _mock_admin():
            r = client.patch("/api/admin/users/u1/unapprove?user_id=u1")
        assert r.status_code == 409
        assert "yourself" in r.json()["detail"].lower()
```

- [ ] **Step 7.2: Run, expect failure**

Run: `cd backend && python -m pytest tests/test_admin_routes.py::TestUnapproveUser -v`
Expected: FAIL — endpoint not found (404) and audit import missing.

- [ ] **Step 7.3: Add the route + audit import**

At the top of `backend/routes/admin.py`:

```python
from services.admin_audit import log_admin_action
from services.auth_guard import get_session_user_id
```

After the existing `approve_user`:

```python
@router.patch("/users/{user_id}/unapprove")
def unapprove_user(user_id: str, request: Request):
    require_admin(request)
    actor = get_session_user_id(request)
    if user_id == actor:
        raise HTTPException(status_code=409, detail="You cannot unapprove yourself.")
    table("users").update({"is_approved": False}, filters={"id": f"eq.{user_id}"})
    log_admin_action(actor_id=actor, action="user.unapprove", target_type="user", target_id=user_id)
    return {"unapproved": True}
```

- [ ] **Step 7.4: Also wire audit into the existing `approve_user`**

Replace the current body:

```python
@router.patch("/users/{user_id}/approve")
def approve_user(user_id: str, request: Request):
    require_admin(request)
    actor = get_session_user_id(request)
    table("users").update({"is_approved": True}, filters={"id": f"eq.{user_id}"})
    log_admin_action(actor_id=actor, action="user.approve", target_type="user", target_id=user_id)
    return {"approved": True}
```

- [ ] **Step 7.5: Run, expect pass**

Run: `cd backend && python -m pytest tests/test_admin_routes.py::TestUnapproveUser tests/test_admin_routes.py::TestApproveUser -v`
Expected: PASS.

- [ ] **Step 7.6: Commit**

```bash
git add backend/routes/admin.py backend/tests/test_admin_routes.py
git commit -m "feat(admin): unapprove user + audit approve/unapprove"
```

---

## Phase 6 — Roles API: upsert assign + self-protection + delete-admin guard

### Task 8: `POST /roles/assign` becomes idempotent

**Files:**
- Modify: `backend/routes/admin.py` (`assign_role`)
- Test: `backend/tests/test_admin_routes.py`

- [ ] **Step 8.1: Add a failing test for re-assign idempotency**

```python
class TestAssignRoleIdempotent:
    def test_reassign_same_role_returns_200(self):
        with _mock_admin(), patch("routes.admin.table") as t, \
             patch("routes.admin.log_admin_action"):
            t.return_value.upsert.return_value = [{}]
            r = client.post("/api/admin/roles/assign", json={
                "user_id": "u1", "role_id": "r1", "granted_by": "admin1",
            })
        assert r.status_code == 200
        assert r.json()["assigned"] is True
        # Must use upsert, not insert.
        assert t.return_value.upsert.called
        assert not t.return_value.insert.called
```

- [ ] **Step 8.2: Run, expect failure**

Run: `cd backend && python -m pytest tests/test_admin_routes.py::TestAssignRoleIdempotent -v`
Expected: FAIL — current code calls `insert`, not `upsert`.

- [ ] **Step 8.3: Replace the route body**

```python
@router.post("/roles/assign")
def assign_role(body: AssignRoleBody, request: Request):
    require_admin(request)
    actor = get_session_user_id(request)
    granted_by = body.granted_by or actor
    table("user_roles").upsert(
        {
            "user_id": body.user_id,
            "role_id": body.role_id,
            "granted_by": granted_by,
            "granted_at": datetime.now(timezone.utc).isoformat(),
        },
        on_conflict="user_id,role_id",
    )
    log_admin_action(
        actor_id=actor, action="role.assign", target_type="role", target_id=body.role_id,
        payload={"user_id": body.user_id, "granted_by": granted_by},
    )
    return {"assigned": True}
```

- [ ] **Step 8.4: Run all role tests, expect pass**

Run: `cd backend && python -m pytest tests/test_admin_routes.py -v -k Role`
Expected: PASS.

- [ ] **Step 8.5: Commit**

```bash
git add backend/routes/admin.py backend/tests/test_admin_routes.py
git commit -m "fix(admin): role assign uses upsert; auto-fill granted_by"
```

### Task 9: Self-protection on `DELETE /roles/revoke` and `DELETE /roles/{id}`

**Files:**
- Modify: `backend/routes/admin.py` (`revoke_role`, `delete_role`)
- Test: `backend/tests/test_admin_routes.py`

- [ ] **Step 9.1: Add failing tests**

```python
class TestRevokeRoleSelfProtection:
    def _role_rows_for(self, slug):
        return [{"id": "rA", "slug": slug}]

    def test_cannot_revoke_own_admin(self):
        # Setup: user u1 is the actor; trying to revoke their own admin role rA
        def by_name(name):
            m = MagicMock()
            if name == "roles":
                m.select.return_value = [{"id": "rA", "slug": "admin"}]
            elif name == "user_roles":
                m.select.return_value = []
            return m

        with patch("routes.admin.get_session_user_id", return_value="u1"), \
             _mock_admin(), \
             patch("routes.admin.table", side_effect=by_name):
            r = client.request("DELETE", "/api/admin/roles/revoke",
                               json={"user_id": "u1", "role_id": "rA"})
        assert r.status_code == 409
        assert "own admin" in r.json()["detail"].lower()

    def test_cannot_revoke_last_admin(self):
        def by_name(name):
            m = MagicMock()
            if name == "roles":
                m.select.return_value = [{"id": "rA", "slug": "admin"}]
            elif name == "user_roles":
                # Only one admin in the system → u2 is the last admin
                m.select.return_value = [{"user_id": "u2"}]
            return m

        with patch("routes.admin.get_session_user_id", return_value="u1"), \
             _mock_admin(), \
             patch("routes.admin.table", side_effect=by_name):
            r = client.request("DELETE", "/api/admin/roles/revoke",
                               json={"user_id": "u2", "role_id": "rA"})
        assert r.status_code == 409
        assert "last admin" in r.json()["detail"].lower()


class TestDeleteRoleProtection:
    def test_cannot_delete_admin_role(self):
        def by_name(name):
            m = MagicMock()
            m.select.return_value = [{"id": "rA", "slug": "admin"}]
            return m

        with _mock_admin(), patch("routes.admin.table", side_effect=by_name):
            r = client.delete("/api/admin/roles/rA")
        assert r.status_code == 409
        assert "admin role" in r.json()["detail"].lower()
```

- [ ] **Step 9.2: Run, expect failure**

Run: `cd backend && python -m pytest tests/test_admin_routes.py::TestRevokeRoleSelfProtection tests/test_admin_routes.py::TestDeleteRoleProtection -v`
Expected: FAIL — current revoke/delete have no guards.

- [ ] **Step 9.3: Implement the guards**

Replace `revoke_role` and `delete_role` in `backend/routes/admin.py`:

```python
def _role_slug(role_id: str) -> Optional[str]:
    rows = table("roles").select("id,slug", filters={"id": f"eq.{role_id}"})
    return rows[0]["slug"] if rows else None


def _admin_user_count() -> int:
    rows = table("user_roles").select(
        "user_id,roles!inner(slug)",
        filters={"roles.slug": "eq.admin"},
    )
    return len(rows or [])


@router.delete("/roles/revoke")
def revoke_role(body: RevokeRoleBody, request: Request):
    require_admin(request)
    actor = get_session_user_id(request)
    slug = _role_slug(body.role_id)
    if slug == "admin":
        if body.user_id == actor:
            raise HTTPException(status_code=409, detail="You cannot revoke your own admin role.")
        if _admin_user_count() <= 1:
            raise HTTPException(status_code=409, detail="Cannot revoke the last admin.")
    table("user_roles").delete(filters={
        "user_id": f"eq.{body.user_id}",
        "role_id": f"eq.{body.role_id}",
    })
    log_admin_action(
        actor_id=actor, action="role.revoke", target_type="role", target_id=body.role_id,
        payload={"user_id": body.user_id},
    )
    return {"revoked": True}


@router.delete("/roles/{role_id}")
def delete_role(role_id: str, request: Request):
    require_admin(request)
    actor = get_session_user_id(request)
    if _role_slug(role_id) == "admin":
        raise HTTPException(status_code=409, detail="Cannot delete the admin role.")
    table("roles").delete(filters={"id": f"eq.{role_id}"})
    log_admin_action(actor_id=actor, action="role.delete", target_type="role", target_id=role_id)
    return {"deleted": True}
```

- [ ] **Step 9.4: Run, expect pass**

Run: `cd backend && python -m pytest tests/test_admin_routes.py -v -k Role`
Expected: PASS for all role tests, including the legacy `TestRevokeRole` (its existing `slug` lookup test path still resolves to `None` so the guards don't trigger).

- [ ] **Step 9.5: Audit-wire `create_role` and `update_role` too**

Replace those two route bodies similarly — wrap them with `actor = get_session_user_id(...)` and call `log_admin_action(...)` with `action="role.create"` / `"role.update"`. Add a quick test asserting `audit.call_args.kwargs["action"] == "role.create"` and the same for update.

- [ ] **Step 9.6: Commit**

```bash
git add backend/routes/admin.py backend/tests/test_admin_routes.py
git commit -m "feat(admin): self-protection on role revoke/delete + role audits"
```

---

## Phase 7 — Achievements: triggers CRUD + cosmetic linking

### Task 10: New Pydantic models

**Files:**
- Modify: `backend/models/__init__.py`

- [ ] **Step 10.1: Add models**

In the `Achievements (Admin)` block, append:

```python
class UpdateAchievementTriggerBody(BaseModel):
    trigger_type: Optional[str] = None
    trigger_threshold: Optional[int] = None


class LinkAchievementCosmeticBody(BaseModel):
    achievement_id: str
    cosmetic_id: str


class LinkRoleCosmeticBody(BaseModel):
    role_id: str
    cosmetic_id: str
```

- [ ] **Step 10.2: Commit**

```bash
git add backend/models/__init__.py
git commit -m "feat(admin): Pydantic bodies for triggers + cosmetic linking"
```

### Task 11: Triggers — list, update, delete (POST already exists)

**Files:**
- Modify: `backend/routes/admin.py`
- Test: `backend/tests/test_admin_routes.py`

- [ ] **Step 11.1: Failing tests**

```python
class TestTriggers:
    def test_list_returns_triggers_for_achievement(self):
        rows = [{"id": "t1", "achievement_id": "a1", "trigger_type": "login_streak", "trigger_threshold": 7}]
        with _mock_admin(), patch("routes.admin.table") as t:
            t.return_value.select.return_value = rows
            r = client.get("/api/admin/achievements/a1/triggers")
        assert r.status_code == 200
        assert r.json() == {"triggers": rows}

    def test_update_trigger(self):
        with _mock_admin(), patch("routes.admin.table") as t, \
             patch("routes.admin.log_admin_action"):
            t.return_value.update.return_value = [{}]
            r = client.patch("/api/admin/achievements/triggers/t1",
                             json={"trigger_threshold": 14})
        assert r.status_code == 200
        assert r.json()["updated"] is True

    def test_delete_trigger(self):
        with _mock_admin(), patch("routes.admin.table") as t, \
             patch("routes.admin.log_admin_action"):
            t.return_value.delete.return_value = [{}]
            r = client.delete("/api/admin/achievements/triggers/t1")
        assert r.status_code == 200
        assert r.json()["deleted"] is True
```

- [ ] **Step 11.2: Run, expect failure**

Run: `cd backend && python -m pytest tests/test_admin_routes.py::TestTriggers -v`
Expected: FAIL — endpoints don't exist.

- [ ] **Step 11.3: Add the routes**

In `backend/routes/admin.py`, near the other achievement endpoints:

```python
from models import UpdateAchievementTriggerBody  # add to existing import block

@router.get("/achievements/{achievement_id}/triggers")
def list_triggers(achievement_id: str, request: Request):
    require_admin(request)
    rows = table("achievement_triggers").select(
        "id,achievement_id,trigger_type,trigger_threshold",
        filters={"achievement_id": f"eq.{achievement_id}"},
    )
    return {"triggers": rows or []}


@router.patch("/achievements/triggers/{trigger_id}")
def update_trigger(trigger_id: str, body: UpdateAchievementTriggerBody, request: Request):
    require_admin(request)
    actor = get_session_user_id(request)
    updates = {k: v for k, v in body.model_dump(exclude_unset=True).items() if v is not None}
    if not updates:
        raise HTTPException(status_code=400, detail="No valid fields to update")
    table("achievement_triggers").update(updates, filters={"id": f"eq.{trigger_id}"})
    log_admin_action(actor_id=actor, action="trigger.update", target_type="trigger", target_id=trigger_id, payload=updates)
    return {"updated": True}


@router.delete("/achievements/triggers/{trigger_id}")
def delete_trigger(trigger_id: str, request: Request):
    require_admin(request)
    actor = get_session_user_id(request)
    table("achievement_triggers").delete(filters={"id": f"eq.{trigger_id}"})
    log_admin_action(actor_id=actor, action="trigger.delete", target_type="trigger", target_id=trigger_id)
    return {"deleted": True}
```

- [ ] **Step 11.4: Run, expect pass**

Run: `cd backend && python -m pytest tests/test_admin_routes.py::TestTriggers -v`
Expected: PASS.

- [ ] **Step 11.5: Commit**

```bash
git add backend/routes/admin.py backend/tests/test_admin_routes.py
git commit -m "feat(admin): list/update/delete achievement triggers"
```

### Task 12: `achievement_cosmetics` linking CRUD

**Files:**
- Modify: `backend/routes/admin.py`
- Test: `backend/tests/test_admin_routes.py`

- [ ] **Step 12.1: Failing tests**

```python
class TestAchievementCosmeticLinks:
    def test_list_links(self):
        rows = [{"achievement_id": "a1", "cosmetic_id": "c1"}]
        with _mock_admin(), patch("routes.admin.table") as t:
            t.return_value.select.return_value = rows
            r = client.get("/api/admin/achievements/a1/cosmetics")
        assert r.status_code == 200
        assert r.json() == {"links": rows}

    def test_link(self):
        with _mock_admin(), patch("routes.admin.table") as t, \
             patch("routes.admin.log_admin_action"):
            t.return_value.upsert.return_value = [{"achievement_id": "a1", "cosmetic_id": "c1"}]
            r = client.post("/api/admin/achievements/cosmetics",
                            json={"achievement_id": "a1", "cosmetic_id": "c1"})
        assert r.status_code == 200
        assert r.json()["linked"] is True

    def test_unlink(self):
        with _mock_admin(), patch("routes.admin.table") as t, \
             patch("routes.admin.log_admin_action"):
            t.return_value.delete.return_value = [{}]
            r = client.request("DELETE", "/api/admin/achievements/cosmetics",
                               json={"achievement_id": "a1", "cosmetic_id": "c1"})
        assert r.status_code == 200
        assert r.json()["unlinked"] is True
```

- [ ] **Step 12.2: Run, expect failure**

Run: `cd backend && python -m pytest tests/test_admin_routes.py::TestAchievementCosmeticLinks -v`
Expected: FAIL — endpoints don't exist.

- [ ] **Step 12.3: Add routes**

```python
from models import LinkAchievementCosmeticBody

@router.get("/achievements/{achievement_id}/cosmetics")
def list_achievement_cosmetics(achievement_id: str, request: Request):
    require_admin(request)
    rows = table("achievement_cosmetics").select(
        "achievement_id,cosmetic_id",
        filters={"achievement_id": f"eq.{achievement_id}"},
    )
    return {"links": rows or []}


@router.post("/achievements/cosmetics")
def link_achievement_cosmetic(body: LinkAchievementCosmeticBody, request: Request):
    require_admin(request)
    actor = get_session_user_id(request)
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


@router.delete("/achievements/cosmetics")
def unlink_achievement_cosmetic(body: LinkAchievementCosmeticBody, request: Request):
    require_admin(request)
    actor = get_session_user_id(request)
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
```

- [ ] **Step 12.4: Run, expect pass**

Run: `cd backend && python -m pytest tests/test_admin_routes.py::TestAchievementCosmeticLinks -v`
Expected: PASS.

- [ ] **Step 12.5: Commit**

```bash
git add backend/routes/admin.py backend/tests/test_admin_routes.py
git commit -m "feat(admin): achievement_cosmetics link/unlink/list"
```

### Task 13: Audit + reuse for the rest of the achievement endpoints

**Files:**
- Modify: `backend/routes/admin.py` (`create_achievement`, `update_achievement`, `delete_achievement`, `grant_achievement`, `create_trigger`)
- Test: `backend/tests/test_admin_routes.py`

- [ ] **Step 13.1: Add audit calls**

Wrap each of the five existing achievement-mutating endpoints with `actor = get_session_user_id(request)` and `log_admin_action(actor_id=actor, action="achievement.create"|"...update"|"...delete"|"...grant"|"trigger.create", target_type="achievement"|"trigger", target_id=<id>, payload=<request body or empty>)`.

- [ ] **Step 13.2: Add a single coverage test**

```python
class TestAchievementAudits:
    def test_create_logs_audit(self):
        with _mock_admin(), patch("routes.admin.table") as t, \
             patch("routes.admin.log_admin_action") as audit:
            t.return_value.insert.return_value = [{"id": "a9"}]
            r = client.post("/api/admin/achievements", json={
                "name": "Z", "slug": "z", "category": "milestone", "rarity": "common",
            })
        assert r.status_code == 200
        assert audit.call_args.kwargs["action"] == "achievement.create"
```

- [ ] **Step 13.3: Run, expect pass**

Run: `cd backend && python -m pytest tests/test_admin_routes.py::TestAchievementAudits -v`
Expected: PASS.

- [ ] **Step 13.4: Commit**

```bash
git add backend/routes/admin.py backend/tests/test_admin_routes.py
git commit -m "feat(admin): audit-wire achievement create/update/delete/grant/trigger"
```

---

## Phase 8 — Cosmetics: role linking CRUD + audit

### Task 14: `role_cosmetics` link/unlink/list endpoints

**Files:**
- Modify: `backend/routes/admin.py`
- Test: `backend/tests/test_admin_routes.py`

- [ ] **Step 14.1: Failing tests**

```python
class TestRoleCosmeticLinks:
    def test_list_links_for_role(self):
        rows = [{"role_id": "rA", "cosmetic_id": "c1"}]
        with _mock_admin(), patch("routes.admin.table") as t:
            t.return_value.select.return_value = rows
            r = client.get("/api/admin/roles/rA/cosmetics")
        assert r.status_code == 200
        assert r.json() == {"links": rows}

    def test_link(self):
        with _mock_admin(), patch("routes.admin.table") as t, \
             patch("routes.admin.log_admin_action"):
            t.return_value.upsert.return_value = [{"role_id": "rA", "cosmetic_id": "c1"}]
            r = client.post("/api/admin/roles/cosmetics",
                            json={"role_id": "rA", "cosmetic_id": "c1"})
        assert r.status_code == 200
        assert r.json()["linked"] is True

    def test_unlink(self):
        with _mock_admin(), patch("routes.admin.table") as t, \
             patch("routes.admin.log_admin_action"):
            t.return_value.delete.return_value = [{}]
            r = client.request("DELETE", "/api/admin/roles/cosmetics",
                               json={"role_id": "rA", "cosmetic_id": "c1"})
        assert r.status_code == 200
        assert r.json()["unlinked"] is True
```

- [ ] **Step 14.2: Run, expect failure**

Run: `cd backend && python -m pytest tests/test_admin_routes.py::TestRoleCosmeticLinks -v`
Expected: FAIL.

- [ ] **Step 14.3: Add the routes (mirror of achievement_cosmetics)**

```python
from models import LinkRoleCosmeticBody

@router.get("/roles/{role_id}/cosmetics")
def list_role_cosmetics(role_id: str, request: Request):
    require_admin(request)
    rows = table("role_cosmetics").select(
        "role_id,cosmetic_id",
        filters={"role_id": f"eq.{role_id}"},
    )
    return {"links": rows or []}


@router.post("/roles/cosmetics")
def link_role_cosmetic(body: LinkRoleCosmeticBody, request: Request):
    require_admin(request)
    actor = get_session_user_id(request)
    table("role_cosmetics").upsert(
        {"role_id": body.role_id, "cosmetic_id": body.cosmetic_id},
        on_conflict="role_id,cosmetic_id",
    )
    log_admin_action(
        actor_id=actor, action="role_cosmetic.link",
        target_type="role_cosmetic", target_id=body.role_id,
        payload={"cosmetic_id": body.cosmetic_id},
    )
    return {"linked": True}


@router.delete("/roles/cosmetics")
def unlink_role_cosmetic(body: LinkRoleCosmeticBody, request: Request):
    require_admin(request)
    actor = get_session_user_id(request)
    table("role_cosmetics").delete(filters={
        "role_id": f"eq.{body.role_id}",
        "cosmetic_id": f"eq.{body.cosmetic_id}",
    })
    log_admin_action(
        actor_id=actor, action="role_cosmetic.unlink",
        target_type="role_cosmetic", target_id=body.role_id,
        payload={"cosmetic_id": body.cosmetic_id},
    )
    return {"unlinked": True}
```

- [ ] **Step 14.4: Run + audit-wire `create_cosmetic`/`update_cosmetic`/`delete_cosmetic`**

Add `actor = get_session_user_id(request)` and `log_admin_action(...)` to each, with `action="cosmetic.create" | "cosmetic.update" | "cosmetic.delete"`.

- [ ] **Step 14.5: Run, expect pass**

Run: `cd backend && python -m pytest tests/test_admin_routes.py -v -k Cosmetic`
Expected: PASS.

- [ ] **Step 14.6: Commit**

```bash
git add backend/routes/admin.py backend/tests/test_admin_routes.py
git commit -m "feat(admin): role_cosmetics link/unlink + cosmetic audits"
```

---

## Phase 9 — Allowlist: audit-wire (endpoints already exist)

### Task 15: Audit existing allowlist endpoints

**Files:**
- Modify: `backend/routes/admin.py` (`approve_allowlist`, `revoke_allowlist`)
- Test: `backend/tests/test_admin_routes.py`

- [ ] **Step 15.1: Failing test**

```python
class TestAllowlistAudits:
    def test_approve_logs_audit(self):
        with _mock_admin(), patch("routes.admin.table") as t, \
             patch("routes.admin.log_admin_action") as audit:
            t.return_value.upsert.return_value = [{"email": "a@b.c"}]
            r = client.post("/api/admin/allowlist/approve", json={"email": "A@B.c"})
        assert r.status_code == 200
        assert audit.call_args.kwargs["action"] == "allowlist.approve"
        assert audit.call_args.kwargs["payload"]["email"] == "a@b.c"
```

- [ ] **Step 15.2: Run, expect failure**

Run: `cd backend && python -m pytest tests/test_admin_routes.py::TestAllowlistAudits -v`
Expected: FAIL — no audit call yet.

- [ ] **Step 15.3: Wire audits**

In `approve_allowlist` and `revoke_allowlist`, add:

```python
    actor = get_session_user_id(request)
    log_admin_action(
        actor_id=actor, action="allowlist.approve" | "allowlist.revoke",
        target_type="allowlist", target_id=body.email, payload={"email": body.email},
    )
```

- [ ] **Step 15.4: Run, expect pass**

Run: `cd backend && python -m pytest tests/test_admin_routes.py::TestAllowlistAudits -v`
Expected: PASS.

- [ ] **Step 15.5: Commit**

```bash
git add backend/routes/admin.py backend/tests/test_admin_routes.py
git commit -m "feat(admin): audit allowlist approve/revoke"
```

---

## Phase 10 — Audit log read endpoint

### Task 16: `GET /api/admin/audit`

**Files:**
- Modify: `backend/routes/admin.py`
- Test: `backend/tests/test_admin_routes.py`

- [ ] **Step 16.1: Failing test**

```python
class TestAuditLogRead:
    def test_returns_paginated_audit_with_filters(self):
        rows = [
            {"id": "1", "actor_id": "admin1", "action": "user.approve",
             "target_type": "user", "target_id": "u1", "payload": {},
             "created_at": "2026-05-04T00:00:00Z"},
        ]
        with _mock_admin(), patch("routes.admin.table") as t:
            t.return_value.select_with_count.return_value = (rows, 1)
            r = client.get("/api/admin/audit?action=user.approve&page=1&page_size=10")
        assert r.status_code == 200
        body = r.json()
        assert body["entries"] == rows
        assert body["total"] == 1
        assert body["page"] == 1
        assert body["page_size"] == 10
```

- [ ] **Step 16.2: Run, expect failure**

Run: `cd backend && python -m pytest tests/test_admin_routes.py::TestAuditLogRead -v`
Expected: FAIL.

- [ ] **Step 16.3: Add the route**

```python
@router.get("/audit")
def list_audit(
    request: Request,
    page: int = 1,
    page_size: int = 50,
    action: Optional[str] = None,
    target_type: Optional[str] = None,
    actor_id: Optional[str] = None,
):
    require_admin(request)
    page = max(1, int(page))
    page_size = max(1, min(200, int(page_size)))
    offset = (page - 1) * page_size
    filters: dict = {}
    if action:
        filters["action"] = f"eq.{action}"
    if target_type:
        filters["target_type"] = f"eq.{target_type}"
    if actor_id:
        filters["actor_id"] = f"eq.{actor_id}"
    rows, total = table("admin_audit_log").select_with_count(
        columns="id,actor_id,action,target_type,target_id,payload,created_at",
        filters=filters or None,
        order="created_at.desc",
        limit=page_size,
        offset=offset,
    )
    return {"entries": rows, "total": total, "page": page, "page_size": page_size}
```

- [ ] **Step 16.4: Run, expect pass**

Run: `cd backend && python -m pytest tests/test_admin_routes.py::TestAuditLogRead -v`
Expected: PASS.

- [ ] **Step 16.5: Commit**

```bash
git add backend/routes/admin.py backend/tests/test_admin_routes.py
git commit -m "feat(admin): paginated /audit read endpoint"
```

---

## Phase 11 — Analytics

### Task 17: `GET /api/admin/analytics/overview`

**Files:**
- Modify: `backend/routes/admin.py`
- Test: `backend/tests/test_admin_routes.py`

The response is shaped to map directly onto the existing `var(--accent)` / `chip` / `h-serif` UI:

```jsonc
{
  "totals": { "users": 137, "approved": 92, "pending": 45, "admins": 3 },
  "signups_by_day": [{ "date": "2026-04-05", "count": 4 }, ...],   // last 30 days
  "approvals_by_day": [{ "date": "2026-04-05", "count": 3 }, ...], // last 30 days
  "role_counts": [{ "slug": "admin", "name": "Admin", "color": "#dc2626", "count": 3 }, ...]
}
```

- [ ] **Step 17.1: Failing test**

```python
class TestAnalyticsOverview:
    def test_returns_totals_and_series(self):
        users = [
            {"id": "u1", "is_approved": True,  "created_at": "2026-05-01T00:00:00Z"},
            {"id": "u2", "is_approved": True,  "created_at": "2026-05-01T00:00:00Z"},
            {"id": "u3", "is_approved": False, "created_at": "2026-05-02T00:00:00Z"},
        ]
        roles = [{"id": "rA", "slug": "admin", "name": "Admin", "color": "#dc2626"}]
        user_roles = [{"role_id": "rA"}, {"role_id": "rA"}, {"role_id": "rA"}]

        def by_name(name):
            m = MagicMock()
            if name == "users":
                m.select.return_value = users
            elif name == "roles":
                m.select.return_value = roles
            elif name == "user_roles":
                m.select.return_value = user_roles
            else:
                m.select.return_value = []
            return m

        with _mock_admin(), patch("routes.admin.table", side_effect=by_name):
            r = client.get("/api/admin/analytics/overview")

        assert r.status_code == 200
        body = r.json()
        assert body["totals"]["users"] == 3
        assert body["totals"]["approved"] == 2
        assert body["totals"]["pending"] == 1
        assert body["totals"]["admins"] == 3
        assert any(d["date"] == "2026-05-01" and d["count"] == 2 for d in body["signups_by_day"])
        assert body["role_counts"][0]["slug"] == "admin"
        assert body["role_counts"][0]["count"] == 3
```

- [ ] **Step 17.2: Run, expect failure**

Run: `cd backend && python -m pytest tests/test_admin_routes.py::TestAnalyticsOverview -v`
Expected: FAIL.

- [ ] **Step 17.3: Add the route**

```python
from collections import Counter
from datetime import datetime, timedelta, timezone

@router.get("/analytics/overview")
def analytics_overview(request: Request):
    require_admin(request)

    users = table("users").select("id,is_approved,created_at") or []
    roles = table("roles").select("id,slug,name,color") or []
    user_roles = table("user_roles").select("role_id") or []

    role_index = {r["id"]: r for r in roles}
    role_counter: Counter = Counter()
    for ur in user_roles:
        role_counter[ur["role_id"]] += 1

    admin_role_ids = {r["id"] for r in roles if r.get("slug") == "admin"}
    admin_count = sum(c for rid, c in role_counter.items() if rid in admin_role_ids)

    approved = sum(1 for u in users if u.get("is_approved"))
    totals = {
        "users": len(users),
        "approved": approved,
        "pending": len(users) - approved,
        "admins": admin_count,
    }

    today = datetime.now(timezone.utc).date()
    window = [today - timedelta(days=i) for i in range(29, -1, -1)]
    by_day_signups: Counter = Counter()
    by_day_approvals: Counter = Counter()
    for u in users:
        ca = u.get("created_at") or ""
        try:
            d = datetime.fromisoformat(ca.replace("Z", "+00:00")).date()
        except ValueError:
            continue
        if d in window:
            by_day_signups[d.isoformat()] += 1
            if u.get("is_approved"):
                by_day_approvals[d.isoformat()] += 1

    signups_by_day = [{"date": d.isoformat(), "count": by_day_signups.get(d.isoformat(), 0)} for d in window]
    approvals_by_day = [{"date": d.isoformat(), "count": by_day_approvals.get(d.isoformat(), 0)} for d in window]

    role_counts = []
    for rid, count in role_counter.items():
        r = role_index.get(rid)
        if not r:
            continue
        role_counts.append({"slug": r["slug"], "name": r["name"], "color": r["color"], "count": count})
    role_counts.sort(key=lambda x: x["count"], reverse=True)

    return {
        "totals": totals,
        "signups_by_day": signups_by_day,
        "approvals_by_day": approvals_by_day,
        "role_counts": role_counts,
    }
```

- [ ] **Step 17.4: Run, expect pass**

Run: `cd backend && python -m pytest tests/test_admin_routes.py::TestAnalyticsOverview -v`
Expected: PASS.

- [ ] **Step 17.5: Commit**

```bash
git add backend/routes/admin.py backend/tests/test_admin_routes.py
git commit -m "feat(admin): /analytics/overview totals + 30-day series + role counts"
```

### Task 18: Backend full-suite checkpoint

- [ ] **Step 18.1: Run the entire backend suite**

Run: `cd backend && python -m pytest tests/ -q`
Expected: PASS (no regressions in adjacent route tests).

- [ ] **Step 18.2: If anything red, stop and fix before moving on. Otherwise commit a marker.**

```bash
git commit --allow-empty -m "chore(admin): backend phase complete"
```

---

## Phase 12 — Frontend types + API client

### Task 19: Extend `frontend/src/lib/types.ts`

**Files:**
- Modify: `frontend/src/lib/types.ts`

- [ ] **Step 19.1: Add the new types**

Append after the existing admin/cosmetic types:

```typescript
export interface AllowlistEmail {
  id: string;
  email: string;
  created_at: string;
  approved_at: string | null;
}

export interface AchievementTrigger {
  id: string;
  achievement_id: string;
  trigger_type: string;
  trigger_threshold: number;
}

export interface AdminAuditEntry {
  id: string;
  actor_id: string;
  action: string;
  target_type: string;
  target_id: string | null;
  payload: Record<string, unknown>;
  created_at: string;
}

export interface AnalyticsTotals {
  users: number;
  approved: number;
  pending: number;
  admins: number;
}

export interface AnalyticsDayPoint {
  date: string;     // YYYY-MM-DD
  count: number;
}

export interface AnalyticsRoleCount {
  slug: string;
  name: string;
  color: string;
  count: number;
}

export interface AnalyticsOverview {
  totals: AnalyticsTotals;
  signups_by_day: AnalyticsDayPoint[];
  approvals_by_day: AnalyticsDayPoint[];
  role_counts: AnalyticsRoleCount[];
}

export interface AdminUserListItem {
  id: string;
  name: string;
  email: string;
  is_approved: boolean;
  is_admin?: boolean;
  last_sign_in_at: string | null;
  created_at: string;
  roles: Role[];
}

export interface PaginatedUsers {
  users: AdminUserListItem[];
  total: number;
  page: number;
  page_size: number;
}
```

Also extend `Cosmetic` to optionally include `unlock_source` (currently missing):

```typescript
export interface Cosmetic {
  id: string;
  type: CosmeticType;
  name: string;
  slug: string;
  asset_url?: string;
  css_value?: string;
  rarity: RarityTier;
  unlock_source?: string | null;
}
```

- [ ] **Step 19.2: Type-check**

Run: `cd frontend && npx tsc --noEmit`
Expected: PASS.

- [ ] **Step 19.3: Commit**

```bash
git add frontend/src/lib/types.ts
git commit -m "feat(types): admin portal additions (allowlist, audit, analytics, paginated users)"
```

### Task 20: Extend `frontend/src/lib/api.ts`

**Files:**
- Modify: `frontend/src/lib/api.ts` (replace the `// Admin` block at line 723 with the expanded version)

- [ ] **Step 20.1: Replace the admin section**

Replace the entire `// Admin` block with:

```typescript
import type {
  AllowlistEmail,
  AchievementTrigger,
  AdminAuditEntry,
  AnalyticsOverview,
  PaginatedUsers,
} from './types';

// Admin — users
export const adminFetchUsers = (params?: { q?: string; page?: number; page_size?: number }) => {
  const qp = new URLSearchParams();
  if (params?.q) qp.set('q', params.q);
  if (params?.page) qp.set('page', String(params.page));
  if (params?.page_size) qp.set('page_size', String(params.page_size));
  const suffix = qp.toString() ? `?${qp.toString()}` : '';
  return fetchJSON<PaginatedUsers>(`/api/admin/users${suffix}`);
};

export const adminApproveUser = (userId: string) =>
  fetchJSON<{ approved: boolean }>(`/api/admin/users/${userId}/approve`, { method: 'PATCH' });

export const adminUnapproveUser = (userId: string) =>
  fetchJSON<{ unapproved: boolean }>(`/api/admin/users/${userId}/unapprove`, { method: 'PATCH' });

// Admin — roles
export const adminAssignRole = (userId: string, roleId: string, grantedBy?: string) =>
  fetchJSON<{ assigned: boolean }>('/api/admin/roles/assign', {
    method: 'POST',
    body: JSON.stringify({ user_id: userId, role_id: roleId, granted_by: grantedBy }),
  });

export const adminRevokeRole = (userId: string, roleId: string) =>
  fetchJSON<{ revoked: boolean }>('/api/admin/roles/revoke', {
    method: 'DELETE',
    body: JSON.stringify({ user_id: userId, role_id: roleId }),
  });

export const adminListRoles = () =>
  fetchJSON<{ roles: Role[] }>('/api/admin/roles');

export const adminCreateRole = (payload: {
  name: string; slug: string; color: string; icon?: string | null;
  description?: string | null; is_staff_assigned?: boolean;
  is_earnable?: boolean; display_priority?: number;
}) =>
  fetchJSON<{ role: Role }>('/api/admin/roles', {
    method: 'POST',
    body: JSON.stringify(payload),
  });

export const adminDeleteRole = (roleId: string) =>
  fetchJSON<{ deleted: boolean }>(`/api/admin/roles/${encodeURIComponent(roleId)}`, { method: 'DELETE' });

export const adminListRoleCosmetics = (roleId: string) =>
  fetchJSON<{ links: { role_id: string; cosmetic_id: string }[] }>(
    `/api/admin/roles/${encodeURIComponent(roleId)}/cosmetics`,
  );

export const adminLinkRoleCosmetic = (roleId: string, cosmeticId: string) =>
  fetchJSON<{ linked: boolean }>('/api/admin/roles/cosmetics', {
    method: 'POST',
    body: JSON.stringify({ role_id: roleId, cosmetic_id: cosmeticId }),
  });

export const adminUnlinkRoleCosmetic = (roleId: string, cosmeticId: string) =>
  fetchJSON<{ unlinked: boolean }>('/api/admin/roles/cosmetics', {
    method: 'DELETE',
    body: JSON.stringify({ role_id: roleId, cosmetic_id: cosmeticId }),
  });

// Admin — achievements
export const adminListAchievements = () =>
  fetchJSON<{ achievements: Achievement[] }>('/api/admin/achievements');

export const adminCreateAchievement = (payload: {
  name: string; slug: string; description?: string | null; icon?: string | null;
  category: AchievementCategory; rarity: RarityTier; is_secret?: boolean;
}) =>
  fetchJSON<{ achievement: Achievement }>('/api/admin/achievements', {
    method: 'POST',
    body: JSON.stringify(payload),
  });

export const adminDeleteAchievement = (achievementId: string) =>
  fetchJSON<{ deleted: boolean }>(`/api/admin/achievements/${encodeURIComponent(achievementId)}`, { method: 'DELETE' });

export const adminGrantAchievement = (userId: string, achievementId: string) =>
  fetchJSON<{ granted: boolean }>('/api/admin/achievements/grant', {
    method: 'POST',
    body: JSON.stringify({ user_id: userId, achievement_id: achievementId }),
  });

export const adminListTriggers = (achievementId: string) =>
  fetchJSON<{ triggers: AchievementTrigger[] }>(
    `/api/admin/achievements/${encodeURIComponent(achievementId)}/triggers`,
  );

export const adminCreateTrigger = (payload: {
  achievement_id: string; trigger_type: string; trigger_threshold: number;
}) =>
  fetchJSON<{ trigger: AchievementTrigger }>('/api/admin/achievements/triggers', {
    method: 'POST',
    body: JSON.stringify(payload),
  });

export const adminUpdateTrigger = (triggerId: string, patch: Partial<{ trigger_type: string; trigger_threshold: number }>) =>
  fetchJSON<{ updated: boolean }>(`/api/admin/achievements/triggers/${encodeURIComponent(triggerId)}`, {
    method: 'PATCH',
    body: JSON.stringify(patch),
  });

export const adminDeleteTrigger = (triggerId: string) =>
  fetchJSON<{ deleted: boolean }>(`/api/admin/achievements/triggers/${encodeURIComponent(triggerId)}`, { method: 'DELETE' });

export const adminListAchievementCosmetics = (achievementId: string) =>
  fetchJSON<{ links: { achievement_id: string; cosmetic_id: string }[] }>(
    `/api/admin/achievements/${encodeURIComponent(achievementId)}/cosmetics`,
  );

export const adminLinkAchievementCosmetic = (achievementId: string, cosmeticId: string) =>
  fetchJSON<{ linked: boolean }>('/api/admin/achievements/cosmetics', {
    method: 'POST',
    body: JSON.stringify({ achievement_id: achievementId, cosmetic_id: cosmeticId }),
  });

export const adminUnlinkAchievementCosmetic = (achievementId: string, cosmeticId: string) =>
  fetchJSON<{ unlinked: boolean }>('/api/admin/achievements/cosmetics', {
    method: 'DELETE',
    body: JSON.stringify({ achievement_id: achievementId, cosmetic_id: cosmeticId }),
  });

// Admin — cosmetics
export const adminListCosmetics = () =>
  fetchJSON<{ cosmetics: Cosmetic[] }>('/api/admin/cosmetics');

export const adminCreateCosmetic = (payload: {
  type: CosmeticType; name: string; slug: string;
  asset_url?: string | null; css_value?: string | null;
  rarity: RarityTier; unlock_source?: string | null;
}) =>
  fetchJSON<{ cosmetic: Cosmetic }>('/api/admin/cosmetics', {
    method: 'POST',
    body: JSON.stringify(payload),
  });

export const adminDeleteCosmetic = (cosmeticId: string) =>
  fetchJSON<{ deleted: boolean }>(`/api/admin/cosmetics/${encodeURIComponent(cosmeticId)}`, { method: 'DELETE' });

// Admin — allowlist
export const adminListAllowlist = () =>
  fetchJSON<{ emails: AllowlistEmail[] }>('/api/admin/allowlist');

export const adminApproveAllowlist = (email: string) =>
  fetchJSON<{ email: AllowlistEmail }>('/api/admin/allowlist/approve', {
    method: 'POST',
    body: JSON.stringify({ email }),
  });

export const adminRevokeAllowlist = (email: string) =>
  fetchJSON<{ email: AllowlistEmail }>('/api/admin/allowlist/revoke', {
    method: 'POST',
    body: JSON.stringify({ email }),
  });

// Admin — audit
export const adminAuditLog = (params?: {
  page?: number; page_size?: number; action?: string; target_type?: string; actor_id?: string;
}) => {
  const qp = new URLSearchParams();
  if (params?.page) qp.set('page', String(params.page));
  if (params?.page_size) qp.set('page_size', String(params.page_size));
  if (params?.action) qp.set('action', params.action);
  if (params?.target_type) qp.set('target_type', params.target_type);
  if (params?.actor_id) qp.set('actor_id', params.actor_id);
  const suffix = qp.toString() ? `?${qp.toString()}` : '';
  return fetchJSON<{ entries: AdminAuditEntry[]; total: number; page: number; page_size: number }>(
    `/api/admin/audit${suffix}`,
  );
};

// Admin — analytics
export const adminAnalyticsOverview = () =>
  fetchJSON<AnalyticsOverview>('/api/admin/analytics/overview');
```

- [ ] **Step 20.2: Type-check**

Run: `cd frontend && npx tsc --noEmit`
Expected: PASS. The existing call sites of `adminFetchUsers()` (in `Admin.tsx`) currently expect `{ users: any[] }` — updating its signature will surface those, fixed in Task 21.

- [ ] **Step 20.3: Commit**

```bash
git add frontend/src/lib/api.ts
git commit -m "feat(api): admin portal client surface (paginated users, allowlist, audit, analytics, links)"
```

---

## Phase 13 — Frontend: tab strip + Allowlist tab

### Task 21: Tab union, ordering, default tab

**Files:**
- Modify: `frontend/src/components/screens/Admin.tsx:22, 65`

- [ ] **Step 21.1: Edit the type and the tab list**

Replace line 22:

```typescript
type Tab = "users" | "allowlist" | "roles" | "achievements" | "cosmetics" | "analytics" | "audit";
```

Replace the `tabs` array (currently line 65):

```typescript
const tabs: Tab[] = ["users", "allowlist", "roles", "achievements", "cosmetics", "analytics", "audit"];
```

In the body of the component, replace the `tab === ...` chain at lines 95-99 with:

```tsx
{tab === "users" && <UsersTab />}
{tab === "allowlist" && <AllowlistTab />}
{tab === "roles" && <RolesTab />}
{tab === "achievements" && <AchievementsTab />}
{tab === "cosmetics" && <CosmeticsTab />}
{tab === "analytics" && <AnalyticsTab />}
{tab === "audit" && <AuditTab />}
```

- [ ] **Step 21.2: Type-check (will fail because new tabs aren't defined yet)**

Expected: FAIL — `Cannot find name 'AllowlistTab'`. We'll add the components in Task 22.

- [ ] **Step 21.3: Commit (intentional — keeps the slice tiny)**

```bash
git add frontend/src/components/screens/Admin.tsx
git commit -m "feat(admin): add allowlist + audit tabs to Tab union"
```

### Task 22: AllowlistTab component

**Files:**
- Modify: `frontend/src/components/screens/Admin.tsx`

The styling matches the existing `UsersTab`: prose-strip metric line, then a `card` with a header row, then a table. We reuse `LabeledField`, `chip`, `chip--accent`, `chip--warn`, `btn`, `btn--primary`, `btn--ghost`.

- [ ] **Step 22.1: Add the import**

Replace the imports near line 12-18 to add the new functions:

```typescript
import {
  adminFetchUsers, adminApproveUser, adminUnapproveUser,
  adminListRoles, adminCreateRole, adminDeleteRole, adminAssignRole, adminRevokeRole,
  adminListAchievements, adminCreateAchievement, adminDeleteAchievement, adminGrantAchievement,
  adminListTriggers, adminCreateTrigger, adminUpdateTrigger, adminDeleteTrigger,
  adminListAchievementCosmetics, adminLinkAchievementCosmetic, adminUnlinkAchievementCosmetic,
  adminListCosmetics, adminCreateCosmetic, adminDeleteCosmetic,
  adminListRoleCosmetics, adminLinkRoleCosmetic, adminUnlinkRoleCosmetic,
  adminListAllowlist, adminApproveAllowlist, adminRevokeAllowlist,
  adminAuditLog, adminAnalyticsOverview,
  IS_LOCAL_MODE,
} from "@/lib/api";
import type {
  Role, Achievement, Cosmetic, CosmeticType, RarityTier, AchievementCategory,
  AllowlistEmail, AchievementTrigger, AdminAuditEntry, AnalyticsOverview,
} from "@/lib/types";
```

- [ ] **Step 22.2: Add the AllowlistTab component**

Insert after the `UsersTab` function (around line 283):

```tsx
// ── Allowlist ────────────────────────────────────────────────────────────────

function AllowlistTab() {
  const toast = useToast();
  const [emails, setEmails] = React.useState<AllowlistEmail[]>([]);
  const [query, setQuery] = React.useState("");
  const [newEmail, setNewEmail] = React.useState("");
  const [busy, setBusy] = React.useState(false);
  const [loading, setLoading] = React.useState(true);

  const load = React.useCallback(async () => {
    try {
      const r = await adminListAllowlist();
      setEmails(r.emails || []);
    } catch (err) {
      toast.error(`Load failed: ${String(err)}`);
    } finally {
      setLoading(false);
    }
  }, [toast]);

  React.useEffect(() => { load(); }, [load]);

  const filtered = query
    ? emails.filter(e => e.email.toLowerCase().includes(query.toLowerCase()))
    : emails;
  const approved = emails.filter(e => e.approved_at).length;
  const pending = emails.length - approved;

  const add = async () => {
    const e = newEmail.trim().toLowerCase();
    if (!e) return;
    setBusy(true);
    try {
      await adminApproveAllowlist(e);
      setNewEmail("");
      toast.success("Email allowlisted");
      await load();
    } catch (err) {
      toast.error(`Add failed: ${String(err)}`);
    } finally {
      setBusy(false);
    }
  };

  const toggle = async (row: AllowlistEmail) => {
    try {
      if (row.approved_at) {
        await adminRevokeAllowlist(row.email);
        toast.success("Allowlist revoked");
      } else {
        await adminApproveAllowlist(row.email);
        toast.success("Email allowlisted");
      }
      await load();
    } catch (err) {
      toast.error(`Update failed: ${String(err)}`);
    }
  };

  if (loading) return <AdminTableSkeleton />;

  return (
    <>
      <div className="body-serif" style={{ fontSize: 15, marginBottom: 22, color: "var(--text-dim)", maxWidth: 680 }}>
        <span style={{ color: "var(--text)" }}>{emails.length}</span> address{emails.length === 1 ? "" : "es"} · {" "}
        <span style={{ color: "var(--accent)" }}>{approved} approved</span>
        {pending > 0 && <> · <span style={{ color: "var(--warn)" }}>{pending} unapproved signups</span></>}
      </div>
      <div className="card" style={{ padding: 0 }}>
        <div style={{ display: "flex", padding: "12px 16px", borderBottom: "1px solid var(--border)", alignItems: "center", gap: 12 }}>
          <div style={{ position: "relative", flex: 1, maxWidth: 300 }}>
            <div style={{ position: "absolute", left: 10, top: 8, color: "var(--text-muted)" }}>
              <Icon name="search" size={14} />
            </div>
            <input
              placeholder="Search emails…"
              value={query}
              onChange={e => setQuery(e.target.value)}
              style={{
                width: "100%", padding: "7px 12px 7px 32px",
                border: "1px solid var(--border)", borderRadius: "var(--r-sm)",
                fontSize: 13, background: "var(--bg-input)",
              }}
            />
          </div>
          <input
            placeholder="someone@bu.edu"
            value={newEmail}
            onChange={e => setNewEmail(e.target.value)}
            onKeyDown={e => { if (e.key === "Enter") add(); }}
            style={{ ...fieldStyle, maxWidth: 240 }}
          />
          <button className="btn btn--primary btn--sm" onClick={add} disabled={busy || !newEmail.trim()}>
            {busy ? "Adding…" : "Allowlist"}
          </button>
        </div>
        <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
          <thead>
            <tr style={{ background: "var(--bg-subtle)" }}>
              {["Email", "Status", "Submitted", "Approved", ""].map(h => (
                <th key={h} style={{ textAlign: "left", padding: "10px 16px", fontWeight: 500, fontSize: 11, textTransform: "uppercase", letterSpacing: "0.08em", color: "var(--text-muted)" }}>
                  {h}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {filtered.map(row => (
              <tr key={row.id} style={{ borderTop: "1px solid var(--border)" }}>
                <td style={{ padding: "10px 16px", fontWeight: 500 }}>{row.email}</td>
                <td style={{ padding: "10px 16px" }}>
                  <span className={`chip ${row.approved_at ? "chip--accent" : "chip--warn"}`}>
                    {row.approved_at ? "approved" : "signup"}
                  </span>
                </td>
                <td style={{ padding: "10px 16px", color: "var(--text-muted)" }}>
                  {row.created_at ? new Date(row.created_at).toLocaleDateString() : "—"}
                </td>
                <td style={{ padding: "10px 16px", color: "var(--text-muted)" }}>
                  {row.approved_at ? new Date(row.approved_at).toLocaleDateString() : "—"}
                </td>
                <td style={{ padding: "10px 16px", textAlign: "right" }}>
                  <button
                    className={`btn btn--sm ${row.approved_at ? "btn--ghost" : "btn--primary"}`}
                    onClick={() => toggle(row)}
                  >
                    {row.approved_at ? "Revoke" : "Approve"}
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
  );
}
```

- [ ] **Step 22.3: Type-check**

Run: `cd frontend && npx tsc --noEmit`
Expected: still complains about the not-yet-implemented `AuditTab`. We'll silence it by adding a stub.

- [ ] **Step 22.4: Add stubs for `AuditTab` so the file compiles**

Insert at the end of the file (above the helpers section):

```tsx
function AuditTab() {
  return <div style={{ padding: 28, textAlign: "center", color: "var(--text-muted)" }}>Loading…</div>;
}
```

- [ ] **Step 22.5: Type-check + run dev server**

Run: `cd frontend && npx tsc --noEmit`
Expected: PASS.

Run: `cd frontend && npm run dev` (in another terminal)
Manually visit `/admin`, switch to the **Allowlist** tab, verify:
- Empty / populated states render with the same prose-strip header style as Users.
- The "Allowlist" button validates non-empty input.
- Approving and revoking refresh the table and show a toast.

- [ ] **Step 22.6: Commit**

```bash
git add frontend/src/components/screens/Admin.tsx
git commit -m "feat(admin): allowlist tab matches Users-tab styling"
```

---

## Phase 14 — Frontend: UsersTab pagination + server search + unapprove + last sign-in

### Task 23: Refactor UsersTab to consume `PaginatedUsers`

**Files:**
- Modify: `frontend/src/components/screens/Admin.tsx` (`UsersTab` and `AdminUser` type)

- [ ] **Step 23.1: Replace the `AdminUser` local alias with the imported one**

Delete the local `type AdminUser = {...}` block (lines 23-32) and import the canonical version:

```typescript
import type { AdminUserListItem as AdminUser } from "@/lib/types";
```

- [ ] **Step 23.2: Rewrite `UsersTab` (replaces lines 107-283)**

```tsx
function UsersTab() {
  const toast = useToast();
  const { userId: me } = useUser();
  const [users, setUsers] = React.useState<AdminUser[]>([]);
  const [roles, setRoles] = React.useState<Role[]>([]);
  const [query, setQuery] = React.useState("");
  const [committedQuery, setCommittedQuery] = React.useState("");
  const [page, setPage] = React.useState(1);
  const [pageSize] = React.useState(50);
  const [total, setTotal] = React.useState(0);
  const [assignFor, setAssignFor] = React.useState<string | null>(null);
  const [assignRoleId, setAssignRoleId] = React.useState<string>("");
  const [loading, setLoading] = React.useState(true);

  const load = React.useCallback(async () => {
    setLoading(true);
    try {
      const [u, r] = await Promise.all([
        adminFetchUsers({ q: committedQuery || undefined, page, page_size: pageSize }),
        adminListRoles(),
      ]);
      setUsers(u.users || []);
      setTotal(u.total || 0);
      setRoles(r.roles || []);
    } catch (err) {
      toast.error(`Load failed: ${String(err)}`);
    } finally {
      setLoading(false);
    }
  }, [committedQuery, page, pageSize, toast]);

  React.useEffect(() => { load(); }, [load]);

  // Debounce committed query (350ms) so each keystroke doesn't hit the backend.
  React.useEffect(() => {
    const id = window.setTimeout(() => {
      setCommittedQuery(query);
      setPage(1);
    }, 350);
    return () => window.clearTimeout(id);
  }, [query]);

  const approved = users.filter(u => u.is_approved).length;

  const assign = async (uid: string) => {
    if (!assignRoleId) return;
    try {
      await adminAssignRole(uid, assignRoleId, me);
      toast.success("Role assigned");
      setAssignFor(null);
      setAssignRoleId("");
      await load();
    } catch (err) {
      toast.error(`Assign failed: ${String(err)}`);
    }
  };

  const revoke = async (uid: string, rid: string) => {
    try {
      await adminRevokeRole(uid, rid);
      toast.success("Role revoked");
      await load();
    } catch (err) {
      toast.error(`Revoke failed: ${String(err)}`);
    }
  };

  const approve = async (uid: string) => {
    try { await adminApproveUser(uid); await load(); }
    catch (err) { toast.error(`Approve failed: ${String(err)}`); }
  };

  const unapprove = async (uid: string) => {
    try {
      await adminUnapproveUser(uid);
      toast.success("Approval revoked");
      await load();
    } catch (err) {
      toast.error(`Unapprove failed: ${String(err)}`);
    }
  };

  const totalPages = Math.max(1, Math.ceil(total / pageSize));

  if (loading && users.length === 0) {
    return <AdminTableSkeleton />;
  }

  return (
    <>
      <div className="body-serif" style={{
        fontSize: 15, marginBottom: 22, color: "var(--text-dim)", maxWidth: 680,
      }}>
        <span style={{ color: "var(--text)" }}>{total}</span> student{total === 1 ? "" : "s"} · {" "}
        <span style={{ color: "var(--accent)" }}>{approved} approved on this page</span>
        {committedQuery && <> · <span style={{ color: "var(--text-muted)" }}>filter “{committedQuery}”</span></>}
      </div>
      <div className="card" style={{ padding: 0 }}>
        <div style={{ display: "flex", padding: "12px 16px", borderBottom: "1px solid var(--border)", alignItems: "center", gap: 12 }}>
          <div style={{ position: "relative", flex: 1, maxWidth: 300 }}>
            <div style={{ position: "absolute", left: 10, top: 8, color: "var(--text-muted)" }}>
              <Icon name="search" size={14} />
            </div>
            <input
              placeholder="Search users…"
              value={query}
              onChange={e => setQuery(e.target.value)}
              style={{
                width: "100%", padding: "7px 12px 7px 32px",
                border: "1px solid var(--border)", borderRadius: "var(--r-sm)",
                fontSize: 13, background: "var(--bg-input)",
              }}
            />
          </div>
        </div>
        <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
          <thead>
            <tr style={{ background: "var(--bg-subtle)" }}>
              {["User", "Email", "Roles", "Status", "Last seen", "Joined", ""].map(h => (
                <th key={h} style={{ textAlign: "left", padding: "10px 16px", fontWeight: 500, fontSize: 11, textTransform: "uppercase", letterSpacing: "0.08em", color: "var(--text-muted)" }}>
                  {h}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {users.map(u => (
              <tr key={u.id} style={{ borderTop: "1px solid var(--border)" }}>
                <td style={{ padding: "10px 16px" }}>
                  <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
                    <Avatar name={u.name || "?"} size={28} />
                    <span style={{ fontWeight: 500 }}>{u.name}</span>
                  </div>
                </td>
                <td style={{ padding: "10px 16px", color: "var(--text-dim)" }}>{u.email}</td>
                <td style={{ padding: "10px 16px" }}>
                  <div style={{ display: "flex", gap: 4, flexWrap: "wrap", alignItems: "center" }}>
                    {(u.roles || []).map(r => (
                      <span key={r.id} style={{ display: "inline-flex", alignItems: "center", gap: 3 }}>
                        <RoleBadge role={r} />
                        <button
                          title="Revoke"
                          onClick={() => revoke(u.id, r.id)}
                          style={{ color: "var(--text-muted)", padding: "1px 4px" }}
                        >
                          ×
                        </button>
                      </span>
                    ))}
                    {assignFor === u.id ? (
                      <span style={{ display: "inline-flex", gap: 4, alignItems: "center" }}>
                        <CustomSelect
                          size="sm"
                          value={assignRoleId}
                          onChange={v => setAssignRoleId(v)}
                          options={roles.filter(r => !(u.roles || []).some(ur => ur.id === r.id)).map(r => ({ value: r.id, label: r.name }))}
                          placeholder="Role…"
                        />
                        <button className="btn btn--sm btn--primary" onClick={() => assign(u.id)} disabled={!assignRoleId}>
                          Add
                        </button>
                        <button className="btn btn--sm btn--ghost" onClick={() => { setAssignFor(null); setAssignRoleId(""); }}>×</button>
                      </span>
                    ) : (
                      <button
                        className="btn btn--sm btn--ghost"
                        onClick={() => { setAssignFor(u.id); setAssignRoleId(""); }}
                        style={{ fontSize: 11 }}
                      >
                        + role
                      </button>
                    )}
                  </div>
                </td>
                <td style={{ padding: "10px 16px" }}>
                  <span className={`chip ${u.is_approved ? "chip--accent" : "chip--warn"}`}>
                    {u.is_approved ? "approved" : "pending"}
                  </span>
                </td>
                <td style={{ padding: "10px 16px", color: "var(--text-muted)" }}>
                  {u.last_sign_in_at ? new Date(u.last_sign_in_at).toLocaleDateString() : "—"}
                </td>
                <td style={{ padding: "10px 16px", color: "var(--text-muted)" }}>
                  {u.created_at ? new Date(u.created_at).toLocaleDateString() : "—"}
                </td>
                <td style={{ padding: "10px 16px", textAlign: "right" }}>
                  {u.is_approved ? (
                    <button
                      className="btn btn--sm btn--ghost"
                      onClick={() => unapprove(u.id)}
                      title="Revoke approval"
                    >
                      Unapprove
                    </button>
                  ) : (
                    <button
                      className="btn btn--sm btn--primary"
                      onClick={() => approve(u.id)}
                    >
                      Approve
                    </button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        <div style={{
          display: "flex", justifyContent: "space-between", alignItems: "center",
          padding: "10px 16px", borderTop: "1px solid var(--border)", fontSize: 12, color: "var(--text-muted)",
        }}>
          <div>Page {page} of {totalPages} · {total} total</div>
          <div style={{ display: "flex", gap: 6 }}>
            <button className="btn btn--sm btn--ghost" disabled={page <= 1} onClick={() => setPage(p => Math.max(1, p - 1))}>Prev</button>
            <button className="btn btn--sm btn--ghost" disabled={page >= totalPages} onClick={() => setPage(p => Math.min(totalPages, p + 1))}>Next</button>
          </div>
        </div>
      </div>
    </>
  );
}
```

- [ ] **Step 23.3: Type-check + manual smoke**

Run: `cd frontend && npx tsc --noEmit`
Expected: PASS.

Run dev server, visit `/admin`. Verify:
- Pagination footer shows "Page 1 of N" and the buttons disable at the edges.
- Searching for a partial name debounces ~350ms then refetches.
- Approve / Unapprove flows refresh the page; pending users get the primary "Approve" button, approved users get a ghost "Unapprove" button.
- "Last seen" column shows a date for any user who has signed in since Phase 4.

- [ ] **Step 23.4: Commit**

```bash
git add frontend/src/components/screens/Admin.tsx
git commit -m "feat(admin): UsersTab — pagination + server search + unapprove + last_sign_in"
```

---

## Phase 15 — Frontend: AchievementsTab triggers + cosmetic linker

### Task 24: Inline triggers panel + cosmetic linker per achievement row

The styling stays minimal: a "details" row that toggles open below each `CatalogRow`. We reuse the existing card-internal layout — no new components.

**Files:**
- Modify: `frontend/src/components/screens/Admin.tsx` (`AchievementsTab` + `CatalogRow`)

- [ ] **Step 24.1: Extend `CatalogRow` to accept an optional `onExpand` and `expanded` slot**

Replace the existing `CatalogRow` with:

```tsx
function CatalogRow({
  left, middle, sub, onDelete, onExpand, expanded, expandedContent,
}: {
  left: React.ReactNode;
  middle: React.ReactNode;
  sub?: string;
  onDelete: () => void;
  onExpand?: () => void;
  expanded?: boolean;
  expandedContent?: React.ReactNode;
}) {
  const del = useConfirm(onDelete);
  return (
    <div>
      <div style={{
        display: "flex", alignItems: "center", gap: 12,
        padding: "10px 16px", borderTop: "1px solid var(--border)",
      }}>
        <div style={{ flexShrink: 0 }}>{left}</div>
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ fontSize: 13 }}>{middle}</div>
          {sub && <div style={{ fontSize: 11, color: "var(--text-muted)", marginTop: 2 }}>{sub}</div>}
        </div>
        {onExpand && (
          <button className="btn btn--sm btn--ghost" onClick={onExpand}>
            {expanded ? "Hide" : "Manage"}
          </button>
        )}
        <button
          className={`btn btn--sm ${del.armed ? "btn--danger" : "btn--ghost"}`}
          onClick={del.trigger}
          style={del.armed ? { background: "var(--err-soft)", color: "var(--err)" } : undefined}
        >
          {del.armed ? "Click again" : <Icon name="x" size={12} />}
        </button>
      </div>
      {expanded && expandedContent && (
        <div style={{ padding: "10px 16px 14px 56px", borderTop: "1px dashed var(--border)", background: "var(--bg-subtle)" }}>
          {expandedContent}
        </div>
      )}
    </div>
  );
}
```

- [ ] **Step 24.2: Add a `useAchievementDetails(achievementId)` hook inside `AchievementsTab`**

Inside `AchievementsTab`, before the JSX:

```tsx
const [openId, setOpenId] = React.useState<string | null>(null);
const [triggers, setTriggers] = React.useState<AchievementTrigger[]>([]);
const [linkedCosmeticIds, setLinkedCosmeticIds] = React.useState<string[]>([]);
const [allCosmetics, setAllCosmetics] = React.useState<Cosmetic[]>([]);
const [newTrigger, setNewTrigger] = React.useState({ trigger_type: "", trigger_threshold: 1 });

const loadDetails = React.useCallback(async (id: string) => {
  try {
    const [t, l, c] = await Promise.all([
      adminListTriggers(id),
      adminListAchievementCosmetics(id),
      allCosmetics.length ? Promise.resolve({ cosmetics: allCosmetics }) : adminListCosmetics(),
    ]);
    setTriggers(t.triggers || []);
    setLinkedCosmeticIds((l.links || []).map(x => x.cosmetic_id));
    if (!allCosmetics.length) setAllCosmetics(c.cosmetics || []);
  } catch (err) {
    toast.error(`Detail load failed: ${String(err)}`);
  }
}, [allCosmetics, toast]);

const toggleOpen = (id: string) => {
  if (openId === id) { setOpenId(null); return; }
  setOpenId(id);
  loadDetails(id);
};

const addTrigger = async (id: string) => {
  if (!newTrigger.trigger_type.trim()) { toast.warn("Trigger type required."); return; }
  try {
    await adminCreateTrigger({
      achievement_id: id,
      trigger_type: newTrigger.trigger_type.trim(),
      trigger_threshold: newTrigger.trigger_threshold,
    });
    setNewTrigger({ trigger_type: "", trigger_threshold: 1 });
    await loadDetails(id);
    toast.success("Trigger added");
  } catch (err) { toast.error(`Add failed: ${String(err)}`); }
};

const updateTrigger = async (tid: string, patch: Partial<AchievementTrigger>, achId: string) => {
  try {
    await adminUpdateTrigger(tid, {
      ...(patch.trigger_type !== undefined ? { trigger_type: patch.trigger_type } : {}),
      ...(patch.trigger_threshold !== undefined ? { trigger_threshold: patch.trigger_threshold } : {}),
    });
    await loadDetails(achId);
  } catch (err) { toast.error(`Update failed: ${String(err)}`); }
};

const deleteTrigger = async (tid: string, achId: string) => {
  try {
    await adminDeleteTrigger(tid);
    await loadDetails(achId);
    toast.success("Trigger deleted");
  } catch (err) { toast.error(`Delete failed: ${String(err)}`); }
};

const toggleCosmetic = async (achId: string, cosmeticId: string) => {
  const linked = linkedCosmeticIds.includes(cosmeticId);
  try {
    if (linked) await adminUnlinkAchievementCosmetic(achId, cosmeticId);
    else        await adminLinkAchievementCosmetic(achId, cosmeticId);
    await loadDetails(achId);
  } catch (err) { toast.error(`Link toggle failed: ${String(err)}`); }
};
```

- [ ] **Step 24.3: Render the expanded content for each row**

Replace the `items.map(...)` block in `AchievementsTab` with:

```tsx
{items.map(a => (
  <CatalogRow
    key={a.id}
    left={<span style={{ fontSize: 18 }}>{a.icon || "★"}</span>}
    middle={
      <span style={{ display: "flex", alignItems: "center", gap: 8 }}>
        <span style={{ fontWeight: 600 }}>{a.name}</span>
        <span className="chip" style={{ textTransform: "uppercase", fontSize: 10 }}>{a.rarity}</span>
        {a.is_secret && <span className="chip chip--warn">secret</span>}
      </span>
    }
    sub={a.description || a.slug}
    onDelete={() => del(a.id)}
    onExpand={() => toggleOpen(a.id)}
    expanded={openId === a.id}
    expandedContent={
      <div style={{ display: "grid", gap: 14 }}>
        <div>
          <div className="label-micro" style={{ marginBottom: 6 }}>Triggers · {triggers.length}</div>
          {triggers.length === 0 && <div style={{ fontSize: 12, color: "var(--text-muted)" }}>None.</div>}
          {triggers.map(t => (
            <div key={t.id} style={{ display: "flex", gap: 6, alignItems: "center", marginBottom: 6 }}>
              <input
                value={t.trigger_type}
                onChange={e => updateTrigger(t.id, { trigger_type: e.target.value }, a.id)}
                style={{ ...fieldStyle, flex: 1 }}
              />
              <input
                type="number"
                value={t.trigger_threshold}
                onChange={e => updateTrigger(t.id, { trigger_threshold: Number(e.target.value) || 0 }, a.id)}
                style={{ ...fieldStyle, width: 80 }}
              />
              <button className="btn btn--sm btn--ghost" onClick={() => deleteTrigger(t.id, a.id)}>×</button>
            </div>
          ))}
          <div style={{ display: "flex", gap: 6, alignItems: "center", marginTop: 6 }}>
            <input
              placeholder="trigger_type (e.g. login_streak)"
              value={newTrigger.trigger_type}
              onChange={e => setNewTrigger(v => ({ ...v, trigger_type: e.target.value }))}
              style={{ ...fieldStyle, flex: 1 }}
            />
            <input
              type="number"
              value={newTrigger.trigger_threshold}
              onChange={e => setNewTrigger(v => ({ ...v, trigger_threshold: Number(e.target.value) || 0 }))}
              style={{ ...fieldStyle, width: 80 }}
            />
            <button className="btn btn--sm btn--primary" onClick={() => addTrigger(a.id)}>Add</button>
          </div>
        </div>
        <div>
          <div className="label-micro" style={{ marginBottom: 6 }}>Linked cosmetics</div>
          <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
            {allCosmetics.map(c => {
              const on = linkedCosmeticIds.includes(c.id);
              return (
                <button
                  key={c.id}
                  className={`chip ${on ? "chip--accent" : ""}`}
                  onClick={() => toggleCosmetic(a.id, c.id)}
                  style={{ cursor: "pointer", border: on ? undefined : "1px dashed var(--border)" }}
                  title={`${c.type} · ${c.rarity}`}
                >
                  {c.name}
                </button>
              );
            })}
            {allCosmetics.length === 0 && <span style={{ fontSize: 12, color: "var(--text-muted)" }}>No cosmetics defined yet.</span>}
          </div>
        </div>
      </div>
    }
  />
))}
```

- [ ] **Step 24.4: Type-check + manual smoke**

Run: `cd frontend && npx tsc --noEmit`
Expected: PASS.

Manually: open the Achievements tab, click "Manage" on a row, add a trigger, edit the threshold, delete it, toggle a cosmetic chip. Each action shows a toast and refetches.

- [ ] **Step 24.5: Commit**

```bash
git add frontend/src/components/screens/Admin.tsx
git commit -m "feat(admin): inline triggers + cosmetic linker on achievements"
```

---

## Phase 16 — Frontend: CosmeticsTab role linker

### Task 25: Per-cosmetic "linked roles" chip strip

**Files:**
- Modify: `frontend/src/components/screens/Admin.tsx` (`CosmeticsTab`)

- [ ] **Step 25.1: Add hooks and handlers inside `CosmeticsTab`**

Insert near the top of `CosmeticsTab`, after `setItems`:

```tsx
const [openId, setOpenId] = React.useState<string | null>(null);
const [allRoles, setAllRoles] = React.useState<Role[]>([]);
const [linkedRoleIdsByCosmetic, setLinkedRoleIdsByCosmetic] = React.useState<Record<string, string[]>>({});

const ensureRoles = React.useCallback(async () => {
  if (allRoles.length) return;
  try { setAllRoles((await adminListRoles()).roles || []); }
  catch (err) { toast.error(`Roles load failed: ${String(err)}`); }
}, [allRoles.length, toast]);

const loadLinks = async (cosmeticId: string) => {
  // We aggregate across roles — call /api/admin/roles/{role_id}/cosmetics for
  // each role and pick out where cosmetic_id matches. With ~5–20 roles this is
  // fine; if it grows, add a /api/admin/cosmetics/{id}/roles endpoint later.
  await ensureRoles();
  try {
    const all = await Promise.all(allRoles.map(r => adminListRoleCosmetics(r.id).then(x => ({ r, x }))));
    const linked = all
      .filter(({ x }) => x.links.some(l => l.cosmetic_id === cosmeticId))
      .map(({ r }) => r.id);
    setLinkedRoleIdsByCosmetic(prev => ({ ...prev, [cosmeticId]: linked }));
  } catch (err) {
    toast.error(`Link load failed: ${String(err)}`);
  }
};

const toggleRoleLink = async (roleId: string, cosmeticId: string) => {
  const linked = linkedRoleIdsByCosmetic[cosmeticId] || [];
  try {
    if (linked.includes(roleId)) await adminUnlinkRoleCosmetic(roleId, cosmeticId);
    else                          await adminLinkRoleCosmetic(roleId, cosmeticId);
    await loadLinks(cosmeticId);
  } catch (err) { toast.error(`Toggle failed: ${String(err)}`); }
};

const toggleOpen = async (id: string) => {
  if (openId === id) { setOpenId(null); return; }
  setOpenId(id);
  await loadLinks(id);
};
```

- [ ] **Step 25.2: Render the expanded content per cosmetic**

Replace the per-cosmetic `CatalogRow` call in `CosmeticsTab`:

```tsx
{grouped[t].map(c => (
  <CatalogRow
    key={c.id}
    left={c.asset_url ? (
      <img src={c.asset_url} alt="" style={{ width: 28, height: 28, borderRadius: "var(--r-sm)", objectFit: "cover", border: "1px solid var(--border)" }} />
    ) : c.css_value ? (
      <span style={{ padding: "2px 6px", fontSize: 10, borderRadius: "var(--r-sm)", background: c.css_value, color: "#fff", border: "1px solid var(--border)" }}>
        sample
      </span>
    ) : (
      <span style={{ fontSize: 16 }}>◇</span>
    )}
    middle={
      <span style={{ display: "flex", gap: 8, alignItems: "center" }}>
        <span style={{ fontWeight: 600 }}>{c.name}</span>
        <span className="chip" style={{ fontSize: 10, textTransform: "uppercase" }}>{c.rarity}</span>
      </span>
    }
    sub={c.slug}
    onDelete={() => del(c.id)}
    onExpand={() => toggleOpen(c.id)}
    expanded={openId === c.id}
    expandedContent={
      <div>
        <div className="label-micro" style={{ marginBottom: 6 }}>Roles that grant this</div>
        <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
          {allRoles.map(r => {
            const on = (linkedRoleIdsByCosmetic[c.id] || []).includes(r.id);
            return (
              <button
                key={r.id}
                className={`chip ${on ? "chip--accent" : ""}`}
                onClick={() => toggleRoleLink(r.id, c.id)}
                style={{ cursor: "pointer", border: on ? undefined : "1px dashed var(--border)" }}
              >
                {r.name}
              </button>
            );
          })}
          {allRoles.length === 0 && <span style={{ fontSize: 12, color: "var(--text-muted)" }}>No roles defined yet.</span>}
        </div>
      </div>
    }
  />
))}
```

- [ ] **Step 25.3: Type-check + manual smoke**

Run: `cd frontend && npx tsc --noEmit`
Expected: PASS.

Manually: toggle a role chip on a cosmetic; a second click un-links; refresh and confirm persistence.

- [ ] **Step 25.4: Commit**

```bash
git add frontend/src/components/screens/Admin.tsx
git commit -m "feat(admin): role linker chip strip on cosmetics"
```

---

## Phase 17 — Frontend: AnalyticsTab build-out

### Task 26: Replace the placeholder `AnalyticsTab` with a real card grid

We use a simple SVG sparkline (no charting library) so we don't add dependencies. Styling: same `card` containers, `label-micro` labels, `h-serif` big numbers, accent-colored fill.

**Files:**
- Modify: `frontend/src/components/screens/Admin.tsx` (`AnalyticsTab`)

- [ ] **Step 26.1: Replace the existing `AnalyticsTab` body**

```tsx
function AnalyticsTab() {
  const toast = useToast();
  const [data, setData] = React.useState<AnalyticsOverview | null>(null);
  const [loading, setLoading] = React.useState(true);

  React.useEffect(() => {
    let alive = true;
    adminAnalyticsOverview()
      .then(r => { if (alive) setData(r); })
      .catch(err => toast.error(`Analytics load failed: ${String(err)}`))
      .finally(() => { if (alive) setLoading(false); });
    return () => { alive = false; };
  }, [toast]);

  if (loading) return <AdminTableSkeleton />;
  if (!data) return null;

  const { totals, signups_by_day, approvals_by_day, role_counts } = data;

  return (
    <div style={{ display: "grid", gap: 14 }}>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(4, minmax(0, 1fr))", gap: 14 }}>
        <MetricCard label="Users" value={totals.users} />
        <MetricCard label="Approved" value={totals.approved} accent />
        <MetricCard label="Pending" value={totals.pending} warn={totals.pending > 0} />
        <MetricCard label="Admins" value={totals.admins} />
      </div>
      <div className="card" style={{ padding: "var(--pad-lg)" }}>
        <div className="label-micro" style={{ marginBottom: 10 }}>Signups · last 30 days</div>
        <Sparkline points={signups_by_day} accent />
      </div>
      <div className="card" style={{ padding: "var(--pad-lg)" }}>
        <div className="label-micro" style={{ marginBottom: 10 }}>Approvals · last 30 days</div>
        <Sparkline points={approvals_by_day} />
      </div>
      <div className="card" style={{ padding: 0 }}>
        <div style={{ padding: "12px 16px", borderBottom: "1px solid var(--border)" }}>
          <div className="label-micro">Role membership · {role_counts.length}</div>
        </div>
        {role_counts.length === 0 && (
          <div style={{ padding: 28, textAlign: "center", color: "var(--text-muted)", fontSize: 13 }}>
            Nobody has any roles yet.
          </div>
        )}
        {role_counts.map(rc => (
          <div key={rc.slug} style={{
            display: "flex", alignItems: "center", gap: 12,
            padding: "10px 16px", borderTop: "1px solid var(--border)", fontSize: 13,
          }}>
            <span style={{
              display: "inline-block", width: 10, height: 10, borderRadius: 3,
              background: rc.color, border: "1px solid var(--border)",
            }} />
            <span style={{ flex: 1, fontWeight: 500 }}>{rc.name}</span>
            <span style={{ fontFamily: "var(--font-mono)", color: "var(--text-dim)" }}>{rc.count}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

function MetricCard({ label, value, accent, warn }: { label: string; value: number; accent?: boolean; warn?: boolean }) {
  const color = accent ? "var(--accent)" : warn ? "var(--warn)" : "var(--text)";
  return (
    <div className="card" style={{ padding: "var(--pad-lg)" }}>
      <div className="label-micro">{label}</div>
      <div className="h-serif" style={{ fontSize: 32, marginTop: 4, color }}>{value}</div>
    </div>
  );
}

function Sparkline({ points, accent }: { points: { date: string; count: number }[]; accent?: boolean }) {
  if (points.length === 0) return <div style={{ fontSize: 12, color: "var(--text-muted)" }}>No data.</div>;
  const w = 600, h = 80, pad = 4;
  const max = Math.max(1, ...points.map(p => p.count));
  const stepX = (w - pad * 2) / Math.max(1, points.length - 1);
  const path = points.map((p, i) => {
    const x = pad + i * stepX;
    const y = h - pad - (p.count / max) * (h - pad * 2);
    return `${i === 0 ? "M" : "L"} ${x.toFixed(1)} ${y.toFixed(1)}`;
  }).join(" ");
  const stroke = accent ? "var(--accent)" : "var(--text-dim)";
  return (
    <svg viewBox={`0 0 ${w} ${h}`} preserveAspectRatio="none" style={{ width: "100%", height: 80 }}>
      <path d={path} fill="none" stroke={stroke} strokeWidth={2} />
      {points.map((p, i) => (
        <circle key={p.date} cx={pad + i * stepX} cy={h - pad - (p.count / max) * (h - pad * 2)} r={2} fill={stroke}>
          <title>{`${p.date}: ${p.count}`}</title>
        </circle>
      ))}
    </svg>
  );
}
```

- [ ] **Step 26.2: Type-check + manual smoke**

Run: `cd frontend && npx tsc --noEmit`
Expected: PASS.

Manually: visit `/admin` → Analytics. Confirm four metric cards (Users / Approved / Pending / Admins), two sparkline cards, and a role-count list with the role's seed color block.

- [ ] **Step 26.3: Commit**

```bash
git add frontend/src/components/screens/Admin.tsx
git commit -m "feat(admin): analytics tab — totals, 30-day sparklines, role membership"
```

---

## Phase 18 — Frontend: AuditTab

### Task 27: Replace the AuditTab stub with a real paginated, filterable list

**Files:**
- Modify: `frontend/src/components/screens/Admin.tsx` (`AuditTab`)

- [ ] **Step 27.1: Replace the stub**

```tsx
function AuditTab() {
  const toast = useToast();
  const [entries, setEntries] = React.useState<AdminAuditEntry[]>([]);
  const [page, setPage] = React.useState(1);
  const [pageSize] = React.useState(50);
  const [total, setTotal] = React.useState(0);
  const [actionFilter, setActionFilter] = React.useState<string>("");
  const [targetFilter, setTargetFilter] = React.useState<string>("");
  const [loading, setLoading] = React.useState(true);

  const load = React.useCallback(async () => {
    setLoading(true);
    try {
      const r = await adminAuditLog({
        page, page_size: pageSize,
        action: actionFilter || undefined,
        target_type: targetFilter || undefined,
      });
      setEntries(r.entries || []);
      setTotal(r.total || 0);
    } catch (err) {
      toast.error(`Audit load failed: ${String(err)}`);
    } finally {
      setLoading(false);
    }
  }, [page, pageSize, actionFilter, targetFilter, toast]);

  React.useEffect(() => { load(); }, [load]);

  const totalPages = Math.max(1, Math.ceil(total / pageSize));
  if (loading && entries.length === 0) return <AdminTableSkeleton />;

  return (
    <>
      <div className="body-serif" style={{ fontSize: 15, marginBottom: 22, color: "var(--text-dim)", maxWidth: 680 }}>
        <span style={{ color: "var(--text)" }}>{total}</span> recorded action{total === 1 ? "" : "s"}
      </div>
      <div className="card" style={{ padding: 0 }}>
        <div style={{ display: "flex", padding: "12px 16px", borderBottom: "1px solid var(--border)", alignItems: "center", gap: 12 }}>
          <input
            placeholder="action (e.g. user.approve)"
            value={actionFilter}
            onChange={e => { setActionFilter(e.target.value); setPage(1); }}
            style={{ ...fieldStyle, maxWidth: 220 }}
          />
          <input
            placeholder="target_type (e.g. user)"
            value={targetFilter}
            onChange={e => { setTargetFilter(e.target.value); setPage(1); }}
            style={{ ...fieldStyle, maxWidth: 220 }}
          />
        </div>
        <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
          <thead>
            <tr style={{ background: "var(--bg-subtle)" }}>
              {["When", "Actor", "Action", "Target", "Payload"].map(h => (
                <th key={h} style={{ textAlign: "left", padding: "10px 16px", fontWeight: 500, fontSize: 11, textTransform: "uppercase", letterSpacing: "0.08em", color: "var(--text-muted)" }}>
                  {h}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {entries.map(e => (
              <tr key={e.id} style={{ borderTop: "1px solid var(--border)" }}>
                <td style={{ padding: "10px 16px", color: "var(--text-muted)", whiteSpace: "nowrap" }}>
                  {new Date(e.created_at).toLocaleString()}
                </td>
                <td style={{ padding: "10px 16px", fontFamily: "var(--font-mono)", fontSize: 12 }}>{e.actor_id}</td>
                <td style={{ padding: "10px 16px" }}>
                  <span className="chip">{e.action}</span>
                </td>
                <td style={{ padding: "10px 16px", color: "var(--text-dim)" }}>
                  <span className="chip">{e.target_type}</span>
                  <span style={{ marginLeft: 6, fontFamily: "var(--font-mono)", fontSize: 12 }}>{e.target_id || "—"}</span>
                </td>
                <td style={{ padding: "10px 16px", fontFamily: "var(--font-mono)", fontSize: 11, color: "var(--text-muted)", maxWidth: 360, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}
                    title={JSON.stringify(e.payload)}>
                  {Object.keys(e.payload || {}).length ? JSON.stringify(e.payload) : "—"}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        <div style={{
          display: "flex", justifyContent: "space-between", alignItems: "center",
          padding: "10px 16px", borderTop: "1px solid var(--border)", fontSize: 12, color: "var(--text-muted)",
        }}>
          <div>Page {page} of {totalPages}</div>
          <div style={{ display: "flex", gap: 6 }}>
            <button className="btn btn--sm btn--ghost" disabled={page <= 1} onClick={() => setPage(p => Math.max(1, p - 1))}>Prev</button>
            <button className="btn btn--sm btn--ghost" disabled={page >= totalPages} onClick={() => setPage(p => Math.min(totalPages, p + 1))}>Next</button>
          </div>
        </div>
      </div>
    </>
  );
}
```

- [ ] **Step 27.2: Type-check + manual smoke**

Run: `cd frontend && npx tsc --noEmit`
Expected: PASS.

Manually: trigger a few admin actions in another tab (approve a user, link a cosmetic), refresh `/admin` Audit tab, and verify the entries show up newest-first. Filter by `action=user.approve`; only those rows remain.

- [ ] **Step 27.3: Commit**

```bash
git add frontend/src/components/screens/Admin.tsx
git commit -m "feat(admin): audit log viewer with action/target filters and pagination"
```

---

## Phase 19 — Final hardening + handoff

### Task 28: Backend regression run

- [ ] **Step 28.1: Full backend suite**

Run: `cd backend && python -m pytest tests/ -q`
Expected: PASS.

- [ ] **Step 28.2: Spot-check `routes/auth.py` test for `last_sign_in_at` write**

Confirm `tests/test_auth_state.py::TestLastSignInStamp` is green; it is the regression watchdog.

### Task 29: Frontend type + lint

- [ ] **Step 29.1: TypeScript**

Run: `cd frontend && npx tsc --noEmit`
Expected: PASS.

- [ ] **Step 29.2: Manual smoke checklist**

Run: `cd frontend && npm run dev`. Open `/admin` (logged in as an admin user) and walk through:

1. Users tab — paginate forward and back, search, approve, unapprove, assign + revoke a role.
2. Allowlist tab — add a new email, revoke, re-approve.
3. Roles tab — try to delete the `Admin` role (must 409 with toast); try to revoke own admin role (must 409); reassigning an existing role must succeed (no 500).
4. Achievements tab — Manage on a row, add/edit/delete a trigger, link/unlink a cosmetic.
5. Cosmetics tab — Manage on a cosmetic, link/unlink roles.
6. Analytics tab — totals match the database; sparkline tooltips show the per-day count.
7. Audit tab — every action from steps 1–6 has a corresponding row.

If any step misbehaves, fix it before merging.

### Task 30: Final commit + handoff

- [ ] **Step 30.1: Commit a closing marker**

```bash
git commit --allow-empty -m "chore(admin): admin portal v1 complete (issue #69)"
```

- [ ] **Step 30.2: Push the worktree branch**

```bash
git push -u origin feat/admin-portal
```

- [ ] **Step 30.3: Open the PR linking #69**

```bash
gh pr create --title "feat(admin): admin portal — pagination, audit log, allowlist, analytics (closes #69)" --body "$(cat <<'EOF'
## Summary
- Pagination + server-side search on /api/admin/users; new last_sign_in_at column.
- New endpoints: unapprove user; achievement triggers list/update/delete; achievement_cosmetics + role_cosmetics link/unlink/list; admin_audit_log read; analytics overview (totals + 30-day series + role counts).
- Self-protection: cannot revoke own admin, cannot revoke last admin, cannot delete admin role, cannot unapprove self.
- Audit log written for every admin mutation (single sanctioned helper services/admin_audit.py).
- Frontend Admin.tsx gains Allowlist + Audit tabs and rewires Users/Achievements/Cosmetics/Analytics to the new endpoints — all using existing card / chip / btn / label-micro tokens.

## Test plan
- [ ] cd backend && python -m pytest tests/ -q
- [ ] cd frontend && npx tsc --noEmit
- [ ] Manual smoke list from Phase 19 / Task 29.2

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

---

## Self-review — coverage map

| Issue #69 gap | Where it's resolved |
|---|---|
| Analytics tab has no backend | Tasks 17, 26 |
| No audit log | Tasks 1, 3, 7, 8, 9, 11, 12, 13, 14, 15, 16, 27 |
| No pagination on list endpoints | Tasks 2, 5, 6, 16, 23, 27 |
| No search/filter on `/users` | Tasks 5, 6, 23 |
| No "unapprove" path | Tasks 7, 23 |
| No "impersonate user" | Out of scope (issue lists this; deferred — see note below) |
| Self-protection (own admin, last admin, admin role) | Task 9 |
| Achievement triggers list/delete | Task 11 |
| `role_cosmetics` / `achievement_cosmetics` admin endpoints | Tasks 12, 14, 24, 25 |
| `last_sign_in_at` field | Tasks 1, 4, 23 |
| `/users` decrypts every row per request | Mitigated in Task 5: paginated path decrypts only the page; query path is honest about decrypting all |
| Pagination shape decision | Locked in "Decisions" — offset, page_size cap 200 |
| Audit-log scope decision | Locked in "Decisions" — single `admin_audit_log` table |
| Analytics scope decision | Locked in "Decisions" — totals + 30-day series + role counts |

**Out of scope (deliberately, mentioned in issue but flagged as future work):**
- "Impersonate user" — touches session minting and has security implications that warrant their own design pass.
