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

PORT = int(os.getenv("PORT", "5000"))
FRONTEND_URL = os.getenv("FRONTEND_URL", "http://localhost:3000")
SESSION_SECRET = os.getenv("SESSION_SECRET", "")

# Deployment mode (#174). Defaults to "production" so the config is fail-closed:
# a deployment that sets nothing gets the strict checks. Set APP_ENV=local (or
# development/dev/test) to relax SESSION_SECRET for local dev.
APP_ENV = os.getenv("APP_ENV", "production").strip().lower()
IS_LOCAL = APP_ENV in {"local", "development", "dev", "test"}

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


def get_mastery_tier(score: float) -> str:
    if score >= 0.75:
        return "mastered"
    elif score >= 0.45:
        return "learning"
    elif score >= 0.1:
        return "struggling"
    return "unexplored"
