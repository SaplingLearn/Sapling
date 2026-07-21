#!/usr/bin/env bash
#
# Bring the LOCAL Sapling stack up: start Supabase, apply migrations, seed.
#
#   scripts/local-up.sh
#
# Idempotent — safe to run any time. Migrations skip what's applied, the seed
# skips rows that exist. For a destructive clean slate use scripts/local-db-reset.sh.
#
# First-time setup on a new machine:
#   cp backend/.env.local.example backend/.env       # then fill in GEMINI_API_KEY
#   cp frontend/.env.local.example frontend/.env.local
#   set -Ux DOCKER_HOST "unix:///run/user/"(id -u)"/podman/podman.sock"   # fish
set -uo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"
export DOCKER_HOST="${DOCKER_HOST:-unix:///run/user/$(id -u)/podman/podman.sock}"

LOCAL_DB_URL="postgresql://postgres:postgres@127.0.0.1:54322/postgres"
DB_CONTAINER="supabase_db_sapling"

# Shared migrate → ensure buckets → reload PostgREST → seed sequence (#10).
source "$REPO_ROOT/scripts/lib/local-common.sh"

echo "▶ Starting local Supabase (no-op if already running)…"
supabase start || { echo "✗ supabase start failed"; exit 1; }

migrate_reload_seed

cat <<'NEXT'

✅ Local stack is up. Now run, in two terminals:
     cd backend  && python main.py     # :5000
     cd frontend && npm run dev         # :3000
   Then open http://localhost:3000 and sign in with Google
   (first local sign-in is auto-approved — no /pending wall).
NEXT
