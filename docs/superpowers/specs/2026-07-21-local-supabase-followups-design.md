# Local-Supabase follow-ups — design spec (#363, #362, #365)

- **Date:** 2026-07-21
- **Status:** Approved (design); implementation pending
- **Base branch:** `feat/local-supabase-dev` (PR #372, still OPEN — not yet on `main`)
- **Work branch:** `feat/local-followups` (worktree `../wt-local-followups`)
- **PR target:** `feat/local-supabase-dev` (stacks on #372)
- **Issues:** #363 (rich local seed) → #362 (integration suite) → #365 (frontend middleware→proxy)
- **Order:** #363 first (unblocks #362); #365 independent/low-priority.

## Context

PR #372 added a local Supabase dev stack (rootless Podman + Supabase CLI) with
Google-only local auth. The stack is up and healthy locally (API at
`http://127.0.0.1:54321`). Follow-up work:

1. **#363** — a broad, re-runnable local dataset for realistic E2E/manual testing.
2. **#362** — an opt-in integration test suite that exercises the *real* local stack
   (real Postgres, real encryption round-trips, migrated schema) — today the whole
   backend suite is hermetic (`tests/conftest.py` mocks Supabase + bypasses auth).
3. **#365** — migrate the deprecated Next.js `middleware` file convention to `proxy`.

All backend data access goes through `db/connection.py::table()`. Encryption via
`services/encryption.py`. Model to follow for the seed: `backend/db/seed_staging.py`.

## Key schema discoveries (migration-verified — these correct naive assumptions)

1. **Admin is a role join, not a column.** `roles` (slugs seeded by `0002`: `admin`,
   `moderator`, `verified`, `vip`, `early-adopter`) have **random UUID ids**. To make a
   user admin: look up the admin role id by slug, then insert into
   `user_roles (user_id, role_id)` (PK `(user_id, role_id)`). `require_admin` /
   `require_role` check this join (`services/auth_guard.py`).
2. **`users.email` IS encrypted** — the app encrypts it (`routes/auth.py`), even though
   CLAUDE.md's list omits it. Wrap with `encrypt_if_present`.
3. **Study-room tables are `rooms` / `room_members` / `room_messages`** (NOT
   `study_rooms`). `room_messages.text` is `encrypt_if_present`-encrypted;
   `room_messages.id` is a UUID PK (use fixed UUID literals for deterministic seeding);
   `user_name` is NOT NULL.
   - ⚠️ **Schema drift:** `routes/social.py` SELECTs `topic, course, owner_id, updated_at,
     is_public` from `rooms`, but **no migration adds those columns**. So the
     `/api/social` room-list route may 400 against the migrated schema regardless of
     seed. We seed `rooms` at the DB level (for round-trip coverage) but the route-level
     E2E in #362 targets routes that work against the migrated schema (`/api/auth/me`,
     gradebook, tutor) — NOT social. (Fixing/filing the drift is out of scope here.)
4. **`documents.concept_notes` is `encrypt_json([{name, description}, …])`** (a JSON
   list), read with `decrypt_json` — not a plain encrypted string. (seed_staging wrote a
   plain string; `decrypt_json` has a plaintext-JSON fallback so it still loads, but the
   list form is correct.) `documents.summary` and `documents.extracted_text` are
   `encrypt_if_present`.
5. **`flashcards.front`/`back`/`topic` are PLAINTEXT** (not encrypted); grouping is by
   `topic` (+ optional `offering_id`); there is no deck table. **`quiz_attempts`** is the
   "quiz history" table (not `quiz_sessions`); a completed attempt has
   `score`/`total`/`answers_json`/`completed_at` set; `difficulty ∈ {easy,medium,hard}`.
6. **`get_mastery_tier(score)`** (`config.py`): `≥0.75 mastered`, `≥0.45 learning`,
   `≥0.10 struggling`, else `unexplored` (DB also allows `subject_root`, not produced here).

### Encrypted-column map (what the seed must wrap)

- **`encrypt_if_present` (write) / `decrypt_if_present` (read):** `users.email`;
  `user_profiles.{name,first_name,last_name,bio,location}`; `messages.content`;
  `room_messages.text`; `documents.{summary,extracted_text}`;
  `notes.{title,body,last_summary}`; `assignments.notes`.
- **`encrypt_if_present` (write) / `decrypt_numeric` (read):**
  `assignments.{points_possible,points_earned}` (numeric semantics).
- **`encrypt_json` (write) / `decrypt_json` (read):** `documents.concept_notes` (list),
  `sessions.summary_json` (object).
- **PLAINTEXT:** `user_profiles.{username,website,year,majors,minors,learning_style}`,
  `flashcards.{front,back,topic}`, `quiz_attempts.*`, `notes.tags`, all `curve_*` class
  stats, catalog tables, `roles`/`user_roles`.

## Issue #363 — `backend/db/seed_local_rich.py`

A **local-only**, idempotent, self-contained rich seed in a **new** file. The staging
seed (`seed_staging.py`, explicitly "STAGING ONLY") keeps its dataset and behavior
unchanged; it is only refactored mechanically to import the shared helpers below.

### Shared idempotency helpers

Extract the idempotency/summary helpers currently inline in `seed_staging.py`
(`_record`, `_upsert`, `_insert_if_absent`, `_exists_by`, `_counts`, summary printing)
into a new **`backend/db/seed_helpers.py`**, imported by both `seed_local_rich.py` and
`seed_staging.py`. The `seed_staging.py` edit is mechanical (delete the local defs, import
them). *(Fallback if we decide not to touch the staging seed: copy the ~40-line helper
block into `seed_local_rich.py` instead — decided against; extraction chosen.)*

### Local-destination guard (copied from `seed_local_catalog.py`)

```python
url = (dotenv SUPABASE_URL)   # from backend/.env
if "127.0.0.1" not in url and "localhost" not in url:
    sys.exit("REFUSING: destination is not local — seed_local_rich only writes to local.")
```
`ENCRYPTION_KEY` must be present in the local env (encryption module fails to import
without it).

### Dataset (all ids namespaced `rich-*`; references only canonical terms)

- **School:** `rich-school-demo` (upsert on `slug`). Self-contained — does not depend on
  `seed_staging` having run.
- **Terms:** references the canonical `fall-2025`, `spring-2026`, `summer-2026` (seeded by
  `0019`) — never rewrites them.
- **Users (distinct states):**
  | id | state |
  |----|-------|
  | `rich-user-active` | regular, onboarded, approved — the fully-populated user |
  | `rich-user-second` | populated, approved — second member for shared room / multi-user |
  | `rich-user-new` | `onboarding_completed=false`, approved, **no** enrollments/data |
  | `rich-user-pending` | `is_approved=false` (approval wall) |
  | `rich-user-admin` | approved + `user_roles`→`admin` (role id looked up by slug) |
  Each real user gets a `user_profiles` row (encrypted name fields, plaintext
  majors/minors/etc.). `users.email` encrypted.
- **Courses (6, across 6 departments):** CS101, MATH210, BIO110, ENG150, HIST200,
  CHEM121 (`school_id=rich-school-demo`; upsert on `school_id,course_code`).
- **Offerings (~8, across 3 terms):** CS101 offered in **both** fall-2025 and spring-2026
  (cumulative cross-term graph on the abstract course); one summer-2026 offering; the rest
  spread across fall/spring. `section=""` for a stable UNIQUE conflict target
  (`course_id,term_id,section`). Do **not** set `course_code` (dropped in `0028`).
- **Enrollments:** `rich-user-active` in ~5 offerings incl. multi-term CS101;
  `rich-user-second` in ~2–3 (one **shared** offering with active user). Mix of
  `curve_mode` `raw` and `curved` (curved rows set `curve_avg_target`/`curve_sd_delta`).
  Upsert on `user_id,offering_id`.
- **Knowledge graph (abstract `course_id`):** per course, nodes across all four mastery
  tiers (mastered/learning/struggling/unexplored); edges covering all four
  `relationship_type`s (`related`/`prerequisite`/`builds_on`/`part_of`); append-only
  `node_mastery_events`. `mastery_tier` via `get_mastery_tier`. Upsert nodes on
  `user_id,course_id,concept_name`; edges on
  `user_id,source_node_id,target_node_id,relationship_type`; events insert-by-id.
- **Gradebook:** multiple `gradebook_categories` per enrollment (Homework/Exams/Labs/
  Projects, some `drop_lowest`); `assignments` graded (points set) **and** ungraded
  (`points_earned=None`), with both **past** and **upcoming** `due_date`s, spanning
  `assignment_type` and `source` enums. Points via `encrypt_if_present` (read with
  `decrypt_numeric`). Insert-by-id.
- **Study data:**
  - `rooms` + `room_members` (active + second user) + `room_messages` (a few, from both
    users; `text` encrypted; `user_name` set; deterministic UUID ids).
  - `notes` with `tags` (encrypted title/body).
  - `documents` (syllabus + lecture_notes): encrypted `summary`, `encrypt_json`
    `concept_notes` (list), encrypted `extracted_text`.
  - `flashcards` (plaintext, topic-grouped, on offerings).
  - `quiz_attempts` (completed, scored, tied to concept nodes).
  - `sessions` + `messages`: a tutor session (`mode` enum) with messages (encrypted
    `content`) and `encrypt_json` `summary_json` — exercises the tutor encryption path.

### Idempotency & summary

Same pattern as `seed_staging`: upsert on natural UNIQUE keys, insert-if-absent by
deterministic id for tables without one. A per-table `created/skipped` summary printed at
the end; a second run reports all-skipped (no-op).

### Acceptance

- `python -m db.seed_local_rich` runs idempotently (second run = all skipped, 0 errors).
- Refuses to run against a non-local `SUPABASE_URL`.
- Documented in `docs/local-supabase.md` (new subsection next to the catalog seed).
- Wired as an **optional** step in `scripts/local-db-reset.sh` (behind a flag/comment so
  the default reset still uses the minimal `seed_staging` demo, and rich is opt-in).
- `ruff check .` clean.

## Issue #362 — opt-in integration suite

### Wiring

- Register an `integration` marker in `tests/conftest.py::pytest_configure` (mirrors the
  existing `e2e_staging` marker).
- **Extend the two autouse hermetic fixtures** (`_hermetic_supabase_client`,
  `_bypass_session_auth`) to also bypass when the test carries the `integration` marker
  (today they bypass only `e2e_staging`). This lets integration tests hit the real local
  client and the real auth guard.
- New `backend/tests/integration/` package with its own `conftest.py`.

### Gating & fixture

- A session-scoped autouse fixture (scoped to `tests/integration/`) that **skips the whole
  suite** unless `RUN_INTEGRATION=1` **and** `SUPABASE_URL` is local (`127.0.0.1`/
  `localhost`) — belt-and-suspenders so it never touches a remote project.
- On first use it ensures the #363 rich seed is present by calling
  `db.seed_local_rich.main()` (idempotent, **additive** — no destructive reset, per the
  chosen verify mode). Reset remains a manual/opt-in operation (`scripts/local-db-reset.sh`).
- Default `pytest` (no `RUN_INTEGRATION`) collects them but skips — the hermetic suite is
  unaffected.

### Tests (at least)

1. **DB round-trip** through `db.connection.table()`: write a namespaced throwaway row →
   read it back → delete it. Proves the real PostgREST path.
2. **Encryption round-trip:** write an encrypted value (e.g. a note body via
   `encrypt_if_present`, and an assignment's points via `encrypt_if_present`) → read raw
   from the DB → `decrypt_if_present` / `decrypt_numeric` → assert it matches the
   plaintext. Proves encryption works against real storage with the local key.
3. **Full route E2E:** mint a real HMAC session token (as the `e2e_staging` test does) and
   call `/api/auth/me` (+ a gradebook or tutor read) for a seeded user via FastAPI
   `TestClient` against the real local DB — asserting decrypted values flow through the
   route. Exercises real auth + real DB + real decryption end-to-end.

### Acceptance

- `RUN_INTEGRATION=1 pytest -m integration` (with the local stack up) passes.
- Plain `pytest` still passes and skips the integration suite.
- Documented in `docs/local-supabase.md` (how to run).
- `ruff check .` clean.
- **Stretch:** `.github/workflows/integration.yml` that boots the Supabase CLI and runs
  `-m integration`. Written but **flagged as unverifiable in this environment** (can't run
  GitHub Actions here); kept minimal and clearly marked.

## Issue #365 — `middleware.ts` → `proxy.ts` (frontend-only)

Per the Next.js 16 contract (`proxy` introduced in `v16.0.0`; runs on the Node.js
runtime — fine, our function does a server-side `fetch` to the backend):

- Rename `frontend/src/middleware.ts` → `frontend/src/proxy.ts`; rename the exported
  function `middleware` → `proxy`. Keep `config`/`matcher`, the `NextRequest`/
  `NextResponse` imports, and all gating logic unchanged.
- Rename `frontend/src/middleware.test.ts` → `frontend/src/proxy.test.ts`; update the
  import to `{ proxy, config } from './proxy'` and the calls `middleware(...)` → `proxy(...)`.
  Keep the `#189 /profile` gating assertions.
- Confirm `frontend/package.json` is on Next 16; grep the frontend for any other
  `middleware` references (docs/config) and update as needed.

### Acceptance

- Session gating behavior unchanged; `proxy.test.ts` passes (`vitest`).
- `tsc --noEmit` clean.
- Deprecation warning gone (the rename is the fix).

## Verification plan (stack is up; additive / non-destructive)

- **#363:** `python -m db.seed_local_rich` run **twice** → 2nd run all-skipped; spot-check a
  few seeded rows via `table()`; `ruff check .`.
- **#362:** `RUN_INTEGRATION=1 pytest -m integration` passes; plain `pytest` still skips
  them and the full hermetic suite still passes; `ruff check .`.
- **#365:** frontend `tsc --noEmit` + `vitest run` on the renamed test.

## Commits (one per issue on `feat/local-followups`)

1. `feat(seed): rich local dataset for E2E (#363)`
2. `test: opt-in integration suite against local stack (#362)`
3. `chore(frontend): migrate middleware→proxy convention (#365)`

## Out of scope / risks

- `rooms` schema drift (social.py expects columns not in migrations) — noted, not fixed
  here; the E2E deliberately avoids the social route.
- The CI-workflow stretch for #362 cannot be executed in this environment; it is delivered
  as best-effort and flagged.
- Frontend dep install in the worktree (`node_modules` is gitignored/absent) is handled
  when #365 is implemented.
