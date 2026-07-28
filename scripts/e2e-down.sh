#!/usr/bin/env bash
#
# Tear down the LOCAL E2E stack booted by scripts/e2e-up.sh (#384).
#
#   make e2e-down                     # stop uvicorn + next, then `supabase stop`
#   scripts/e2e-down.sh --apps-only   # stop only the tracked app servers, keep
#                                     # Supabase up (e2e-up.sh uses this so
#                                     # re-runs start from clean processes)
#
# Server PIDs are tracked in .e2e/*.pid. Each server was started under setsid,
# so the recorded PID is its process-group leader and one group signal takes
# down the whole tree (npm → next-server, etc.). Stale or missing PID files are
# cleaned up silently — safe to run any time. LOCAL ONLY.
set -uo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT" || exit 1

# Point the Supabase CLI at the rootless podman socket only when podman exists;
# under Docker leave DOCKER_HOST alone so the default daemon socket is used.
if command -v podman >/dev/null 2>&1; then
  export DOCKER_HOST="${DOCKER_HOST:-unix:///run/user/$(id -u)/podman/podman.sock}"
fi

E2E_DIR="$REPO_ROOT/.e2e"
APPS_ONLY=0
[ "${1:-}" = "--apps-only" ] && APPS_ONLY=1

# Stop the process group recorded in a PID file: SIGTERM, wait up to 10s for a
# graceful exit, then SIGKILL. Tolerates stale/missing PID files.
stop_tracked() { # name pidfile
  local name="$1" pidfile="$2" pid
  [ -f "$pidfile" ] || return 0
  pid="$(cat "$pidfile" 2>/dev/null)"
  if [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null; then
    echo "▶ Stopping $name (pid $pid)…"
    kill -TERM -- "-$pid" 2>/dev/null || kill -TERM "$pid" 2>/dev/null
    for _ in $(seq 1 10); do
      kill -0 "$pid" 2>/dev/null || break
      sleep 1
    done
    if kill -0 "$pid" 2>/dev/null; then
      echo "  still running — sending SIGKILL"
      kill -KILL -- "-$pid" 2>/dev/null || kill -KILL "$pid" 2>/dev/null
    fi
  fi
  rm -f "$pidfile"
}

stop_tracked "frontend (next start)" "$E2E_DIR/frontend.pid"
stop_tracked "backend (uvicorn)" "$E2E_DIR/backend.pid"

[ "$APPS_ONLY" = "1" ] && exit 0

echo "▶ Stopping local Supabase…"
supabase stop || { echo "✗ supabase stop failed"; exit 1; }

echo "✅ E2E stack is down. Logs from the last run are kept in .e2e/."
