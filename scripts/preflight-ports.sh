#!/usr/bin/env bash
#
# Reserve (and diagnose) the local Supabase ports before `supabase start` (#574).
#
#   scripts/preflight-ports.sh
#
# Called from .github/workflows/integration.yml and .github/workflows/e2e.yml
# immediately before the step that boots Supabase. CI ONLY — see "Not local"
# at the bottom of this header.
#
# ── The failure this guards ──────────────────────────────────────────────────
# Run 32624263094 (2026-08-23, push to main @ 9f34454c) died at `supabase
# start`:
#
#   failed to start docker container "supabase_db_sapling": ... failed to bind
#   host port for 0.0.0.0:54322:172.18.0.2:5432/tcp: address already in use
#
# The identical commit, re-run 40 minutes later, passed. The runner is a fresh
# VM per job, so nothing was "left over" holding 54322.
#
# The mechanism: every Supabase port this project uses (54320-54329) sits
# INSIDE Linux's default ephemeral SOURCE-port range (32768-60999). Any
# outbound TCP connection the job makes can be handed 54322 as its source
# port, and Docker's later bind(0.0.0.0:54322) then fails with EADDRINUSE. The
# attempt-1 log times it exactly: the last of dozens of ghcr.io image pulls
# completes at 06:58:38.6156 and `Starting database...` is logged 0.03s later.
# Hundreds of outbound connections; one of them took the port.
#
# Those pulls happen INSIDE `supabase start`, so a pre-flight *check* would
# have passed. The fix has to be pre-emptive, which is exactly what
# net.ipv4.ip_local_reserved_ports is for: it excludes ports from AUTOMATIC
# source-port assignment only. Explicit bind() is unaffected, so Docker can
# still publish them.
#
# ── The two port sets (deliberately different) ───────────────────────────────
# RESERVE set — every `*port` key in supabase/config.toml whose value falls
#   inside the LIVE ephemeral range (read from /proc, not assumed). Enabled or
#   not: reserving a port nothing binds costs nothing, and it keeps the
#   protection in place the day someone flips `enabled = true`.
# CHECK set — the ports `supabase start` will ACTUALLY bind: the `*port` keys
#   of ENABLED sections, minus `shadow_port` (only `supabase db diff` binds
#   that one), and NOT filtered by the ephemeral range, because a foreign
#   listener breaks the bind wherever the port sits. ONLY this set can fail
#   the job or make it wait — a holder on the disabled pooler's 54329 must
#   never stall an unfiltered PR gate.
#   Today that is db 54322 + api 54321 + studio 54323 + local_smtp 54324;
#   enabled-ness is derived per section, so flipping `enabled = true` on the
#   pooler or analytics moves their port into this set with no edit here.
#
# ── What it does ─────────────────────────────────────────────────────────────
#   1. Reserve.  Merge the RESERVE set into whatever is already reserved and
#      write it back, then verify by reading the value back (the kernel stores
#      a bitmap and prints it as ranges, so the readback is compared by
#      MEMBERSHIP, never by string equality).
#   2. Diagnose. Reserving cannot free a socket allocated BEFORE this runs, so
#      the second half looks at what actually holds a CHECK port: a foreign
#      LISTENer fails the job by name (we never kill what is not ours), and a
#      non-listening holder is waited out.
#
# ── Not local ────────────────────────────────────────────────────────────────
# scripts/e2e-up.sh deliberately does NOT call this: the reservation needs root,
# and a local `supabase start` is not racing a runner's image pulls. Run by hand
# it is still safe — every sudo call uses `-n`, so on a box without passwordless
# sudo it fails immediately instead of prompting: the reservation is skipped
# with a warning and the diagnostic half still works, minus the pids `ss -p`
# can only attribute as root.
#
set -uo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT" || exit 1

CONFIG="supabase/config.toml"
PROC_PORT_RANGE="/proc/sys/net/ipv4/ip_local_port_range"
PROC_RESERVED="/proc/sys/net/ipv4/ip_local_reserved_ports"
# 75s, not 30s: a TIME-WAIT entry lives for a FIXED 60s on Linux
# (TCP_TIMEWAIT_LEN is a compile-time constant — there is no sysctl for it),
# so a 30s budget gave up before the one case it exists for could clear.
DRAIN_TIMEOUT="${PREFLIGHT_DRAIN_TIMEOUT:-75}"
# A non-numeric override would make every `-ge` test in the drain loop fail and
# spin the loop until the JOB timeout — a worse failure than the one this guard
# exists to prevent. Fall back loudly instead of failing the lane over a typo.
case "$DRAIN_TIMEOUT" in
  '' | *[!0-9]*)
    echo "preflight: WARNING - PREFLIGHT_DRAIN_TIMEOUT='$DRAIN_TIMEOUT' is not a whole number of seconds; using 75"
    DRAIN_TIMEOUT=75
    ;;
esac

# `printf '  %s\n' "$multiline"` indents only the FIRST line; every other line
# comes out flush-left. One helper so no call site gets it wrong again.
indent() { sed 's/^/  /'; }

# ── 1. Where the ephemeral range actually is ─────────────────────────────────
# Read it rather than hardcoding 32768-60999: it is a tunable, and if the
# runner image ever moves it off the Supabase ports this step becomes a no-op
# that should say so instead of silently "protecting" nothing.
if ! read -r eph_lo eph_hi < "$PROC_PORT_RANGE"; then
  echo "preflight: FAIL - cannot read $PROC_PORT_RANGE"
  echo "  This script guards a Linux-specific mechanism; it cannot run here."
  exit 1
fi
echo "preflight: ephemeral source-port range $eph_lo-$eph_hi"

# ── 2. Parse the ports out of config.toml ────────────────────────────────────
if [ ! -r "$CONFIG" ]; then
  echo "preflight: FAIL - $CONFIG not found or unreadable (run after checkout, from the repo)"
  exit 1
fi

# TOML-lite. Collect (section, key, value) for every port key and classify at
# END, so the result does NOT depend on `enabled` appearing before `port`
# inside a section. Emits tab-separated records: COUNT / RESERVE / CHECK / DROP.
if ! parsed=$(awk -v lo="$eph_lo" -v hi="$eph_hi" '
    /^[[:space:]]*#/ { next }                                   # whole-line comment

    /^[[:space:]]*\[/ {                                         # [section] / [a.b]
        sec = $0
        sub(/^[[:space:]]*\[/, "", sec)
        sub(/\].*$/, "", sec)
        if (!(sec in enabled)) enabled[sec] = 1                 # default ON: [db] has no `enabled` key
        next
    }

    /^[[:space:]]*enabled[[:space:]]*=/ {
        v = $0
        sub(/^[^=]*=[[:space:]]*/, "", v)
        if (v ~ /^false/) enabled[sec] = 0
        next
    }

    # [a-z0-9_]+_port, not [a-z_]*port: `pop3_port` has a DIGIT in the key and
    # the old pattern could not match it. Anchored to `port` or `*_port` so a
    # future key merely ENDING in "port" (e.g. `report`) cannot slip in.
    /^[[:space:]]*(port|[a-z0-9_]+_port)[[:space:]]*=/ {
        key = $0; sub(/[[:space:]]*=.*$/, "", key); gsub(/[[:space:]]/, "", key)
        val = $0; sub(/^[^=]*=[[:space:]]*/, "", val)
        sub(/[[:space:]]*#.*$/, "", val); gsub(/[[:space:]]/, "", val)
        raw = val
        gsub(/_/, "", val)                                      # TOML allows 54_322
        # Bare integers only. `v = $2 + 0` used to coerce 54_322 -> 54 and
        # "54322" -> 0 and drop the port with no trace; say so instead.
        if (val !~ /^[0-9]+$/) { print "DROP\t" NR "\t" key "\t" raw; next }
        n++; pv[n] = val + 0; pk[n] = key; ps[n] = sec
    }

    END {
        print "COUNT\t" n + 0
        for (i = 1; i <= n; i++) {
            if (pv[i] >= lo && pv[i] <= hi)               print "RESERVE\t" pv[i]
            if (enabled[ps[i]] && pk[i] != "shadow_port") print "CHECK\t" pv[i]
        }
    }
  ' "$CONFIG"); then
  echo "preflight: FAIL - could not parse $CONFIG"
  exit 1
fi

# Splitting the records is in-memory string work that realistically cannot
# fail — but "realistically cannot fail" is the reasoning that produced the
# fail-open probe this rework had to fix. An empty $check_csv is indistinguish-
# able from "no enabled service binds a port", which would exit 0 having
# checked nothing, so these branch on their status like everything else.
if ! n_ports=$(printf '%s\n' "$parsed" | awk -F'\t' '$1 == "COUNT" { print $2 + 0 }') ||
   ! drops=$(printf '%s\n' "$parsed" | awk -F'\t' '$1 == "DROP" { printf "line %s: %s = %s\n", $2, $3, $4 }') ||
   ! reserve_csv=$(printf '%s\n' "$parsed" | awk -F'\t' '$1 == "RESERVE" { print $2 }' | sort -un | paste -sd, -) ||
   ! check_csv=$(printf '%s\n' "$parsed" | awk -F'\t' '$1 == "CHECK"   { print $2 }' | sort -un | paste -sd, -); then
  echo "preflight: FAIL - could not classify the port records parsed out of $CONFIG"
  echo "  (awk/sort/paste failed on data that had already parsed — the environment is broken,"
  echo "  and continuing would report an unchecked port set as free.)"
  exit 1
fi
n_ports="${n_ports:-0}"

if [ -n "$drops" ]; then
  echo "preflight: WARNING - port key(s) in $CONFIG whose value is not a bare integer."
  echo "  These ports are NOT protected — fix the value, or teach the parser:"
  printf '%s\n' "$drops" | indent
fi

if [ "$n_ports" -eq 0 ]; then
  echo "preflight: FAIL - no port keys parsed out of $CONFIG"
  echo "  Two very different things look like this and both need a human:"
  echo "    (a) the ports really are gone / renumbered out of the file, in which"
  echo "        case this step is obsolete and should be deleted, or"
  echo "    (b) the parser broke against a restructured config, in which case the"
  echo "        guard has silently stopped guarding."
  exit 1
fi

# ── 3. Reserve ───────────────────────────────────────────────────────────────
reserved=no
if [ -z "$reserve_csv" ]; then
  echo "preflight: note - none of the $n_ports port(s) in $CONFIG fall inside the ephemeral"
  echo "  range ($eph_lo-$eph_hi), so there is nothing to reserve. If that is permanent, the"
  echo "  reservation half of this step is obsolete (the LISTEN check below is not)."
  reserved=moot
elif ! current=$(cat "$PROC_RESERVED" 2>/dev/null); then
  # Read-modify-write, so a failed read must NOT fall through to the write: a
  # blind write replaces the whole bitmap and would clobber a reservation we
  # cannot see.
  echo "preflight: WARNING - could not read net.ipv4.ip_local_reserved_ports;"
  echo "  skipping the write rather than clobbering a reservation we cannot see."
else
  # `sort -u`, NOT `sort -un`: an existing reservation may contain RANGES
  # ("1024-1030"), and a numeric sort coerces that entry to 1024 and silently
  # drops the rest of the range. The kernel takes a mixed, unordered list and
  # normalises it itself.
  # Guarded for the same reason as the record split above, and with a sharper
  # consequence: an empty $want would write an EMPTY reservation, i.e. clear
  # the bitmap this block exists to extend.
  if ! want=$(printf '%s\n%s\n' "$current" "$reserve_csv" | tr ',' '\n' | sed '/^$/d' | sort -u | paste -sd, -); then
    echo "preflight: WARNING - could not build the merged reservation list; skipping the write"
    want=""
  fi
  # `sudo -n`: never block on a password prompt. On a runner this is a no-op;
  # run by hand on a dev box without passwordless sudo it fails immediately and
  # the step degrades to its diagnostic half, which is what the header promises.
  if [ -z "$want" ]; then
    : # already warned
  elif sudo -n sysctl -qw "net.ipv4.ip_local_reserved_ports=$want"; then
    readback=$(cat "$PROC_RESERVED" 2>/dev/null)
    # The kernel prints the bitmap back as ranges ("54320-54324,54327,54329"),
    # so a string compare would report a mismatch on every successful write.
    # Check MEMBERSHIP of each port we asked for instead.
    if ! missing=$(printf '%s\n' "$readback" | tr ',' '\n' | awk -v want="$reserve_csv" '
        BEGIN { n = split(want, w, ",") }
        {
            lo = $0; hi = $0
            if ($0 ~ /^[0-9]+-[0-9]+$/) { split($0, r, "-"); lo = r[1]; hi = r[2] }
            for (i = 1; i <= n; i++) if (w[i] + 0 >= lo + 0 && w[i] + 0 <= hi + 0) ok[i] = 1
        }
        END { for (i = 1; i <= n; i++) if (!(i in ok)) printf "%s%s", (out++ ? "," : ""), w[i] }
      '); then
      # Unverifiable is not verified: claiming reserved=yes here is the exact
      # fail-open shape F4 condemned.
      echo "preflight: WARNING - could not verify the reservation readback; treating the ports as UNRESERVED"
    elif [ -n "$missing" ]; then
      echo "preflight: WARNING - sysctl reported success but the readback is missing $missing"
      echo "  readback: ${readback:-<empty>}"
      echo "  treating the ports as UNRESERVED; collisions stay possible."
    else
      reserved=yes
      echo "preflight: reserved $readback"
    fi
  else
    echo "preflight: WARNING - could not set net.ipv4.ip_local_reserved_ports; collisions stay possible"
  fi
fi

# ── 4. Diagnose what already holds a port supabase start will bind ───────────
if [ "$reserved" = yes ]; then
  how="reserved from the ephemeral range"
elif [ "$reserved" = moot ]; then
  how="no reservation needed - no port is inside the ephemeral range"
else
  how="NOT reserved - see WARNING above, a collision is still possible"
fi

if [ -z "$check_csv" ]; then
  echo "preflight: note - no ENABLED service in $CONFIG binds a port; nothing to check ($how)"
  exit 0
fi

if ! command -v ss >/dev/null 2>&1; then
  echo "preflight: WARNING - \`ss\` is not installed; cannot check who holds ${check_csv}"
  echo "preflight: ports $check_csv unverified ($how)"
  exit 0
fi

# `ss -p` can only attribute a socket to a pid as root, and that pid is the
# entire value of the FAIL message below. CI runners have passwordless sudo;
# a dev box may not, so fall back to an unprivileged probe rather than to no
# probe at all.
ss_probe=(ss -H -tanp)
if sudo -n true 2>/dev/null; then
  ss_probe=(sudo -n ss -H -tanp)
else
  echo "preflight: note - no passwordless sudo; probing sockets unprivileged (holders may show with no pid)"
fi

port_re=":(${check_csv//,/|})\$"
clean=yes
waited=0
announced=no

while :; do
  raw=$("${ss_probe[@]}" 2>/dev/null)
  probe_status=$?
  if [ "$probe_status" -ne 0 ]; then
    # NOT fail-open. A probe that cannot run is indistinguishable from a probe
    # that found nothing only if we let it be; saying "free" here would be a
    # lie in the one line a morning reader greps for.
    echo "preflight: WARNING - socket probe failed (${ss_probe[*]} exited $probe_status);"
    echo "  cannot tell free from busy, so these ports are NOT being reported free."
    clean=no
    break
  fi

  # Same rule as the probe itself: a filter that could not run must not read as
  # "nothing found". Both statuses are checked before either result is trusted.
  if ! busy=$(printf '%s\n' "$raw" | awk -v re="$port_re" '$4 ~ re') ||
     ! listening=$(printf '%s\n' "$busy" | awk '$1 == "LISTEN"'); then
    echo "preflight: WARNING - could not filter the socket table (awk failed);"
    echo "  cannot tell free from busy, so these ports are NOT being reported free."
    clean=no
    break
  fi
  [ -n "$busy" ] || break

  if [ -n "$listening" ]; then
    echo "preflight: FAIL - a foreign process is LISTENing on a port \`supabase start\` will bind"
    echo "  (state / recv-q / send-q / local / peer / process)"
    printf '%s\n' "$listening" | indent
    echo "preflight: not killing it - it is not ours. Free the port and re-run."
    exit 1
  fi

  if [ "$announced" = no ]; then
    announced=yes
    echo "preflight: port(s) held by non-listening socket(s); waiting up to ${DRAIN_TIMEOUT}s:"
    printf '%s\n' "$busy" | indent
    echo "  TIME-WAIT clears itself after ~60s (Linux's fixed TCP_TIMEWAIT_LEN) - hence the"
    echo "  ${DRAIN_TIMEOUT}s budget. ESTABLISHED is a LIVE connection, not a transient one: it"
    echo "  releases when it closes, which may be after the budget or never."
    echo "  SO_REUSEADDR does not rescue this: Linux only lets a bind() step over a TIME-WAIT"
    echo "  socket when BOTH sockets set the option, and the outbound connection that took the"
    echo "  port as its source port never did - so Docker's bind really does get EADDRINUSE."
  fi

  if [ "$waited" -ge "$DRAIN_TIMEOUT" ]; then
    echo "preflight: WARNING - still held after ${DRAIN_TIMEOUT}s:"
    printf '%s\n' "$busy" | indent
    echo "preflight: continuing; if 'supabase start' now fails with 'address already in use', this is why."
    clean=no
    break
  fi

  sleep 2
  waited=$((waited + 2))
done

# One greppable summary line, and the word "free" keeps its meaning: it is only
# printed when the ports were actually observed free.
if [ "$clean" = yes ]; then
  echo "preflight: ports $check_csv free (enabled services; $how)"
else
  echo "preflight: ports $check_csv NOT all free (enabled services; $how) - see WARNING above"
fi
