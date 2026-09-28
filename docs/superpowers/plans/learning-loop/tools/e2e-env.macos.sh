# Learning-loop series: macOS E2E environment (Colima + Supabase CLI, no Docker Desktop).
# Setup used on 2026-09-27; see CONTINUE.md. Expects these under ~/.local/opt (symlinked into
# ~/.local/bin): lima 2.2.0, colima 0.10.3, docker CLI (static client), supabase CLI 2.116.0,
# GNU bash 5 at ~/.local/opt/sapling-e2e/bin, Python shims for flock and setsid, and the
# venv-python shim that binds uvicorn to 127.0.0.1/::1 when AirPlay Receiver holds *:5000.
# Contains no secrets: function mode uses a dummy GEMINI_API_KEY.
# e2e-env.sh — source this (bash or zsh) before ANY Sapling local-E2E stack
# command on this Mac (arm64, no sudo/Homebrew). Then run whole cycles with:
#
#   e2e_cycle <repo_dir> [playwright args...]
#
# Tooling (all userland, ~/.local/opt/<tool>, symlinked into ~/.local/bin):
#   lima 2.2.0 (limactl), colima 0.10.3 (vz VM, docker runtime), docker CLI
#   29.8.1 (client only), supabase CLI 2.116.0 (the version e2e.yml pins),
#   python shims for util-linux `flock` and `setsid` (macOS ships neither),
#   bash 5.3.20 (built from GNU source; macOS /bin/bash 3.2 cannot parse
#   scripts/lib/local-common.sh),
#   and ~/.local/opt/sapling-e2e/venv-python (see "macOS port quirks" below).
#
# macOS port quirks e2e_cycle handles WITHOUT touching tracked repo files:
#   :5000  macOS ControlCenter (AirPlay Receiver) listens on *:5000, so
#          uvicorn's 0.0.0.0:5000 bind fails. e2e_cycle exports VENV_PY (which
#          scripts/lib/local-common.sh honours) = a pass-through shim that
#          serves uvicorn on 127.0.0.1:5000 + [::1]:5000 instead, ONLY when
#          the wildcard bind is actually refused. Turning AirPlay Receiver off
#          (System Settings > General > AirDrop & Handoff) makes it a no-op.
#   :3000  if something else (another project's `next`) already listens,
#          e2e_cycle picks the first free port in 3001-3010 and exports
#          FRONTEND_PORT + E2E_FRONTEND_URL, the two overrides e2e-up.sh and
#          frontend/e2e/support/stack.ts already read.
#
# The stack is a machine singleton: e2e_cycle holds $STACK_LOCK (the path
# scripts/explore.sh and gallery-shots.sh use) for the WHOLE up -> test ->
# oracles -> down cycle in ONE flock. Never flock `up` and `down` separately.

# bash 5 FIRST: scripts/lib/local-common.sh does not parse under macOS's
# /bin/bash 3.2 (a heredoc with an apostrophe inside $(...) -> "unexpected EOF
# while looking for matching '"), so every `#!/usr/bin/env bash` stack script
# must resolve to the bash 5.3.20 built under ~/.local/opt (scoped to this
# file on purpose: ~/.local/bin/bash would change every user script).
export PATH="$HOME/.local/opt/sapling-e2e/bin:$HOME/.local/bin:$PATH"
export DOCKER_HOST="unix://$HOME/.colima/default/docker.sock"
# Explicit, so local-common.sh never probes for podman.
export CONTAINER_CMD=docker

if ! colima status >/dev/null 2>&1; then
  echo "e2e-env: colima not running — starting it (≈1 min)…" >&2
  colima start >/dev/null 2>&1 || echo "e2e-env: ✗ colima start failed — run 'colima start' to see why" >&2
fi

# Node 22: frontend engines pin npm >=10.9 <11 (engine-strict); node 24 fails.
if [ -s "$HOME/.nvm/nvm.sh" ]; then
  . "$HOME/.nvm/nvm.sh" && nvm use 22 >/dev/null
fi

export STACK_LOCK="/tmp/claude-$(id -u)/sapling-e2e-stack.lock"
mkdir -p "${STACK_LOCK%/*}"

E2E_ENV_SCRATCH="${E2E_ENV_SCRATCH:-${TMPDIR:-/tmp}/sapling-e2e}"
export E2E_LOG_DIR="${E2E_LOG_DIR:-$E2E_ENV_SCRATCH/e2e-logs}"

# e2e_cycle <repo_dir> [playwright args...]
#
# ONE flock around: make e2e-up && (cd frontend && npx playwright test ARGS);
# then the oracles; then make e2e-down — teardown ALWAYS runs (also on
# SIGINT/SIGTERM via a trap; only SIGKILL can skip it). Full output of every
# step goes to a log file whose path is printed first; stdout gets a short
# summary. Exit code = max(playwright-or-up rc, oracle rc, e2e-down rc).
# 75 = gave up waiting for the lock (E2E_LOCK_WAIT seconds, default 5400).
#
# A cold first cycle takes >10 min (image pulls + Next build): run it with the
# Bash tool's run_in_background, not in the foreground.
#
# Env knobs (all optional):
#   SAPLING_MODEL_MODE / SAPLING_FUNCTION_HANDLERS  default function /
#       agents.function_handlers_e2e, exactly as e2e.yml; in function mode
#       GEMINI_API_KEY is forced to a dummy so nothing can bill.
#   E2E_MID_HOOK   shell snippet run from <repo_dir> while the stack is still
#                  up (BEFORE the oracles, so the oracles judge its writes) — e.g. a DB probe.
#   E2E_FRESH_DB=1 drop the Supabase volumes before e2e-up, so migrations
#                  replay from EMPTY (the DB volume is shared by every
#                  checkout: project_id "sapling" names the containers/volume).
#   FRONTEND_PORT  force the frontend port instead of auto-picking.
#   E2E_LOCK_WAIT  seconds to wait for the stack lock (default 5400).
e2e_cycle() {
  if [ $# -lt 1 ] || [ ! -d "$1/frontend" ] || [ ! -d "$1/backend" ]; then
    echo "usage: e2e_cycle <repo_dir> [playwright args...]" >&2
    return 2
  fi
  local repo log
  repo="$(cd "$1" && pwd -P)"
  shift
  mkdir -p "$E2E_LOG_DIR"
  log="$E2E_LOG_DIR/cycle-$(date +%Y%m%d-%H%M%S)-$$.log"
  : >"$log"
  echo "e2e_cycle: log → $log"
  echo "e2e_cycle: waiting for stack lock $STACK_LOCK (up to ${E2E_LOCK_WAIT:-5400}s)…"
  command flock -w "${E2E_LOCK_WAIT:-5400}" -E 75 "$STACK_LOCK" bash -c '
    repo="$1"; log="$2"; shift 2
    t0=$(date +%s)
    cd "$repo" || exit 2
    echo "e2e_cycle: lock acquired $(date "+%H:%M:%S") — repo $repo"

    export SAPLING_MODEL_MODE="${SAPLING_MODEL_MODE:-function}"
    export SAPLING_FUNCTION_HANDLERS="${SAPLING_FUNCTION_HANDLERS:-agents.function_handlers_e2e}"
    if [ "$SAPLING_MODEL_MODE" = function ]; then
      export GEMINI_API_KEY=e2e-dummy-key-no-billing
    fi
    export QUIZ_GENERATE_RATE_LIMIT="${QUIZ_GENERATE_RATE_LIMIT:-1000}"
    export SAPLING_REAL_PY="$repo/backend/venv/bin/python"
    export VENV_PY="$HOME/.local/opt/sapling-e2e/venv-python"
    if [ -z "${FRONTEND_PORT:-}" ]; then
      for p in 3000 3001 3002 3003 3004 3005 3006 3007 3008 3009 3010; do
        lsof -nP -iTCP:$p -sTCP:LISTEN >/dev/null 2>&1 || { FRONTEND_PORT=$p; break; }
      done
    fi
    export FRONTEND_PORT="${FRONTEND_PORT:-3000}"
    export E2E_FRONTEND_URL="http://localhost:$FRONTEND_PORT"

    down_done=0; down=0
    teardown() {
      [ "$down_done" = 1 ] && return
      down_done=1
      echo "=== [e2e_cycle] make e2e-down $(date "+%H:%M:%S")" >>"$log"
      make e2e-down >>"$log" 2>&1; down=$?
    }
    trap "teardown; exit 130" INT
    trap "teardown; exit 143" TERM
    trap teardown EXIT

    {
      echo "=== [e2e_cycle] repo=$repo $(date)"
      echo "=== [e2e_cycle] SAPLING_MODEL_MODE=$SAPLING_MODEL_MODE FRONTEND_PORT=$FRONTEND_PORT VENV_PY=$VENV_PY"
      if [ "${E2E_FRESH_DB:-0}" = 1 ]; then
        echo "=== [e2e_cycle] E2E_FRESH_DB=1: supabase stop --no-backup (drop volumes)"
        supabase stop --no-backup
      fi
      echo "=== [e2e_cycle] make e2e-up $(date "+%H:%M:%S")"
    } >>"$log" 2>&1
    make e2e-up >>"$log" 2>&1; up=$?
    t_up=$(date +%s)
    if [ $up -eq 0 ]; then
      echo "=== [e2e_cycle] npx playwright test $* $(date "+%H:%M:%S")" >>"$log"
      (cd frontend && npx playwright test "$@") >>"$log" 2>&1; rc=$?
    else
      echo "=== [e2e_cycle] make e2e-up FAILED (rc=$up) — skipping playwright" >>"$log"
      rc=$up
    fi
    t_pw=$(date +%s)
    if [ -n "${E2E_MID_HOOK:-}" ]; then
      echo "=== [e2e_cycle] E2E_MID_HOOK $(date "+%H:%M:%S")" >>"$log"
      bash -c "$E2E_MID_HOOK" >>"$log" 2>&1
      echo "=== [e2e_cycle] E2E_MID_HOOK exit=$?" >>"$log"
    fi
    echo "=== [e2e_cycle] e2e_oracles $(date "+%H:%M:%S")" >>"$log"
    (cd backend && venv/bin/python -m e2e_oracles) >>"$log" 2>&1; orc=$?
    echo "=== [e2e_cycle] oracles exit=$orc" >>"$log"
    teardown
    left=$(docker ps --filter name=supabase_ --format "{{.Names}}" 2>/dev/null | wc -l | tr -d " ")
    t1=$(date +%s)
    {
      echo "=== [e2e_cycle] done: up=$up playwright=$rc oracles=$orc down=$down supabase_containers_left=$left"
      echo "=== [e2e_cycle] timing: up $((t_up-t0))s, playwright $((t_pw-t_up))s, total $((t1-t0))s"
    } >>"$log"

    echo "── summary ($log)"
    echo "   make e2e-up rc=$up   playwright rc=$rc   oracles rc=$orc   e2e-down rc=$down   supabase containers left=$left"
    echo "   timing: up $((t_up-t0))s · playwright $((t_pw-t_up))s · total $((t1-t0))s"
    if [ $up -ne 0 ]; then
      echo "   e2e-up failure tail:"; sed -n "/make e2e-up [0-9]/,/make e2e-up FAILED/p" "$log" | grep -E "✗|⚠|rror" | tail -n 12 | cut -c1-220 | sed "s/^/     /"
    fi
    grep -E "^[[:space:]]+[0-9]+ (passed|failed|flaky|skipped|did not run|interrupted)" "$log" | sed "s/^ */   playwright: /"
    grep -E "^[[:space:]]+✘" "$log" | cut -c1-220 | sed "s/^ */   FAIL /" | head -n 40
    sed -n "/=== \[e2e_cycle\] e2e_oracles/,/=== \[e2e_cycle\] oracles exit/p" "$log" | grep -v -E "^[[:space:]]+(excerpt|count|first_line):" | tail -n 14 | cut -c1-220 | sed "s/^/   oracle| /"
    final=$rc
    [ $orc -gt $final ] && final=$orc
    [ $down -gt $final ] && final=$down
    trap - EXIT INT TERM
    exit $final
  ' e2e_cycle "$repo" "$log" "$@"
  local _e2e_rc=$?
  [ $_e2e_rc -eq 75 ] && echo "e2e_cycle: ✗ gave up waiting for $STACK_LOCK (another session holds the stack; lsof $STACK_LOCK shows who)"
  echo "e2e_cycle: exit $_e2e_rc — full log: $log"
  return $_e2e_rc
}
