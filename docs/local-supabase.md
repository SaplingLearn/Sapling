# Local Supabase (Podman)

Run the whole app — frontend → backend → database — against a **local** Supabase
stack in containers, instead of testing against the live staging database.

The stack (Postgres, PostgREST, Storage, Auth, Studio) runs under **rootless
Podman** via the Supabase CLI. The backend and frontend run on the host so you
keep hot-reload.

## Prerequisites (one-time, host)

```bash
# Podman + rootless API socket
sudo pacman -S --needed podman
systemctl --user enable --now podman.socket

# Point the Supabase CLI at Podman's Docker-compatible socket (fish; -U = persistent)
set -Ux DOCKER_HOST "unix:///run/user/"(id -u)"/podman/podman.sock"

# Supabase CLI (AUR)
paru -S supabase-bin      # or: yay -S supabase-bin
```

Verify: `supabase --version && podman ps`.

The dev scripts (`scripts/local-up.sh`, `scripts/local-db-reset.sh`) run
`db.migrate` / `db.seed_staging` through `backend/venv/bin/python`, so create the
backend venv once (from the repo root) before the first run — otherwise the
scripts fail fast with a "backend/venv not found" message:

```bash
python -m venv backend/venv && backend/venv/bin/pip install -r backend/requirements.txt
```

## Endpoints

| Service        | URL                                             |
|----------------|-------------------------------------------------|
| API (PostgREST)| `http://127.0.0.1:54321`                        |
| Postgres       | `postgresql://postgres:postgres@127.0.0.1:54322/postgres` |
| Studio (GUI)   | `http://127.0.0.1:54323`                        |
| Mailpit        | `http://127.0.0.1:54324`                        |

Local API keys are the shared Supabase demo keys (fine — local only). `analytics`
and `edge_runtime` are disabled in `supabase/config.toml` (unused; analytics also
trips health checks under rootless Podman). `auto_expose_new_tables = true` is set
so migration-created tables are reachable by the Data API roles, matching hosted
Supabase — **do not turn it off** or the backend gets 403s from PostgREST.

## Daily run loop

```bash
# 1. Start the database stack (from repo root)
supabase start                 # `supabase stop` to shut down; data persists

# 2. Backend (from backend/, reads backend/.env → local Supabase)
python main.py                 # uvicorn on :5000

# 3. Frontend (from frontend/)
npm run dev                    # Next on :3000

# 4. Sign in with Google at http://localhost:3000
#    (first local sign-in is auto-approved — see "Sign-in" below)
```

`supabase start`/`stop` keep the database between runs. To wipe and re-seed:

```bash
scripts/local-db-reset.sh      # db reset → migrate → reload PostgREST → seed
```

## Sign-in: Google OAuth (local)

Local sign-in uses the **real Google OAuth flow** — same as prod. Dev-login was
removed, so Google OAuth is the **only** local sign-in path: filling
`GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET` in `backend/.env` is **required** to
sign in. They're optional only for bringing the stack *up* — if you leave the
`.env.local.example` placeholders in place, the stack still starts but clicking
"sign in with Google" fails silently. The staging OAuth creds work here; point the
redirect at `http://localhost:5000/api/auth/google/callback`. **One-time setup:**
add that URI (and `http://localhost:5000/api/calendar/callback` for calendar) to
the OAuth client's authorized redirect URIs in the Google Cloud console.

Two local-only conveniences make it "just work", both strictly `IS_LOCAL`-gated so
staging/prod are unaffected:

- `ALLOWED_EMAIL_DOMAINS=` is empty locally, so **any** Google account can sign in
  (prod restricts to the configured domains).
- `routes/auth.py` **auto-approves new users when `IS_LOCAL`**, so a first sign-in
  skips the `/pending` approval wall (prod keeps the real approval gate).

The backend `SESSION_SECRET` **must equal** `frontend/.env.local`'s. Signing in with
Google creates *your* user (`user_<google-id>`) — a fresh account that goes through
onboarding — not the seeded `seed-user-demo`; the seed is reference/sample data.

## Env files

- `backend/.env` — the default env, so `python main.py`, `db.migrate`, and
  `db.seed_staging` all target **local**. `APP_ENV=local`, local Supabase URL/keys,
  a fresh local `ENCRYPTION_KEY` (not staging/prod's), `SESSION_SECRET`, and a
  `GEMINI_API_KEY` (reused from `.env.staging` for convenience — swap if you like).
  Staging/prod stay behind `dotenv -f .env.staging|.env.production run -- …`.
- `frontend/.env.local` — empty `NEXT_PUBLIC_API_URL` (same-origin — a cross-origin
  value drops the session cookie), `BACKEND_URL=http://localhost:5000`, matching
  `SESSION_SECRET`, and local `NEXT_PUBLIC_SUPABASE_URL`/`ANON_KEY` for `/social`.

## Schema: migrations replay from empty

Local schema comes from replaying `backend/db/migrations/*.sql` with
`python -m db.migrate` against the local Postgres. The `0001` baseline had been
consolidated (it folds in later columns/tables), so a few later migrations
collided when replayed onto an empty DB. Those were repaired with `IF NOT EXISTS`
/ retargeting guards — all **no-ops on already-migrated databases** (staging/prod):

- `0021_gradebook.sql` — guard the `curve_*` re-add on `enrollments`.
- `0021_gradebook_curve.sql` — retarget `user_courses` → `enrollments` (renamed in 0020).
- `0027_gradescope.sql` — `IF NOT EXISTS` on `gradescope_credentials`; drop the old
  `gradescope_course_links` shape before recreating it enrollment-keyed.

The full chain now applies cleanly from empty (33 migrations).

## Real course catalog (optional)

The demo seed is a single user with 3 courses. To load a *plethora* of real data,
pull the unencrypted course catalog from staging (read-only) into local:

```bash
python -m db.seed_local_catalog     # ~8.2k courses + offerings from .env.staging
```

Only `courses`/`course_offerings` are copied (idempotent, upsert on `id`). User-scoped
encrypted rows are **not** — they use the remote project's `ENCRYPTION_KEY` and would be
undecryptable locally. Requires the staging REST API (reachable over HTTPS) + `.env.staging`
creds; the direct DB is IPv6-only and unreachable from most machines. Surfaces in the app's
course search (`/api/onboarding/courses?q=`). Source `SOURCE_ENV=.env.production` to pull from prod instead.

## Rich local dataset (optional, #363)

The default seed is a single demo user. For a broad, realistic dataset — multiple
users in distinct states (regular, brand-new, pending-approval, admin), 6 courses
across 3 terms, knowledge graphs at varied mastery, a full gradebook, study rooms,
notes, documents, flashcards, quiz history, and tutor sessions — run:

    python -m db.seed_local_rich          # idempotent; re-runnable; local-only (guarded)

Or fold it into a full reset:

    SEED_RICH=1 scripts/local-db-reset.sh # reset → migrate → seed_staging → seed_local_rich

All ids are namespaced `rich-*`; encrypted columns use the local `ENCRYPTION_KEY`.
The script refuses to run against a non-local `SUPABASE_URL`.

## Integration tests (opt-in, #362)

With the local stack up and `backend/.env` active, from `backend/`:

    RUN_INTEGRATION=1 python -m pytest -m integration -q

These bypass the hermetic mocks and hit the real local Supabase (real Postgres,
encryption round-trips, migrated schema). Skipped by default. The suite seeds the
rich dataset (idempotent) on first run and never resets your DB.

## Troubleshooting

- **`supabase start` hangs on health checks** — usually the analytics/vector
  containers under Podman. They're disabled in config; if you re-enable them, start
  with `supabase start -x analytics,vector,logflare`.
- **Backend 403 "permission denied for table …" from PostgREST** — the tables
  aren't granted to the API roles. Ensure `auto_expose_new_tables = true` in
  `supabase/config.toml`, then `scripts/local-db-reset.sh`.
- **404 "Could not find the table … in the schema cache"** — PostgREST cache is
  stale after a migration. `podman exec supabase_db_sapling psql -U postgres -d postgres
  -c "NOTIFY pgrst, 'reload schema';"` (the reset script does this for you).
- **Postgres version** — local is PG17, staging/prod is PG15. The migrations are
  version-agnostic and verified to replay on 17; keep new migrations portable.
- **Ports 54321–54327 already in use** — another project's `supabase start` is
  running; `supabase stop` in that project (or `podman ps` to find it).
```
