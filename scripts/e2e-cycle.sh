#!/usr/bin/env bash
#
# The ONE way a local E2E stack exists: a cycle. It claims a free slot (and
# this checkout), runs e2e-up → <command> → e2e-down, and holds both locks for
# its whole life — so everything about who owns a stack lives in this process.
# Concurrent cycles (other worktrees, other sessions) take other slots.
#
#   scripts/e2e-cycle.sh                                   # full Playwright suite + oracles
#   scripts/e2e-cycle.sh -- bash -c 'cd frontend && npx playwright test e2e/quiz*.spec.ts'
#   scripts/e2e-cycle.sh --slot 2 -- <command>             # a specific slot (or E2E_SLOT=2)
#   scripts/e2e-cycle.sh --background                      # hold a stack for manual use (make e2e-up)
#   scripts/e2e-cycle.sh --stop                            # end this checkout's held stack (make e2e-down)
#
# <command> runs in the foreground (your terminal, your Ctrl-C) from the repo
# root with the slot's URLs exported (E2E_FRONTEND_URL, E2E_BACKEND_URL,
# E2E_DB_URL, SUPABASE_DB_URL, …). The cycle's exit code is the command's
# (teardown always runs); 3 means the stack never came up.
#
# --background starts a detached HOLD (a cycle whose command is "stay up";
# log .e2e/cycle.log) and returns once its stack is up; with --new it fails
# (exit 4) instead of reporting a stack this checkout already holds. --stop
# signals the hold and waits for its teardown — and when a hold died without
# one (SIGKILL, OOM), it tears down the stack the hold left behind.
#
# Slots and their ports: scripts/lib/e2e-slot.sh. The dev app's :3000/:5000
# are never used. LOCAL ONLY — CI runs the classic slot 0 through e2e.yml.
set -uo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT" || exit 1
source "$REPO_ROOT/scripts/lib/e2e-slot.sh"
E2E_DIR="$REPO_ROOT/.e2e"
mkdir -p "$E2E_LOCK_DIR" "$E2E_DIR"
CHECKOUT_LOCK="$E2E_DIR/cycle.lock"
# This script by absolute path: the cd above would break a relative $0.
SELF="$REPO_ROOT/scripts/e2e-cycle.sh"

MODE=run
NEW=0
WANT_SLOT="${E2E_SLOT:-}"
WAIT_S="${E2E_SLOT_WAIT_S:-3600}"
while [ $# -gt 0 ]; do
  case "$1" in
    --slot) WANT_SLOT="${2:-}"; shift; [ $# -gt 0 ] && shift ;;
    --background) MODE=background; shift ;;
    --new) NEW=1; shift ;;
    --stop) MODE=stop; shift ;;
    --hold) MODE=hold; shift ;;   # internal: what --background runs detached
    --) shift; break ;;
    -h|--help) sed -n '2,26p' "$SELF"; exit 0 ;;
    *) break ;;
  esac
done
case "$WANT_SLOT" in
  *[!0-9]*) echo "✗ --slot / E2E_SLOT must be a slot number (1..$E2E_SLOTS_MAX), got '$WANT_SLOT'"; exit 2 ;;
esac

# Detach children into their own session (and process group) where setsid
# exists, so one group signal reaches a whole step. A background child of a
# non-interactive shell is never a group leader, so setsid execs in place and
# $! stays the child's pid. Git Bash has no setsid: plain children there.
DETACH=()
command -v setsid >/dev/null 2>&1 && DETACH=(setsid)

checkout_busy() { ! flock -n "$CHECKOUT_LOCK" true 2>/dev/null; }

held_pid() { e2e_held_cycle_pid "$REPO_ROOT"; }

# A cycle that died without its teardown (SIGKILL, OOM) leaves .e2e/booted
# behind, naming its slot — and its servers and containers keep running.
# Tear that stack down the way the cycle would have: under the slot's lock.
# The caller holds this checkout's lock (fd 8), so no live cycle here owns it.
recover_orphan() {
  local slot rc
  slot="$(tr -d '[:space:]' <"$E2E_DIR/booted")"
  case "$slot" in ''|*[!0-9]*) echo "✗ .e2e/booted does not name a slot — inspect .e2e/ by hand"; return 1 ;; esac
  exec 9>"$(e2e_slot_lock_file "$slot")"
  if ! flock -n 9; then
    exec 9>&-
    echo "✗ a cycle that died left its stack in slot $slot, and another run holds slot $slot now —"
    echo "  not touching it. Once that run ends: make e2e-down"
    return 1
  fi
  echo "▶ A cycle here died without its teardown — stopping the stack it left in slot $slot…"
  ( export E2E_SLOT="$slot" E2E_SLOT_LOCKED=1; "$REPO_ROOT/scripts/e2e-down.sh" )
  rc=$?
  exec 9>&-
  return $rc
}

# ── --stop: end this checkout's held stack ───────────────────────────────────
if [ "$MODE" = "stop" ]; then
  if pid="$(held_pid)"; then
    echo "▶ Stopping the held E2E stack (cycle pid $pid; teardown log: .e2e/cycle.log)…"
    kill -TERM "$pid" 2>/dev/null
    for _ in $(seq 1 300); do
      kill -0 "$pid" 2>/dev/null || break
      sleep 1
    done
    if kill -0 "$pid" 2>/dev/null; then
      echo "✗ the cycle did not finish its teardown within 5 minutes (pid $pid) — see .e2e/cycle.log"
      exit 1
    fi
    tail -n 2 "$E2E_DIR/cycle.log" 2>/dev/null | sed 's/^/  /'
    exit 0
  fi
  if checkout_busy; then
    echo "✗ a foreground E2E cycle is running in this checkout — it tears down when its command ends (Ctrl-C it)."
    exit 1
  fi
  rm -f "$E2E_DIR/cycle.pid" "$E2E_DIR/ready"
  if [ ! -f "$E2E_DIR/booted" ]; then
    echo "✓ no held E2E stack in this checkout — nothing to stop."
    exit 0
  fi
  exec 8>"$CHECKOUT_LOCK"
  flock -n 8 || { echo "✗ a cycle just started in this checkout — try again once it is done"; exit 1; }
  recover_orphan
  exit $?
fi

# ── --background: start a hold detached, return once it is up ───────────────
if [ "$MODE" = "background" ]; then
  OURS=1
  if pid="$(held_pid)"; then
    if [ "$NEW" = "1" ]; then
      echo "✗ this checkout already holds an E2E stack (cycle pid $pid) — stop it first (make e2e-down)."
      exit 4
    fi
    # Someone else's hold: report it once it is up, never before (a caller
    # that runs Playwright next needs the stack, not just the process).
    OURS=0
    echo "✓ this checkout already holds an E2E stack (cycle pid $pid)…"
  else
    if checkout_busy; then
      echo "✗ an E2E cycle is running in this checkout — wait for it, or hold a stack from another worktree."
      exit 3
    fi
    printf '\n── hold started %s ──\n' "$(date -Iseconds)" >>"$E2E_DIR/cycle.log"
    "${DETACH[@]}" "$SELF" ${WANT_SLOT:+--slot "$WANT_SLOT"} --hold >>"$E2E_DIR/cycle.log" 2>&1 </dev/null &
    pid=$!
    # Leaving early (Ctrl-C) or giving up must not strand a hold that is
    # still booting: it would come up later with nobody waiting for it.
    trap 'kill -TERM "$pid" 2>/dev/null; echo; echo "✗ interrupted — the hold is tearing down (log: .e2e/cycle.log)"; exit 130' INT TERM
    echo "▶ Holding an E2E stack in the background (cycle pid $pid, log: .e2e/cycle.log)…"
  fi
  # The hold writes its own pid into .e2e/ready once its stack is up, so a
  # ready file left by an earlier hold never passes for this one. Waiting for
  # a slot is bounded by the hold itself (E2E_SLOT_WAIT_S); the boot after it
  # gets 20 more minutes.
  deadline=$(( $(date +%s) + WAIT_S + 1200 ))
  told=0
  while [ "$(cat "$E2E_DIR/ready" 2>/dev/null)" != "$pid" ]; do
    if ! kill -0 "$pid" 2>/dev/null; then
      echo "✗ the cycle exited before its stack came up:"
      tail -n 25 "$E2E_DIR/cycle.log" | sed 's/^/    /'
      exit 3
    fi
    if [ "$told" = "0" ] && tail -n 5 "$E2E_DIR/cycle.log" 2>/dev/null | grep -q 'every E2E slot is busy'; then
      echo "  … every E2E slot is busy — waiting for one to free up (up to ${WAIT_S}s)"
      told=1
    fi
    if [ "$(date +%s)" -ge "$deadline" ]; then
      [ "$OURS" = "1" ] && kill -TERM "$pid" 2>/dev/null
      echo "✗ the stack did not come up in time — see .e2e/cycle.log"
      exit 3
    fi
    sleep 1
  done
  slot="$(e2e_manifest_slot "$REPO_ROOT")"
  # shellcheck disable=SC1091
  source "$E2E_DIR/env.sh"
  echo "✅ E2E slot $slot is up: $E2E_FRONTEND_URL (backend $E2E_BACKEND_URL)"
  echo "   In a browser use http://127.0.0.1:${E2E_FRONTEND_URL##*:} — a localhost cookie would sign the dev app out."
  echo "   Harnesses read .e2e/stack.json; a shell can \`source .e2e/env.sh\`. Stop it: make e2e-down"
  exit 0
fi

# ── a cycle: run (foreground command) or hold (for --background) ────────────
if [ "$MODE" = "run" ] && [ $# -eq 0 ]; then
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
exec 8>"$CHECKOUT_LOCK"
if ! flock -n 8; then
  echo "✗ an E2E cycle is already running in this checkout ($REPO_ROOT)."
  echo "  .e2e/ and frontend/.next are per checkout — run concurrent cycles from separate worktrees,"
  echo "  or stop this checkout's held stack first (make e2e-down)."
  exit 3
fi
[ "$MODE" = "hold" ] && echo "$$" >"$E2E_DIR/cycle.pid"
# A stack a dead cycle left here would be clobbered by this one's boot (same
# .e2e/ PID files and markers) and then never torn down: stop it first.
if [ -f "$E2E_DIR/booted" ]; then
  recover_orphan || exit 3
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

CHILD=""
teardown() {
  # Once teardown starts it finishes: a second TERM (another --stop, a
  # second Ctrl-C) must not cut it short before e2e-down has run.
  trap '' INT TERM
  if [ -n "$CHILD" ]; then
    if [ ${#DETACH[@]} -gt 0 ]; then kill -TERM -- "-$CHILD" 2>/dev/null; else kill -TERM "$CHILD" 2>/dev/null; fi
    wait "$CHILD" 2>/dev/null
  fi
  rm -f "$E2E_DIR/ready"
  if [ -f "$E2E_DIR/booted" ]; then
    "$REPO_ROOT/scripts/e2e-down.sh" || true
  elif [ -n "${CLAIMED:-}" ]; then
    echo "  (nothing booted by this cycle — no teardown)"
  fi
  [ "$MODE" = "hold" ] && [ "$(cat "$E2E_DIR/cycle.pid" 2>/dev/null)" = "$$" ] && rm -f "$E2E_DIR/cycle.pid"
}
trap teardown EXIT
trap 'exit 130' INT TERM

CLAIMED=""
deadline=$(( $(date +%s) + WAIT_S ))
announced=0
while [ -z "$CLAIMED" ]; do
  if [ -n "$WANT_SLOT" ]; then
    claim "$WANT_SLOT" && break
  else
    for n in $(seq 1 "$E2E_SLOTS_MAX"); do
      claim "$n" || continue
      # A free lock over busy ports: a stack whose cycle died without its
      # teardown. Leave it (its checkout's next cycle or make e2e-down
      # recovers it) and try the next slot.
      if e2e_slot_ports_busy "$n"; then
        echo "  ! slot $n is unlocked but its ports are in use (a stack left by a cycle that died?) — skipping it"
        CLAIMED=""
        exec 9>&-
        continue
      fi
      break
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
rm -f "$E2E_DIR/booted"

if [ "$MODE" = "hold" ]; then
  # A hold has no terminal and must answer --stop at any point, booting
  # included. Bash runs a trap only between commands, so each step runs in the
  # background in its own group and the hold WAITS on it: `wait` returns as
  # soon as the TERM arrives, and teardown signals the whole step.
  # Children never inherit the lock fds (8, 9): only this process may hold
  # them, so a hold killed outright (SIGKILL, OOM) frees its slot and its
  # checkout at once, and the next cycle or --stop can recover its stack.
  step() { "${DETACH[@]}" "$@" 8>&- 9>&- & CHILD=$!; wait "$CHILD"; local rc=$?; CHILD=""; return $rc; }
  step "$REPO_ROOT/scripts/e2e-up.sh" || exit 3
  echo "$$" >"$E2E_DIR/ready"
  # Stay up. Short sleeps rather than one long child: nothing outlives a
  # killed hold by more than a few seconds, and a TERM interrupts the wait.
  while :; do
    sleep 5 8>&- 9>&- &
    wait $!
  done
fi

# A run is the user's: the command keeps the terminal (stdin, Ctrl-C reaches
# its whole tree), and teardown follows when it ends either way. Like a
# hold's steps it never inherits the lock fds, so a child that outlives the
# cycle (an orphaned oracle, say) cannot keep the slot or the checkout taken.
"$REPO_ROOT/scripts/e2e-up.sh" 8>&- 9>&- || exit 3
"$@" 8>&- 9>&-
exit $?
