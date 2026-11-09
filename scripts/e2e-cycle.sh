#!/usr/bin/env bash
#
# One whole E2E cycle in a free slot: claim a slot → e2e-up → <command> →
# e2e-down, under that slot's lock. Concurrent cycles (other worktrees, other
# sessions) take other slots instead of queueing behind one machine-wide lock.
#
#   scripts/e2e-cycle.sh                                   # full Playwright suite + oracles
#   scripts/e2e-cycle.sh -- npx playwright test e2e/quiz*.spec.ts
#   scripts/e2e-cycle.sh --slot 2 -- npx playwright test   # a specific slot
#   make e2e                                               # the default cycle
#
# <command> runs from the repo root with the slot's URLs exported
# (E2E_FRONTEND_URL, E2E_BACKEND_URL, E2E_DB_URL, SUPABASE_DB_URL, …), so
# `npx playwright test` needs `cd frontend &&` like any other invocation.
# The cycle's exit code is the command's (teardown always runs); 3 means the
# stack never came up.
#
# Slots and their ports: scripts/lib/e2e-slot.sh. The dev app's :3000/:5000
# are never used. LOCAL ONLY — CI runs the classic slot 0 through e2e.yml.
set -uo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT" || exit 1
source "$REPO_ROOT/scripts/lib/e2e-slot.sh"

WANT_SLOT=""
WAIT_S="${E2E_SLOT_WAIT_S:-3600}"
while [ $# -gt 0 ]; do
  case "$1" in
    --slot)
      case "${2:-}" in
        ''|*[!0-9]*) echo "✗ --slot needs a slot number (1..$E2E_SLOTS_MAX)"; exit 2 ;;
      esac
      WANT_SLOT="$2"; shift 2 ;;
    --) shift; break ;;
    -h|--help) sed -n '2,20p' "$0"; exit 0 ;;
    *) break ;;
  esac
done

if [ $# -eq 0 ]; then
  # The default: the whole browser suite, then the deterministic judges.
  set -- bash -c 'cd frontend && npx playwright test; pw=$?; cd ../backend && venv/bin/python -m e2e_oracles; or=$?; [ $pw -ne 0 ] && exit $pw; exit $or'
fi

mkdir -p "$E2E_LOCK_DIR" "$REPO_ROOT/.e2e"

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
# of this script, like the slot lock on fd 9.
exec 8>"$REPO_ROOT/.e2e/cycle.lock"
if ! flock -n 8; then
  echo "✗ an E2E cycle is already running in this checkout ($REPO_ROOT)."
  echo "  .e2e/ and frontend/.next are per checkout — run concurrent cycles from separate worktrees."
  exit 3
fi

# Claim a slot: the requested one (waiting for it), else the first free one
# (waiting until any frees up). The lock fd stays open for the rest of this
# script, so the slot is ours until we exit.
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
rm -f "$REPO_ROOT/.e2e/booted"
teardown() {
  if [ -f "$REPO_ROOT/.e2e/booted" ]; then
    "$REPO_ROOT/scripts/e2e-down.sh" || true
  else
    echo "  (nothing booted by this cycle — no teardown)"
  fi
}
trap teardown EXIT
trap 'exit 130' INT TERM

"$REPO_ROOT/scripts/e2e-up.sh" || exit 3

"$@"
rc=$?
exit "$rc"
