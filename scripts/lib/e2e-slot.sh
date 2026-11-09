# shellcheck shell=bash
#
# E2E slots: isolated, numbered E2E stacks that can run side by side.
#
# Sourced by scripts/e2e-up.sh, scripts/e2e-down.sh, scripts/e2e-cycle.sh and
# scripts/explore.sh. A slot is everything one E2E run owns:
#
#   slot N (1..E2E_SLOTS_MAX)   frontend :310N  backend :510N
#                               Supabase project sapling-e2e-N, every port of
#                               supabase/config.toml shifted by +100·N
#                               (API :54321+100N, Postgres :54322+100N, …),
#                               its own containers and its own (throwaway)
#                               database volume
#   slot 0 — CI only            the classic contract: :3000 / :5000 / :54321,
#                               project "sapling", the repo's own config.toml
#
# Locally the classic ports belong to the human dev stack — `npm run dev` on
# :3000 and the backend on :5000, which is the ONLY place Google sign-in can
# land (the OAuth redirect URI is http://localhost:5000/...). An E2E run that
# boots there evicts the dev servers and points a signed-in browser at a
# backend with placeholder OAuth credentials. So slot 0 is refused outside CI.
#
# Each slot has its own lock (/tmp/claude-<uid>/sapling-e2e-slot-N.lock).
# scripts/e2e-cycle.sh claims the first free one for a whole up → test → down
# cycle, so concurrent runs no longer queue behind a machine-wide lock.

E2E_SLOTS_MAX="${E2E_SLOTS_MAX:-3}"
E2E_LOCK_DIR="/tmp/claude-$(id -u)"

# Containers a slot never needs: the dashboard, mail catcher, log pipeline,
# edge functions and the connection pooler (disabled in config.toml anyway).
# Overridable (empty = start everything). Slot 0 always starts everything, so
# CI is unchanged.
E2E_SUPABASE_EXCLUDE_DEFAULT="studio,postgres-meta,mailpit,logflare,vector,edge-runtime,supavisor"

e2e_slot_lock_file() { # slot → lock path
  echo "$E2E_LOCK_DIR/sapling-e2e-slot-$1.lock"
}

# Is slot N's lock free right now? (Takes it and lets go at once; a held lock
# means a cycle is using the slot.)
e2e_slot_is_free() { # slot → 0 free, 1 busy
  local file
  file="$(e2e_slot_lock_file "$1")"
  mkdir -p "$E2E_LOCK_DIR"
  ( flock -n 9 ) 9>"$file"
}

# Resolve E2E_SLOT (explicit env, else the slot this checkout last booted —
# .e2e/slot, so `make e2e-down` finds the stack `make e2e-up` started — else 1)
# and export everything that slot owns. Prints the reason and returns 1 when
# the slot is not allowed here.
resolve_e2e_slot() { # repo_root
  local repo="$1" offset
  if [ -z "${E2E_SLOT:-}" ] && [ -f "$repo/.e2e/slot" ]; then
    E2E_SLOT="$(tr -d '[:space:]' <"$repo/.e2e/slot")"
  fi
  E2E_SLOT="${E2E_SLOT:-1}"
  case "$E2E_SLOT" in
    ''|*[!0-9]*) echo "✗ E2E_SLOT must be a slot number (0 in CI, 1..$E2E_SLOTS_MAX locally), got '$E2E_SLOT'"; return 1 ;;
  esac
  if [ "$E2E_SLOT" = "0" ] && [ "${CI:-}" != "true" ]; then
    echo "✗ E2E_SLOT=0 is the classic :3000/:5000/:54321 stack — CI only. Locally those ports are"
    echo "  the dev app's (Google sign-in can only land on :5000). Use a slot 1..$E2E_SLOTS_MAX, or"
    echo "  scripts/e2e-cycle.sh, which picks a free one."
    return 1
  fi
  if [ "$E2E_SLOT" -gt "$E2E_SLOTS_MAX" ]; then
    echo "✗ E2E_SLOT=$E2E_SLOT is past E2E_SLOTS_MAX=$E2E_SLOTS_MAX"
    return 1
  fi

  if [ "$E2E_SLOT" = "0" ]; then
    offset=0
    FRONTEND_PORT="${FRONTEND_PORT:-3000}"
    BACKEND_PORT=5000
    # The Windows/WinNAT override documented in e2e-up.sh still applies here.
    SUPABASE_API_PORT="${SUPABASE_API_PORT:-54321}"
    SUPABASE_DB_PORT="${SUPABASE_DB_PORT:-54322}"
    SUPABASE_WORKDIR="$repo"
    SUPABASE_PROJECT_ID="sapling"
    E2E_SUPABASE_EXCLUDE=""
  else
    offset=$((100 * E2E_SLOT))
    FRONTEND_PORT=$((3100 + E2E_SLOT))
    BACKEND_PORT=$((5100 + E2E_SLOT))
    SUPABASE_API_PORT=$((54321 + offset))
    SUPABASE_DB_PORT=$((54322 + offset))
    SUPABASE_WORKDIR="$repo/.e2e/supabase-slot-$E2E_SLOT"
    SUPABASE_PROJECT_ID="sapling-e2e-$E2E_SLOT"
    E2E_SUPABASE_EXCLUDE="${E2E_SUPABASE_EXCLUDE-$E2E_SUPABASE_EXCLUDE_DEFAULT}"
  fi
  E2E_SLOT_PORT_OFFSET="$offset"
  DB_CONTAINER="supabase_db_${SUPABASE_PROJECT_ID}"
  LOCAL_DB_URL="postgresql://postgres:postgres@127.0.0.1:$SUPABASE_DB_PORT/postgres"

  # What every process in the run reads. Exported, so each beats backend/.env
  # (python-dotenv never overrides an existing variable) and the test-profile
  # frontend build/start (package.json reads E2E_BACKEND_URL and
  # NEXT_PUBLIC_SUPABASE_URL) without anyone editing a file.
  export E2E_SLOT FRONTEND_PORT BACKEND_PORT SUPABASE_API_PORT SUPABASE_DB_PORT
  export SUPABASE_WORKDIR SUPABASE_PROJECT_ID DB_CONTAINER LOCAL_DB_URL E2E_SUPABASE_EXCLUDE
  export SUPABASE_URL="http://127.0.0.1:$SUPABASE_API_PORT"
  export NEXT_PUBLIC_SUPABASE_URL="$SUPABASE_URL"
  export E2E_FRONTEND_URL="http://localhost:$FRONTEND_PORT"
  export E2E_BACKEND_URL="http://localhost:$BACKEND_PORT"
  export E2E_DB_URL="$LOCAL_DB_URL"
  # The backend's own links back to the app (emails, OAuth returns) point at
  # this slot's frontend, not the dev app's :3000.
  export FRONTEND_URL="$E2E_FRONTEND_URL"
}

# A slot's own copy of supabase/ with project_id = sapling-e2e-N and every
# `port`/`shadow_port`/`inspector_port` shifted by the slot's offset. Rewritten
# on every boot, so a config.toml change on the branch always reaches it.
write_e2e_slot_supabase_config() { # repo_root
  local repo="$1"
  [ "$E2E_SLOT" = "0" ] && return 0
  rm -rf "$SUPABASE_WORKDIR/supabase"
  mkdir -p "$SUPABASE_WORKDIR"
  cp -R "$repo/supabase" "$SUPABASE_WORKDIR/supabase"
  awk -v off="$E2E_SLOT_PORT_OFFSET" -v pid="$SUPABASE_PROJECT_ID" '
    /^project_id[[:space:]]*=/ { print "project_id = \"" pid "\""; next }
    /^(port|shadow_port|inspector_port)[[:space:]]*=[[:space:]]*[0-9]+[[:space:]]*$/ {
      split($0, kv, "=")
      key = kv[1]; gsub(/[[:space:]]+$/, "", key)
      val = kv[2]; gsub(/[[:space:]]/, "", val)
      print key " = " (val + off)
      next
    }
    { print }
  ' "$repo/supabase/config.toml" >"$SUPABASE_WORKDIR/supabase/config.toml"
}

# Write what the run resolved where the harnesses look for it, so
# `npx playwright test` and `python -m e2e_oracles` find this slot after a bare
# `make e2e-up` without anyone exporting anything (frontend/e2e/support/stack.ts
# reads .e2e/stack.json; .e2e/env.sh is for a shell: `source .e2e/env.sh`).
write_e2e_slot_manifest() { # e2e_dir
  local dir="$1"
  mkdir -p "$dir"
  echo "$E2E_SLOT" >"$dir/slot"
  cat >"$dir/stack.json" <<JSON
{
  "slot": $E2E_SLOT,
  "frontendUrl": "$E2E_FRONTEND_URL",
  "backendUrl": "$E2E_BACKEND_URL",
  "dbUrl": "$E2E_DB_URL",
  "supabaseUrl": "$SUPABASE_URL"
}
JSON
  cat >"$dir/env.sh" <<ENV
# E2E slot $E2E_SLOT — written by scripts/e2e-up.sh. \`source .e2e/env.sh\`
export E2E_SLOT=$E2E_SLOT
export E2E_FRONTEND_URL=$E2E_FRONTEND_URL
export E2E_BACKEND_URL=$E2E_BACKEND_URL
export E2E_DB_URL=$E2E_DB_URL
export SUPABASE_DB_URL=$E2E_DB_URL
export SUPABASE_URL=$SUPABASE_URL
ENV
}

# Arguments for `supabase start|stop|status` against this slot.
e2e_supabase_args() {
  if [ "$E2E_SLOT" = "0" ]; then
    return 0
  fi
  printf '%s\n' --workdir "$SUPABASE_WORKDIR"
}
