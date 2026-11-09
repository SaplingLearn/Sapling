#!/usr/bin/env bash
#
# The ONE way a local E2E stack exists: a cycle. It claims a free slot (and
# this checkout), runs e2e-up → <command> → e2e-down, and holds both locks for
# its whole life — so everything about who owns a stack lives in this process.
# Concurrent cycles (other worktrees, other sessions) take other slots.
#
#   scripts/e2e-cycle.sh                                   # full Playwright suite + oracles
#   scripts/e2e-cycle.sh -- bash -c 'cd frontend && npx playwright test e2e/quiz*.spec.ts'
#   scripts/e2e-cycle.sh --slot 2 -- <command>             # a specific slot
#   scripts/e2e-cycle.sh --background                      # hold a stack for manual use (make e2e-up)
#   scripts/e2e-cycle.sh --stop                            # end this checkout's held stack (make e2e-down)
#
# <command> runs from the repo root with the slot's URLs exported
# (E2E_FRONTEND_URL, E2E_BACKEND_URL, E2E_DB_URL, SUPABASE_DB_URL, …).
# The cycle's exit code is the command's (teardown always runs); 3 means the
# stack never came up. --background returns once the stack is up and leaves
# the cycle running detached (log: .e2e/cycle.log); --stop signals it and
# waits for its teardown.
#
# Slots and their ports: scripts/lib/e2e-slot.sh. The dev app's :3000/:5000
# are never used. LOCAL ONLY — CI runs the classic slot 0 through e2e.yml.
set -uo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT" || exit 1
source "$REPO_ROOT/scripts/lib/e2e-slot.sh"
E2E_DIR="$REPO_ROOT/.e2e"
mkdir -p "$E2E_LOCK_DIR" "$E2E_DIR"

MODE=run
WANT_SLOT=""
WAIT_S="${E2E_SLOT_WAIT_S:-3600}"
while [ $# -gt 0 ]; do
  case "$1" in
    --slot)
      case "${2:-}" in
        ''|*[!0-9]*) echo "✗ --slot needs a slot number (1..$E2E_SLOTS_MAX)"; exit 2 ;;
      esac
      WANT_SLOT="$2"; shift 2 ;;
    --background) MODE=background; shift ;;
    --stop) MODE=stop; shift ;;
    --hold) MODE=hold; shift ;;   # internal: what --background runs detached
    --) shift; break ;;
    -h|--help) sed -n '2,22p' "$0"; exit 0 ;;
    *) break ;;
  esac
done

held_pid() { # the detached cycle this checkout started, if it is alive
  local pid
  pid="$(cat "$E2E_DIR/cycle.pid" 2>/dev/null)" || return 1
  [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null && echo "$pid"
}

# ── --stop: end this checkout's held stack ───────────────────────────────────
if [ "$MODE" = "stop" ]; then
  if ! pid="$(held_pid)"; then
    echo "✓ no held E2E stack in this checkout — nothing to stop."
    rm -f "$E2E_DIR/cycle.pid" "$E2E_DIR/ready"
    exit 0
  fi
  echo "▶ Stopping the held E2E stack (cycle pid $pid; teardown log: .e2e/cycle.log)…"
  kill -TERM "$pid" 2>/dev/null
  for _ in $(seq 1 180); do
    kill -0 "$pid" 2>/dev/null || break
    sleep 1
  done
  if kill -0 "$pid" 2>/dev/null; then
    echo "✗ the cycle did not finish its teardown within 3 minutes (pid $pid) — see .e2e/cycle.log"
    exit 1
  fi
  rm -f "$E2E_DIR/cycle.pid" "$E2E_DIR/ready"
  tail -n 2 "$E2E_DIR/cycle.log" 2>/dev/null | sed 's/^/  /'
  exit 0
fi

# ── --background: start a held cycle detached, return once it is up ─────────
if [ "$MODE" = "background" ]; then
  if pid="$(held_pid)"; then
    echo "✓ this checkout already holds an E2E stack (cycle pid $pid):"
    sed -n 's/^export \(E2E_SLOT\|E2E_FRONTEND_URL\|E2E_BACKEND_URL\)=/  \1=/p' "$E2E_DIR/env.sh" 2>/dev/null
    exit 0
  fi
  rm -f "$E2E_DIR/ready"
  DETACH_CMD=()
  command -v setsid >/dev/null 2>&1 && DETACH_CMD=(setsid)
  "${DETACH_CMD[@]}" "$0" ${WANT_SLOT:+--slot "$WANT_SLOT"} --hold >"$E2E_DIR/cycle.log" 2>&1 </dev/null &
  pid=$!
  echo "$pid" >"$E2E_DIR/cycle.pid"
  echo "▶ Holding an E2E stack in the background (cycle pid $pid, log: .e2e/cycle.log)…"
  for _ in $(seq 1 1200); do
    [ -f "$E2E_DIR/ready" ] && break
    if ! kill -0 "$pid" 2>/dev/null; then
      echo "✗ the cycle exited before its stack came up:"
      tail -n 25 "$E2E_DIR/cycle.log" | sed 's/^/    /'
      rm -f "$E2E_DIR/cycle.pid"
      exit 3
    fi
    sleep 1
  done
  if [ ! -f "$E2E_DIR/ready" ]; then
    echo "✗ the stack did not come up within 20 minutes — see .e2e/cycle.log"
    exit 3
  fi
  # shellcheck disable=SC1091
  source "$E2E_DIR/env.sh"
  echo "✅ E2E slot $E2E_SLOT is up: $E2E_FRONTEND_URL (backend $E2E_BACKEND_URL)"
  echo "   Harnesses read .e2e/stack.json; a shell can \`source .e2e/env.sh\`. Stop it: make e2e-down"
  exit 0
fi

# ── a cycle: run (foreground command) or hold (for --background) ────────────
if [ "$MODE" = "hold" ]; then
  set -- bash -c 'touch "$0/.e2e/ready" && exec sleep infinity' "$REPO_ROOT"
elif [ $# -eq 0 ]; then
  # The default: the whole browser suite, then the deterministic judges.
  set -- bash -c 'cd frontend && npx playwright test; pw=$?; cd ../backend && venv/bin/python -m e2e_oracles; or=$?; [ $pw -ne 0 ] && exit $pw; exit $or'
fi

# The deterministic lane by default: function-mode agents replaying the E2E_*
# handler constants (what e2e.yml and explore.sh run). A caller that exports
# SAPLING_MODEL_MODE (e.g. =real, to look at a branch with live models) keeps it.
export SAPLING_MODEL_MODE="${SAPLING_MODEL_MODE:-function}"
if [ "$SAPLING_MODEL_MODE" = "function" ]; then
  export SAPLING_FUNCTION_HANDLERS="${SAPLING_FUNCTION_HANDLERS:-agents.function_handlers_e2e}"
fi

# One cycle per CHECKOUT: .e2e/ (server PIDs, logs, manifest) and the
# frontend's .next build are per checkout, so two cycles here would stop each
# other's servers and overwrite each other's build. Concurrent cycles come
# from separate worktrees — each takes its own slot. Held on fd 8 for the life
# of this process, like the slot lock on fd 9.
exec 8>"$E2E_DIR/cycle.lock"
if ! flock -n 8; then
  echo "✗ an E2E cycle is already running in this checkout ($REPO_ROOT)."
  echo "  .e2e/ and frontend/.next are per checkout — run concurrent cycles from separate worktrees,"
  echo "  or stop this checkout's held stack first (make e2e-down)."
  exit 3
fi

# Claim a slot: the requested one (waiting for it), else the first free one
# (waiting until any frees up). The lock fd stays open for the rest of this
# process, so the slot is ours until we exit.
claim() { # slot → 0 claimed
  local file
  file="$(e2e_slot_lock_file "$1")"
  exec 9>"$file"
  if flock -n 9; then
    CLAIMED="$1"
    return 0
  fi
  exec 9>&-
  return 1
}

CLAIMED=""
deadline=$(( $(date +%s) + WAIT_S ))
announced=0
while [ -z "$CLAIMED" ]; do
  if [ -n "$WANT_SLOT" ]; then
    claim "$WANT_SLOT" && break
  else
    for n in $(seq 1 "$E2E_SLOTS_MAX"); do
      claim "$n" && break
    done
    [ -n "$CLAIMED" ] && break
  fi
  if [ "$(date +%s)" -ge "$deadline" ]; then
    echo "✗ no E2E slot came free within ${WAIT_S}s"
    exit 3
  fi
  if [ "$announced" = "0" ]; then
    echo "… every E2E slot is busy (${WANT_SLOT:-1..$E2E_SLOTS_MAX}); waiting for one to free up"
    announced=1
  fi
  sleep 5
done

export E2E_SLOT="$CLAIMED"
export E2E_SLOT_LOCKED=1
resolve_e2e_slot "$REPO_ROOT" || exit 3
# Oracles and pytest read SUPABASE_DB_URL; the cycle's command gets this slot's.
export SUPABASE_DB_URL="$E2E_DB_URL"
echo "▶ E2E cycle in slot $E2E_SLOT ($E2E_FRONTEND_URL)"

# Tear down only what this cycle booted. e2e-up writes .e2e/booted just
# before it starts Supabase, so a boot refused at preflight (a port held by
# someone else's server, say) never makes this cycle stop a project — and drop
# a database — that isn't its own.
rm -f "$E2E_DIR/booted" "$E2E_DIR/ready"
CHILD=""
teardown() {
  [ -n "$CHILD" ] && kill "$CHILD" 2>/dev/null
  rm -f "$E2E_DIR/ready"
  if [ -f "$E2E_DIR/booted" ]; then
    "$REPO_ROOT/scripts/e2e-down.sh" || true
  else
    echo "  (nothing booted by this cycle — no teardown)"
  fi
}
trap teardown EXIT
trap 'exit 130' INT TERM

"$REPO_ROOT/scripts/e2e-up.sh" || exit 3

# The command runs in the background and this process WAITS on it: bash only
# runs a trap between commands, so a foreground `sleep infinity` (a held
# stack) would never let --stop's TERM reach the teardown; `wait` returns as
# soon as a trapped signal arrives.
"$@" &
CHILD=$!
wait "$CHILD"
rc=$?
CHILD=""
exit "$rc"
