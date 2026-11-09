#!/usr/bin/env bash
#
# Tear down the LOCAL E2E stack booted by scripts/e2e-up.sh (#384).
#
#   make e2e-down                     # stop uvicorn + next, then the slot's Supabase
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

# Which stack: E2E_SLOT if set, else the slot this checkout's e2e-up recorded
# in .e2e/slot (scripts/lib/e2e-slot.sh). With neither, this checkout booted
# nothing — and guessing slot 1 could stop another checkout's run.
source "$REPO_ROOT/scripts/lib/e2e-slot.sh"
E2E_DIR="$REPO_ROOT/.e2e"
if [ -z "${E2E_SLOT:-}" ] && [ ! -f "$E2E_DIR/slot" ] && [ ! -f "$E2E_DIR/booted" ]; then
  echo "✓ nothing booted in this checkout (no .e2e/slot) — nothing to tear down. Set E2E_SLOT=N to stop a slot explicitly."
  exit 0
fi
[ -z "${E2E_SLOT:-}" ] && [ ! -f "$E2E_DIR/slot" ] && E2E_SLOT="$(tr -d '[:space:]' <"$E2E_DIR/booted")"
resolve_e2e_slot "$REPO_ROOT" || exit 1
mapfile -t SUPABASE_ARGS < <(e2e_supabase_args)

# Never another run's slot. A cycle/explore tearing down its own stack passes
# E2E_SLOT_LOCKED=1; a bare e2e-up's slot is held by this checkout's own
# detached holder (.e2e/lock.pid). Any other holder is someone else's run.
OWN_HOLDER=0
if [ -f "$E2E_DIR/lock.pid" ] && kill -0 "$(cat "$E2E_DIR/lock.pid" 2>/dev/null)" 2>/dev/null; then
  OWN_HOLDER=1
fi
if [ "$E2E_SLOT" != "0" ] && [ "${E2E_SLOT_LOCKED:-0}" != "1" ] && [ "$OWN_HOLDER" = "0" ] \
  && ! e2e_slot_is_free "$E2E_SLOT"; then
  echo "✗ E2E slot $E2E_SLOT is held by another run, not this checkout — not tearing it down."
  exit 1
fi

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
stop_tracked "job worker (opt-in)" "$E2E_DIR/worker.pid"

[ "$APPS_ONLY" = "1" ] && exit 0

# A slot's database is throwaway: dropping its volume means the next run on
# the slot migrates and seeds from empty, so no run inherits another branch's
# tables or another checkout's ENCRYPTION_KEY canary. E2E_KEEP_DB=1 keeps it
# (a faster re-run of the same branch). Slot 0 (CI) keeps the old behaviour.
STOP_ARGS=()
if [ "$E2E_SLOT" != "0" ] && [ "${E2E_KEEP_DB:-0}" != "1" ]; then
  STOP_ARGS=(--no-backup)
fi
echo "▶ Stopping Supabase (slot $E2E_SLOT, project $SUPABASE_PROJECT_ID)…"
supabase stop "${SUPABASE_ARGS[@]}" "${STOP_ARGS[@]}" || { echo "✗ supabase stop failed"; exit 1; }

# The manifest pointed the harnesses at this stack; it is gone now.
rm -f "$E2E_DIR/stack.json" "$E2E_DIR/env.sh" "$E2E_DIR/slot" "$E2E_DIR/booted"
# A bare e2e-up's slot lock: released with the stack.
e2e_release_detached_slot_lock "$E2E_DIR"

echo "✅ E2E stack (slot $E2E_SLOT) is down. Logs from the last run are kept in .e2e/."
