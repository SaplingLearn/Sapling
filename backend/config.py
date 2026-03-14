import os
from dotenv import load_dotenv

load_dotenv()

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")

# Google Calendar OAuth client
GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID", "")
GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET", "")
GOOGLE_REDIRECT_URI = os.getenv("GOOGLE_REDIRECT_URI", "http://localhost:5000/api/calendar/callback")

# Google Sign-In OAuth client
GOOGLE_CLIENT_ID_SIGN_IN = os.getenv("GOOGLE_CLIENT_ID_SIGN_IN", "")
GOOGLE_CLIENT_SECRET_SIGN_IN = os.getenv("GOOGLE_CLIENT_SECRET_SIGN_IN", "")
GOOGLE_AUTH_REDIRECT_URI = os.getenv("GOOGLE_AUTH_REDIRECT_URI", "http://localhost:5000/api/auth/google/callback")

SUPABASE_URL = os.getenv("SUPABASE_URL", "")
SUPABASE_SERVICE_KEY = os.getenv("SUPABASE_SERVICE_KEY", "")

PORT = int(os.getenv("PORT", "5000"))
FRONTEND_URL = os.getenv("FRONTEND_URL", "http://localhost:3000")

GOOGLE_SCOPES = [
    "https://www.googleapis.com/auth/calendar.events",
    "https://www.googleapis.com/auth/calendar.readonly",
]


def get_mastery_tier(score: float) -> str:
    if score >= 0.75:
        return "mastered"
    elif score >= 0.45:
        return "learning"
    elif score >= 0.1:
        return "struggling"
    return "unexplored"
