# Admin account tools — seed by major, wipe, copy between environments

Date: 2026-11-08 · Branch `feat/admin-account-tools`

## Why

Testing Sapling means signing in to an account that already looks like a real
student's semester. Today that only exists locally (`db/seed_local_rich.py`,
refuses non-local). Admins need, on **every environment (local, staging,
prod)**, from the admin dashboard, for a chosen existing account:

1. **Seed** — fill the account with a realistic semester for a chosen major
   (4 courses each). Six majors: Computer Science, Business, Biology,
   Psychology, Health Science (BU's pre-nursing/health track — BU has no
   nursing school), Mechanical Engineering.
2. **Wipe** — remove the account's academic/study data, leaving the account.
3. **Copy between environments** — overwrite the account's data on the other
   environment (staging ↔ prod) with this environment's copy, in either
   direction.

## Decisions (user)

- Admin-triggered from the admin dashboard, on a selected existing account.
- Admin chooses the major; data aligns with it; 4 courses per major.
- Re-seeding replaces (wipe-then-seed), never stacks.
- Works everywhere, including prod.

## Decisions (builder's calls — flagged for review)

- **Courses are real catalog courses**, resolved by `course_code` (BU format
  `"CAS CS 111"`), all verified present in the staging catalog 2026-11-08. If a
  code is missing (a bare local stack without the pulled catalog), the seeder
  creates that one `courses` row under the school of any existing course (or a
  `sapling-sample` school) so seeding never fails for lack of catalog.
- **Offerings**: `services/academics.resolve_offering(course_id, current term)`
  — all 4 courses in the current term.
- **No LLM calls.** All content is authored statically in per-major packs
  (`backend/services/account_seed/packs/*.py`). Seeding is deterministic and free.
- **Documents** are seeded with `index_status='pending'` and
  `shareability='personal_notes'` (confidence 1.0) → the sweeper indexes them
  PRIVATELY in real-mode envs, so the tutor gets real RAG over the seeded
  material and no seeded text can ever enter a class pool. No storage file.
- **Wipe scope** (the "account data" set): enrollments (→ gradebook categories,
  assignments, gradescope links, topic checklists cascade), documents (chunks
  withdrawn first via `chunk_visibility.withdraw_document_chunks`, plus any
  private `course_chunks` still carrying `uploader_id = user`), notes, flashcards,
  sessions (+messages), study guides, quiz attempts (+responses), quiz context,
  graph nodes (+edges, mastery events, note_concepts), xp_events,
  user_achievements; counters `total_xp/level/streak_count/longest_streak` reset.
  **Kept**: the account itself, profile, settings, roles, OAuth tokens,
  gradescope credentials, cosmetics, social (rooms, friendships — they involve
  other people), feedback/issue reports, telemetry (`events`, `llm_usage`),
  admin audit log. Class-wide aggregates (`offering_concept_stats`) untouched.
- **Seed also** sets `user_profiles.majors = [<major label>]` and
  `users.onboarding_completed = true`, and gives XP/streak/level so gamified
  surfaces render.
- **Not atomic** (PostgREST has no transactions). Every operation starts with a
  wipe, so re-running after a mid-way failure converges. A per-user in-process
  lock rejects a concurrent second operation on the same account (409).
- **Copy target must already exist** (the person signed in once on that env).
  Copy never creates accounts, approvals, or roles on the other side. 404 with
  "sign in on <env> first" otherwise.
- **Copy is an overwrite**, not a merge: target is wiped, then the bundle is
  imported. Bundle = the wipe-scope data + profile fields (name/bio/etc.,
  majors/minors/year) + settings (minus cosmetic ids) + the counters. Achievements
  move by `slug`. OAuth tokens, roles, social, telemetry never move.
- **Copy transport**: server-to-server. Each env has
  `ACCOUNT_SYNC_PEER_URL` (other env's backend base URL),
  `ACCOUNT_SYNC_PEER_TOKEN` (what we send), `ACCOUNT_SYNC_INBOUND_TOKEN` (what we
  accept). Peer endpoints `/api/internal/account-sync/{export,import}` follow the
  `routes/internal_metrics.py` token pattern (unset inbound token → 404,
  constant-time compare). Push = we export locally and POST to peer's import;
  pull = we GET peer's export and import locally. The bundle is plaintext JSON
  in transit only (HTTPS), decrypted on the source, re-encrypted on the target.
  Self-copy refused (peer reports the same `APP_ENV` → 409).
- **Catalog remap on import**: offerings by `(course_code, term_id, section)`
  (created via `resolve_offering` if absent), graph `course_id` by
  `course_code`, achievements by `slug`. Row ids are preserved (user-scoped,
  target wiped first). Documents import as `index_status='pending'` (no chunks
  copied — the target re-indexes with its own key and visibility rules).
- **Guardrails**: `require_admin`; body `confirm` must equal the action word
  (`"SEED"`, `"WIPE"`, `"COPY"`); the UI additionally makes the admin type the
  target account's email; every action writes `log_admin_action`
  (`account.seed` / `account.wipe` / `account.copy_push` / `account.copy_pull`,
  and `account.import` / `account.export` on the receiving side with
  `actor_id` = null→ logged as event only) and an `events_service` audit event.
  No feature flag: admin-only and inert without explicit config is the gate.
- **Env badge**: the admin account-tools dialog shows which environment you are
  on (from a new `GET /api/admin/accounts/meta`), since the same buttons now
  exist on prod.

## API (contract between backend and frontend)

All under `/api/admin/accounts`, `require_admin` first.

- `GET /meta` →
  `{"env": "staging", "majors": [{"key": "cs", "label": "Computer Science",
  "courses": [{"code": "CAS CS 111", "name": "..."}]}],
  "sync": {"configured": true, "peer_env": "production"}}`
  (`peer_env` is null when not configured or peer unreachable; probing the peer
  is a cheap `GET {peer}/api/internal/account-sync/ping` returning
  `{"env": APP_ENV}` under the token.)
- `POST /{user_id}/seed` body `{"major": "cs", "confirm": "SEED"}` →
  `{"major": "cs", "wiped": {<table>: n}, "created": {<table>: n}}`
- `POST /{user_id}/wipe` body `{"confirm": "WIPE"}` → `{"wiped": {<table>: n}}`
- `POST /{user_id}/copy` body `{"direction": "push"|"pull", "confirm": "COPY"}`
  → `{"direction": "push", "peer_env": "production", "counts": {<table>: n}}`

Errors: 400 bad confirm/major, 404 unknown user (local or peer), 409 operation
already running for that user / self-copy, 502 peer error, 503 sync not
configured.

Internal (token, never `auth_guard`, `include_in_schema=False`) under
`/api/internal/account-sync`: `GET /ping`, `GET /export?user_id=`,
`POST /import` (body = bundle).

## Components

- `services/account_seed/schema.py` — `MajorPack` pydantic content model.
- `services/account_seed/packs/{cs,business,biology,psychology,health,mech_eng}.py`
  — one `PACK: MajorPack` each; `packs/__init__.py` registry `PACKS`.
- `services/account_seed/seeder.py` — `seed_account(user_id, major) -> dict`.
- `services/account_wipe.py` — `wipe_account_data(user_id) -> dict[str,int]`.
- `services/account_bundle.py` — `export_account(user_id) -> dict`,
  `import_account(user_id, bundle) -> dict[str,int]`, `BUNDLE_VERSION = 1`.
- `services/account_sync_client.py` — httpx peer client (third-party-style REST
  call to our own other deploy, not Supabase access).
- `services/account_ops_lock.py` — per-user non-blocking lock.
- `routes/admin_accounts.py`, `routes/internal_account_sync.py`, mounts in
  `main.py`, config getters in `config.py`.
- Frontend: `components/screens/admin/AccountToolsDialog.tsx` opened from a new
  per-row "Account tools" button in `UsersTab`; api helpers in `lib/api.ts`;
  testids `admin-account-*` registered in `docs/frontend-testids.md`.

## Content per major (each pack)

4 courses, each with: nickname + color; 8 concepts (graph nodes) with a mastery
spread over all four tiers plus ~7 edges and a few mastery events; 2 gradebook
categories and 6 assignments (mix of graded-past and upcoming, dates as day
offsets from the term start); 2 notes; 2 documents (syllabus + lecture notes:
summary, concept notes, ~150–300 words extracted text); 6 flashcards; 1 cached
study guide for the course's midterm; 2 completed quiz attempts (3–4 questions
each, on named concepts); 1 tutor session with 4–6 messages. Account level:
XP events, streak, level.

## Non-goals

Creating accounts; copying social/rooms/friendships; copying telemetry or
OAuth; merging data; seeding non-BU catalogs; background/async execution.
