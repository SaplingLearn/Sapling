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

# Overridable to match supabase/config.toml when a machine cannot use the
# default ports. Windows reserves whole bands of the ephemeral range for
# WinNAT/Hyper-V — on this project's dev box TCP 54288-54788 is excluded, which
# swallows the API (54321), DB (54322) and Studio (54323) ports, and binding
# them fails with "An attempt was made to access a socket in a way forbidden by
# its access permissions" even though every container is healthy. Shifting
# config.toml's ports and exporting these two is the no-admin way out.
# Defaults are the documented contract, so Linux and CI are unaffected.
SUPABASE_DB_PORT="${SUPABASE_DB_PORT:-54322}"
SUPABASE_API_PORT="${SUPABASE_API_PORT:-54321}"
LOCAL_DB_URL="postgresql://postgres:postgres@127.0.0.1:$SUPABASE_DB_PORT/postgres"
DB_CONTAINER="supabase_db_sapling"

# Shared migrate → ensure buckets → reload PostgREST → seed sequence (#10),
# plus $CONTAINER_CMD (podman/docker) detection, $VENV_PY resolution and
# set_docker_host_for_podman.
source "$REPO_ROOT/scripts/lib/local-common.sh"

# Point the Supabase CLI at the rootless podman socket when there is one.
# Moved below the source (and guarded on the socket existing) because the old
# inline form exported the Linux socket path on any machine with the podman
# binary — including Windows, where podman lives in a VM, the socket path does
# not exist, and every supabase command then failed with "Cannot connect to the
# Docker daemon". A pre-set DOCKER_HOST still always wins (e2e.yml relies on it).
set_docker_host_for_podman

# setsid makes each server its own process-group leader, so e2e-down.sh can
# signal the whole tree with one group kill. Git Bash on Windows has no setsid;
# there the servers are plain background jobs and teardown falls back to a
# taskkill /T process-tree walk (see e2e-down.sh) to reach the same children.
if command -v setsid >/dev/null 2>&1; then
  DETACH="setsid"
else
  DETACH=""
  echo "  ℹ setsid not found (Git Bash?) — servers start as plain background jobs; e2e-down falls back to a process-tree kill"
fi

E2E_DIR="$REPO_ROOT/.e2e"
BACKEND_PORT="$(grep -E '^PORT=' backend/.env 2>/dev/null | head -n1 | cut -d= -f2-)"
BACKEND_PORT="${BACKEND_PORT:-5000}"
# Overridable so a machine whose :3000 is already taken (another worktree's
# `next dev`, say) can still boot the lane without stopping that server. The
# Playwright harness follows via E2E_FRONTEND_URL (frontend/e2e/support/stack.ts);
# nothing else hardcodes the frontend's own port — build:test only bakes
# BACKEND_URL, and the browser reaches the API same-origin through Next.
FRONTEND_PORT="${FRONTEND_PORT:-3000}"

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
  # python-dotenv accepts an optional `export ` prefix and we may be handed a
  # CRLF-edited .env — accept both, strip any trailing CR (PR #467 review).
  val="$(grep -E '^(export[[:space:]]+)?SESSION_SECRET=' "$env_file" 2>/dev/null | head -n1 | sed -E 's/^export[[:space:]]+//' | cut -d= -f2- | tr -d '\r')"
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
# $VENV_PY is resolved in local-common.sh and accepts both the POSIX
# (venv/bin/python) and Windows (venv/Scripts/python.exe) venv layouts.
[ -n "${VENV_PY:-}" ] \
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
# #537: raise the quiz-generation rate limit for the lane. The guard
# (services/quiz_config.py::QUIZ_GENERATE_RATE_LIMIT, 8 per 300s) keeps its
# sliding window in a module-level dict, so it is neither per-test nor
# per-spec: ONE Playwright run shares a single window across every worker,
# and the per-test TRUNCATE + re-seed does not reset it — only a backend
# restart does. The redesigned quiz lane makes ~20 real generations, so the
# production number 429s the specs that happen to run last (alphabetically:
# quiz.spec.ts after quiz-errors/quiz-integration). Under function mode a
# generation is a scripted constant that costs nothing, which is the only
# thing the limit exists to bound. Exported, so it beats backend/.env
# (python-dotenv never overrides existing env); overridable for anyone who
# wants to exercise the real guard.
export QUIZ_GENERATE_RATE_LIMIT="${QUIZ_GENERATE_RATE_LIMIT:-1000}"
echo "  ℹ QUIZ_GENERATE_RATE_LIMIT=$QUIZ_GENERATE_RATE_LIMIT for this stack (production default is 8; #537)"
# `setsid <simple command> &` is load-bearing: bash fork+execs the simple
# command directly, so $! is setsid's PID, which becomes the new session's
# process-group leader — the PID e2e-down.sh kills as a group. (Backgrounding a
# `cd … && setsid …` list instead records a wrapper-subshell PID and teardown
# would orphan the server.)
(
  cd backend || exit 1
  $DETACH "$VENV_PY" -m uvicorn main:app --host 0.0.0.0 --port "$BACKEND_PORT" \
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
  $DETACH npm run start:test -- --port "$FRONTEND_PORT" >"$E2E_DIR/frontend.log" 2>&1 &
  echo $! >"$E2E_DIR/frontend.pid"
) || { echo "✗ could not start frontend"; exit 1; }

# ── Health-check all four services ───────────────────────────────────────────
echo "▶ Health-checking all services…"
if "$CONTAINER_CMD" exec "$DB_CONTAINER" pg_isready -U postgres -d postgres >/dev/null 2>&1; then
  echo "  ✓ Postgres (:$SUPABASE_DB_PORT)"
else
  echo "✗ Postgres health check failed ($CONTAINER_CMD exec $DB_CONTAINER pg_isready)"
  exit 1
fi
KEY="$(grep -E '^SUPABASE_SERVICE_KEY=' backend/.env | head -n1 | cut -d= -f2-)"
wait_for_http "Supabase REST / PostgREST (:$SUPABASE_API_PORT)" \
  "http://127.0.0.1:$SUPABASE_API_PORT/rest/v1/terms?select=id&limit=1" 30 "" \
  -H "apikey: $KEY" -H "Authorization: Bearer $KEY"
wait_for_http "backend (uvicorn :$BACKEND_PORT)" \
  "http://127.0.0.1:$BACKEND_PORT/api/health" 15 "$E2E_DIR/backend.log"
wait_for_http "frontend (next start :$FRONTEND_PORT)" \
  "http://127.0.0.1:$FRONTEND_PORT/" 60 "$E2E_DIR/frontend.log" -L

# Without setsid, $! is the `npm` wrapper, and npm EXITS once next-server is
# spawned. e2e-down then finds a dead PID, skips (kill -0 fails, so even the
# taskkill fallback never runs), and next-server survives holding the port —
# observed exactly once, orphaning :3001 through a clean `e2e-down`.
#
# The server is healthy by this line, so the process listening on the port is
# unambiguously ours: record THAT pid instead. Only on the no-setsid path —
# under setsid the recorded pid leads the process group and is already right.
if [ -z "$DETACH" ] && command -v netstat >/dev/null 2>&1; then
  owner="$(netstat -ano -p tcp 2>/dev/null \
    | awk -v p=":$FRONTEND_PORT" '$2 ~ p"$" && $4 == "LISTENING" {print $5; exit}')"
  if [ -n "$owner" ]; then
    echo "$owner" >"$E2E_DIR/frontend.pid"
    echo "  ↳ tracking frontend by port owner (pid $owner); npm wrapper has exited"
  fi
fi

cat <<DONE

✅ E2E stack is up.
     frontend  http://localhost:$FRONTEND_PORT   (test-profile production build)
     backend   http://localhost:$BACKEND_PORT   (health: /api/health)
     Supabase  http://127.0.0.1:$SUPABASE_API_PORT  (Studio: see supabase/config.toml [studio])
   PIDs + logs: .e2e/          Tear down: make e2e-down
   Harness sign-in: POST /api/auth/test-login with a seeded rich-* user (#381).
DONE
