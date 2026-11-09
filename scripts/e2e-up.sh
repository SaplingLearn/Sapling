#!/usr/bin/env bash
#
# One-command LOCAL E2E stack boot (#384).
#
#   make e2e-up          # or: scripts/e2e-up.sh
#   make e2e-down        # tear down — scripts/e2e-down.sh
#
# Sequence: supabase start → db.migrate → ensure Storage buckets →
# NOTIFY pgrst 'reload schema' → PostgREST poll → seed (demo + rich) →
# uvicorn backend → test-profile Next production build
# (`npm run build:test && npm run start:test`, #380) →
# health-check all four services (Postgres, PostgREST, backend, frontend).
#
# The stack boots in an E2E SLOT (scripts/lib/e2e-slot.sh): E2E_SLOT=N (1..3,
# default: the slot this checkout last used, else 1) gets frontend :310N,
# backend :510N and its own Supabase project on ports shifted by +100·N, with a
# throwaway database. Slots never touch :3000/:5000/:54321 — those are the dev
# app's (Google sign-in can only land on :5000). Slot 0 is that classic stack,
# for CI only. scripts/e2e-cycle.sh claims a free slot and runs a whole
# up → test → down cycle under its lock; prefer it to a bare e2e-up.
#
# Idempotent — re-running restarts the app servers and re-applies the
# skip-if-done migrations/seeds. LOCAL ONLY — never touches staging/prod.
#
# First-time setup on a new machine (same as scripts/local-up.sh):
#   cp backend/.env.local.example backend/.env       # then fill in ANTHROPIC_API_KEY + GEMINI_API_KEY
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

# The slot decides every port, the Supabase project, DB_CONTAINER and
# LOCAL_DB_URL (scripts/lib/e2e-slot.sh). On slot 0 (CI) SUPABASE_DB_PORT /
# SUPABASE_API_PORT stay overridable to match a shifted config.toml: Windows
# reserves whole bands of the ephemeral range for WinNAT/Hyper-V — on this
# project's dev box TCP 54288-54788 is excluded, which swallows the classic
# API (54321), DB (54322) and Studio (54323) ports.
source "$REPO_ROOT/scripts/lib/e2e-slot.sh"
resolve_e2e_slot "$REPO_ROOT" || exit 1
mapfile -t SUPABASE_ARGS < <(e2e_supabase_args)

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
  || { echo "✗ backend/.env not found. Create it first: cp backend/.env.local.example backend/.env  (then fill in ANTHROPIC_API_KEY + GEMINI_API_KEY)"; exit 1; }
# $VENV_PY is resolved in local-common.sh and accepts both the POSIX
# (venv/bin/python) and Windows (venv/Scripts/python.exe) venv layouts.
[ -n "${VENV_PY:-}" ] \
  || { echo "✗ backend/venv not found. Create it first: python -m venv backend/venv && backend/venv/bin/pip install -r backend/requirements.txt"; exit 1; }
[ -d frontend/node_modules ] \
  || { echo "✗ frontend/node_modules not found. Install first: cd frontend && npm ci"; exit 1; }
# A bare e2e-up in a checkout whose cycle is running would stop that cycle's
# servers (.e2e/*.pid) and rebuild its frontend under it. The cycle's own
# e2e-up passes E2E_SLOT_LOCKED=1.
if [ "${E2E_SLOT_LOCKED:-0}" != "1" ] && [ -f "$REPO_ROOT/.e2e/cycle.lock" ] \
  && ! ( flock -n 8 ) 8>"$REPO_ROOT/.e2e/cycle.lock"; then
  echo "✗ an E2E cycle is running in this checkout — wait for it, or boot from another worktree."
  exit 1
fi
# A slot's lock means a run is using it. A cycle (or explore) holds the lock
# itself and passes E2E_SLOT_LOCKED=1. A BARE `make e2e-up` takes it here,
# through a detached holder that outlives this script (the stack stays up for
# manual use) and that e2e-down stops — so a cycle never claims a slot a human
# booted, and a stray e2e-down elsewhere can't take this one down.
if [ "$E2E_SLOT" != "0" ] && [ "${E2E_SLOT_LOCKED:-0}" != "1" ]; then
  if ! e2e_take_slot_lock_detached "$E2E_SLOT" "$REPO_ROOT/.e2e"; then
    echo "✗ E2E slot $E2E_SLOT is in use by another run ($(e2e_slot_lock_file "$E2E_SLOT"))."
    echo "  Pick another (E2E_SLOT=1..$E2E_SLOTS_MAX) or run scripts/e2e-cycle.sh, which takes a free one."
    exit 1
  fi
  echo "  ✓ holding E2E slot $E2E_SLOT for this boot (released by make e2e-down)"
fi
# Same class of baked-in constant: the frontend's SESSION_SECRET lives in
# package.json's start:test, the backend's in backend/.env — verify they agree
# up front, because no health check would ever notice the drift (#425).
check_session_secrets backend/.env frontend/package.json || exit 1
# The E2E sign-in seam POST /api/auth/test-login (#381) only exists when
# APP_ENV is exactly local or test — warn, the stack still boots without it.
grep -qE '^APP_ENV=(local|test)$' backend/.env \
  || echo "  ⚠ backend/.env APP_ENV is not local/test — /api/auth/test-login will 404 for E2E harnesses"
# RLS step 2e: study-room live chat subscribes ONLY with the backend-minted
# Realtime token (room_messages has RLS on and no anon SELECT), signed with
# SUPABASE_JWT_SIGNING_KEY. Without it GET /api/auth/realtime-token answers
# 503, rooms are REST-only, and study-room.spec.ts cannot see live messages.
# Every stack this script boots runs the Supabase CLI's default JWT secret,
# whose oct JWK backend/.env.local.example carries, so when neither the shell
# nor backend/.env sets the key, export that demo key — the same way the slot
# setup exports its URLs (an exported variable beats backend/.env, since
# python-dotenv never overrides one). It is the public CLI demo secret, never
# a real project's.
if [ -z "${SUPABASE_JWT_SIGNING_KEY:-}" ] && ! grep -qE '^SUPABASE_JWT_SIGNING_KEY=.+' backend/.env; then
  DEMO_JWT_SIGNING_KEY="$(grep -E '^SUPABASE_JWT_SIGNING_KEY=.+' backend/.env.local.example | tail -n1 | cut -d= -f2- | tr -d '\r')"
  if [ -z "$DEMO_JWT_SIGNING_KEY" ]; then
    echo "✗ SUPABASE_JWT_SIGNING_KEY is unset in backend/.env and missing from backend/.env.local.example — study rooms would get no live chat. Set it in backend/.env."
    exit 1
  fi
  export SUPABASE_JWT_SIGNING_KEY="$DEMO_JWT_SIGNING_KEY"
  echo "  ℹ SUPABASE_JWT_SIGNING_KEY unset in backend/.env — using the local demo key from backend/.env.local.example (RLS step 2e live chat)"
fi
# e2e-up deliberately does NOT set the LLM-seam envs — a live-model stack is
# legitimate. But the deterministic lanes need them, so leave a pointer when
# they're absent instead of letting journeys silently hit live Gemini.
if [ -z "${SAPLING_MODEL_MODE:-}" ] && ! grep -qE '^SAPLING_MODEL_MODE=' backend/.env; then
  echo "  ℹ SAPLING_MODEL_MODE is unset — agents will call the LIVE model; for deterministic E2E export SAPLING_MODEL_MODE=function SAPLING_FUNCTION_HANDLERS=agents.function_handlers_e2e (what e2e.yml does)"
fi
# The deterministic lane exercises the typed decision seam (#640, ADR 0027).
# The tutor router runs whatever the `decision_router` feature flag says
# (ADR 0029) and the flag is off by default — no stored config on this stack —
# so switch it on through its generic env override, respecting a value the
# caller exported (`off` skips the seam). Under function mode an on variant
# runs the scripted `function` backend; Gemini/Jev are never dialled. Function
# mode is detected the same way as the check above: the shell first, then
# backend/.env.
MODEL_MODE="${SAPLING_MODEL_MODE:-$(grep -E '^SAPLING_MODEL_MODE=' backend/.env | tail -n1 | cut -d= -f2- | tr -d '\r')}"
if [ "$MODEL_MODE" = "function" ]; then
  export SAPLING_FLAG_DECISION_ROUTER="${SAPLING_FLAG_DECISION_ROUTER:-jev}"
fi

mkdir -p "$E2E_DIR"
write_e2e_slot_manifest "$E2E_DIR"
echo "▶ E2E slot $E2E_SLOT: frontend :$FRONTEND_PORT, backend :$BACKEND_PORT, Supabase :$SUPABASE_API_PORT (db :$SUPABASE_DB_PORT, project $SUPABASE_PROJECT_ID)"

# Stop any servers a previous e2e-up left running (keeps re-runs clean).
"$REPO_ROOT/scripts/e2e-down.sh" --apps-only

# With our own tracked servers gone, the ports must be free — anything still
# listening is someone else's dev server and uvicorn/next would fail to bind.
if command -v ss >/dev/null 2>&1; then
  for port in "$BACKEND_PORT" "$FRONTEND_PORT"; do
    if ss -ltn 2>/dev/null | grep -q ":$port "; then
      echo "✗ port $port is already in use by an untracked process — a server left over from an earlier run on this slot, or someone else's:"
      ss -ltnp 2>/dev/null | grep ":$port " | sed 's/^/    /'
      echo "  Stop it (or pick another E2E_SLOT) and re-run."
      exit 1
    fi
  done
fi

# ── Database stack ───────────────────────────────────────────────────────────
echo "▶ Starting local Supabase (no-op if already running)…"
# From here on this checkout owns a stack on the slot: what a cycle's teardown
# (and e2e-down) may stop.
echo "$E2E_SLOT" >"$E2E_DIR/booted"
write_e2e_slot_supabase_config "$REPO_ROOT"
EXCLUDE_ARGS=()
[ -n "$E2E_SUPABASE_EXCLUDE" ] && EXCLUDE_ARGS=(-x "$E2E_SUPABASE_EXCLUDE")
if ! supabase start "${SUPABASE_ARGS[@]}" "${EXCLUDE_ARGS[@]}"; then
  # A stale project (containers left 'exited', e.g. after a reboot) makes the
  # CLI claim it's "already running" and then fail — stop and retry once.
  # `supabase stop` keeps the DB volume, so no data is lost.
  echo "  ⚠ supabase start failed — retrying once after supabase stop"
  supabase stop "${SUPABASE_ARGS[@]}" >/dev/null 2>&1 || true
  supabase start "${SUPABASE_ARGS[@]}" "${EXCLUDE_ARGS[@]}" || { echo "✗ supabase start failed"; exit 1; }
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
# ADR 0029 §9: the backend caches the flag snapshot (30 s) and each user's
# roles (60 s) per process, and the per-test TRUNCATE + re-seed writes the DB
# directly, which clears neither — one journey's rules would leak into the
# next, and a retried feature-flags.spec.ts would fail its baseline. TTL 0 =
# every resolution reads the DB. Unconditional: a local lane has no load for
# the cache to save.
export FEATURE_FLAGS_SNAPSHOT_TTL_S=0
export FEATURE_FLAGS_ROLES_TTL_S=0
echo "  ℹ FEATURE_FLAGS_SNAPSHOT_TTL_S=0, FEATURE_FLAGS_ROLES_TTL_S=0 for this stack (ADR 0029)"
# ADR 0028: this stack must never send to PostHog, whatever backend/.env
# holds. The seam is also off under any non-real SAPLING_MODEL_MODE, but this
# script does NOT force function mode (it only prints a notice when it is
# unset) and runs APP_ENV=local — so say it explicitly rather than rely on
# that inference: blank the project token, and no PostHog client is built.
# Erasure is not capture (account deletion still calls PostHog's bulk_delete
# when a personal key is configured), so blank the personal key too: an E2E
# account-deletion journey must never reach a real PostHog project. Exported
# empty, each beats backend/.env (python-dotenv never overrides an existing
# variable). Unconditional: there is no reason to send from a local lane.
export POSTHOG_PROJECT_TOKEN=
export POSTHOG_PERSONAL_API_KEY=
echo "  ℹ POSTHOG_PROJECT_TOKEN and POSTHOG_PERSONAL_API_KEY blank for this stack (ADR 0028)"
# The servers never inherit the cycle's locks (fds 8/9, scripts/e2e-cycle.sh):
# a server that outlived its teardown would otherwise hold the slot's lock
# forever and the slot would silently drop out of rotation. Without them, a
# leftover server fails the next boot's port check loudly instead.
# `setsid <simple command> &` is load-bearing: bash fork+execs the simple
# command directly, so $! is setsid's PID, which becomes the new session's
# process-group leader — the PID e2e-down.sh kills as a group. (Backgrounding a
# `cd … && setsid …` list instead records a wrapper-subshell PID and teardown
# would orphan the server.)
(
  cd backend || exit 1
  $DETACH "$VENV_PY" -m uvicorn main:app --host 0.0.0.0 --port "$BACKEND_PORT" \
    >"$E2E_DIR/backend.log" 2>&1 8>&- 9>&- &
  echo $! >"$E2E_DIR/backend.pid"
) || { echo "✗ could not start backend"; exit 1; }
wait_for_http "backend (uvicorn :$BACKEND_PORT)" \
  "http://127.0.0.1:$BACKEND_PORT/api/health" 30 "$E2E_DIR/backend.log"

# ── Job worker (opt-in, #116) ────────────────────────────────────────────────
# The lane runs the `jobs_queue` flag OFF, so nothing is enqueued and no worker
# is needed. E2E_WORKER=1 starts `python -m worker` beside the backend, with
# the same exported env (function mode included: the worker freezes the model
# mode at boot like the API lifespan), for exploring the flag-on paths. Same
# setsid-simple-command shape as the backend; e2e-down stops it.
if [ "${E2E_WORKER:-0}" = "1" ]; then
  echo "▶ Starting job worker (python -m worker, log: .e2e/worker.log)…"
  (
    cd backend || exit 1
    $DETACH "$VENV_PY" -m worker --poll-interval 1 >"$E2E_DIR/worker.log" 2>&1 8>&- 9>&- &
    echo $! >"$E2E_DIR/worker.pid"
  ) || { echo "✗ could not start worker"; exit 1; }
fi

# ── Frontend (test-profile production build, #380) ───────────────────────────
# `start:test` prints a "next start does not work with output: standalone"
# warning — expected and harmless, see docs/local-supabase.md.
if [ "${E2E_FRONTEND:-test}" = "dev" ]; then
  # For a HUMAN looking at a branch in a slot: `next dev` (hot reload, real
  # motion — the test-profile build sets NEXT_PUBLIC_TEST_MODE, which turns
  # animations off), proxying to this slot's backend. Not for test runs.
  echo "▶ Starting frontend (next dev on :$FRONTEND_PORT, E2E_FRONTEND=dev, log: .e2e/frontend.log)…"
  (
    cd frontend || exit 1
    BACKEND_URL="$E2E_BACKEND_URL" $DETACH npx next dev -p "$FRONTEND_PORT" >"$E2E_DIR/frontend.log" 2>&1 8>&- 9>&- &
    echo $! >"$E2E_DIR/frontend.pid"
  ) || { echo "✗ could not start frontend"; exit 1; }
else
echo "▶ Building test-profile frontend (npm run build:test, log: .e2e/frontend-build.log)…"
( cd frontend && npm run build:test ) >"$E2E_DIR/frontend-build.log" 2>&1 \
  || { echo "✗ frontend build failed"; tail -n 20 "$E2E_DIR/frontend-build.log" | sed 's/^/    /'; exit 1; }

echo "▶ Starting frontend (next start on :$FRONTEND_PORT, log: .e2e/frontend.log)…"
# Same setsid-simple-command shape as the backend launch above.
(
  cd frontend || exit 1
  $DETACH npm run start:test -- --port "$FRONTEND_PORT" >"$E2E_DIR/frontend.log" 2>&1 8>&- 9>&- &
  echo $! >"$E2E_DIR/frontend.pid"
) || { echo "✗ could not start frontend"; exit 1; }
fi

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
wait_for_http "frontend (:$FRONTEND_PORT)" \
  "http://127.0.0.1:$FRONTEND_PORT/" 120 "$E2E_DIR/frontend.log" -L

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

✅ E2E stack is up (slot $E2E_SLOT).
     frontend  http://localhost:$FRONTEND_PORT   (test-profile production build)
     backend   http://localhost:$BACKEND_PORT   (health: /api/health)
     Supabase  http://127.0.0.1:$SUPABASE_API_PORT  (project $SUPABASE_PROJECT_ID)
   PIDs + logs: .e2e/          Tear down: make e2e-down
   Harnesses read .e2e/stack.json; a shell can \`source .e2e/env.sh\`.
   Harness sign-in: POST /api/auth/test-login with a seeded rich-* user (#381).
DONE
