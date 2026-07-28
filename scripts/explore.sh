#!/usr/bin/env bash
#
# Chapter 2 explore harness (#399): boot the local E2E stack, hand a
# Playwright-MCP-armed `claude -p` the explorer prompt to poke around the
# running app, run the #400 oracle CLI, then tear everything down. See
# docs/e2e-exploration.md (the runbook, landing in a later #399 task) for the
# full walkthrough and how to read `.explore/findings.md`.
#
#   make explore          # full pipeline: up -> run explorer -> down
#   make explore-down     # down only (same as: scripts/explore.sh down)
#
# Modes:
#   scripts/explore.sh          full pipeline (up, run the explorer, down)
#   scripts/explore.sh up       boot only — leaves the stack running so you
#                                can drive `claude` yourself against
#                                .explore/mcp.json (the interactive flow)
#   scripts/explore.sh down     oracle final pass + findings + teardown +
#                                lock release (for the interactive flow above,
#                                or to clean up after a crashed full run)
#
# Env knobs:
#   EXPLORE_MAX_TURNS   turn budget passed to `claude -p --max-turns` (default 40)
#   EXPLORE_MODEL       model alias passed to `claude -p --model` (default sonnet)
#   EXPLORE_HEADED      1 = headed browser, 0 = headless (default 0)
#   EXPLORE_USER        seeded rich-* user to mint a session for (default rich-user-active)
#
# Outputs land in .explore/ (wiped and recreated by `up`, but only AFTER the
# lock is acquired — see do_up/start_lock_holder — so a lock-busy `up` never
# touches another session's live artifacts; previous-run artifacts are
# otherwise the operator's to triage before re-running):
#   storageState.json        Playwright storage state (cookie + sapling_user localStorage)
#   mcp.json                 --mcp-config fed to `claude -p` (the playwright MCP server)
#   session.log               `claude -p` transcript (tee'd)
#   findings.md               running human-readable findings log
#   oracle-final.{txt,json}   final #400 oracle pass, appended at teardown
#   traces/                   playwright MCP session artifacts (see write_mcp_config)
#   lock.ok                   internal lock-holder bookkeeping (start_lock_holder /
#                             stop_lock_holder) — deliberately excluded from the wipe.
#                             Content is the holder process's PID, written ONLY by
#                             that process itself after it actually acquires the
#                             flock (never by the parent, and never speculatively) —
#                             see start_lock_holder for why.
#
# Lock: /tmp/claude-$(id -u)/sapling-e2e-stack.lock — the machine-singleton
# E2E stack lock, held by a DETACHED setsid process (start_lock_holder below),
# never by this script's own shell. A prior session proved that wrapping
# `make e2e-up` in `flock -c ...` leaves the lock held by the detached
# uvicorn/next children instead (fd inheritance), so a flock-wrapped teardown
# then deadlocks. Because this script never opens the lock fd itself and
# always invokes scripts/e2e-up.sh / scripts/e2e-down.sh unwrapped, that
# failure mode can't happen here, and `up`/`down` can safely be two separate
# invocations (the interactive flow above).
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

EXPLORE_DIR="$REPO_ROOT/.explore"
LOCK_FILE="/tmp/claude-$(id -u)/sapling-e2e-stack.lock"

# @playwright/mcp version pin (determinism beats freshness). Checked via
# `npm view @playwright/mcp version` on 2026-07-28 — see task-5-report.md.
PLAYWRIGHT_MCP_VERSION="0.0.78"

EXPLORE_MAX_TURNS="${EXPLORE_MAX_TURNS:-40}"
EXPLORE_MODEL="${EXPLORE_MODEL:-sonnet}"
EXPLORE_HEADED="${EXPLORE_HEADED:-0}"
EXPLORE_USER="${EXPLORE_USER:-rich-user-active}"

die() {
  echo "✗ $*" >&2
  exit 1
}

usage() {
  cat <<'USAGE'
Usage: scripts/explore.sh [up|down]

  (no arg)   full pipeline: up -> run the explorer -> down
  up         boot the stack, mint a session, write .explore/mcp.json, and
             leave it running (drive `claude` yourself, then run `down`)
  down       oracle final pass + findings + teardown + lock release

Env: EXPLORE_MAX_TURNS EXPLORE_MODEL EXPLORE_HEADED EXPLORE_USER
See docs/e2e-exploration.md for the full runbook.
USAGE
}

# ── Lock (both modes) ─────────────────────────────────────────────────────────
# The flock must survive this process so `up` and `down` can be separate
# invocations: a detached setsid holder opens fd 9 on $LOCK_FILE and sleeps
# forever; stop_lock_holder kills it. Neither this script nor scripts/e2e-up.sh
# (invoked below, not by the holder) ever has the lock fd open, so the stack's
# own detached servers can't inherit it either.
#
# do_up calls this BEFORE touching .explore/ at all (see do_up): a busy lock
# means another session owns the stack, and .explore/'s current contents
# (including that session's own lock.ok) are that session's live state —
# nothing here may wipe, delete, or overwrite them.
#
# Bookkeeping ownership is the subtle part (fixed after a real bug was found
# in review): a FAILED acquisition attempt must never touch lock.ok, because
# lock.ok may belong to another, currently-live session. The old design had
# the PARENT unconditionally `rm -f` lock.ok and write lock.pid before even
# knowing whether the flock would succeed — session B's failed attempt could
# delete session A's lock.ok and overwrite session A's lock.pid with B's own
# (about-to-die) PID, leaving A's later `down` unable to find A's holder at
# all (a permanent leaked process + leaked machine-singleton lock). Fixed by
# making the HOLDER subprocess itself the only writer of lock.ok, and only
# ever AFTER its own `flock -n 9` has actually succeeded — the parent here
# just polls for that write to appear, and does nothing to disk at all on
# the failure path. The write is atomic (temp file + mv) and self-identifying
# (content = the holder's own $$, which — because `setsid CMD &` execs CMD
# directly without an intervening fork — equals $! as seen by the parent) so
# the poll can't be fooled by a stale lock.ok left behind by a crashed prior
# session: it only accepts a lock.ok whose content is THIS attempt's pid.
start_lock_holder() {
  mkdir -p "$(dirname "$LOCK_FILE")" "$EXPLORE_DIR"
  setsid bash -c "
    exec 9>\"$LOCK_FILE\"
    flock -n 9 || exit 42
    tmp=\"$EXPLORE_DIR/lock.ok.\$\$.tmp\"
    echo \"\$\$\" > \"\$tmp\"
    mv -f \"\$tmp\" \"$EXPLORE_DIR/lock.ok\"
    exec sleep infinity
  " &
  local holder_pid=$!
  local acquired=1
  for _ in $(seq 1 20); do
    if [ "$(cat "$EXPLORE_DIR/lock.ok" 2>/dev/null)" = "$holder_pid" ]; then
      acquired=0
      break
    fi
    kill -0 "$holder_pid" 2>/dev/null || break
    sleep 0.1
  done
  [ "$acquired" -eq 0 ] && return 0
  # Acquisition failed (busy, or the holder died before confirming) — reap
  # our OWN doomed holder only. lock.ok is never touched here: it may belong
  # to another session's live, already-successful holder.
  kill "$holder_pid" 2>/dev/null || true
  die "e2e stack lock busy ($LOCK_FILE) — another session is using the stack"
}

stop_lock_holder() {
  local pid
  pid="$(cat "$EXPLORE_DIR/lock.ok" 2>/dev/null)" || true
  [ -n "${pid:-}" ] && kill "$pid" 2>/dev/null || true
  rm -f "$EXPLORE_DIR/lock.ok"
}

# ── Storage-state mint ────────────────────────────────────────────────────────
# POST through the frontend origin (also proves the /api/:path* proxy), then
# build the exact shape frontend/e2e/global-setup.ts builds: cookie
# `sapling_session` (httpOnly/secure/sameSite=Lax — Chromium accepts Secure
# cookies on http://localhost) plus the `sapling_user` localStorage half. The
# cookie alone renders an infinite skeleton (bug #430) — both halves are
# required.
mint_storage_state() {
  local body
  body="$(curl -fsS -X POST "http://localhost:3000/api/auth/test-login" \
    -H 'Content-Type: application/json' \
    -d "{\"user_id\": \"$EXPLORE_USER\"}")" \
    || die "POST /api/auth/test-login failed — is the frontend (:3000) up and running with APP_ENV=local|test?"
  python3 - "$body" "$EXPLORE_USER" > "$EXPLORE_DIR/storageState.json" <<'PY'
import json, sys, time
body = json.loads(sys.argv[1]); user = sys.argv[2]
state = {
    "cookies": [{
        "name": "sapling_session", "value": body["token"],
        "domain": "localhost", "path": "/",
        "expires": time.time() + float(body.get("expires_in") or 3600),
        "httpOnly": True, "secure": True, "sameSite": "Lax",
    }],
    "origins": [{
        "origin": "http://localhost:3000",
        "localStorage": [{
            "name": "sapling_user",
            "value": json.dumps({"id": user, "name": "Rich Active", "avatar": ""}),
        }],
    }],
}
print(json.dumps(state, indent=2))
PY
}

# ── mcp.json ───────────────────────────────────────────────────────────────
# Flags verified against `npx -y @playwright/mcp@0.0.78 --help` (see
# task-5-report.md for the full transcript):
#   --headless / --browser / --storage-state / --output-dir all appear
#   verbatim in --help. "chromium" (not "chrome"/"msedge", the two literal
#   values --help lists) is confirmed valid — it's the package's own
#   config.d.ts browserName type AND the exact value used in the package's
#   own README Docker example.
#
# --save-trace does NOT exist in 0.0.78 — neither --help nor the installed
# package's config.d.ts mentions any trace/tracing flag or config key.
# --save-session ("Whether to save the Playwright MCP session into the output
# directory") is the closest available artifact-capture flag, so traces/
# holds an MCP session recording, not a Playwright Trace Viewer .zip. Revisit
# this substitution if a future @playwright/mcp version adds real tracing.
write_mcp_config() {
  local headless_args='"--headless", '
  [ "$EXPLORE_HEADED" = "1" ] && headless_args=''
  cat > "$EXPLORE_DIR/mcp.json" <<EOF
{
  "mcpServers": {
    "playwright": {
      "command": "npx",
      "args": ["-y", "@playwright/mcp@$PLAYWRIGHT_MCP_VERSION", ${headless_args}"--browser", "chromium",
               "--storage-state", "$EXPLORE_DIR/storageState.json",
               "--output-dir", "$EXPLORE_DIR/traces", "--save-session"]
    }
  }
}
EOF
}

# ── Explorer leg (full mode only) ─────────────────────────────────────────────
# Flags verified against `claude --help` (2.1.220 — see task-5-report.md):
#   -p/--print, --mcp-config, --strict-mcp-config, --model, --allowedTools all
#   appear verbatim in --help.
#
# --max-turns is NOT listed in --help (a real gap in this CLI version's help
# text) but IS accepted by the option parser: probed by combining it with a
# deliberately-bad --mcp-config path (so the process fails fast on config
# validation, before any model call) and comparing against a control run with
# a genuinely-unknown flag. The control errored immediately with "unknown
# option"; --max-turns did not — it passed parsing straight through to MCP
# config validation, proving the CLI recognizes it. See task-5-report.md.
#
# allowedTools forms verified against the CLI's own permission-rule validator
# (embedded error strings, since `claude mcp --help` doesn't document MCP tool
# wildcards): "mcp__<server>__*" grants every tool on that server (confirmed
# — "...or use 'mcp__<server>__*' for all tools"); "Bash(prefix:*)" is valid
# too, labeled "legacy prefix matching" (must end in exactly ":*" — the
# current preferred form is "Bash(prefix *)", but both are functional). The
# explorer must not gain broader Bash than the oracle invocation below.
run_explorer() {
  cd "$REPO_ROOT"
  claude -p "$(cat "$REPO_ROOT/scripts/explore/explorer-prompt.md")" \
    --mcp-config "$EXPLORE_DIR/mcp.json" \
    --strict-mcp-config \
    --model "$EXPLORE_MODEL" \
    --max-turns "$EXPLORE_MAX_TURNS" \
    --allowedTools "mcp__playwright__*,Read,Write,Edit,Bash(cd backend && venv/bin/python -m e2e_oracles:*)" \
    2>&1 | tee "$EXPLORE_DIR/session.log" || \
    echo "explorer exited nonzero (turn budget or error) — continuing to oracle pass" | tee -a "$EXPLORE_DIR/session.log"
}

# ── up ─────────────────────────────────────────────────────────────────────
do_up() {
  echo "▶ Preflight…"
  command -v claude  >/dev/null 2>&1 || die "claude CLI not found on PATH — install it first"
  command -v npx     >/dev/null 2>&1 || die "npx not found on PATH — install Node.js first"
  command -v curl    >/dev/null 2>&1 || die "curl not found on PATH"
  command -v python3 >/dev/null 2>&1 || die "python3 not found on PATH"
  [ -f "$REPO_ROOT/scripts/explore/explorer-prompt.md" ] \
    || die "scripts/explore/explorer-prompt.md not found (lands in a later #399 task) — nothing to run yet"

  # Acquire the lock FIRST, before touching .explore/ at all and before
  # arming any trap that can call do_down (which runs scripts/e2e-down.sh —
  # destructive). A busy lock means another session owns the stack; failing
  # here must exit with the "stack busy" message having wiped nothing, torn
  # nothing down, and leaked no process (start_lock_holder cleans up its own
  # failed attempt — see above). Only once the lock is truly ours do we arm
  # the boot-failure safety net and wipe .explore/ for this run.
  start_lock_holder

  # Lock is ours: NOW it's safe to arm do_down as a cleanup-on-failure trap
  # (idempotent-safe even with nothing up) so a boot failure partway through
  # still releases the lock and tears down whatever partially came up.
  # Disarmed just before a successful return so a bare `up` leaves the stack
  # running for the interactive flow.
  trap do_down EXIT

  echo "▶ Preparing .explore/ (previous run's artifacts, if any, are wiped — triage them first if you need them)…"
  # Preserve lock.ok — start_lock_holder just wrote it (containing our
  # holder's pid), and a later, separate `scripts/explore.sh down` invocation
  # (the interactive flow) needs it on disk to know which holder to stop.
  find "$EXPLORE_DIR" -mindepth 1 -maxdepth 1 ! -name lock.ok -exec rm -rf {} +
  mkdir -p "$EXPLORE_DIR/traces"

  echo "▶ Booting the E2E stack (scripts/e2e-up.sh)…"
  export SAPLING_MODEL_MODE=function
  export SAPLING_FUNCTION_HANDLERS=agents.function_handlers_e2e
  # Default only if unset — never clobber an operator's real key.
  export GEMINI_API_KEY="${GEMINI_API_KEY:-e2e-dummy-key-no-billing}"
  "$REPO_ROOT/scripts/e2e-up.sh" || die "scripts/e2e-up.sh failed — see .e2e/*.log"

  echo "▶ Minting a session for $EXPLORE_USER…"
  mint_storage_state

  echo "▶ Writing .explore/mcp.json (playwright MCP server, @playwright/mcp@$PLAYWRIGHT_MCP_VERSION)…"
  write_mcp_config

  trap - EXIT

  cat <<DONE

✅ Explore stack is up.
   storage state:  $EXPLORE_DIR/storageState.json
   mcp config:     $EXPLORE_DIR/mcp.json

   Drive it yourself:
     claude --mcp-config "$EXPLORE_DIR/mcp.json" --strict-mcp-config
   Finish with:
     scripts/explore.sh down   (or: make explore-down)
DONE
}

# ── down ───────────────────────────────────────────────────────────────────
# Oracle final pass -> append to findings -> tear down -> release the lock.
# Idempotent-safe: runs cleanly even with no stack up (mkdir + `|| true`
# guards throughout — verified, see task-5-report.md).
do_down() {
  mkdir -p "$EXPLORE_DIR"
  (
    cd "$REPO_ROOT/backend"
    venv/bin/python -m e2e_oracles --json > "$EXPLORE_DIR/oracle-final.json" || true
    venv/bin/python -m e2e_oracles > "$EXPLORE_DIR/oracle-final.txt" 2>&1 || true
  ) || true
  [ -f "$EXPLORE_DIR/findings.md" ] || printf '# Exploration findings\n' > "$EXPLORE_DIR/findings.md"
  {
    printf '\n## Oracle final pass (%s)\n\n```\n' "$(date -Iseconds)"
    cat "$EXPLORE_DIR/oracle-final.txt" 2>/dev/null || true
    printf '```\n'
  } >> "$EXPLORE_DIR/findings.md"
  "$REPO_ROOT/scripts/e2e-down.sh" || true
  stop_lock_holder
}

# ── Full pipeline ────────────────────────────────────────────────────────────
run_full() {
  do_up
  trap do_down EXIT
  run_explorer
}

case "${1:-}" in
  "")
    run_full
    ;;
  up)
    do_up
    ;;
  down)
    do_down
    ;;
  -h|--help)
    usage
    ;;
  *)
    usage
    die "unknown argument: ${1:-}"
    ;;
esac
