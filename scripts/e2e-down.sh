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

# $CONTAINER_CMD / $VENV_PY / set_docker_host_for_podman. Sourced (rather than
# inlining the DOCKER_HOST export as before) so up and down agree exactly on
# which daemon they talk to — see the guard's comment in local-common.sh for
# why exporting the Linux socket path unconditionally broke Windows.
source "$REPO_ROOT/scripts/lib/local-common.sh"
set_docker_host_for_podman

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
    # Windows fallback. Without setsid (Git Bash) the recorded PID leads no
    # process group, so both group kills above no-op and a plain SIGKILL to the
    # `npm run start:test` wrapper leaves the real next-server child running
    # and holding :3000 — the next e2e-up then fails its port preflight. Walk
    # the actual process tree instead. Only reached when the PID survived the
    # POSIX path, so it never fires on Linux/CI.
    if kill -0 "$pid" 2>/dev/null && command -v taskkill >/dev/null 2>&1; then
      echo "  still running — taskkill /T (no setsid on this platform)"
      taskkill //T //F //PID "$pid" >/dev/null 2>&1 || true
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
