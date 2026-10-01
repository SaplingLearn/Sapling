import os
from dotenv import load_dotenv

load_dotenv()

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
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

# Deployment mode (#174). Defaults to "production" so the config is fail-closed:
# a deployment that sets nothing gets the strict checks. Set APP_ENV=local (or
# development/dev/test) to relax SESSION_SECRET for local dev.
APP_ENV = os.getenv("APP_ENV", "production").strip().lower()
IS_LOCAL = APP_ENV in {"local", "development", "dev", "test"}

# Sign-in email-domain allowlist. Comma-separated; empty value = allow any domain.
# Default preserves prod's @bu.edu-only behavior. Staging can widen this (e.g.
# "bu.edu,saplinglearn.com") or set it empty to allow any Google account — safe
# on staging because Cloudflare Access already gates who reaches the app at all.
ALLOWED_EMAIL_DOMAINS = [
    d.strip().lstrip("@").lower()
    for d in os.getenv("ALLOWED_EMAIL_DOMAINS", "bu.edu").split(",")
    if d.strip()
]

# Learning loop series (docs/superpowers/specs/2026-09-26-learning-loop-design.md §7,
# post-launch parse — PKG-14b). The loop is the default for every student.
_raw = os.getenv("LEARNING_LOOP_ENABLED", "").strip().lower()
# Kill switch (spec §13 A14): any falsy spelling turns the loop off; unset or empty means ON.
_LOOP_OFF = {"false", "0", "off", "no"}
LEARNING_LOOP_ENABLED = _raw not in _LOOP_OFF
if _raw not in _LOOP_OFF | {"", "true", "1", "on", "yes"}:
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
# † Tutor calls per student per UTC day (owner decision A38, HANDOFF-06b): a COUNT cap that
# holds when llm_usage cost reads wrong (#689) or EVENTS_LOGGING_ENABLED=false writes no rows.
STUDENT_DAILY_TUTOR_CALLS = int(os.getenv("STUDENT_DAILY_TUTOR_CALLS", "200"))
# Platform spend alert: alert-only, never blocks a request. Unset = no alert (the owner sets it).
_platform_budget = os.getenv("PLATFORM_DAILY_BUDGET_USD", "").strip()
PLATFORM_DAILY_BUDGET_USD: float | None = float(_platform_budget) if _platform_budget else None
PLATFORM_ALERT_FRACTION = float(os.getenv("PLATFORM_ALERT_FRACTION", "0.8"))
PLATFORM_CHECK_INTERVAL_S = int(os.getenv("PLATFORM_CHECK_INTERVAL_S", "300"))

GOOGLE_SCOPES = [
    "https://www.googleapis.com/auth/calendar.events",
    "https://www.googleapis.com/auth/calendar.readonly",
]

# Unified scopes for sign-in: identity + calendar access in one consent screen
AUTH_SCOPES = [
    "openid",
    "https://www.googleapis.com/auth/userinfo.email",
    "https://www.googleapis.com/auth/userinfo.profile",
    "https://www.googleapis.com/auth/calendar.events",
    "https://www.googleapis.com/auth/calendar.readonly",
]


STORAGE_BUCKET: str = "avatars"
MAX_AVATAR_SIZE: int = 5 * 1024 * 1024  # 5 MB


def validate_config() -> None:
    """Fail loudly at startup if required configuration is missing (#174).

    Without this the app boots with empty secrets and fails opaquely later:
    a "" SUPABASE_URL builds a malformed REST URL on the first DB call, a
    missing GEMINI_API_KEY surfaces only mid-request, and — worst — an empty
    SESSION_SECRET silently disables HMAC signing and drops session/OAuth
    state into an unsigned in-memory fallback. Raise one clear error naming
    every missing key instead.

    SESSION_SECRET is required outside local dev (IS_LOCAL) and must be a
    strong secret — a whitespace-only or short value would silently become a
    weak HMAC signing key. We require >= 32 bytes after stripping, matching the
    frontend (lib/sessionToken.ts). The other three are always required
    (CI/tests supply dummy values).
    """
    missing = []
    if not SUPABASE_URL:
        missing.append("SUPABASE_URL")
    if not SUPABASE_SERVICE_KEY:
        missing.append("SUPABASE_SERVICE_KEY")
    if not GEMINI_API_KEY:
        missing.append("GEMINI_API_KEY")
    if not IS_LOCAL and len((SESSION_SECRET or "").strip().encode("utf-8")) < 32:
        missing.append("SESSION_SECRET (must be set and >= 32 bytes)")
    if missing:
        raise RuntimeError(
            "Missing required configuration: "
            + ", ".join(missing)
            + f". (APP_ENV={APP_ENV!r}; set APP_ENV=local to relax SESSION_SECRET for local dev.)"
        )


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
    `SAPLING_METRICS_TOKEN` Worker secret. Optional and deliberately absent from
    `validate_config`: unset, empty or whitespace-only means the route answers a
    plain 404, as if it did not exist. Generate with `openssl rand -hex 32`.

    Stripped, because a value pasted into a host's dashboard with a trailing
    newline would otherwise never match anything and fail as a silent 401.

    Read at call time, not import time (like `build_commit` below), so a
    rotation needs no code change and a test can set the env var.
    """
    return (os.getenv("CANOPY_METRICS_TOKEN") or "").strip()


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
