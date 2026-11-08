#!/usr/bin/env bash
#
# Push Sapling screens/states into Figma as editable layers.
#
# usage: scripts/figma-capture.sh <captures.json>        push to Figma
#        scripts/figma-capture.sh --pool <pool.json> <states.json> <promptId>  (chain on nextCaptureId)
#        scripts/figma-capture.sh --dryrun <dir> [ids]  validate recipes → <dir>/*.png + results.json
#   captures.json = [{state, captureId, endpoint}, ...] minted via the Figma MCP
#   generate_figma_design tool. Recipes: frontend/e2e/figma-capture.spec.ts;
#   state ids: docs/figma/inventory/.
#
# (Derived from scripts/gallery-shots.sh — same showcase stack.)
#
# Design: docs/superpowers/specs/2026-09-03-gallery-screenshots-design.md
#
#   boot the deterministic local stack in SHOWCASE mode
#     → overlay the showcase seed
#     → drive twelve screens with Playwright, writing frontend/public/gallery
#     → tear down
#
# Showcase mode is two pieces and needs both. The seed overlay
# (db/seed_showcase.py) fixes what a screenshot reads from the DATABASE —
# display names, room names. The handler module
# (agents/function_handlers_showcase.py) fixes what it reads from an AGENT.
# The rich seed with E2E handlers still photographs "[e2e-function-model]".
#
# LOCAL ONLY. The whole up→capture→down cycle runs inside ONE flock: the local
# stack is a machine singleton, and a separately-flocked teardown deadlocks
# because the detached uvicorn/next children inherit the lock fd (see
# scripts/explore.sh and CLAUDE.md).
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

LOCK_FILE="/tmp/claude-$(id -u)/sapling-e2e-stack.lock"
if [ "${1:-}" = "--pool" ]; then
  MODE=pool; POOL="$(realpath "$2")"; STATES="$(realpath "$3")"; PROMPT="${4:?usage: --pool <pool.json> <states.json> <promptId>}"
elif [ "${1:-}" = "--dryrun" ]; then
  MODE=dryrun; DRY_DIR="$(realpath -m "${2:?usage: figma-capture.sh --dryrun <dir> [ids]}")"; ONLY="${3:-}"
  mkdir -p "$DRY_DIR"
else
  MODE=capture; CAPTURES="$(realpath "${1:?usage: figma-capture.sh <captures.json>}")"
fi
VENV_PY="$ROOT/backend/venv/bin/python"

die() { echo "✗ $*" >&2; exit 1; }

mkdir -p "$(dirname "$LOCK_FILE")"
exec 9>"$LOCK_FILE"
flock -n 9 || die "e2e stack lock busy ($LOCK_FILE) — another session is using the stack"

[ -x "$VENV_PY" ] || die "no backend venv at $VENV_PY"

teardown() {
  echo "▶ Restoring the rich-seed baseline (undo the showcase overlay)…"
  ( cd frontend && node --no-warnings e2e/figma/reset-db.ts ) || echo "⚠ DB reset failed — next e2e-up may 409 on rooms"
  echo "▶ Tearing down the stack…"
  make e2e-down || true
}
trap teardown EXIT

echo "▶ Booting the stack in showcase mode…"
# SEED_RICH stays 1: the rich seed's substance is already photogenic (CS101 /
# MATH210 / BIO110, real concept names, mastery across all four tiers) and it
# creates the rich-* users that /api/auth/test-login signs in as. The showcase
# seed is an OVERLAY on it, not a replacement.
SAPLING_MODEL_MODE=function \
SAPLING_FUNCTION_HANDLERS=agents.function_handlers_showcase \
  make e2e-up || die "make e2e-up failed"

echo "▶ Applying the showcase overlay…"
( cd backend && "$VENV_PY" -m db.seed_showcase ) || die "seed_showcase failed"

if [ "$MODE" = pool ]; then
  echo "▶ Pushing $(python3 -c 'import json,sys;print(len(json.load(open(sys.argv[1]))))' "$STATES") states to Figma (pool+chain)…"
  ( cd frontend && FIGMA_POOL_FILE="$POOL" FIGMA_STATES_FILE="$STATES" FIGMA_PROMPT_ID="$PROMPT" FIGMA_WORKERS="${FIGMA_WORKERS:-4}" npx playwright test figma-capture.spec.ts --reporter=line --workers="${FIGMA_WORKERS:-4}" --fully-parallel ) \
    || echo "✗ some captures failed — see $(dirname "$POOL")/results.json"
elif [ "$MODE" = dryrun ]; then
  echo "▶ Dry run → $DRY_DIR"
  ( cd frontend && FIGMA_DRYRUN_DIR="$DRY_DIR" FIGMA_ONLY="$ONLY" npx playwright test figma-capture.spec.ts --reporter=line ) \
    || echo "✗ some recipes failed — see $DRY_DIR/results.json"
else
  echo "▶ Pushing $(python3 -c 'import json,sys;print(len(json.load(open(sys.argv[1]))))' "$CAPTURES") states to Figma…"
  ( cd frontend && FIGMA_CAPTURES_FILE="$CAPTURES" npx playwright test figma-capture.spec.ts --reporter=line ) \
    || echo "✗ some captures failed — see $(dirname "$CAPTURES")/results.json"
fi
