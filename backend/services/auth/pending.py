"""The /pending hand-off token (#118, moved from ``routes/auth.py``)."""
import base64
import hashlib
import hmac as _hmac
import json
import time as _time

from config import SESSION_SECRET
from services.encryption import decrypt_if_present, encrypt

# ── Unapproved sign-in → /pending ─────────────────────────────────────────────
# An unapproved sign-in gets no account and no session. The hand-off to /pending
# carries a short-lived "pending token" instead, so that page can say whether the
# email is on the waitlist and add it without the student retyping it. The token
# holds the sign-in email encrypted with ENCRYPTION_KEY (so the URL never shows
# it) and is signed with a key derived from SESSION_SECRET, so it can never
# verify as a `sapling_session` (auth_guard checks against the raw secret). It
# travels in the redirect URL, not a cookie, because the OAuth callback runs on
# the API origin rather than the frontend's.
_PENDING_TOKEN_TTL_SECONDS = 3600


def _pending_token_key() -> str:
    if not SESSION_SECRET:
        return ""
    return _hmac.new(SESSION_SECRET.encode(), b"sapling-pending-v1", hashlib.sha256).hexdigest()


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _mint_pending_token(email: str, first_name: str = "") -> str:
    key = _pending_token_key()
    if not key:
        return ""
    claims = {"e": encrypt(email), "exp": int(_time.time()) + _PENDING_TOKEN_TTL_SECONDS}
    if first_name:
        claims["n"] = encrypt(first_name)
    payload = json.dumps(claims)
    payload_b64 = _b64(payload.encode())
    return f"{payload_b64}.{_b64(_hmac.new(key.encode(), payload_b64.encode(), hashlib.sha256).digest())}"


def _pending_token_claims(token: str) -> dict | None:
    """{"email", "first_name"} from a pending token, or None if forged or expired."""
    key = _pending_token_key()
    payload_b64, _, sig_b64 = (token or "").partition(".")
    if not key or not payload_b64 or not sig_b64:
        return None
    expected = _b64(_hmac.new(key.encode(), payload_b64.encode(), hashlib.sha256).digest())
    if not _hmac.compare_digest(sig_b64, expected):
        return None
    try:
        payload = json.loads(base64.urlsafe_b64decode(payload_b64 + "=" * (-len(payload_b64) % 4)))
    except Exception:
        return None
    if not isinstance(payload, dict):
        return None
    exp = payload.get("exp")
    if not isinstance(exp, int) or exp < int(_time.time()):
        return None
    email = (decrypt_if_present(payload.get("e")) or "").strip() if isinstance(payload.get("e"), str) else ""
    if "@" not in email:
        return None
    name = payload.get("n")
    first_name = (decrypt_if_present(name) or "").strip() if isinstance(name, str) else ""
    return {"email": email, "first_name": first_name}


def _pending_token_email(token: str) -> str | None:
    """The sign-in email a pending token carries, or None if forged or expired."""
    claims = _pending_token_claims(token)
    return claims["email"] if claims else None
