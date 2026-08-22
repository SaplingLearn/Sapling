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


# ── Mastery tiers (#557) ────────────────────────────────────────────────────
#
# THE thresholds. Every surface that classifies a mastery score reads them
# from here — the Tree, the tutor's progress tool, flashcard selection, the
# seeds. Three sets used to exist (this one, the tutor's 0.7/0.4, and
# flashcards' ad-hoc <0.4), which meant a student could read "Struggling" on
# the Tree and be counted as in-progress by the tutor in the same session.
#
# If a surface ever needs a genuinely different cut, name it HERE as its own
# constant with the reason. A local literal is how the last three diverged.
MASTERY_MASTERED_MIN = 0.75
MASTERY_LEARNING_MIN = 0.45
MASTERY_STRUGGLING_MIN = 0.1


def get_mastery_tier(score: float) -> str:
    if score >= MASTERY_MASTERED_MIN:
        return "mastered"
    elif score >= MASTERY_LEARNING_MIN:
        return "learning"
    elif score >= MASTERY_STRUGGLING_MIN:
        return "struggling"
    return "unexplored"


def is_mastered(score: float) -> bool:
    """The top tier — the same one the Tree labels "mastered"."""
    return score >= MASTERY_MASTERED_MIN


def is_weak(score: float) -> bool:
    """Below the learning floor: "struggling" OR "unexplored".

    Both mean "not yet learning this", which is the question every caller is
    actually asking — which concepts need work (weak counts, flashcard drills,
    quiz focus). Splitting them here would just push the union back out to the
    call sites, which is where the drift came from.
    """
    return score < MASTERY_LEARNING_MIN


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
