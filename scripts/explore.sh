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
#   scripts/explore.sh down     oracle final pass + findings + teardown (for
#                                the interactive flow above, or to clean up
#                                after a crashed full run)
#
# Env knobs:
#   EXPLORE_MAX_TURNS   turn budget passed to `claude -p --max-turns` (default 40)
#   EXPLORE_MODEL       model alias passed to `claude -p --model` (default sonnet)
#   EXPLORE_HEADED      1 = headed browser, 0 = headless (default 0)
#   EXPLORE_USER        seeded rich-* user to mint a session for (default rich-user-active)
#
# Outputs land in .explore/ (wiped and recreated by `up`, but only AFTER this
# checkout's stack is ours — a busy checkout fails before .explore/ is touched;
# previous-run artifacts are otherwise the operator's to triage before
# re-running):
#   storageState.json        Playwright storage state (cookie + sapling_user localStorage)
#   mcp.json                 --mcp-config fed to `claude -p` (the playwright MCP server)
#   session.log               readable transcript, reformatted by jq from `claude -p
#                             --output-format stream-json --verbose` (see run_explorer
#                             for why plain "text" output can't show tool calls)
#   session.stderr.log        `claude -p`'s stderr, kept separate so it can never
#                             corrupt the JSON stream session.log is parsed from
#   findings.md               running human-readable findings log
#   oracle-final.{txt,json}   final #400 oracle pass, appended at teardown
#   traces/                   playwright MCP session artifacts (see write_mcp_config)
#   cycle.pid                 the held E2E cycle THIS explore started (see do_up) —
#                             deliberately excluded from the wipe; `down` stops
#                             only that cycle, never one another command started.
#
# Stack: an E2E SLOT held by a background cycle (scripts/e2e-cycle.sh
# --background) — the same owner as `make e2e-up`. The cycle takes the slot's
# lock and this checkout's, boots the stack on the slot's ports (never the dev
# app's :3000/:5000), and tears it down when `down` stops it, so `up` and
# `down` can be two separate invocations (the interactive flow above). This
# script never holds a lock itself.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

EXPLORE_DIR="$REPO_ROOT/.explore"
# Explore runs in an E2E SLOT like every other lane (scripts/lib/e2e-slot.sh).
# E2E_SLOT picks one; otherwise the cycle takes the first free slot.
CYCLE="$REPO_ROOT/scripts/e2e-cycle.sh"

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
  down       oracle final pass + findings + stop the stack explore started

Env: EXPLORE_MAX_TURNS EXPLORE_MODEL EXPLORE_HEADED EXPLORE_USER
See docs/e2e-exploration.md for the full runbook.
USAGE
}

# ── Stack ownership ─────────────────────────────────────────────────────────
# The held cycle's pid, if this checkout has one running — the same test as
# e2e-cycle.sh's held_pid: the checkout lock is held AND .e2e/cycle.pid names
# a live e2e-cycle.sh (a stale pid, since reused, never counts).
EXPLORE_CYCLE_PID=""
held_cycle_pid() {
  local pid
  pid="$(cat "$REPO_ROOT/.e2e/cycle.pid" 2>/dev/null)" || return 1
  [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null || return 1
  flock -n "$REPO_ROOT/.e2e/cycle.lock" true 2>/dev/null && return 1
  if [ -r "/proc/$pid/cmdline" ]; then
    tr '\0' ' ' <"/proc/$pid/cmdline" | grep -q 'e2e-cycle\.sh' || return 1
  fi
  echo "$pid"
}

# ── Storage-state mint ────────────────────────────────────────────────────────
# POST through the frontend origin (also proves the /api/:path* proxy), then
# build the exact shape frontend/e2e/global-setup.ts builds: cookie
# `sapling_session` (httpOnly/sameSite=Lax) plus the `sapling_user`
# localStorage half. The cookie alone renders an infinite skeleton (bug
# #430) — both halves are required.
#
# `secure: False` — NOT True. This mirrors what the backend itself actually
# issues locally: config.py derives SECURE_COOKIES from FRONTEND_URL's scheme
# (`FRONTEND_URL=http://localhost:3000` in backend/.env → False), and
# routes/auth.py's real `Set-Cookie` always passes `secure=SECURE_COOKIES`.
# A first live bounded run (task-8-report.md's follow-up round) found a live
# `sapling_session` cookie in the MCP browser's persistent profile with
# `is_secure=0` — i.e. exactly this real backend policy — while a byte-clean
# profile probe with the (then) secure:true storageState.json produced ZERO
# `sapling_session` cookie at all (confirmed via sqlite3 on the profile's
# Cookies db) and an immediate redirect to a REAL accounts.google.com sign-in
# page. Root cause turned out to be `--isolated` missing (see write_mcp_config
# below), not this flag, but a state file that doesn't match what the app
# would actually set is still wrong on its own — fix it regardless.
mint_storage_state() {
  local body display_name
  body="$(curl -fsS -X POST "$E2E_FRONTEND_URL/api/auth/test-login" \
    -H 'Content-Type: application/json' \
    -d "{\"user_id\": \"$EXPLORE_USER\"}")" \
    || die "POST /api/auth/test-login failed — is the frontend ($E2E_FRONTEND_URL) up and running with APP_ENV=local|test?"
  # Display name for the seeded rich-* users (backend/db/seed_local_rich.py's
  # _USERS/_PROFILES) — EXPLORE_USER is the id, but sapling_user localStorage
  # wants the human name. Falls back to the raw id for anything else.
  case "$EXPLORE_USER" in
    rich-user-active)  display_name="Rich Active" ;;
    rich-user-second)  display_name="Sam Second" ;;
    rich-user-new)     display_name="Newt Newman" ;;
    rich-user-pending) display_name="Penny Pending" ;;
    rich-user-admin)   display_name="Ada Admin" ;;
    *)                 display_name="$EXPLORE_USER" ;;
  esac
  python3 - "$body" "$EXPLORE_USER" "$display_name" "$E2E_FRONTEND_URL" > "$EXPLORE_DIR/storageState.json" <<'PY'
import json, sys, time
body = json.loads(sys.argv[1]); user = sys.argv[2]; name = sys.argv[3]; origin = sys.argv[4]
state = {
    "cookies": [{
        "name": "sapling_session", "value": body["token"],
        "domain": "localhost", "path": "/",
        "expires": time.time() + float(body.get("expires_in") or 3600),
        "httpOnly": True, "secure": False, "sameSite": "Lax",
    }],
    "origins": [{
        "origin": origin,
        "localStorage": [{
            "name": "sapling_user",
            "value": json.dumps({"id": user, "name": name, "avatar": ""}),
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
#
# --isolated is load-bearing, not an optimization — this is the actual fix
# for the #399 follow-up bug (task-8-report.md): the FIRST live bounded run
# looked half-signed-in (a valid session cookie but the UI acting fully
# logged out, the #430 symptom) and a second run looked signed in via a
# stale leftover cookie. Root-caused by reading @playwright/mcp@0.0.78's
# bundled source (playwright-core/lib/coreBundle.js): without --isolated,
# the MCP server launches ONE PERSISTENT Chrome profile per REPO PATH
# (`mcp-<browser>-<sha256(cwd)[:7]>` under ~/.cache/ms-playwright-mcp/,
# reused across every explore.sh run from this checkout — confirmed via
# `createUserDataDir`'s hash) via `browserType.launchPersistentContext`, and
# then its `factory.create()` does
# `config.browser.isolated ? await browser.newContext(contextOptions) :
# browser.contexts()[0]` — i.e. in the DEFAULT (non-isolated) branch it just
# grabs the browser's already-open context and NEVER calls newContext with
# our --storage-state at all for that reused context. Confirmed empirically:
# wiped the profile dir, booted a clean stack, and drove a 3-turn `claude -p`
# probe against the unmodified (then-current) mcp.json — navigating to
# /dashboard redirected straight to a REAL accounts.google.com sign-in page
# (sqlite3 on the profile's Cookies db afterward: zero sapling_session rows
# — the minted cookie was never applied at all, cookie or localStorage). The
# exact same probe with `--isolated` added (which routes through
# `createIsolatedBrowser` + an explicit `browser.newContext(config.browser.
# contextOptions)` — the same mechanism `@playwright/test` itself uses in
# Chapter 1's global-setup.ts) rendered the real, fully-authenticated
# dashboard (concepts/courses/streak all populated) on the FIRST navigation,
# with `localStorage.sapling_user` correctly present.
write_mcp_config() {
  local headless_args='"--headless", '
  [ "$EXPLORE_HEADED" = "1" ] && headless_args=''
  cat > "$EXPLORE_DIR/mcp.json" <<EOF
{
  "mcpServers": {
    "playwright": {
      "command": "npx",
      "args": ["-y", "@playwright/mcp@$PLAYWRIGHT_MCP_VERSION", "--isolated", ${headless_args}"--browser", "chromium",
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
#
# Edit(.explore/**) — not bare "Edit" — scopes writes to match the prompt's
# hard rule that the explorer's only writes are .explore/findings.md.
# Verified empirically: Edit path-pattern rules are matched by the file
# permission check ("Edit(path)" rules), but a "Write(...)" pattern is NOT —
# so a bare "Write" grant would be unscoped no matter what pattern follows
# it. Dropped Write entirely; do_up now pre-creates .explore/findings.md so
# the explorer always has an existing file to Edit rather than needing Write
# to create one.
#
# --output-format stream-json (which the CLI requires pairing with --verbose —
# confirmed via `claude -p ... --output-format stream-json` alone erroring
# "requires --verbose") is load-bearing, not cosmetic: plain "text" (the
# default) only ever prints claude -p's FINAL message. The first live bounded
# run (task-8-report.md) hit the normal --max-turns cutoff and produced a
# session.log containing exactly one line — the CLI's own "Error: Reached max
# turns" — with zero tool-call evidence, failing the #399 acceptance bar
# ("session.log shows real Playwright MCP tool calls"). stream-json emits one
# JSON event per turn, including tool_use/tool_result, so it's the only format
# that can show the browser actually being driven regardless of how the run
# ends. The jq filter below reformats each event into one readable
# `[assistant]`/`[tool_use]`/`[tool_result]`/`[result]` line (each truncated
# to 500 chars) so session.log stays both grep-able (`grep -c
# mcp__playwright`) and skimmable by a human — a raw JSONL firehose would
# satisfy the letter of "shows tool calls" but not "readable transcript".
# `fromjson?` skips any stray non-JSON line instead of aborting the whole
# pipeline; stderr is captured to its own file so it can never interleave
# with (and corrupt) the JSON stream jq is parsing.
run_explorer() {
  cd "$REPO_ROOT"
  claude -p "$(sed "s#{{FRONTEND_URL}}#$E2E_FRONTEND_URL#g" "$REPO_ROOT/scripts/explore/explorer-prompt.md")" \
    --mcp-config "$EXPLORE_DIR/mcp.json" \
    --strict-mcp-config \
    --model "$EXPLORE_MODEL" \
    --max-turns "$EXPLORE_MAX_TURNS" \
    --output-format stream-json \
    --verbose \
    --allowedTools "mcp__playwright__*,Read,Edit(.explore/**),Bash(cd backend && venv/bin/python -m e2e_oracles:*)" \
    2>"$EXPLORE_DIR/session.stderr.log" | jq -R -r '
      def trunc: if (. // "" | length) > 500 then (.[0:500] + " …[truncated]") else . end;
      (fromjson?) as $d
      | if $d.type == "assistant" then
          ($d.message.content // [])[]
          | (if .type == "text" then "[assistant] " + .text
             elif .type == "tool_use" then "[tool_use] " + .name + " " + (.input | tostring)
             else empty end)
          | trunc
        elif $d.type == "user" then
          ($d.message.content // [])[]
          | (if .type == "tool_result" then
               "[tool_result] " + (
                 if (.content | type) == "string" then .content
                 elif (.content | type) == "array" then ([ .content[] | select(.type=="text") | .text ] | join(" "))
                 else (.content | tostring) end)
             else empty end)
          | trunc
        elif $d.type == "result" then
          ("[result] " + ($d.subtype // "unknown") + " turns=" + (($d.num_turns // 0) | tostring)
           + (if $d.result then " :: " + ($d.result | tostring) else "" end))
          | trunc
        else empty end
    ' > "$EXPLORE_DIR/session.log" || \
    echo "explorer exited nonzero (turn budget or error) — continuing to oracle pass" | tee -a "$EXPLORE_DIR/session.log"
}

# ── up ─────────────────────────────────────────────────────────────────────
do_up() {
  echo "▶ Preflight…"
  command -v claude  >/dev/null 2>&1 || die "claude CLI not found on PATH — install it first"
  command -v npx     >/dev/null 2>&1 || die "npx not found on PATH — install Node.js first"
  command -v curl    >/dev/null 2>&1 || die "curl not found on PATH"
  command -v python3 >/dev/null 2>&1 || die "python3 not found on PATH"
  command -v jq      >/dev/null 2>&1 || die "jq not found on PATH — required for the session transcript"
  [ -f "$REPO_ROOT/scripts/explore/explorer-prompt.md" ] \
    || die "scripts/explore/explorer-prompt.md not found (lands in a later #399 task) — nothing to run yet"

  # This checkout's stack must be free: a held cycle here is someone else's
  # (`make e2e-up`, another explore) and `down` would end it. Failing here has
  # touched nothing — .explore/ is wiped only once the stack is ours.
  if pid="$(held_cycle_pid)"; then
    die "this checkout already holds an E2E stack (cycle pid $pid) — stop it first (make e2e-down), or explore from another worktree"
  fi

  # The held cycle inherits this environment, so the explore lane's knobs are
  # exported BEFORE it starts.
  export SAPLING_MODEL_MODE=function
  export SAPLING_FUNCTION_HANDLERS=agents.function_handlers_e2e
  # ADR 0028: never send exploration traffic to PostHog: no project token,
  # no client. e2e-up.sh blanks both too; set here as well so the explore
  # lane does not depend on it.
  export POSTHOG_PROJECT_TOKEN=
  export POSTHOG_PERSONAL_API_KEY=   # erasure is not gated by capture
  # Unconditional (matches CI's unconditional dummy, #439): the below-seam RAG
  # path can still bill a real key even in function mode, and an ambient real
  # key routinely stays exported in dev shells. This only exports into this
  # process tree (the stack we're about to boot) — it never mutates the
  # operator's actual shell.
  export GEMINI_API_KEY=e2e-dummy-key-no-billing
  # Same for the agents' provider (ADR 0030): function mode never dials Claude;
  # the dummy makes sure a slip in this local-only harness can't bill either.
  export ANTHROPIC_API_KEY=e2e-dummy-key-no-billing
  # SEED_RICH defaults to 1 in e2e-up.sh, but an ambient SEED_RICH=0 in the
  # operator's shell would silently defeat it — this harness requires the
  # rich dataset (mint_storage_state below dies late otherwise).
  export SEED_RICH=1

  echo "▶ Booting the E2E stack (scripts/e2e-cycle.sh --background)…"
  # --new: a hold this checkout already runs (someone else's, started since
  # the check above) is a failure here, never adopted as ours.
  "$CYCLE" --new --background || die "the E2E stack did not come up — see .e2e/cycle.log"
  EXPLORE_CYCLE_PID="$(held_cycle_pid)" || die "the E2E cycle exited right after coming up — see .e2e/cycle.log"

  # The stack is ours: NOW arm do_down as the boot-failure safety net (it
  # stops EXPLORE_CYCLE_PID even if .explore/ can't be written), so a failure
  # below still stops the cycle. Disarmed just before a successful return so a
  # bare `up` leaves the stack running for the interactive flow.
  trap do_down EXIT
  # shellcheck disable=SC1091
  source "$REPO_ROOT/.e2e/env.sh"

  echo "▶ Preparing .explore/ (previous run's artifacts, if any, are wiped — triage them first if you need them)…"
  mkdir -p "$EXPLORE_DIR"
  find "$EXPLORE_DIR" -mindepth 1 -maxdepth 1 -exec rm -rf {} +
  echo "$EXPLORE_CYCLE_PID" > "$EXPLORE_DIR/cycle.pid"
  mkdir -p "$EXPLORE_DIR/traces"
  # Pre-create findings.md with a header so the explorer (allowedTools grants
  # Edit(.explore/**), not Write — see run_explorer) always has an existing
  # file to append to.
  printf '# Exploration findings — %s\n' "$(date -Iseconds)" > "$EXPLORE_DIR/findings.md"

  echo "▶ Minting a session for $EXPLORE_USER…"
  mint_storage_state

  echo "▶ Writing .explore/mcp.json (playwright MCP server, @playwright/mcp@$PLAYWRIGHT_MCP_VERSION)…"
  write_mcp_config

  trap - EXIT

  cat <<DONE

✅ Explore stack is up (E2E slot $E2E_SLOT, $E2E_FRONTEND_URL).
   storage state:  $EXPLORE_DIR/storageState.json
   mcp config:     $EXPLORE_DIR/mcp.json

   Drive it yourself:
     claude --mcp-config "$EXPLORE_DIR/mcp.json" --strict-mcp-config
   Finish with:
     scripts/explore.sh down   (or: make explore-down)
DONE
}

# ── down ───────────────────────────────────────────────────────────────────
# Oracle final pass -> append to findings -> stop the cycle explore started
# (the cycle tears the stack down). Idempotent-safe: runs cleanly with no
# stack up, and never stops a held cycle another command started.
#
# This runs as both a plain function AND an EXIT trap (see do_up/run_full)
# under `set -euo pipefail`, so every fallible statement below is `|| true`
# guarded — a failed write must never abort this function before the cycle is
# stopped, or it leaks the running stack AND the slot. The oracle pass needs
# the stack still up, so stopping stays last — it just must be
# UNCONDITIONALLY reached.
do_down() {
  mkdir -p "$EXPLORE_DIR" || true
  local mine held
  mine="${EXPLORE_CYCLE_PID:-}"
  [ -n "$mine" ] || mine="$(cat "$EXPLORE_DIR/cycle.pid" 2>/dev/null)" || true
  held="$(held_cycle_pid)" || true
  if [ -z "${mine:-}" ] || [ "${held:-}" != "$mine" ]; then
    if [ -n "${held:-}" ]; then
      echo "✗ this checkout's held E2E stack (cycle pid $held) was not started by explore — leaving it (make e2e-down stops it)." >&2
    else
      echo "✓ no explore stack is running — nothing to stop."
    fi
    rm -f "$EXPLORE_DIR/cycle.pid" || true
    return 0
  fi
  # The oracles and findings target the stack's slot via its manifest.
  # shellcheck disable=SC1091
  [ -f "$REPO_ROOT/.e2e/env.sh" ] && source "$REPO_ROOT/.e2e/env.sh" || true
  (
    cd "$REPO_ROOT/backend"
    venv/bin/python -m e2e_oracles --json --user "$EXPLORE_USER" > "$EXPLORE_DIR/oracle-final.json" || true
    venv/bin/python -m e2e_oracles --user "$EXPLORE_USER" > "$EXPLORE_DIR/oracle-final.txt" 2>&1 || true
  ) || true
  [ -f "$EXPLORE_DIR/findings.md" ] || printf '# Exploration findings\n' > "$EXPLORE_DIR/findings.md" || true
  {
    printf '\n## Oracle final pass (%s)\n\n```\n' "$(date -Iseconds)"
    cat "$EXPLORE_DIR/oracle-final.txt" 2>/dev/null || true
    printf '```\n'
  } >> "$EXPLORE_DIR/findings.md" || true
  "$CYCLE" --stop || true
  rm -f "$EXPLORE_DIR/cycle.pid" || true
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
