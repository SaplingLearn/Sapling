# Shared helpers for the LOCAL Sapling dev scripts.
#
# Sourced (never executed) by scripts/local-up.sh, scripts/local-db-reset.sh and
# scripts/e2e-up.sh so the identical "migrate → ensure buckets → reload
# PostgREST → seed" sequence lives in exactly one place (#10). LOCAL ONLY —
# never touches staging/prod.
#
# The caller is expected to have already:
#   • set -uo pipefail
#   • cd'd to the repo root
#   • exported DOCKER_HOST (rootless podman socket) when running under podman
#   • defined LOCAL_DB_URL and DB_CONTAINER
#
# No shebang / +x needed — this file is meant to be `source`d.

# Container runtime used to `exec` into the Supabase DB container: rootless
# Podman is the documented default, Docker also works (#384). An explicit
# $CONTAINER_CMD wins; otherwise prefer podman, falling back to docker.
if [ -z "${CONTAINER_CMD:-}" ]; then
  if command -v podman >/dev/null 2>&1; then
    CONTAINER_CMD=podman
  else
    CONTAINER_CMD=docker
  fi
fi

# Python interpreter inside backend/venv. A POSIX venv puts it in bin/, a
# Windows venv (what `python -m venv` produces under Git Bash / MSYS) in
# Scripts/python.exe. Resolve it once here so every caller — the three dev
# scripts that source this file and e2e-up.sh's preflight — agrees on one
# answer instead of hardcoding the POSIX layout. Empty means "no venv", which
# callers report with the create-it instructions. $REPO_ROOT is set by the
# caller before sourcing. An explicit $VENV_PY wins, so CI can pin one.
if [ -z "${VENV_PY:-}" ]; then
  if [ -x "$REPO_ROOT/backend/venv/bin/python" ]; then
    VENV_PY="$REPO_ROOT/backend/venv/bin/python"
  elif [ -x "$REPO_ROOT/backend/venv/Scripts/python.exe" ]; then
    VENV_PY="$REPO_ROOT/backend/venv/Scripts/python.exe"
  else
    VENV_PY=""
  fi
fi

# Point the Supabase CLI at the rootless podman socket, but ONLY when that
# socket actually exists. Sourced by the callers that used to inline this.
#
# The old form was `export DOCKER_HOST="${DOCKER_HOST:-unix:///run/user/$(id -u)/podman/podman.sock}"`,
# which exported the Linux socket path whenever the podman BINARY was present.
# On Windows podman is present but the socket is not (podman runs in a VM the
# CLI reaches through its own default connection), so that export pointed the
# Supabase CLI at a nonexistent socket and every command failed with
# "Cannot connect to the Docker daemon". Guarding on the socket file leaves
# DOCKER_HOST unset there, which is exactly what the Windows setup needs.
#
# A DOCKER_HOST already in the environment always wins and is never recomputed
# — .github/workflows/e2e.yml depends on that, because ubuntu-latest ships
# podman alongside Docker and pre-sets DOCKER_HOST to the real Docker socket.
set_docker_host_for_podman() {
  [ -n "${DOCKER_HOST:-}" ] && return 0
  command -v podman >/dev/null 2>&1 || return 0
  local sock="unix:///run/user/$(id -u)/podman/podman.sock"
  [ -S "/run/user/$(id -u)/podman/podman.sock" ] || return 0
  export DOCKER_HOST="$sock"
}

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
  if "$CONTAINER_CMD" exec "$DB_CONTAINER" psql -U postgres -d postgres \
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
  # Fail fast with a clear message if the backend venv is missing — every step
  # below shells out to backend/venv/bin/python, so without it the migrate step
  # dies with a confusing "venv/bin/python: No such file or directory" and leaves
  # the stack half-up. $REPO_ROOT is set by both caller scripts before sourcing.
  if [ -z "${VENV_PY:-}" ]; then
    echo "✗ backend/venv not found. Create it first: python -m venv backend/venv && backend/venv/bin/pip install -r backend/requirements.txt"
    echo "  (on Windows the interpreter lands in backend/venv/Scripts/python.exe — both layouts are accepted)"
    return 1
  fi

  echo "▶ Applying pending migrations…"
  ( cd backend && SUPABASE_DB_URL="$LOCAL_DB_URL" "$VENV_PY" -m db.migrate ) \
    || { echo "✗ migrations failed"; exit 1; }

  echo "▶ Ensuring local Storage buckets…"
  ensure_storage_buckets

  echo "▶ Reloading PostgREST schema cache…"
  "$CONTAINER_CMD" exec "$DB_CONTAINER" psql -U postgres -d postgres \
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
  ( cd backend && "$VENV_PY" -m db.seed_staging ) || { echo "✗ seed failed"; exit 1; }

  # Optional rich local dataset (#363): opt-in via SEED_RICH=1.
  if [ "${SEED_RICH:-0}" = "1" ]; then
    echo "▶ Seeding rich local dataset (SEED_RICH=1)…"
    ( cd backend && SUPABASE_DB_URL="$LOCAL_DB_URL" "$VENV_PY" -m db.seed_local_rich ) \
      || { echo "✗ rich seed failed"; exit 1; }
  fi
}
