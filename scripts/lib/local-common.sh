# Shared helpers for the LOCAL Sapling dev scripts.
#
# Sourced (never executed) by scripts/local-up.sh and scripts/local-db-reset.sh
# so the identical "migrate → ensure buckets → reload PostgREST → seed" sequence
# lives in exactly one place (#10). LOCAL ONLY — never touches staging/prod.
#
# The caller is expected to have already:
#   • set -uo pipefail
#   • cd'd to the repo root
#   • exported DOCKER_HOST (rootless podman socket)
#   • defined LOCAL_DB_URL and DB_CONTAINER
#
# No shebang / +x needed — this file is meant to be `source`d.

# Ensure the Supabase Storage buckets the app expects exist locally, plus a
# blunt LOCAL-ONLY RLS policy so anon-key frontend uploads work (#2).
#
# Without this, only `avatars` gets created (by migration 0011), so cosmetic-asset
# uploads (Admin.tsx, direct anon-key upload) and issue-screenshot uploads fail on
# a fresh local stack. issues-media-files is uploaded via the backend service role
# (which bypasses Storage RLS), so it only needs the bucket to exist; cosmetic-assets
# is uploaded straight from the browser with the anon key, so storage.objects RLS
# applies and it also needs a permissive policy.
ensure_storage_buckets() {
  local sql
  sql="$(cat <<'SQL'
-- Buckets the app expects. `avatars` mirrors migration 0011's column list;
-- the other two are otherwise never created locally. NULL size/mime keeps
-- local uploads frictionless. ON CONFLICT never clobbers a tuned bucket.
INSERT INTO storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
VALUES
  ('avatars',            'avatars',            true,  5242880, ARRAY['image/jpeg', 'image/png', 'image/webp', 'image/gif']),
  ('cosmetic-assets',    'cosmetic-assets',    true,  NULL,    NULL),
  ('issues-media-files', 'issues-media-files', false, NULL,    NULL)
ON CONFLICT (id) DO NOTHING;

-- cosmetic-assets is uploaded DIRECTLY from the frontend with the anon key
-- (frontend Admin.tsx), so storage.objects RLS applies. This blunt permissive
-- policy is LOCAL-ONLY — these scripts never run against staging/prod.
-- issues-media-files goes via the backend service role (bypasses RLS) but is
-- harmless to include. DROP-then-CREATE makes re-running idempotent.
DROP POLICY IF EXISTS "local dev storage open" ON storage.objects;
CREATE POLICY "local dev storage open"
  ON storage.objects
  FOR ALL
  TO anon, authenticated
  USING (bucket_id IN ('cosmetic-assets', 'issues-media-files'))
  WITH CHECK (bucket_id IN ('cosmetic-assets', 'issues-media-files'));
SQL
)"
  if podman exec "$DB_CONTAINER" psql -U postgres -d postgres \
       -v ON_ERROR_STOP=1 -c "$sql" >/dev/null 2>&1; then
    echo "  ensured storage buckets"
  else
    echo "  ⚠ storage bucket setup hit an error (continuing)"
  fi
}

# Apply pending migrations, ensure local Storage buckets, nudge PostgREST to
# reload its schema cache, wait until the schema is exposed, then seed demo data.
# This is the verbatim-shared sequence extracted from both local dev scripts.
migrate_reload_seed() {
  echo "▶ Applying pending migrations…"
  ( cd backend && SUPABASE_DB_URL="$LOCAL_DB_URL" venv/bin/python -m db.migrate ) \
    || { echo "✗ migrations failed"; exit 1; }

  echo "▶ Ensuring local Storage buckets…"
  ensure_storage_buckets

  echo "▶ Reloading PostgREST schema cache…"
  podman exec "$DB_CONTAINER" psql -U postgres -d postgres \
    -c "NOTIFY pgrst, 'reload schema';" >/dev/null 2>&1 || true

  echo "▶ Waiting for PostgREST to expose the schema…"
  local KEY code
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
}
