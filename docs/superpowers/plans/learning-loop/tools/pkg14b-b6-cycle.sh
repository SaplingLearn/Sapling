#!/usr/bin/env bash
# PKG-14 half B, Task B6 (spec §11.4): BOTH E2E lanes, the local kill-switch
# drill, the real-SQL integration tests and the local loop smoke — in ONE
# up→test→down sequence. Run it under ONE flock invocation (CLAUDE.md: the stack
# is a machine singleton; never separate flocks for up and down):
#
#   cd <worktree root>
#   flock /tmp/claude-$(id -u)/sapling-e2e-stack.lock \
#     bash docs/superpowers/plans/learning-loop/tools/pkg14b-b6-cycle.sh
#
# Optional: FRONTEND_PORT=3100 E2E_FRONTEND_URL=http://localhost:3100 when :3000
# is taken (e2e-down kills by PID, never by port). The last line is the gate:
#   default: playwright=0 oracles=0 integration=0 drill=0  kill-switch: playwright=0 oracles=0 drill=0
#
# It writes nothing outside the local stack and .e2e/. It never touches staging
# or production.
set -u
cd "$(dirname "${BASH_SOURCE[0]}")/../../../../.." || exit 2
[ -f backend/.env ] || { echo "✗ backend/.env missing"; exit 2; }
if grep -qE '^[[:space:]]*(export[[:space:]]+)?LEARNING_LOOP_ENABLED=' backend/.env; then
  echo "✗ remove LEARNING_LOOP_ENABLED from backend/.env (spec §11.4)"; exit 2
fi

# Function mode for the stack AND Playwright (memory: e2e-up does not set it).
export SAPLING_MODEL_MODE=function
export SAPLING_FUNCTION_HANDLERS=agents.function_handlers_e2e

rm -rf frontend/test-results frontend/e2e/results  # no stale red artifacts in review

status_of() {  # HTTP status of GET /api/learn/loop/status for rich-user-active (minted session)
  (cd backend && env -u SAPLING_MODEL_MODE -u SAPLING_FUNCTION_HANDLERS venv/bin/python - <<'PY'
import os, httpx
from dotenv import load_dotenv
load_dotenv(".env", override=True)
from services.session_tokens import mint_session
port = next((l.split("=", 1)[1].strip() for l in open(".env") if l.startswith("PORT=")), "5000")
r = httpx.get(
    f"http://127.0.0.1:{port}/api/learn/loop/status",
    params={"user_id": "rich-user-active", "session_id": "b6-drill-probe"},
    cookies={"sapling_session": mint_session("rich-user-active", 600)},
    timeout=10,
)
print(r.status_code)
PY
  )
}

# ── Lane 1: default (no LEARNING_LOOP_ENABLED at all), fresh volumes ─────────
# Dropping the volumes makes e2e-up's db.migrate replay EVERY migration from an
# empty database (the replay-from-empty proof the integration tests read).
supabase stop --no-backup >/dev/null 2>&1 || true
unset LEARNING_LOOP_ENABLED
s1=1; o1=1; i1=1; d1=1
if make e2e-up; then
  (cd frontend && npx playwright test); s1=$?
  (cd backend && venv/bin/python -m e2e_oracles); o1=$?
  # Drill, default half: /status answers for an ordinary student. (The smoke —
  # probe → plan → teach → check → close — is learn-loop.spec.ts's loop journey.)
  st=$(status_of)
  echo "drill(default): /status=$st"
  [ "$st" = "200" ] && d1=0
  # Real-SQL integration tests (they truncate + reseed: run AFTER Playwright).
  (cd backend && env -u SAPLING_MODEL_MODE -u SAPLING_FUNCTION_HANDLERS RUN_INTEGRATION=1 \
    venv/bin/python -m pytest -m integration -q -p no:cacheprovider \
      tests/integration/test_posttest_poses_db.py \
      tests/integration/test_teach_reveal_db.py \
      tests/integration/test_zpd_metrics_db.py \
      tests/integration/test_posttest_claim_db.py \
      tests/integration/test_learning_migrations_replay_db.py \
      tests/integration/test_migrations_ledger.py); i1=$?
fi
make e2e-down

# ── Lane 2: kill switch (LEARNING_LOOP_ENABLED=false for stack AND Playwright) ─
export LEARNING_LOOP_ENABLED=false
s2=1; o2=1; d2=1
if make e2e-up; then
  (cd frontend && npx playwright test); s2=$?
  (cd backend && venv/bin/python -m e2e_oracles); o2=$?
  # Drill, kill-switch half (spec §11.6): /status 404s. The rest of the drill
  # runs inside the lane's Playwright suite: "kill switch restores the legacy
  # Learn screen" (tutor-topic-picker, no loop-phase), study-semester
  # (review-due-panel absent) and upload.spec (the upload drafts no check_items).
  st=$(status_of)
  echo "drill(kill-switch): /status=$st"
  [ "$st" = "404" ] && d2=0
fi
make e2e-down
unset LEARNING_LOOP_ENABLED

echo "default: playwright=$s1 oracles=$o1 integration=$i1 drill=$d1  kill-switch: playwright=$s2 oracles=$o2 drill=$d2"
exit $((s1 | o1 | i1 | d1 | s2 | o2 | d2))
