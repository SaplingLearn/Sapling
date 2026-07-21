#!/usr/bin/env bash
#
# Reset the LOCAL Supabase database to a clean, fully-seeded state.
#
#   scripts/local-db-reset.sh
#
# Recreates the database, replays every migration with db.migrate, nudges
# PostgREST to reload its schema cache, waits until the new tables are exposed,
# then loads the demo dataset. Safe to run any time you want a clean slate.
#
# Requires: the local Supabase stack running (`supabase start`) and the backend
# venv at backend/venv. Targets local ONLY — never staging/prod.
set -uo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

# Point the Supabase CLI / podman at the rootless socket (matches the DOCKER_HOST
# universal var); harmless if it's already set.
export DOCKER_HOST="${DOCKER_HOST:-unix:///run/user/$(id -u)/podman/podman.sock}"

LOCAL_DB_URL="postgresql://postgres:postgres@127.0.0.1:54322/postgres"
DB_CONTAINER="supabase_db_sapling"

# Shared migrate → ensure buckets → reload PostgREST → seed sequence (#10).
source "$REPO_ROOT/scripts/lib/local-common.sh"

echo "▶ Recreating local database (empty)…"
supabase db reset --no-seed || { echo "✗ supabase db reset failed"; exit 1; }

migrate_reload_seed

echo
echo "✅ Local database reset + seeded."
echo "   Start the app (python main.py + npm run dev), then sign in with Google at http://localhost:3000"
