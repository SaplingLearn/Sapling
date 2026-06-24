# Staging Environment Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stand up an admin-only, fully-hosted staging environment that mirrors prod (Cloudflare Workers frontend + Railway backend + a dedicated Supabase project) so DB migrations and bugfixes can be verified before reaching prod.

**Architecture:** Staging is the same code as prod, differing only by environment variables. A psycopg-based migration runner gives a reproducible apply path — **already merged on `main`** (see #197), so the runner/migrations work below is documented for context, not redone here. Staging is gated at the edge with Cloudflare Access. Deploys are trunk-based: `main` continuously deploys to staging; a `production` branch (fast-forwarded from a verified commit of `main`) deploys to prod.

> **Re-baseline note (Phase 0 is done):** This plan was written before the migration runner landed on `main`. As of current `main`, `backend/db/migrate.py`, the ordered `backend/db/migrations/0001…0018` set, `psycopg[binary]>=3.2,<4` in `requirements.txt`, the idempotent `0009_cosmetics.sql`, `backend/tests/test_migrate.py`, the `frontend/wrangler.toml` `[env.staging]` block, and the `package.json` `cf:deploy:staging` script all already exist. Phase 0 (Tasks 1–5) and Task 11 are therefore **already done** and are kept below for reference only — do not re-implement them. The genuinely-remaining work is Tasks 6–10 and 12–15.

**Tech Stack:** FastAPI + Supabase (PostgREST for app, direct Postgres via psycopg for migrations), Next.js on Cloudflare Workers, Railway environments, Cloudflare Access (Zero Trust), Google OAuth.

## Global Constraints

- App-runtime DB access goes through `db/connection.py::table()` (PostgREST). The migration runner is the **only** sanctioned direct-Postgres path (DDL can't run over PostgREST).
- Migration runner connects with the Supabase **direct** connection string (`SUPABASE_DB_URL`), not the pooler.
- Encrypted columns must be written via `services/encryption.py::encrypt_if_present`; never write ciphertext-bearing columns as raw SQL through the app path.
- Staging uses its **own** `ENCRYPTION_KEY`, `SESSION_SECRET`, Google OAuth client, and Supabase project. Never reuse prod secrets.
- New dependency pin follows the repo's existing `requirements.txt` style; add `psycopg[binary]>=3.2,<4`.
- Tests live in `backend/tests/`, run via `python -m pytest tests/ -q`.

---

## File Structure

**Already on `main` (done — do not recreate):**
- `backend/db/migrate.py` — migration runner CLI (psycopg, direct connection).
- `backend/db/migrations/` — directory holding ordered, numbered `NNNN_*.sql` migrations (`0001…0018`).
- `backend/tests/test_migrate.py` — unit tests for the runner's pure functions.
- `backend/requirements.txt` — already pins `psycopg[binary]>=3.2,<4`.
- `backend/db/migrations/0009_cosmetics.sql` — already idempotent (#196).
- `frontend/wrangler.toml` — already has the `[env.staging]` block.
- `frontend/package.json` — already has the `cf:deploy:staging` script.

**Created (remaining):**
- `backend/db/seed_staging.py` — inserts fake app data (encrypted via helpers, through `table()`).
- `backend/db/dirty_fixtures.sql` — deliberately-broken rows that reproduce the backlog's failure modes.

**Modified (remaining):**
- `backend/config.py` — recognize `APP_ENV=staging` (drives `noindex`).
- `backend/main.py` — emit `X-Robots-Tag: noindex` when `APP_ENV=staging`.
- `backend/.env.example` — document `SUPABASE_DB_URL` and `APP_ENV=staging` (see Task 6.5).

**Operator runbooks (no repo files):** Supabase staging project, Google staging OAuth client, Railway staging environment, Cloudflare DNS + Access, deploy wiring.

---

## Phase 0 — Migration runner (ALREADY MERGED ON `main` — reference only)

> **Status: DONE on `main`.** Tasks 1–5 below were implemented and merged after this plan was
> written (addressing #197, hardening #196). **Do not re-run them** — they would conflict with
> merged code. They are retained verbatim only so the design rationale is traceable. To confirm,
> the following already exist on `main`: `backend/requirements.txt` pins `psycopg[binary]>=3.2,<4`;
> `backend/db/migrations/0001_baseline_schema.sql … 0018_documents_request_id.sql`;
> `backend/db/migrate.py` with `discover_migrations`/`pending_migrations`/`run`/`main`;
> `backend/tests/test_migrate.py`; and an idempotent `backend/db/migrations/0009_cosmetics.sql`.

<details>
<summary>Phase 0 tasks (already merged — click to expand for reference)</summary>

### Task 1: Add psycopg dependency [DONE on `main`]

**Files:**
- Modify: `backend/requirements.txt`

- [ ] **Step 1: Add the driver**

Add this line to `backend/requirements.txt` (match the file's existing ordering/style):

```
psycopg[binary]>=3.2,<4
```

- [ ] **Step 2: Install and verify import**

Run: `cd backend && pip install -r requirements.txt && python -c "import psycopg; print(psycopg.__version__)"`
Expected: prints a 3.2.x version, no error.

- [ ] **Step 3: Commit**

```bash
git add backend/requirements.txt
git commit -m "build: add psycopg for the migration runner (#197)"
```

### Task 2: Create the ordered migrations directory [DONE on `main`]

**Files:**
- Create: `backend/db/migrations/` (move existing `migration_*.sql` here with numeric prefixes)

**Interfaces:**
- Produces: a `backend/db/migrations/` directory of `NNNN_name.sql` files in apply order, consumed by `migrate.py`.

- [ ] **Step 1: Create the directory and move migrations in dependency order**

The order is dictated by FK dependencies (roles before role_cosmetics, users before everything user-scoped). Use this mapping (rename as you move):

```bash
cd backend/db
mkdir -p migrations
git mv supabase_schema.sql            migrations/0001_baseline_schema.sql
git mv migration_roles.sql            migrations/0002_roles.sql
git mv migration_google_auth.sql      migrations/0003_google_auth.sql
git mv migration_onboarding_fields.sql migrations/0004_onboarding_fields.sql
git mv migration_profile_settings.sql migrations/0005_profile_settings.sql
git mv migration_add_is_approved.sql  migrations/0006_add_is_approved.sql
git mv migration_achievements.sql     migrations/0007_achievements.sql
git mv migration_newsletter.sql       migrations/0008_newsletter.sql
git mv migration_cosmetics.sql        migrations/0009_cosmetics.sql
git mv migration_admin_portal.sql     migrations/0010_admin_portal.sql
git mv migration_avatars_bucket.sql   migrations/0011_avatars_bucket.sql
git mv migration_gradebook.sql        migrations/0012_gradebook.sql
git mv migration_drop_legacy_grade_tables.sql migrations/0013_drop_legacy_grade_tables.sql
git mv migration_notes.sql            migrations/0014_notes.sql
git mv migration_concept_notes.sql    migrations/0015_concept_notes.sql
git mv migration_flashcard_course_id.sql migrations/0016_flashcard_course_id.sql
git mv migration_encryption_text_columns.sql migrations/0017_encryption_text_columns.sql
git mv migration_documents_request_id.sql migrations/0018_documents_request_id.sql
```

Leave `seed.sql` and `archive/` where they are — they are not migrations.

> NOTE: This order is a best-effort reconstruction. Before running against a *fresh* DB (Phase 1), if any migration fails on a missing dependency, swap its number so the dependency comes first, then re-run. This is exactly the ordering knowledge #197 says is currently undocumented.

- [ ] **Step 2: Commit the reorganization**

```bash
git add -A backend/db
git commit -m "refactor(db): move migrations into ordered migrations/ dir (#197)"
```

### Task 3: Migration runner — pure functions (TDD) [DONE on `main`]

**Files:**
- Create: `backend/db/migrate.py`
- Test: `backend/tests/test_migrate.py`

**Interfaces:**
- Produces: `discover_migrations(dir) -> list[Path]`, `pending_migrations(all_files, applied: set[str]) -> list[Path]`, consumed by `run()` in Task 4.

- [ ] **Step 1: Write the failing tests**

```python
# backend/tests/test_migrate.py
from db.migrate import discover_migrations, pending_migrations


def test_discover_migrations_sorts_by_filename(tmp_path):
    for name in ["0002_b.sql", "0001_a.sql", "0010_c.sql"]:
        (tmp_path / name).write_text("SELECT 1;")
    result = [p.name for p in discover_migrations(tmp_path)]
    assert result == ["0001_a.sql", "0002_b.sql", "0010_c.sql"]


def test_pending_migrations_excludes_applied(tmp_path):
    files = [tmp_path / "0001_a.sql", tmp_path / "0002_b.sql"]
    for f in files:
        f.write_text("SELECT 1;")
    pending = pending_migrations(files, {"0001_a.sql"})
    assert [p.name for p in pending] == ["0002_b.sql"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && python -m pytest tests/test_migrate.py -q`
Expected: FAIL with `ModuleNotFoundError`/`ImportError` (migrate.py not created yet).

- [ ] **Step 3: Write the pure functions**

```python
# backend/db/migrate.py
"""Minimal migration runner for Supabase Postgres (#197).

App runtime uses db/connection.py::table() (PostgREST), which cannot execute DDL.
Migrations are raw DDL, so this admin tool connects directly with psycopg over the
Supabase *direct* connection string (SUPABASE_DB_URL, NOT the pooler). This is the
one sanctioned exception to the table()-only convention.

Usage:
    SUPABASE_DB_URL=postgresql://... python -m db.migrate            # apply pending
    SUPABASE_DB_URL=postgresql://... python -m db.migrate --baseline # record as applied without running
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

MIGRATIONS_DIR = Path(__file__).parent / "migrations"


def discover_migrations(migrations_dir: Path) -> list[Path]:
    """All *.sql migration files, sorted by filename (numeric prefix = order)."""
    return sorted(Path(migrations_dir).glob("*.sql"))


def pending_migrations(all_files: list[Path], applied: set[str]) -> list[Path]:
    """Migration files whose basename has not yet been recorded as applied."""
    return [p for p in all_files if p.name not in applied]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && python -m pytest tests/test_migrate.py -q`
Expected: PASS (2 passed).

- [ ] **Step 5: Commit**

```bash
git add backend/db/migrate.py backend/tests/test_migrate.py
git commit -m "feat(db): migration runner discovery/pending logic (#197)"
```

### Task 4: Migration runner — DB I/O + CLI [DONE on `main`]

**Files:**
- Modify: `backend/db/migrate.py`

**Interfaces:**
- Consumes: `discover_migrations`, `pending_migrations` from Task 3.
- Produces: `run(conn, migrations_dir, baseline) -> list[str]`, `main() -> int`.

- [ ] **Step 1: Append the DB-facing functions and CLI**

```python
import psycopg  # add to the imports at the top of migrate.py


def ensure_tracking_table(conn: "psycopg.Connection") -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS schema_migrations (
                filename   TEXT PRIMARY KEY,
                applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
            )
            """
        )
    conn.commit()


def applied_filenames(conn: "psycopg.Connection") -> set[str]:
    with conn.cursor() as cur:
        cur.execute("SELECT filename FROM schema_migrations")
        return {row[0] for row in cur.fetchall()}


def apply_migration(conn: "psycopg.Connection", path: Path) -> None:
    """Run one migration's SQL and record it, atomically."""
    with conn.cursor() as cur:
        cur.execute(path.read_text())
        cur.execute("INSERT INTO schema_migrations (filename) VALUES (%s)", (path.name,))
    conn.commit()


def run(conn: "psycopg.Connection", migrations_dir: Path = MIGRATIONS_DIR, baseline: bool = False) -> list[str]:
    """Apply (or baseline-record) all pending migrations. Returns filenames handled."""
    ensure_tracking_table(conn)
    applied = applied_filenames(conn)
    pending = pending_migrations(discover_migrations(migrations_dir), applied)
    handled: list[str] = []
    for path in pending:
        if baseline:
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO schema_migrations (filename) VALUES (%s) ON CONFLICT DO NOTHING",
                    (path.name,),
                )
            conn.commit()
        else:
            apply_migration(conn, path)
        handled.append(path.name)
    return handled


def main() -> int:
    db_url = os.environ.get("SUPABASE_DB_URL", "").strip()
    if not db_url:
        print(
            "ERROR: SUPABASE_DB_URL is not set "
            "(Supabase → Settings → Database → Connection string → Direct).",
            file=sys.stderr,
        )
        return 1
    baseline = "--baseline" in sys.argv[1:]
    with psycopg.connect(db_url) as conn:
        handled = run(conn, baseline=baseline)
    verb = "Baselined" if baseline else "Applied"
    print(f"{verb} {len(handled)} migration(s):" if handled else "No pending migrations.")
    for name in handled:
        print(f"  - {name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 2: Verify the module still imports and pure-function tests still pass**

Run: `cd backend && python -m pytest tests/test_migrate.py -q && python -c "import db.migrate"`
Expected: tests PASS; import succeeds (psycopg installed in Task 1).

- [ ] **Step 3: Commit**

```bash
git add backend/db/migrate.py
git commit -m "feat(db): migration runner apply/baseline + CLI (#197)"
```

### Task 5: Make migration_cosmetics idempotent (#196) [DONE on `main`]

**Files:**
- Modify: `backend/db/migrations/0009_cosmetics.sql`

- [ ] **Step 1: Guard every `ADD CONSTRAINT` (Postgres has no `ADD CONSTRAINT IF NOT EXISTS`)**

Replace each bare `ALTER TABLE user_settings ADD CONSTRAINT fk_... ...;` block with a guarded form. Example for the first; repeat the pattern for `fk_user_settings_banner`, `fk_user_settings_name_color`, `fk_user_settings_title`, `fk_user_settings_featured_role`:

```sql
DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint WHERE conname = 'fk_user_settings_avatar_frame'
  ) THEN
    ALTER TABLE user_settings
      ADD CONSTRAINT fk_user_settings_avatar_frame
      FOREIGN KEY (equipped_avatar_frame_id) REFERENCES cosmetics(id);
  END IF;
END $$;
```

- [ ] **Step 2: Verify it is re-runnable (against any reachable dev/staging DB)**

Run: `SUPABASE_DB_URL=<dev-or-staging-direct-url> python -m db.migrate` twice.
Expected: second run prints "No pending migrations." and never errors on a duplicate constraint.

- [ ] **Step 3: Commit**

```bash
git add backend/db/migrations/0009_cosmetics.sql
git commit -m "fix(db): make cosmetics FK constraints idempotent (#196)"
```

</details>

---

## Phase 1 — Staging Supabase project + data

### Task 6: Create and bootstrap the staging Supabase project (operator runbook)

- [ ] **Step 1:** In the Supabase dashboard, create a new project named `sapling-staging` (same region as prod). Record its `SUPABASE_URL`, service-role key, and **Direct** connection string (Settings → Database → Connection string → "Direct connection", port 5432).
- [ ] **Step 2:** Generate a staging encryption key: `python -c "import secrets; print(secrets.token_hex(32))"`. Keep it separate from prod.
- [ ] **Step 3:** Apply the full schema to the empty project:

Run: `cd backend && SUPABASE_DB_URL=<staging-direct-url> python -m db.migrate`
Expected: prints "Applied N migration(s)" listing `0001_…` through `0018_…`. If any fails on a missing dependency, reorder per Task 2's NOTE and re-run.

- [ ] **Step 4:** Create the `avatars` and `cosmetic-assets` storage buckets in the staging project (Storage → New bucket), matching prod.
- [ ] **Step 5 (verify):** Run `SUPABASE_DB_URL=<staging-direct-url> python -m db.migrate` again → expect "No pending migrations." Confirms the tracking table is populated.

### Task 6.5: Document `SUPABASE_DB_URL` and `APP_ENV` in `.env.example`

**Files:**
- Modify: `backend/.env.example`

The migration runner (`db/migrate.py`) hard-errors when `SUPABASE_DB_URL` is unset, and the
`noindex`/`IS_STAGING` work (Task 13) keys off `APP_ENV`, yet neither variable is documented in
`backend/.env.example` on `main`. Add both so a fresh checkout knows they exist.

- [ ] **Step 1: Add the two variables to `backend/.env.example`** (in the Supabase section, after `SUPABASE_SERVICE_KEY`):

```
# Direct Postgres connection string (Settings → Database → Connection string → "Direct connection",
# port 5432, NOT the pooler). Required by the migration runner (python -m db.migrate); unused by the
# app runtime, which goes through PostgREST.
SUPABASE_DB_URL=postgresql://postgres:[password]@db.your-project-ref.supabase.co:5432/postgres

# Deployment environment. Defaults to "production" when unset (strict, fail-closed checks).
# Set APP_ENV=local for local dev (relaxes SESSION_SECRET); set APP_ENV=staging on the staging
# deploy (drives the noindex header). "staging" is NOT in IS_LOCAL, so it stays fail-closed.
APP_ENV=production
```

- [ ] **Step 2: Commit**

```bash
git add backend/.env.example
git commit -m "docs(env): document SUPABASE_DB_URL and APP_ENV in .env.example"
```

### Task 7: Synthetic seed data

**Files:**
- Create: `backend/db/seed_staging.py`

**Interfaces:**
- Consumes: `db/connection.py::table()`, `services/encryption.py::encrypt_if_present`.

- [ ] **Step 1: Write the seed script**

```python
# backend/db/seed_staging.py
"""Seed the STAGING Supabase project with a handful of fake users/courses/graphs.

Run with the staging env vars loaded (SUPABASE_URL/SUPABASE_SERVICE_KEY/ENCRYPTION_KEY
pointing at staging). Encrypted columns go through encrypt_if_present so they decrypt
correctly under the staging key. Idempotent: upserts on stable string ids.
"""
from db.connection import table
from services.encryption import encrypt_if_present

FAKE_USERS = [
    {"id": "stg-user-1", "name": "Ada Tester", "email": "ada@staging.local", "onboarding_completed": True},
    {"id": "stg-user-2", "name": "Borg Tester", "email": "borg@staging.local", "onboarding_completed": True},
]


def seed() -> None:
    for u in FAKE_USERS:
        row = dict(u)
        row["name"] = encrypt_if_present(row["name"])
        table("users").upsert(row, on_conflict="id")
    table("courses").upsert(
        {"id": "stg-course-1", "user_id": "stg-user-1", "name": "Staging 101"},
        on_conflict="id",
    )
    print(f"Seeded {len(FAKE_USERS)} users + 1 course.")


if __name__ == "__main__":
    seed()
```

> NOTE: extend `FAKE_USERS`/courses to whatever breadth you want to click through. Keep ids `stg-*` so re-runs upsert rather than duplicate.

- [ ] **Step 2: Run against staging**

Run: `cd backend && <staging env vars> python -m db.seed_staging`
Expected: prints "Seeded 2 users + 1 course."; rows visible in the Supabase table editor (name column is ciphertext).

- [ ] **Step 3: Commit**

```bash
git add backend/db/seed_staging.py
git commit -m "feat(db): synthetic staging seed data"
```

### Task 8: Dirty fixtures (reproduce backlog failure modes)

**Files:**
- Create: `backend/db/dirty_fixtures.sql`

- [ ] **Step 1: Write fixtures that violate what the migrations must later fix**

```sql
-- backend/db/dirty_fixtures.sql
-- Deliberately-broken rows for staging only. Applied via the direct connection so
-- they bypass the app's guards. Each row targets a specific open issue so its fix
-- can be proven on staging.

-- #181: duplicate graph nodes (same user + concept_name) — a UNIQUE-backed dedup must collapse these.
-- (Inserted first: graph_edges below references these node ids via FK.)
INSERT INTO graph_nodes (id, user_id, concept_name) VALUES
  ('stg-node-dup-a', 'stg-user-1', 'Photosynthesis'),
  ('stg-node-dup-b', 'stg-user-1', 'Photosynthesis');

-- #179: orphan graph_edges.user_id (no such user) — an FK migration must reject/clean this.
-- Note: graph_edges uses source_node_id/target_node_id (both REFERENCE graph_nodes(id)),
-- so the endpoint nodes must exist; only user_id is the dangling reference here.
INSERT INTO graph_edges (id, user_id, source_node_id, target_node_id)
VALUES ('stg-edge-orphan', 'stg-user-DOES-NOT-EXIST', 'stg-node-dup-a', 'stg-node-dup-b');

-- #184: a quiz attempt that generated zero questions — the UI must not strand the user.
-- There is no `quizzes` table; quizzes are recorded as quiz_attempts rows. An empty quiz
-- has total = 0 and an empty questions_json array.
INSERT INTO quiz_attempts (id, user_id, total, questions_json)
VALUES ('stg-quiz-empty', 'stg-user-1', 0, '[]'::jsonb);
```

> NOTE: column names above match `0001_baseline_schema.sql` on `main` (`graph_edges.source_node_id`/`target_node_id`, `graph_nodes.concept_name`, `quiz_attempts` — there is no `quizzes` table). Still confirm against the live staging schema before applying if the schema has since changed. Keep ids `stg-*`.

- [ ] **Step 2: Apply to staging via the direct connection**

Run: `psql "<staging-direct-url>" -f backend/db/dirty_fixtures.sql` (or load it through a one-off psycopg call).
Expected: all 3 INSERT statements succeed (they violate app logic, not yet DB constraints).

- [ ] **Step 3: Commit**

```bash
git add backend/db/dirty_fixtures.sql
git commit -m "test(db): dirty fixtures reproducing #179/#181/#184 on staging"
```

---

## Phase 2 — Staging Google OAuth client (operator runbook)

### Task 9: Create the staging OAuth client

- [ ] **Step 1:** Google Cloud Console → APIs & Services → Credentials → Create OAuth client ID (Web application), named "Sapling Staging".
- [ ] **Step 2:** Authorized redirect URIs:
  - `https://api.staging.saplinglearn.com/api/auth/google/callback`
  - `https://api.staging.saplinglearn.com/api/calendar/callback`
- [ ] **Step 3:** Authorized JavaScript origin: `https://staging.saplinglearn.com`.
- [ ] **Step 4:** Record the client id + secret for the staging backend env (Task 10). Add staging testers to the OAuth consent screen if it is in "testing" mode.

---

## Phase 3 — Staging backend on Railway (operator runbook)

### Task 10: Railway staging environment

- [ ] **Step 1:** Railway project → Environments → create `staging` (duplicate of `production`).
- [ ] **Step 2:** Set staging variables (see the spec's env-var matrix). Critically distinct from prod:
  - `SUPABASE_URL`, `SUPABASE_SERVICE_KEY` → staging project
  - `SUPABASE_DB_URL` → staging direct connection string
  - `ENCRYPTION_KEY` → staging key (Task 6)
  - `SESSION_SECRET` → fresh `python -c "import secrets; print(secrets.token_hex(32))"`
  - `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET` → staging OAuth client (Task 9)
  - `GOOGLE_REDIRECT_URI=https://api.staging.saplinglearn.com/api/calendar/callback`
  - `GOOGLE_AUTH_REDIRECT_URI=https://api.staging.saplinglearn.com/api/auth/google/callback`
  - `FRONTEND_URL=https://staging.saplinglearn.com`
  - `APP_ENV=staging`
  - `GEMINI_API_KEY` → prod key (shared) or a separate staging key
- [ ] **Step 3:** Point the staging environment's deploy source at the `main` branch (Phase 7 finalizes this).
- [ ] **Step 4:** Add the custom domain `api.staging.saplinglearn.com` to the staging service.
- [ ] **Step 5 (verify):** Hit `https://api.staging.saplinglearn.com/` (or a health route) → backend responds; logs show it booted against the staging Supabase.

---

## Phase 4 — Staging frontend on Cloudflare Workers

### Task 11: Add the staging Worker environment [config DONE on `main`]

> **Status: the repo changes are already merged on `main`.** `frontend/wrangler.toml` already
> contains the `[env.staging]` / `[env.staging.vars]` / `[env.staging.observability]` blocks shown
> below (the merged `[env.staging.vars]` matches exactly: `NEXT_PUBLIC_API_URL`, `BACKEND_URL`,
> `COOKIE_DOMAIN`), and `frontend/package.json` already has the `cf:deploy:staging` script. **Do not
> re-add them.** Only Step 3 (the actual deploy) remains — and it is operator work, not a code edit.

**Files (already merged — reference only):**
- `frontend/wrangler.toml`
- `frontend/package.json`

- [x] **Step 1: `[env.staging]` in `wrangler.toml`** (already on `main`; mirrors the top-level config but points at staging)

```toml
[env.staging]
name = "frontend-staging"

[env.staging.vars]
NEXT_PUBLIC_API_URL = "https://api.staging.saplinglearn.com"
BACKEND_URL = "https://api.staging.saplinglearn.com"
COOKIE_DOMAIN = ".staging.saplinglearn.com"

[env.staging.observability]
enabled = true
```

- [x] **Step 2: `cf:deploy:staging` script in `package.json`** (already on `main`, alongside the existing `cf:deploy`)

```json
"cf:deploy:staging": "opennextjs-cloudflare build && wrangler deploy --env staging"
```

- [ ] **Step 3 (remaining — operator): Deploy and verify**

Run: `cd frontend && npm run cf:deploy:staging`
Expected: Wrangler deploys a `frontend-staging` worker with no error; the temporary `*.workers.dev` URL loads the app.

> Step 4 (commit) no longer applies — the `wrangler.toml`/`package.json` changes are already on `main`.

---

## Phase 5 — DNS + end-to-end smoke test (operator runbook)

### Task 12: Wire DNS and smoke-test

- [ ] **Step 1:** In the Cloudflare zone, add a (proxied) record routing `staging.saplinglearn.com` to the `frontend-staging` worker (Workers route / custom domain).
- [ ] **Step 2:** Confirm `api.staging.saplinglearn.com` (Task 10) resolves and is proxied.
- [ ] **Step 3 (smoke test):** From a browser, visit `https://staging.saplinglearn.com`, log in via Google (staging client), upload a document, and confirm the knowledge graph renders. All three should work end-to-end against the staging Supabase.
- [ ] **Step 4:** Confirm the dirty fixtures are visible/handled where expected (e.g. the zero-question quiz #184 path).

---

## Phase 6 — Lock staging to admins (operator runbook + code)

### Task 13: `noindex` for staging

**Files:**
- Modify: `backend/config.py`, `backend/main.py`

- [ ] **Step 1: Recognize the staging env in `config.py`**

```python
IS_STAGING = APP_ENV == "staging"
```

(Place beside the existing `IS_LOCAL`. Note: `staging` is NOT in the `IS_LOCAL` set, so staging keeps prod's fail-closed config checks.)

- [ ] **Step 2: Emit the header in `main.py`** (add middleware near the app/CORS setup)

```python
from config import IS_STAGING

@app.middleware("http")
async def _noindex_on_staging(request, call_next):
    response = await call_next(request)
    if IS_STAGING:
        response.headers["X-Robots-Tag"] = "noindex, nofollow"
    return response
```

- [ ] **Step 3: Verify**

Run: `curl -sI https://api.staging.saplinglearn.com/ | grep -i x-robots-tag`
Expected: `x-robots-tag: noindex, nofollow`.

- [ ] **Step 4: Commit**

```bash
git add backend/config.py backend/main.py
git commit -m "feat: noindex header on staging (APP_ENV=staging)"
```

### Task 14: Cloudflare Access on both hostnames

- [ ] **Step 1:** Cloudflare Zero Trust → Access → Applications → add a self-hosted app for `staging.saplinglearn.com`. Policy: Allow, with an email allowlist (or org Google domain) of admins. Identity provider: Google.
- [ ] **Step 2:** Add a second Access application for `api.staging.saplinglearn.com` with the same allowlist.
- [ ] **Step 3:** Create an Access **service token** for the Worker→backend hop. Add a policy on the `api.staging…` app that allows that service token.
- [ ] **Step 4:** Store the service token's `CF-Access-Client-Id`/`CF-Access-Client-Secret` as staging Worker secrets and have the Worker attach them on its server-side fetch to the backend (the `/api/*` proxy). (If using OpenNext's default proxy, set them as forwarded headers; otherwise add a tiny middleware.)
- [ ] **Step 5 (verify):** In an incognito window with a non-allowlisted account, `https://staging.saplinglearn.com` shows the Access login wall and denies access. An allowlisted admin gets in, and the app's `/api/*` calls succeed (service token reaches the backend).

---

## Phase 7 — Trunk-based deploy wiring (operator runbook + docs)

### Task 15: Continuous staging + promote-to-prod

- [ ] **Step 1:** Railway: confirm the `staging` environment auto-deploys on every push to `main`; set the `production` environment to deploy from the `production` branch.
- [ ] **Step 2:** Cloudflare: configure Workers Builds (or CI) so `main` runs `cf:deploy:staging`, and the `production` branch runs `cf:deploy` (prod).
- [ ] **Step 3:** Create the `production` branch from the current prod commit: `git branch production <prod-commit> && git push -u origin production`.
- [ ] **Step 4: Document the promotion command in `README.md`** (Migrations / Deploy section):

```markdown
### Promote to prod
1. Verify the change on https://staging.saplinglearn.com (auto-deployed from `main`).
2. Apply migrations to prod: `SUPABASE_DB_URL=<prod-direct-url> python -m db.migrate`
3. Fast-forward prod: `git checkout production && git merge --ff-only main && git push`
4. `git checkout main`
```

- [ ] **Step 5: Commit the docs**

```bash
git add README.md
git commit -m "docs: staging→prod promotion workflow"
```

---

## Self-review notes

- **Spec coverage:** every spec component (Supabase project, Railway env, Worker env, OAuth client, DNS, seed+fixtures, migration runner, access control, git model) maps to a task above. The "prerequisite" #163 (dep pinning) is out of scope for this plan — track separately.
- **Baseline caveat:** Phase 0's runner applies migrations to *fresh* DBs. To bring it to the **existing prod** DB without re-running already-applied SQL, run `python -m db.migrate --baseline` once against prod first (records all current files as applied), then normal runs apply only new migrations. Call this out when wiring prod (Phase 7).
- **Dirty-fixture columns** now match `0001_baseline_schema.sql` on `main`; re-confirm against the live schema only if it has since changed (noted in Task 8).
