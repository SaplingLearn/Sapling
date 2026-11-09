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
# LOCAL ONLY. The whole up→capture→down cycle runs as ONE scripts/e2e-cycle.sh
# cycle, which claims a free E2E slot (scripts/lib/e2e-slot.sh) and holds its
# lock throughout — so a capture never waits on, or collides with, another
# session's run, and never touches the dev app's :3000/:5000.
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

OUT_DIR="$ROOT/frontend/public/gallery"
VENV_PY="$ROOT/backend/venv/bin/python"

die() { echo "✗ $*" >&2; exit 1; }

[ -x "$VENV_PY" ] || die "no backend venv at $VENV_PY"

# SEED_RICH stays 1: the rich seed's substance is already photogenic (CS101 /
# MATH210 / BIO110, real concept names, mastery across all four tiers) and it
# creates the rich-* users that /api/auth/test-login signs in as. The showcase
# seed is an OVERLAY on it, not a replacement. The cycle exports the slot's
# SUPABASE_DB_URL / SUPABASE_URL, so the overlay lands in that slot's database.
export SAPLING_MODEL_MODE=function
export SAPLING_FUNCTION_HANDLERS=agents.function_handlers_showcase
export GALLERY_OUT_DIR="$OUT_DIR"

"$ROOT/scripts/e2e-cycle.sh" -- bash -c '
  echo "▶ Applying the showcase overlay…"
  ( cd backend && venv/bin/python -m db.seed_showcase ) || { echo "✗ seed_showcase failed"; exit 1; }
  echo "▶ Capturing twelve screens into $GALLERY_OUT_DIR …"
  mkdir -p "$GALLERY_OUT_DIR"
  ( cd frontend && GALLERY_SHOTS_DIR="$GALLERY_OUT_DIR" npx playwright test gallery-shots.spec.ts --reporter=list ) \
    || { echo "✗ capture failed — no partial screenshots were committed"; exit 1; }
' || die "gallery capture cycle failed"

echo
echo "✓ Captured:"
ls -la "$OUT_DIR" | tail -n +2
echo
echo "Review them before committing — these ship on a public page."
