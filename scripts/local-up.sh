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

echo "▶ Starting local Supabase (no-op if already running)…"
supabase start || { echo "✗ supabase start failed"; exit 1; }

echo "▶ Applying pending migrations…"
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

echo "▶ Seeding demo data (idempotent)…"
( cd backend && venv/bin/python -m db.seed_staging ) || { echo "✗ seed failed"; exit 1; }

cat <<'NEXT'

✅ Local stack is up. Now run, in two terminals:
     cd backend  && python main.py     # :5000
     cd frontend && npm run dev         # :3000
   Then open http://localhost:3000 and sign in with Google
   (first local sign-in is auto-approved — no /pending wall).
NEXT
