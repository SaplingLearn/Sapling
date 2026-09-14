#!/usr/bin/env bash
#
# Capture the twelve /gallery product screenshots.
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
OUT_DIR="$ROOT/frontend/public/gallery"
VENV_PY="$ROOT/backend/venv/bin/python"

die() { echo "✗ $*" >&2; exit 1; }

mkdir -p "$(dirname "$LOCK_FILE")"
exec 9>"$LOCK_FILE"
flock -n 9 || die "e2e stack lock busy ($LOCK_FILE) — another session is using the stack"

[ -x "$VENV_PY" ] || die "no backend venv at $VENV_PY"

teardown() {
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

echo "▶ Capturing twelve screens into $OUT_DIR …"
mkdir -p "$OUT_DIR"
(
  cd frontend
  GALLERY_SHOTS_DIR="$OUT_DIR" npx playwright test gallery-shots.spec.ts --reporter=list
) || die "capture failed — no partial screenshots were committed"

echo
echo "✓ Captured:"
ls -la "$OUT_DIR" | tail -n +2
echo
echo "Review them before committing — these ship on a public page."
