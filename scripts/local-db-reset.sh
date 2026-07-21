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

echo "▶ Recreating local database (empty)…"
supabase db reset --no-seed || { echo "✗ supabase db reset failed"; exit 1; }

echo "▶ Applying migrations…"
( cd backend && SUPABASE_DB_URL="$LOCAL_DB_URL" venv/bin/python -m db.migrate ) \
  || { echo "✗ migrations failed"; exit 1; }

echo "▶ Reloading PostgREST schema cache…"
podman exec "$DB_CONTAINER" psql -U postgres -d postgres \
  -c "NOTIFY pgrst, 'reload schema';" >/dev/null 2>&1 || true

echo "▶ Waiting for PostgREST to expose the schema…"
KEY="$(grep -E '^SUPABASE_SERVICE_KEY=' backend/.env | cut -d= -f2-)"
for _ in $(seq 1 30); do
  code="$(curl -s -o /dev/null -w '%{http_code}' \
    "http://127.0.0.1:54321/rest/v1/terms?select=id&limit=1" \
    -H "apikey: $KEY" -H "Authorization: Bearer $KEY")"
  [ "$code" = "200" ] && { echo "  ready"; break; }
  sleep 1
done

echo "▶ Seeding demo data…"
( cd backend && venv/bin/python -m db.seed_staging ) || { echo "✗ seed failed"; exit 1; }

echo
echo "✅ Local database reset + seeded."
echo "   Start the app (python main.py + npm run dev), then sign in with Google at http://localhost:3000"
