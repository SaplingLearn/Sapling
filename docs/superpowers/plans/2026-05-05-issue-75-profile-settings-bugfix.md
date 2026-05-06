# Issue #75 — Profile Settings PATCH/GET/Avatar Bugfix Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix the three reported failures on `/api/profile/{user_id}` (PATCH fields, GET preview, POST avatar) which all share a single root cause in `_get_user_or_404`.

**Architecture:** `backend/routes/profile.py::_get_user_or_404` SELECTs `school,major` from the `users` table — neither column exists in `backend/db/supabase_schema.sql` or any migration file. PostgREST returns HTTP 400 ("column users.school does not exist"); the route doesn't catch it; FastAPI returns 500; the frontend toast surfaces "Couldn't save / load preview / Upload failed". Three endpoints fail because all three call `_get_user_or_404`. Fix: drop the two non-existent columns from the SELECT, add a column-list regression test, and confirm via the existing test suite that nothing else regresses.

**Tech Stack:** Python 3.13, FastAPI, Supabase (PostgREST via `db/connection.py`), pytest with `MagicMock`-based table mocking. No frontend changes (the bug is server-side; the frontend's existing toast already surfaces the new HTTP 200 cleanly).

---

## File Structure

| File | Responsibility | Change |
|---|---|---|
| `backend/routes/profile.py` | Profile route handlers + `_get_user_or_404` helper | Modify line 30: drop `school,` and `major,` from SELECT string |
| `backend/tests/test_profile_routes.py` | Profile route tests | Add `TestGetUserOrFour04SelectColumns` regression test class pinning the exact column list against the schema |

No new files. No frontend changes.

---

## Confirmed root cause (one-pager — read before starting)

`_get_user_or_404` (currently at `backend/routes/profile.py:28-38`):

```python
def _get_user_or_404(user_id: str) -> dict:
    rows = table("users").select(
        "id,username,name,first_name,last_name,email,avatar_url,school,major,year,majors,minors,bio,location,website,streak_count,created_at",
        filters={"id": f"eq.{user_id}"},
    )
```

**The SELECT references two columns that don't exist on `users`:**
- `school` — never added by any migration. The actual school is fetched separately from `user_courses → courses(school)` in `get_public_profile` at line 175-183.
- `major` (singular) — never added. The schema has `majors TEXT[]` (plural array) which IS in the SELECT and correctly used.

Authoritative schema sources:
- `backend/db/supabase_schema.sql:7` — base `users` table (no school, no major).
- `backend/db/migration_profile_settings.sql` — adds `username`, `bio`, `location`, `website`, `deleted_at`. Not `school` or `major`.
- `grep -hE "ADD COLUMN.*\busers\b" backend/db/migration_*.sql` returns no `school` or `major`.

Why three endpoints fail simultaneously:
- `update_profile` (PATCH) calls `_get_user_or_404(user_id)` at `profile.py:221`.
- `get_public_profile` (GET) calls it at `profile.py:170`.
- `upload_user_avatar` (POST avatar) calls it at `profile.py:261`.

Why existing tests don't catch it: every test in `test_profile_routes.py` mocks `routes.profile.table` with `MagicMock()` which happily returns whatever the test sets without validating that the SELECT'd columns exist on a schema. So unit tests pass while prod 500s.

---

## Task 1: Reproduce the bug with a failing regression test

**Files:**
- Modify: `backend/tests/test_profile_routes.py`

The new test pins the contract: the SELECT in `_get_user_or_404` must reference only columns that actually exist in `users`. The schema columns are derived from `supabase_schema.sql` + migrations. We hardcode the allowed set in the test as the source of truth — if a future migration adds a column, the test gets updated alongside.

- [ ] **Step 1.1: Add the regression test class to `backend/tests/test_profile_routes.py`**

Append this class at the bottom of the file (after the existing `TestCheckUsername` class):

```python
# ── _get_user_or_404 column contract (issue #75) ────────────────────────────

class TestGetUserOrFour04SelectColumns:
    """Pin the column list used by `_get_user_or_404`'s SELECT against the
    actual `users` schema. Issue #75 was caused by `school` and `major` being
    SELECTed despite never being added by any migration; PostgREST returned
    HTTP 400, the route 500'd, and three endpoints (PATCH, GET, avatar POST)
    failed simultaneously. Existing MagicMock-based tests didn't catch it
    because the mock returns success for any column.
    """

    # Columns that actually exist on `users` per
    # `backend/db/supabase_schema.sql:7` + `migration_profile_settings.sql`
    # + `migration_google_auth.sql` + `migration_add_is_approved.sql` +
    # `migration_onboarding_fields.sql`. If a future migration adds a column
    # to `users`, update this set in the same PR that introduces the
    # migration so the test stays the source of truth.
    USERS_SCHEMA_COLUMNS = {
        "id", "name", "email", "first_name", "last_name", "year",
        "majors", "minors", "learning_style", "onboarding_completed",
        "streak_count", "last_active_date", "room_id", "created_at",
        "google_id", "avatar_url", "auth_provider", "is_approved",
        "username", "bio", "location", "website", "deleted_at",
    }

    def test_select_columns_all_exist_on_users_schema(self):
        """Every column in `_get_user_or_404`'s SELECT must exist on
        `users`. The column string is the second positional arg to
        `table('users').select(...)`; we capture it and compare against
        the schema set above."""
        captured = {}

        def table_side_effect(name):
            m = MagicMock()
            if name == "users":
                def _capture_select(columns, **kwargs):
                    captured["users_columns"] = columns
                    return [{
                        # Return a row with every column in the schema
                        # so post-select decryption + dict access don't
                        # NoneType-blow-up when the test runs.
                        "id": USER_ID, "name": "Test", "email": None,
                        "first_name": None, "last_name": None,
                        "username": None, "avatar_url": None,
                        "year": None, "majors": [], "minors": [],
                        "bio": None, "location": None, "website": None,
                        "streak_count": 0, "created_at": "2026-01-01",
                    }]
                m.select.side_effect = _capture_select
            else:
                m.select.return_value = []
            return m

        with patch("routes.profile.table", side_effect=table_side_effect):
            from routes.profile import _get_user_or_404
            _get_user_or_404(USER_ID)

        assert "users_columns" in captured, "table('users').select(...) was not called"
        selected = {c.strip() for c in captured["users_columns"].split(",")}
        unknown = selected - self.USERS_SCHEMA_COLUMNS
        assert not unknown, (
            f"_get_user_or_404 SELECTs columns that don't exist on `users`: "
            f"{sorted(unknown)}. This is the root cause of issue #75 — "
            f"PostgREST returns HTTP 400 for unknown columns and the route "
            f"500s. Fix: remove these columns from the SELECT in "
            f"backend/routes/profile.py:_get_user_or_404."
        )
```

- [ ] **Step 1.2: Run the test to verify it FAILS with the expected error**

```bash
cd backend
python -m pytest tests/test_profile_routes.py::TestGetUserOrFour04SelectColumns::test_select_columns_all_exist_on_users_schema -v
```

Expected output:
```
FAILED tests/test_profile_routes.py::TestGetUserOrFour04SelectColumns::test_select_columns_all_exist_on_users_schema
AssertionError: _get_user_or_404 SELECTs columns that don't exist on `users`: ['major', 'school'].
```

If the test passes instead of fails, you're not on the right branch — `school` and `major` should still be in the SELECT at this point. Verify by `grep -n 'school,major' backend/routes/profile.py` (should match line 30).

---

## Task 2: Fix `_get_user_or_404`

**Files:**
- Modify: `backend/routes/profile.py:28-38`

- [ ] **Step 2.1: Drop `school,` and `major,` from the SELECT string**

Open `backend/routes/profile.py` and locate `_get_user_or_404` (around line 28). The current code is:

```python
def _get_user_or_404(user_id: str) -> dict:
    rows = table("users").select(
        "id,username,name,first_name,last_name,email,avatar_url,school,major,year,majors,minors,bio,location,website,streak_count,created_at",
        filters={"id": f"eq.{user_id}"},
    )
    if not rows:
        raise HTTPException(status_code=404, detail="User not found")
    row = rows[0]
    for col in ("name", "first_name", "last_name", "email", "bio", "location"):
        row[col] = decrypt_if_present(row.get(col))
    return row
```

Change the SELECT string. The replacement removes `school,` and `major,`:

```python
def _get_user_or_404(user_id: str) -> dict:
    rows = table("users").select(
        "id,username,name,first_name,last_name,email,avatar_url,year,majors,minors,bio,location,website,streak_count,created_at",
        filters={"id": f"eq.{user_id}"},
    )
    if not rows:
        raise HTTPException(status_code=404, detail="User not found")
    row = rows[0]
    for col in ("name", "first_name", "last_name", "email", "bio", "location"):
        row[col] = decrypt_if_present(row.get(col))
    return row
```

Use the `Edit` tool, not `Write` — this is a one-line change inside a 600-line file.

- [ ] **Step 2.2: Verify nothing else in the route reads `user["school"]` or `user["major"]`**

Run:
```bash
cd backend
grep -n 'user\["school"\]\|user\["major"\]\|user\.get("school")\|user\.get("major")' routes/profile.py
```

Expected: no matches. The `school` value the response surfaces (`get_public_profile:194`) comes from a different fetch (`enrollments[0]["courses"]["school"]` at line 182), not from `users.school`. The `majors` (plural array) is read at line 192 — that column DOES exist and stays in the SELECT.

If the grep returns matches, stop and ask — there's another consumer that needs to be addressed.

- [ ] **Step 2.3: Re-run the regression test to verify it PASSES**

```bash
cd backend
python -m pytest tests/test_profile_routes.py::TestGetUserOrFour04SelectColumns::test_select_columns_all_exist_on_users_schema -v
```

Expected: `PASSED`. The SELECT now references only existing columns.

---

## Task 3: Verify nothing else broke

**Files:**
- No code changes; pure verification.

- [ ] **Step 3.1: Run the full profile test suite**

```bash
cd backend
python -m pytest tests/test_profile_routes.py -q
```

Expected output:
```
N passed in X.XXs
```

Where `N` is the previous test count + 1 (the new regression test). No failures.

- [ ] **Step 3.2: Run the full backend suite to confirm no regressions elsewhere**

```bash
cd backend
python -m pytest tests/ -q --ignore=tests/evals
```

Baseline: 596 passing + 3 pre-existing live-Supabase failures (`test_skips_self_edges`, `test_save_to_db`, `test_full_pipeline`). After this fix: **597 passing + same 3 failures** (the +1 is the new regression test). Anything else red is a regression — stop and investigate before continuing.

- [ ] **Step 3.3: Manual smoke verification against a local backend**

Skip this step if you don't have a local backend wired up; the regression test plus the full suite is sufficient automated coverage. If you do have one running:

```bash
# In one terminal, start the backend.
cd backend && python main.py

# In a second terminal, hit the endpoint that previously 500'd.
# Use a real session token from a logged-in browser cookie, OR run the
# request through the frontend's /settings page in a browser.
curl -i -X PATCH "http://localhost:8000/api/profile/<your-user-id>" \
  -H "Content-Type: application/json" \
  -H "Cookie: sapling_session=<paste-from-browser>" \
  -d '{"display_name":"Smoke test"}'
```

Expected: `HTTP/1.1 200 OK` with body `{"updated":true}`. Before the fix this returned 500 with a PostgREST `column users.school does not exist` error in the response body.

---

## Task 4: Commit and open PR

**Files:**
- No code changes; git operations.

- [ ] **Step 4.1: Branch + stage + commit**

```bash
cd "/Users/josegaelcruzlopez/Documents/Startup_Projects /Sapling"
git fetch origin
git checkout -b fix/issue-75-profile-routes origin/main

git add backend/routes/profile.py backend/tests/test_profile_routes.py

git commit -m "$(cat <<'EOF'
fix(profile): drop non-existent school/major from users SELECT (closes #75)

_get_user_or_404 SELECTed columns that don't exist on the users table:
- `school` was never added by any migration. The school value surfaced
  on the public profile actually comes from a separate user_courses ->
  courses(school) join in get_public_profile.
- `major` (singular) was never added either. The schema has `majors`
  (plural array) which IS used and stays in the SELECT.

PostgREST returned HTTP 400 ("column users.school does not exist") on
every read, the route didn't catch it, and three endpoints all 500'd:
  - PATCH /api/profile/{user_id}        (update_profile)
  - GET   /api/profile/{user_id}        (get_public_profile / preview)
  - POST  /api/profile/{user_id}/avatar (upload_user_avatar)

All three call _get_user_or_404 — single root cause, single fix.

Existing tests didn't catch it because they mock routes.profile.table
with MagicMock which returns success for any column. Added
TestGetUserOrFour04SelectColumns that pins the SELECT against the
actual schema (USERS_SCHEMA_COLUMNS set), so any future drift fails
loudly in CI rather than at runtime.

Verification:
- Regression test fails before the fix (asserts the unknown columns).
- Regression test passes after the fix.
- Full backend suite: 597 passing (was 596 + 1 new), same 3
  pre-existing live-Supabase failures unchanged.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

- [ ] **Step 4.2: Push and open the PR**

```bash
cd "/Users/josegaelcruzlopez/Documents/Startup_Projects /Sapling"
git push -u origin fix/issue-75-profile-routes

gh pr create --base main --head fix/issue-75-profile-routes \
  --title "fix(profile): drop non-existent school/major from users SELECT (closes #75)" \
  --body "$(cat <<'EOF'
## Summary

Closes #75 (profile PATCH + GET preview + avatar upload all 500'ing).
Single root cause: \`_get_user_or_404\` SELECTed two columns
(\`school\`, \`major\`) that don't exist on the \`users\` table. PostgREST
returned HTTP 400, the route didn't catch it, and all three endpoints
that call this helper failed simultaneously.

## What changed

- \`backend/routes/profile.py:30\` — removed \`school,major,\` from the
  SELECT string. The remaining columns all exist on \`users\` per
  \`supabase_schema.sql\` + the relevant migrations.
- \`backend/tests/test_profile_routes.py\` — added
  \`TestGetUserOrFour04SelectColumns\` regression test that asserts every
  SELECTed column exists on the schema. Future column drift fails
  loudly in CI instead of at runtime.

## Why the existing tests missed it

Every test in \`test_profile_routes.py\` mocks \`routes.profile.table\`
with a \`MagicMock()\` that returns success regardless of which columns
the SELECT requests. So the unit suite was green while production
500'd. The new test extracts the SELECT string itself and validates
against the schema column set — no DB needed, but catches the
specific drift class that caused this bug.

## Test plan

- [x] \`pytest tests/test_profile_routes.py -q\` — all green.
- [x] Full suite: 597 passing (+1 new test), same 3 pre-existing
      live-Supabase failures.
- [ ] Manual smoke against a logged-in session: PATCH a display name,
      reload the page, confirm the value persists. (Recommended before
      merge.)

## Out of scope

- Frontend behavior is unchanged. The toast UX surfaces success/failure
  the same way; the success path now actually fires.
- The \`school\` / \`major\` data the route response exposes still works
  exactly as before — \`school\` comes from the
  \`user_courses → courses(school)\` join (\`profile.py:175-183\`); the
  user's \`majors\` (plural array) is unaffected.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

The PR URL prints to stdout. Paste it into the issue as a closing reference.

---

## Self-review

**Spec coverage** — every part of issue #75 is addressed by Task 2 (the SELECT fix), pinned by Task 1 (the regression test), and verified by Task 3 (full-suite run). Acceptance criteria from the issue:
- *"Editing any of Display name / Bio / Location / Website / Username and blurring saves to the DB"* → covered by the PATCH path no longer 500'ing.
- *"...and survives a hard refresh"* → covered (the existing PATCH writes to `users` + `user_settings`; once the SELECT succeeds, the writes succeed too).
- *"No error toast on the happy path; surfaced error message is meaningful when the request actually fails"* → covered (the toast already surfaces `await res.text()` from the response body; with the fix, the happy path returns 200 and the toast doesn't fire).
- *"Preview profile button"* and *"Change avatar button"* (from comments) → covered by the same fix since both endpoints share `_get_user_or_404`.

**Placeholder scan** — no TODOs, no "fill in details", no "similar to Task N", no references to types/methods not defined in the plan. Every command and code block is complete.

**Type consistency** — the test class name `TestGetUserOrFour04SelectColumns`, the method `test_select_columns_all_exist_on_users_schema`, the column set `USERS_SCHEMA_COLUMNS`, and the route function `_get_user_or_404` are referenced consistently across Tasks 1, 2, and 4.
