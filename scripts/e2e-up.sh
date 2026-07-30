#!/usr/bin/env bash
#
# One-command LOCAL E2E stack boot (#384).
#
#   make e2e-up          # or: scripts/e2e-up.sh
#   make e2e-down        # tear down — scripts/e2e-down.sh
#
# Sequence: supabase start → db.migrate → ensure Storage buckets →
# NOTIFY pgrst 'reload schema' → PostgREST poll → seed (demo + rich) →
# uvicorn backend on :5000 → test-profile Next production build
# (`npm run build:test && npm run start:test`, #380) on :3000 →
# health-check all four services (Postgres, PostgREST, backend, frontend).
#
# Idempotent — re-running restarts the app servers and re-applies the
# skip-if-done migrations/seeds. LOCAL ONLY — never touches staging/prod.
#
# First-time setup on a new machine (same as scripts/local-up.sh):
#   cp backend/.env.local.example backend/.env       # then fill in GEMINI_API_KEY
#   python -m venv backend/venv && backend/venv/bin/pip install -r backend/requirements.txt
#   cd frontend && npm ci
#
# Rootless Podman is the documented runtime; Docker also works — the runtime is
# auto-detected in scripts/lib/local-common.sh ($CONTAINER_CMD overrides).
#
# The servers run detached (setsid, so each PID is its process-group leader);
# PIDs and logs live in .e2e/ at the repo root. E2E harnesses sign in via
# POST /api/auth/test-login (#381) with the seeded rich-* users.
set -uo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT" || exit 1

# Point the Supabase CLI at the rootless podman socket only when podman exists;
# under Docker leave DOCKER_HOST alone so the default daemon socket is used.
if command -v podman >/dev/null 2>&1; then
  export DOCKER_HOST="${DOCKER_HOST:-unix:///run/user/$(id -u)/podman/podman.sock}"
fi

LOCAL_DB_URL="postgresql://postgres:postgres@127.0.0.1:54322/postgres"
DB_CONTAINER="supabase_db_sapling"

# Shared migrate → ensure buckets → reload PostgREST → seed sequence (#10),
# plus $CONTAINER_CMD (podman/docker) detection.
source "$REPO_ROOT/scripts/lib/local-common.sh"

E2E_DIR="$REPO_ROOT/.e2e"
BACKEND_PORT="$(grep -E '^PORT=' backend/.env 2>/dev/null | head -n1 | cut -d= -f2-)"
BACKEND_PORT="${BACKEND_PORT:-5000}"
FRONTEND_PORT=3000

# Poll a URL until it returns HTTP 200 (same curl style as local-common.sh),
# failing the boot if it never comes up — with a log tail when the caller has
# a logfile to tail (the app servers do; the PostgREST check passes "").
wait_for_http() { # name url attempts logfile [extra curl args…]
  local name="$1" url="$2" attempts="$3" logfile="$4" code=000
  shift 4
  for _ in $(seq 1 "$attempts"); do
    code="$(curl -s -o /dev/null -w '%{http_code}' "$@" "$url")"
    [ "$code" = "200" ] && { echo "  ✓ $name"; return 0; }
    sleep 1
  done
  echo "✗ $name did not become healthy (last HTTP $code from $url)"
  if [ -n "$logfile" ] && [ -f "$logfile" ]; then
    echo "  last lines of $logfile:"
    tail -n 20 "$logfile" | sed 's/^/    /'
  fi
  exit 1
}

# ── SESSION_SECRET preflight (#425) ─────────────────────────────────────────
# All four health checks are unauthenticated, so a backend/frontend
# SESSION_SECRET drift yields a "healthy" stack where every
# POST /api/auth/test-login session then fails signature verification in the
# frontend session route (frontend/src/app/api/auth/session/route.ts).
# Resolve the value each side will ACTUALLY use and fail fast on
# mismatch/empty. Only sha256 fingerprints are printed — never the secrets.

secret_fingerprint() { # value → first 8 hex chars of sha256, or "(empty)"
  [ -n "$1" ] || { echo "(empty)"; return; }
  printf '%s' "$1" | sha256sum | cut -c1-8
}

resolve_backend_session_secret() { # env_file → BACKEND_SECRET, BACKEND_SECRET_SRC
  # Mirrors backend/config.py: load_dotenv() never overrides existing env, so
  # an exported SESSION_SECRET beats the backend/.env line.
  local env_file="$1" val
  if [ -n "${SESSION_SECRET:-}" ]; then
    BACKEND_SECRET="$SESSION_SECRET"
    BACKEND_SECRET_SRC="exported SESSION_SECRET env (overrides $env_file)"
    return 0
  fi
  val="$(grep -E '^SESSION_SECRET=' "$env_file" 2>/dev/null | head -n1 | cut -d= -f2-)"
  # python-dotenv strips one layer of matching quotes; mirror that.
  case "$val" in
    \"*\") val="${val#\"}"; val="${val%\"}" ;;
    \'*\') val="${val#\'}"; val="${val%\'}" ;;
  esac
  BACKEND_SECRET="$val"
  BACKEND_SECRET_SRC="$env_file SESSION_SECRET="
}

resolve_frontend_session_secret() { # package_json → FRONTEND_SECRET, FRONTEND_SECRET_SRC
  # start:test bakes SESSION_SECRET in as a command-prefix assignment (#380),
  # which beats any inherited env — that literal is what `next start` sees.
  local package_json="$1" line
  line="$(grep -E '"start:test"[[:space:]]*:' "$package_json" 2>/dev/null | head -n1)"
  case "$line" in
    *SESSION_SECRET=*)
      FRONTEND_SECRET="$(printf '%s' "$line" | sed -E 's/.*SESSION_SECRET=([^ "]*).*/\1/')"
      FRONTEND_SECRET_SRC="$package_json \"start:test\" SESSION_SECRET="
      ;;
    *)
      FRONTEND_SECRET="${SESSION_SECRET:-}"
      FRONTEND_SECRET_SRC="inherited env (no SESSION_SECRET= in $package_json \"start:test\")"
      ;;
  esac
}

check_session_secrets() { # env_file package_json → 0 match, 1 empty/mismatch (message printed)
  resolve_backend_session_secret "$1"
  resolve_frontend_session_secret "$2"
  local why
  if [ -z "$BACKEND_SECRET" ] || [ -z "$FRONTEND_SECRET" ]; then
    why="empty on at least one side"
  elif [ "$BACKEND_SECRET" != "$FRONTEND_SECRET" ]; then
    why="mismatch"
  else
    return 0
  fi
  echo "✗ SESSION_SECRET $why — the stack would pass every health check (they're unauthenticated) while all test-login sessions silently fail signature verification (#425):"
  echo "    backend  ← $BACKEND_SECRET_SRC  (sha256 $(secret_fingerprint "$BACKEND_SECRET"))"
  echo "    frontend ← $FRONTEND_SECRET_SRC  (sha256 $(secret_fingerprint "$FRONTEND_SECRET"))"
  echo "  Fix: make both sides identical — SESSION_SECRET in backend/.env and the SESSION_SECRET=… baked into frontend/package.json's \"start:test\"."
  return 1
}

# ── Preflight ────────────────────────────────────────────────────────────────
# Fail fast with the exact fix before touching anything, so a clean machine
# gets one actionable message instead of a half-up stack.
echo "▶ Preflight…"
command -v supabase >/dev/null 2>&1 \
  || { echo "✗ supabase CLI not found. Install it first (Arch: paru -S supabase-bin) — see docs/local-supabase.md"; exit 1; }
[ -f backend/.env ] \
  || { echo "✗ backend/.env not found. Create it first: cp backend/.env.local.example backend/.env  (then fill in GEMINI_API_KEY)"; exit 1; }
[ -x backend/venv/bin/python ] \
  || { echo "✗ backend/venv not found. Create it first: python -m venv backend/venv && backend/venv/bin/pip install -r backend/requirements.txt"; exit 1; }
[ -d frontend/node_modules ] \
  || { echo "✗ frontend/node_modules not found. Install first: cd frontend && npm ci"; exit 1; }
# build:test/start:test hardcode BACKEND_URL=http://localhost:5000 (#380), so a
# nonstandard backend port would silently break the Next → FastAPI proxy.
[ "$BACKEND_PORT" = "5000" ] \
  || { echo "✗ backend/.env sets PORT=$BACKEND_PORT, but the test-profile frontend proxies to :5000. Unset PORT (or set it to 5000) for E2E."; exit 1; }
# Same class of baked-in constant: the frontend's SESSION_SECRET lives in
# package.json's start:test, the backend's in backend/.env — verify they agree
# up front, because no health check would ever notice the drift (#425).
check_session_secrets backend/.env frontend/package.json || exit 1
# The E2E sign-in seam POST /api/auth/test-login (#381) only exists when
# APP_ENV is exactly local or test — warn, the stack still boots without it.
grep -qE '^APP_ENV=(local|test)$' backend/.env \
  || echo "  ⚠ backend/.env APP_ENV is not local/test — /api/auth/test-login will 404 for E2E harnesses"
# e2e-up deliberately does NOT set the LLM-seam envs — a live-model stack is
# legitimate. But the deterministic lanes need them, so leave a pointer when
# they're absent instead of letting journeys silently hit live Gemini.
if [ -z "${SAPLING_MODEL_MODE:-}" ] && ! grep -qE '^SAPLING_MODEL_MODE=' backend/.env; then
  echo "  ℹ SAPLING_MODEL_MODE is unset — agents will call the LIVE model; for deterministic E2E export SAPLING_MODEL_MODE=function SAPLING_FUNCTION_HANDLERS=agents.function_handlers_e2e (what e2e.yml does)"
fi

mkdir -p "$E2E_DIR"

# Stop any servers a previous e2e-up left running (keeps re-runs clean).
"$REPO_ROOT/scripts/e2e-down.sh" --apps-only

# With our own tracked servers gone, the ports must be free — anything still
# listening is someone else's dev server and uvicorn/next would fail to bind.
if command -v ss >/dev/null 2>&1; then
  for port in "$BACKEND_PORT" "$FRONTEND_PORT"; do
    if ss -ltn 2>/dev/null | grep -q ":$port "; then
      echo "✗ port $port is already in use by an untracked process — stop your dev server first"
      exit 1
    fi
  done
fi

# ── Database stack ───────────────────────────────────────────────────────────
echo "▶ Starting local Supabase (no-op if already running)…"
if ! supabase start; then
  # A stale project (containers left 'exited', e.g. after a reboot) makes the
  # CLI claim it's "already running" and then fail — stop and retry once.
  # `supabase stop` keeps the DB volume, so no data is lost.
  echo "  ⚠ supabase start failed — retrying once after supabase stop"
  supabase stop >/dev/null 2>&1 || true
  supabase start || { echo "✗ supabase start failed"; exit 1; }
fi

# Seed the rich dataset by default (#363): E2E harnesses sign in via
# /api/auth/test-login, which needs the seeded rich-* users. SEED_RICH=0 skips.
export SEED_RICH="${SEED_RICH:-1}"
migrate_reload_seed

# ── Backend (uvicorn) ────────────────────────────────────────────────────────
# Same app entry as `python main.py` but without --reload: a file-watcher
# restarting mid-test would make E2E runs nondeterministic.
echo "▶ Starting backend (uvicorn on :$BACKEND_PORT, log: .e2e/backend.log)…"
# `setsid <simple command> &` is load-bearing: bash fork+execs the simple
# command directly, so $! is setsid's PID, which becomes the new session's
# process-group leader — the PID e2e-down.sh kills as a group. (Backgrounding a
# `cd … && setsid …` list instead records a wrapper-subshell PID and teardown
# would orphan the server.)
(
  cd backend || exit 1
  setsid venv/bin/python -m uvicorn main:app --host 0.0.0.0 --port "$BACKEND_PORT" \
    >"$E2E_DIR/backend.log" 2>&1 &
  echo $! >"$E2E_DIR/backend.pid"
) || { echo "✗ could not start backend"; exit 1; }
wait_for_http "backend (uvicorn :$BACKEND_PORT)" \
  "http://127.0.0.1:$BACKEND_PORT/api/health" 30 "$E2E_DIR/backend.log"

# ── Frontend (test-profile production build, #380) ───────────────────────────
# `start:test` prints a "next start does not work with output: standalone"
# warning — expected and harmless, see docs/local-supabase.md.
echo "▶ Building test-profile frontend (npm run build:test, log: .e2e/frontend-build.log)…"
( cd frontend && npm run build:test ) >"$E2E_DIR/frontend-build.log" 2>&1 \
  || { echo "✗ frontend build failed"; tail -n 20 "$E2E_DIR/frontend-build.log" | sed 's/^/    /'; exit 1; }

echo "▶ Starting frontend (next start on :$FRONTEND_PORT, log: .e2e/frontend.log)…"
# Same setsid-simple-command shape as the backend launch above.
(
  cd frontend || exit 1
  setsid npm run start:test >"$E2E_DIR/frontend.log" 2>&1 &
  echo $! >"$E2E_DIR/frontend.pid"
) || { echo "✗ could not start frontend"; exit 1; }

# ── Health-check all four services ───────────────────────────────────────────
echo "▶ Health-checking all services…"
if "$CONTAINER_CMD" exec "$DB_CONTAINER" pg_isready -U postgres -d postgres >/dev/null 2>&1; then
  echo "  ✓ Postgres (:54322)"
else
  echo "✗ Postgres health check failed ($CONTAINER_CMD exec $DB_CONTAINER pg_isready)"
  exit 1
fi
KEY="$(grep -E '^SUPABASE_SERVICE_KEY=' backend/.env | head -n1 | cut -d= -f2-)"
wait_for_http "Supabase REST / PostgREST (:54321)" \
  "http://127.0.0.1:54321/rest/v1/terms?select=id&limit=1" 30 "" \
  -H "apikey: $KEY" -H "Authorization: Bearer $KEY"
wait_for_http "backend (uvicorn :$BACKEND_PORT)" \
  "http://127.0.0.1:$BACKEND_PORT/api/health" 15 "$E2E_DIR/backend.log"
wait_for_http "frontend (next start :$FRONTEND_PORT)" \
  "http://127.0.0.1:$FRONTEND_PORT/" 60 "$E2E_DIR/frontend.log" -L

cat <<DONE

✅ E2E stack is up.
     frontend  http://localhost:$FRONTEND_PORT   (test-profile production build)
     backend   http://localhost:$BACKEND_PORT   (health: /api/health)
     Supabase  http://127.0.0.1:54321  (Studio: http://127.0.0.1:54323)
   PIDs + logs: .e2e/          Tear down: make e2e-down
   Harness sign-in: POST /api/auth/test-login with a seeded rich-* user (#381).
DONE
