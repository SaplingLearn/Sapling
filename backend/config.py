import logging
import os
from dotenv import load_dotenv

from learning.params import PROBE_PLAN_READS_PER_MIN

load_dotenv()

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
# Every agent slot defaults to Claude (ADR 0030); GEMINI_API_KEY stays required
# for RAG embeddings, which have no Anthropic equivalent.
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID", "")
GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET", "")
GOOGLE_REDIRECT_URI = os.getenv("GOOGLE_REDIRECT_URI", "http://localhost:5000/api/calendar/callback")
GOOGLE_AUTH_REDIRECT_URI = os.getenv("GOOGLE_AUTH_REDIRECT_URI", "http://localhost:5000/api/auth/google/callback")

SUPABASE_URL = os.getenv("SUPABASE_URL", "")
SUPABASE_SERVICE_KEY = os.getenv("SUPABASE_SERVICE_KEY", "")

# Logfire ops/error/LLM tracing. Optional: unset = dormant (main.py configures
# send_to_logfire="if-token-present", so no spans egress without it). Logfire's
# SDK reads this env var itself; surfaced here only so all env access stays
# visible through config.py.
LOGFIRE_TOKEN = os.getenv("LOGFIRE_TOKEN", "")

PORT = int(os.getenv("PORT", "5000"))
FRONTEND_URL = os.getenv("FRONTEND_URL", "http://localhost:3000")
SESSION_SECRET = os.getenv("SESSION_SECRET", "")
_sc_env = os.getenv("SECURE_COOKIES")
SECURE_COOKIES: bool = _sc_env.lower() == "true" if _sc_env is not None else FRONTEND_URL.startswith("https://")
# Whether SECURE_COOKIES was switched on EXPLICITLY (not derived from
# FRONTEND_URL): one of the deployment markers `validate_config` reads.
SECURE_COOKIES_EXPLICIT: bool = _sc_env is not None and _sc_env.strip().lower() == "true"

# Deployment mode (#174). Defaults to "production" so the config is fail-closed:
# a deployment that sets nothing gets the strict checks. Set APP_ENV=local (or
# development/dev/test) to relax SESSION_SECRET and ANTHROPIC_API_KEY for local
# dev. A process that looks like a real deployment refuses to boot in those
# modes (validate_config).
APP_ENV = os.getenv("APP_ENV", "production").strip().lower()
LOCAL_APP_ENVS = frozenset({"local", "development", "dev", "test"})  # every other value = production
IS_LOCAL = APP_ENV in LOCAL_APP_ENVS

# ── Session lifetime, revocation and admin step-up ──────────────────────────
# A `sapling_session` token carries `iat` (issued at, unix seconds to the
# millisecond). The guard (services/auth_guard.py) refuses a session older than
# SESSION_MAX_AGE_SECONDS whatever its `exp` says, and the frontend BFF mints cookies with the same
# lifetime (frontend/src/lib/sessionToken.ts SESSION_MAX_AGE; keep them equal).
SESSION_MAX_AGE_SECONDS = 7 * 24 * 3600
# Admin routes need a session issued within this window (step-up: an older one
# answers 401 `reauth_required` and the admin signs in with Google again).
ADMIN_REAUTH_WINDOW_SECONDS = int(os.getenv("ADMIN_REAUTH_WINDOW_SECONDS", str(12 * 3600)))
# The stricter window for destructive admin actions: account wipe/seed/copy,
# role changes, email broadcasts and feature-flag changes.
ADMIN_DESTRUCTIVE_REAUTH_WINDOW_SECONDS = int(
    os.getenv("ADMIN_DESTRUCTIVE_REAUTH_WINDOW_SECONDS", str(30 * 60))
)

# There is no sign-in email-domain restriction (ALLOWED_EMAIL_DOMAINS was
# removed, docs/design/open-access-gate.md): the waitlist is the only gate, and
# a non-school address is a "Non-BU" label in Admin → Allowlist
# (services/open_access.py), never a refusal.

# Learning loop series (docs/superpowers/specs/2026-09-26-learning-loop-design.md §7,
# post-launch parse — PKG-14b). The loop is the default for every student.
_raw = os.getenv("LEARNING_LOOP_ENABLED", "").strip().lower()
# Kill switch (spec §13 A14): any falsy spelling turns the loop off; unset or empty means ON.
LEARNING_LOOP_ENABLED = _raw not in {"false", "0", "off", "no"}
if _raw not in {"false", "0", "off", "no", "", "true", "1", "on", "yes"}:
    # Still ON (the §7 table is unchanged), but say so: a typo such as "disabled"
    # or "n" would otherwise leave the loop on with no trace (PKG-14 review).
    import logging

    logging.getLogger(__name__).warning(
        "LEARNING_LOOP_ENABLED=%r is not a recognised spelling; the learning loop is ON. "
        "Use false/0/off/no to turn it off.",
        _raw,
    )
# Spec §13 A5: every GATE_* seconds constant is scaled by this factor (production never
# sets it; the E2E lane sets 0.01 so hint gates open in seconds). learning.params stays
# config-free (invariant 2), so routes/learn_loop.py reads it here and passes
# time_scale= to learning.gates (HANDOFF-06). Must be finite and > 0 (params.gate_seconds).
LEARNING_GATE_TIME_SCALE = float(os.getenv("LEARNING_GATE_TIME_SCALE", "1.0"))

# AI budget (spec §3.5, §13 A20): owner-approved caps (†), env-overridable so a deploy or a
# paid tier can move them without a code change. services/ai_budget.py reads them at call time.
STUDENT_DAILY_BUDGET_USD = float(os.getenv("STUDENT_DAILY_BUDGET_USD", "0.20"))
BUDGET_NOVICE_MULTIPLIER = float(os.getenv("BUDGET_NOVICE_MULTIPLIER", "2.5"))
STUDENT_SOFT_FRACTION = float(os.getenv("STUDENT_SOFT_FRACTION", "0.8"))
STUDENT_MONTHLY_BUDGET_USD = float(os.getenv("STUDENT_MONTHLY_BUDGET_USD", "2.00"))
STUDENT_DAILY_TOKENS = int(os.getenv("STUDENT_DAILY_TOKENS", "400000"))
STUDENT_DAILY_GRADES = int(os.getenv("STUDENT_DAILY_GRADES", "300"))
LEARN_RATE_LIMIT_PER_MIN = int(os.getenv("LEARN_RATE_LIMIT_PER_MIN", "20"))


def _positive_int_env(name: str, default: int) -> int:
    """Keep a request guard enabled if a deployment override is invalid."""
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    try:
        value = int(raw.strip())
    except ValueError:
        value = 0
    if value <= 0:
        logging.getLogger(__name__).warning(
            "%s=%r is not a positive integer; using the policy default %d", name, raw, default
        )
        return default
    return value


# The no-model diagnostic/goal/plan guard keeps the policy's production default.
# Only the scripted E2E launcher raises its process-wide burst allowance.
LOOP_PROBE_PLAN_READS_PER_MIN = _positive_int_env(
    "LOOP_PROBE_PLAN_READS_PER_MIN", PROBE_PLAN_READS_PER_MIN
)
# † Tutor calls per student per UTC day (owner decision A38, HANDOFF-06b): a COUNT cap that
# holds when llm_usage cost reads wrong (#689) or EVENTS_LOGGING_ENABLED=false writes no rows.
STUDENT_DAILY_TUTOR_CALLS = int(os.getenv("STUDENT_DAILY_TUTOR_CALLS", "200"))
# Platform spend alert: alert-only, never blocks a request. Unset = no alert (the owner sets it).
_platform_budget = os.getenv("PLATFORM_DAILY_BUDGET_USD", "").strip()
PLATFORM_DAILY_BUDGET_USD: float | None = float(_platform_budget) if _platform_budget else None
PLATFORM_ALERT_FRACTION = float(os.getenv("PLATFORM_ALERT_FRACTION", "0.8"))
PLATFORM_CHECK_INTERVAL_S = int(os.getenv("PLATFORM_CHECK_INTERVAL_S", "300"))

# Google Calendar access. Asked for ONLY by the calendar consent flow
# (GET /api/calendar/auth-url, from onboarding's Connect step or the Calendar
# page), and "connected" means a grant that covers every one of these.
GOOGLE_SCOPES = [
    "https://www.googleapis.com/auth/calendar.events",
    "https://www.googleapis.com/auth/calendar.readonly",
]

# Sign-in asks for identity only (owner decision, 2026-11-12). A student who
# already granted calendar access keeps it: sign-in asks Google to include the
# scopes granted earlier (include_granted_scopes), and refreshes the stored
# calendar tokens only when that grant still covers GOOGLE_SCOPES
# (services/auth/signin.py). Sapling holds no token for an identity-only
# sign-in, so deleting an account that never connected the calendar does not
# revoke its Google grant: the student can remove Sapling in their Google
# account (Security > Third-party connections).
AUTH_SCOPES = [
    "openid",
    "https://www.googleapis.com/auth/userinfo.email",
    "https://www.googleapis.com/auth/userinfo.profile",
]

# The Terms of Service and Privacy Policy versions in force. Each is the "Last
# updated" date on the public /terms and /privacy pages. Onboarding refuses a
# submit that accepted any other version and records the ones accepted
# (services/legal.py). They live here, not in services/legal.py, so that every
# layer can read them, including the db/ ops scripts (.importlinter). The
# frontend keeps the same two values in frontend/src/lib/legal/versions.ts, and
# tests/test_legal_versions.py fails when they differ: bump both together.
TERMS_VERSION = "2026-10-22"
PRIVACY_VERSION = "2026-11-16"


# Transactional + broadcast email over Resend (services/email_service.py).
# RESEND_API_KEY unset/empty is the kill switch: every send is still recorded in
# `email_sends` (status `skipped`) and logged at INFO, but nothing leaves the
# process. Tests, E2E and local dev run without it and never touch the network.
# email_service reads these off this module at call time, so a test can patch them.
RESEND_API_KEY = os.getenv("RESEND_API_KEY", "").strip()
EMAIL_FROM = os.getenv("EMAIL_FROM", "").strip() or "Sapling <hello@saplinglearn.com>"
EMAIL_REPLY_TO = os.getenv("EMAIL_REPLY_TO", "").strip()
# Where the emails' header image loads from ({base}/email/header.jpg, built by
# frontend/scripts/build-email-header.mjs into frontend/public/email/). Defaults to
# FRONTEND_URL; staging sets it to the public prod site, since its own
# frontend sits behind Cloudflare Access and a recipient couldn't load them.
EMAIL_ASSET_BASE_URL = os.getenv("EMAIL_ASSET_BASE_URL", "").strip()


# Ops alerts (services/spend_alerts.py): thresholds for the hourly check that
# emails admins. The on/off switch is the `spend_alerts` feature flag, not an
# env var. Read at call time (functions), so tests and operators need no reload.


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, "").strip() or default)
    except ValueError:
        return default


def spend_alert_daily_usd() -> float:
    """Today's (UTC) total LLM cost that triggers the daily-spend alert."""
    return _env_float("SPEND_ALERT_DAILY_USD", 50.0)


def spend_alert_user_daily_usd() -> float:
    """One student's LLM cost today that makes them an outlier."""
    return _env_float("SPEND_ALERT_USER_DAILY_USD", 5.0)


def spend_alert_denied_per_hour() -> float:
    """auth.permission_denied events in the last hour that count as a spike."""
    return _env_float("SPEND_ALERT_DENIED_PER_HOUR", 50)


def spend_alert_5xx_per_hour() -> float:
    """error.5xx events in the last hour that count as a spike."""
    return _env_float("SPEND_ALERT_5XX_PER_HOUR", 20)


def spend_alert_spike_factor() -> float:
    """A spike must also be this many times the previous 24 h's hourly mean."""
    return _env_float("SPEND_ALERT_SPIKE_FACTOR", 3.0)


def spend_alert_recipients() -> list[str]:
    """Comma-separated addresses; empty = every admin-role account's email."""
    raw = os.getenv("SPEND_ALERT_RECIPIENTS", "")
    return [a.strip() for a in raw.split(",") if "@" in a]


STORAGE_BUCKET: str = "avatars"
MAX_AVATAR_SIZE: int = 5 * 1024 * 1024  # 5 MB


def validate_config() -> None:
    """Fail loudly at startup if required configuration is missing (#174).

    Without this the app boots with empty secrets and fails opaquely later:
    a "" SUPABASE_URL builds a malformed REST URL on the first DB call, a
    missing GEMINI_API_KEY / ANTHROPIC_API_KEY surfaces only mid-request, and — worst — an empty
    SESSION_SECRET silently disables HMAC signing and drops session/OAuth
    state into an unsigned in-memory fallback. Raise one clear error naming
    every missing key instead.

    SESSION_SECRET is required outside local dev (IS_LOCAL) and must be a
    strong secret — a whitespace-only or short value would silently become a
    weak HMAC signing key. We require >= 32 bytes after stripping, matching the
    frontend (lib/sessionToken.ts). ANTHROPIC_API_KEY is also optional locally
    so the backend can start without Claude access; AI requests still need a
    real key. Supabase credentials and GEMINI_API_KEY remain required.
    """
    missing = []
    if not SUPABASE_URL:
        missing.append("SUPABASE_URL")
    if not SUPABASE_SERVICE_KEY:
        missing.append("SUPABASE_SERVICE_KEY")
    if not GEMINI_API_KEY:
        missing.append("GEMINI_API_KEY")
    if not IS_LOCAL and not ANTHROPIC_API_KEY:
        missing.append("ANTHROPIC_API_KEY")
    if not IS_LOCAL and len((SESSION_SECRET or "").strip().encode("utf-8")) < 32:
        missing.append("SESSION_SECRET (must be set and >= 32 bytes)")
    if missing:
        raise RuntimeError(
            "Missing required configuration: "
            + ", ".join(missing)
            + f". (APP_ENV={APP_ENV!r}; set APP_ENV=local to relax SESSION_SECRET and ANTHROPIC_API_KEY for local dev.)"
        )
    _refuse_local_mode_on_a_real_deployment()
    _refuse_test_model_mode_on_a_real_deployment()
    _refuse_committed_demo_secrets()
    _refuse_weak_internal_tokens()
    _warn_db_user_scope_config()


# The optional server-to-server bearer tokens. Each is the WHOLE gate of its
# route (ACCOUNT_SYNC_INBOUND_TOKEN alone admits plaintext export and overwrite
# of any account), so a set value must be long enough to be unguessable.
# Unset stays fine: it means the feature is off (routes 404).
MIN_INTERNAL_TOKEN_BYTES = 32


def _internal_tokens() -> dict[str, str]:
    return {
        "CANOPY_METRICS_TOKEN": canopy_metrics_token(),
        "ACCOUNT_SYNC_INBOUND_TOKEN": account_sync_inbound_token(),
        "ACCOUNT_SYNC_PEER_TOKEN": account_sync_peer_token(),
    }


def _refuse_weak_internal_tokens() -> None:
    """Refuse to boot when an internal bearer token is set (non-blank after
    strip) but shorter than MIN_INTERNAL_TOKEN_BYTES utf-8 bytes. Every
    environment, local included: a token is a deliberate opt-in. Names the
    variable, never the value."""
    weak = [
        name for name, value in _internal_tokens().items()
        if value and len(value.encode("utf-8")) < MIN_INTERNAL_TOKEN_BYTES
    ]
    if weak:
        raise RuntimeError(
            "Refusing to start: " + ", ".join(weak)
            + (" is" if len(weak) == 1 else " are")
            + f" set but shorter than {MIN_INTERNAL_TOKEN_BYTES} bytes. Generate one with "
            "`openssl rand -hex 32`, or unset it to turn the route off; "
            "see backend/.env.example."
        )


# The secrets committed to the repo for local dev and CI. Anyone can read them,
# so outside local dev they are as good as no secret: a SESSION_SECRET from this
# list lets anyone mint a session for any account, an ENCRYPTION_KEY from it
# decrypts every encrypted column. Compared exactly (after strip); never echoed.
KNOWN_DEMO_SESSION_SECRETS = frozenset({
    # backend/.env.local.example, frontend/.env.local.example and
    # frontend/package.json's "start:test".
    "sapling-local-dev-session-secret-change-only-if-you-know-why",
    # frontend/.env.example's placeholder (long enough to pass the length check).
    "replace-me-with-at-least-32-bytes-of-random-string",
})
KNOWN_DEMO_ENCRYPTION_KEYS = frozenset({
    # backend/.env.local.example
    "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
    # tests/conftest.py and the CI workflows
    "0" * 64,
})

# Hosts that mean "this machine" (or a docker-compose service name).
_LOOPBACK_HOSTS = frozenset({"localhost", "127.0.0.1", "::1", "0.0.0.0", "backend", "frontend"})

# Environment variables only a hosting platform sets. Any of them present means
# this process is a real deployment, whatever APP_ENV says.
_PLATFORM_MARKERS = (
    "RAILWAY_ENVIRONMENT", "RAILWAY_ENVIRONMENT_NAME", "RAILWAY_PROJECT_ID",
    "RENDER", "FLY_APP_NAME", "K_SERVICE", "DYNO",
)


def _is_public_https(url: str) -> bool:
    """Whether `url` is https on a host other than this machine."""
    from urllib.parse import urlparse

    try:
        parsed = urlparse((url or "").strip())
        host = (parsed.hostname or "").lower()
    except ValueError:
        return False
    if parsed.scheme != "https" or not host:
        return False
    return not (host in _LOOPBACK_HOSTS or host.endswith(".localhost"))


def real_deployment_markers() -> list[str]:
    """Why this process looks like a real (shared, internet-facing) deployment
    rather than a developer's machine, CI or the local E2E stack. Names only,
    never values; empty when nothing says so."""
    reasons = []
    if _is_public_https(FRONTEND_URL):
        reasons.append("FRONTEND_URL is a public https origin")
    if _is_public_https(GOOGLE_AUTH_REDIRECT_URI):
        reasons.append("GOOGLE_AUTH_REDIRECT_URI is a public https URL")
    if SECURE_COOKIES_EXPLICIT:
        reasons.append("SECURE_COOKIES=true")
    for name in _PLATFORM_MARKERS:
        if (os.getenv(name) or "").strip():
            reasons.append(f"{name} is set (hosting platform)")
    return reasons


def _refuse_local_mode_on_a_real_deployment() -> None:
    """A local APP_ENV relaxes SESSION_SECRET, and `local`/`test` arm
    POST /api/auth/test-login, which mints a session for ANY user id with no
    credential. On a real deployment that is a takeover of every account, so a
    process that looks deployed refuses to boot in those modes."""
    if not IS_LOCAL:
        return
    reasons = real_deployment_markers()
    if reasons:
        raise RuntimeError(
            f"Refusing to start: APP_ENV={APP_ENV!r} is only for a developer's machine, CI or "
            "the local E2E stack (it enables POST /api/auth/test-login and relaxes "
            "SESSION_SECRET), but this process looks like a real deployment ("
            + "; ".join(reasons)
            + "). Set APP_ENV=production or APP_ENV=staging on deployed services."
        )


def _refuse_test_model_mode_on_a_real_deployment() -> None:
    """SAPLING_MODEL_MODE other than `real` is the test seam (#391): `function`
    answers every student with fixed E2E constants, and turns off RAG
    embeddings, the index sweeper and PostHog. On a deployed host that is
    silent fake tutoring, so a process that looks deployed refuses it,
    whatever APP_ENV says. Read the way agents/_providers.py reads it (unset or
    blank is `real`), without importing the agents package here."""
    mode = (os.getenv("SAPLING_MODEL_MODE") or "real").strip().lower()
    if mode == "real":
        return
    reasons = real_deployment_markers()
    if reasons:
        raise RuntimeError(
            f"Refusing to start: SAPLING_MODEL_MODE={mode!r} is the test seam (fixed "
            "model answers, embeddings and analytics off) and is only for CI and the "
            "local E2E stack, but this process looks like a real deployment ("
            + "; ".join(reasons)
            + "). Unset SAPLING_MODEL_MODE (or set it to 'real') on deployed services."
        )


def _refuse_committed_demo_secrets() -> None:
    """Outside local dev, refuse the SESSION_SECRET / ENCRYPTION_KEY values
    committed to the repository (KNOWN_DEMO_*). Names the variable, never the
    value."""
    if IS_LOCAL:
        return
    bad = []
    if (SESSION_SECRET or "").strip() in KNOWN_DEMO_SESSION_SECRETS:
        bad.append("SESSION_SECRET")
    if (os.getenv("ENCRYPTION_KEY") or "").strip().lower() in KNOWN_DEMO_ENCRYPTION_KEYS:
        bad.append("ENCRYPTION_KEY")
    if bad:
        raise RuntimeError(
            "Refusing to start: " + " and ".join(bad)
            + (" is" if len(bad) == 1 else " are")
            + " set to a value committed to the repository (a local-dev or CI example "
            f"anyone can read). Generate a fresh value for APP_ENV={APP_ENV!r}; "
            "see backend/.env.example."
        )


def _warn_db_user_scope_config() -> None:
    """#115 (RLS step 2): warn at boot when the `db_user_scope` flag could be
    moved past `off` without the keys the user-scoped client needs
    (SUPABASE_JWT_SIGNING_KEY + SUPABASE_ANON_KEY, db/user_jwt.py). Never
    raises: the flag lives in the DB and is off by default, so a deployment
    without the keys is fine until someone flips it — at which point enforce
    answers 503 (fail closed) and shadow skips its comparisons. An env
    override already asking for shadow/enforce makes it an ERROR."""
    import logging

    from db import user_jwt

    problems = user_jwt.config_problems()
    if not problems:
        return
    log = logging.getLogger("sapling.config")
    override = (os.getenv("SAPLING_FLAG_DB_USER_SCOPE") or "").strip().lower()
    msg = ("db_user_scope cannot leave 'off' on this deployment (%s): enforce would "
           "answer 503 and shadow would skip its comparisons. See .env.example.")
    if override in ("shadow", "enforce"):
        log.error("SAPLING_FLAG_DB_USER_SCOPE=%s but " + msg, override, "; ".join(problems))
    elif not IS_LOCAL:
        log.warning(msg, "; ".join(problems))


# ── Mastery tiers ───────────────────────────────────────────────────────────
#
# PKG-14b (spec §11.2): the one score → tier map is learning/bkt.py::tier_for
# (with in_mastered_tier / is_weak), on the spec §3.1 cuts in learning/params.py
# (TIER_UNEXPLORED_MAX / BAND_NOVICE_MAX / BKT_PROFICIENT). The legacy copy
# that lived here (#557) is deleted.


def canopy_metrics_token() -> str:
    """Shared secret for `GET /api/internal/metrics`, or "" when the feature is off.

    Canopy (the team dashboard) polls that route hourly with
    `Authorization: Bearer <this value>`; the same value is Canopy's
    `SAPLING_METRICS_TOKEN` Worker secret. Optional: unset, empty or
    whitespace-only means the route answers a plain 404, as if it did not
    exist. A SET value shorter than 32 bytes refuses boot
    (`validate_config` → `_refuse_weak_internal_tokens`). Generate with
    `openssl rand -hex 32`.

    Stripped, because a value pasted into a host's dashboard with a trailing
    newline would otherwise never match anything and fail as a silent 401.

    Read at call time, not import time (like `build_commit` below), so a
    rotation needs no code change and a test can set the env var.
    """
    return (os.getenv("CANOPY_METRICS_TOKEN") or "").strip()


# ── Cross-environment account copy (admin account tools) ────────────────────
#
# OPTIONAL: with any of these unset the copy feature is inert (the admin route
# answers 503, the internal `/api/internal/account-sync/*` routes answer 404).
# A SET token shorter than 32 bytes refuses boot (`validate_config` →
# `_refuse_weak_internal_tokens`; `openssl rand -hex 32`). Read at call time and
# stripped, like `canopy_metrics_token`, so a rotation needs no code change and
# a pasted trailing newline cannot fail as a silent 401.


def account_sync_peer_url() -> str:
    """The OTHER environment's backend base URL (no trailing slash), or ""."""
    return (os.getenv("ACCOUNT_SYNC_PEER_URL") or "").strip().rstrip("/")


def account_sync_peer_token() -> str:
    """Bearer token we SEND to the peer's internal account-sync routes, or ""."""
    return (os.getenv("ACCOUNT_SYNC_PEER_TOKEN") or "").strip()


def account_sync_inbound_token() -> str:
    """Bearer token our internal account-sync routes ACCEPT, or "" (= routes 404)."""
    return (os.getenv("ACCOUNT_SYNC_INBOUND_TOKEN") or "").strip()


def build_commit() -> str:
    """Short git SHA of the running build, or "unknown".

    The promotion runner (#516) polls /api/health until this matches the commit
    it just promoted, which is what lets it distinguish "the deploy has not
    landed yet" from "the deploy landed and the app is broken". Railway injects
    RAILWAY_GIT_COMMIT_SHA; GIT_COMMIT_SHA is the generic fallback for any other
    host. Local, Docker and E2E runs set neither and report "unknown", which the
    runner degrades on rather than hanging.

    Read at call time, not import time, so a test can set the env var.
    """
    # Strip each candidate independently before picking one: `A or B` picks
    # A whenever it is non-empty, and a whitespace-only string IS non-empty
    # (truthy), so a blank RAILWAY_GIT_COMMIT_SHA would win over a real
    # GIT_COMMIT_SHA and then strip down to "" — silently reporting
    # "unknown" instead of the SHA that was actually available.
    railway = (os.getenv("RAILWAY_GIT_COMMIT_SHA") or "").strip()
    generic = (os.getenv("GIT_COMMIT_SHA") or "").strip()
    raw = railway or generic
    return raw[:7].lower() or "unknown"


# ── PostHog (optional product analytics, ADR 0028) ──────────────────────────
#
# All of these are OPTIONAL and deliberately absent from `validate_config`: unset
# means the PostHog seam (services/posthog_client.py) is fully inert — no
# client, no threads, no network. Whether a set token is actually USED is
# decided there (`disabled_reason`), not here: it is also forced off under
# pytest, APP_ENV=test and any non-"real" SAPLING_MODEL_MODE; the runtime
# switch is the product_analytics feature flag. Read at call time, not import
# time (like `canopy_metrics_token`), so tests need no reload.

POSTHOG_DEFAULT_HOST = "https://us.i.posthog.com"  # US cloud ingestion


def posthog_project_token() -> str:
    """The project (public, write-only) token events are captured with."""
    return (os.getenv("POSTHOG_PROJECT_TOKEN") or "").strip()


def posthog_host() -> str:
    """Ingestion host. Defaults to US cloud."""
    return (os.getenv("POSTHOG_HOST") or POSTHOG_DEFAULT_HOST).strip().rstrip("/")


def posthog_personal_api_key() -> str:
    """Personal API key (scope `person:write`) — used ONLY by the account-
    deletion person delete, never handed to the capture client (a personal key
    there would start feature-flag polling, i.e. background network)."""
    return (os.getenv("POSTHOG_PERSONAL_API_KEY") or "").strip()


def posthog_project_id() -> str:
    """Numeric project id for the private REST API (person deletion)."""
    return (os.getenv("POSTHOG_PROJECT_ID") or "").strip()


#: The ONLY ingestion hosts an API host is ever derived from. The personal API
#: key (`person:write`) is sent to whatever posthog_api_host() returns, so a
#: derivation must never be able to point it at a host that is not PostHog's
#: own app: a string rewrite of an arbitrary POSTHOG_HOST (a reverse proxy, a
#: typo, a self-hosted ingest) would hand the key to that host.
_POSTHOG_INGEST_TO_API_HOST = {
    "https://us.i.posthog.com": "https://us.posthog.com",
    "https://eu.i.posthog.com": "https://eu.posthog.com",
    # The app hosts also accept ingestion; they ARE the API hosts.
    "https://us.posthog.com": "https://us.posthog.com",
    "https://eu.posthog.com": "https://eu.posthog.com",
}


def posthog_api_host() -> str | None:
    """Private REST API host for the personal-key calls (person deletion), or
    None when it cannot be determined safely.

    The ingestion host (`us.i.posthog.com`) does not serve `/api/projects/...`;
    the app host does. POSTHOG_API_HOST, when set, is used as-is (self-hosted
    or proxied setups must name their API host explicitly). Otherwise it is
    derived ONLY from the PostHog-cloud hosts (us/eu, ingestion or app); any other
    POSTHOG_HOST returns None and the caller WARNs and skips rather than
    guessing where to send the key."""
    explicit = (os.getenv("POSTHOG_API_HOST") or "").strip().rstrip("/")
    if explicit:
        return explicit
    return _POSTHOG_INGEST_TO_API_HOST.get(posthog_host().lower())
