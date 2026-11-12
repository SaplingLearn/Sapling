"""OAuth state for the Google sign-in and calendar-connect flows (#118, moved
from ``routes/auth.py``): PKCE, the signed state cookie, the once-only nonce,
the redirect-token TTL and the client config."""
import base64
import hashlib
import hmac as _hmac
import json
import logging
import os
import re
import secrets
import threading
import time as _time

# The module (not just its constants) so _clean_return_to reads the LIVE
# APP_ENV instead of an import-time snapshot.
import config
from config import (
    GOOGLE_CLIENT_ID,
    GOOGLE_CLIENT_SECRET,
    GOOGLE_AUTH_REDIRECT_URI,
    GOOGLE_SCOPES,
    SESSION_SECRET,
    IS_LOCAL,
)
from services import pg_lease

logger = logging.getLogger(__name__)

OAUTH_STATE_COOKIE = "sapling_oauth_state"
_OAUTH_COOKIE_MAX_AGE = 600
_POPUP_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,128}$")

# Cloudflare preview URLs of the frontend-staging worker, one per PR/version:
# https://<alias>-frontend-staging.saplinglearn.workers.dev. Google only accepts
# exact redirect URIs, so a preview can't be registered. Instead it starts sign-in
# here with ?return_to=<its origin>: Google still calls back to the one registered
# api.staging URI, and only the final hand-off redirect goes back to the preview.
# The <alias> label is capped so the whole DNS label stays within 63 chars.
_PREVIEW_ORIGIN_RE = re.compile(
    r"^https://[a-z0-9](?:[a-z0-9-]{0,44}[a-z0-9])?"
    r"-frontend-staging\.saplinglearn\.workers\.dev$"
)

# TTL of the one-shot HMAC token handed to the frontend on the OAuth-callback
# redirect. This is NOT the session lifetime (#168): the frontend session BFF
# (frontend/src/app/api/auth/session) verifies this token once and re-mints a
# long-lived `sapling_session` cookie (SESSION_MAX_AGE = 30 days) in the same
# backend-compatible HMAC format, which `auth_guard._decode_session` accepts.
# So this token only needs to outlive the redirect round-trip. Configurable for
# environments with slow OAuth hops. See docs/decisions/0018-session-token-lifecycle.md.
_DEFAULT_REDIRECT_TOKEN_TTL_SECONDS = 300


def _clamp_redirect_ttl(seconds: int) -> int:
    """Clamp the redirect-handoff token TTL to [30, 600]s.

    This one-shot token travels in the OAuth-callback URL, so a misconfigured
    override must not be able to turn it into a long-lived credential — it is
    NOT the session (see docs/decisions/0018-session-token-lifecycle.md). The
    floor keeps slow OAuth hops working; the ceiling keeps the handoff short.
    """
    return max(30, min(seconds, 600))


def _parse_redirect_ttl(raw: str | None) -> int:
    """Parse the SAPLING_AUTH_REDIRECT_TOKEN_TTL override into a clamped TTL.

    A non-numeric or empty override (e.g. the var declared in Railway/Wrangler
    with no value) must not take the whole app down: this module is imported at
    router-mount time, so an unguarded int() would raise ValueError and stop the
    app from booting. Fall back to the default and warn instead.
    """
    if raw is None:
        return _DEFAULT_REDIRECT_TOKEN_TTL_SECONDS
    try:
        return _clamp_redirect_ttl(int(raw))
    except ValueError:
        logger.warning(
            "Ignoring malformed SAPLING_AUTH_REDIRECT_TOKEN_TTL=%r (expected an "
            "integer number of seconds); falling back to %ss.",
            raw,
            _DEFAULT_REDIRECT_TOKEN_TTL_SECONDS,
        )
        return _DEFAULT_REDIRECT_TOKEN_TTL_SECONDS


_REDIRECT_TOKEN_TTL_SECONDS = _parse_redirect_ttl(
    os.getenv("SAPLING_AUTH_REDIRECT_TOKEN_TTL")
)

# Fallback in-memory store for environments without SESSION_SECRET; entries
# are keyed by nonce and expire after _OAUTH_COOKIE_MAX_AGE seconds.
_OAUTH_FALLBACK_STORE: dict[str, tuple[float, dict]] = {}

# #756: OAuth state nonces the callback has already accepted, nonce → monotonic
# expiry. The state cookie is cleared on every callback response, but a client
# that ignores (or an attacker that captured) the cookie could otherwise replay
# the same state for the cookie's whole max-age. Each nonce is honoured once:
# here, and (`stateless_locks`, services/pg_lease.py) on every replica via a
# never-released lease on the nonce's HASH. Google's code is itself single-use.
_CONSUMED_OAUTH_NONCES: dict[str, float] = {}
_CONSUMED_OAUTH_NONCES_LOCK = threading.Lock()


def _consume_oauth_nonce(nonce: str) -> bool:
    """Mark `nonce` used. True the first time, False on any replay."""
    now = _time.monotonic()
    with _CONSUMED_OAUTH_NONCES_LOCK:
        for k in [k for k, exp in _CONSUMED_OAUTH_NONCES.items() if exp < now]:
            del _CONSUMED_OAUTH_NONCES[k]
        if nonce in _CONSUMED_OAUTH_NONCES:
            return False
        _CONSUMED_OAUTH_NONCES[nonce] = now + _OAUTH_COOKIE_MAX_AGE
    if pg_lease.consume_once(pg_lease.hashed_key("oauth_nonce", nonce), _OAUTH_COOKIE_MAX_AGE) is False:
        return False  # consumed on another replica
    _OAUTH_FALLBACK_STORE.pop(nonce, None)
    return True


def clear_consumed_oauth_nonces() -> None:
    """Test hook: forget every consumed nonce (tests reuse fixed nonces)."""
    with _CONSUMED_OAUTH_NONCES_LOCK:
        _CONSUMED_OAUTH_NONCES.clear()


def _google_client_config() -> dict:
    return {
        "web": {
            "client_id": GOOGLE_CLIENT_ID,
            "client_secret": GOOGLE_CLIENT_SECRET,
            "redirect_uris": [GOOGLE_AUTH_REDIRECT_URI],
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
        }
    }


def granted_scopes(creds, requested) -> frozenset[str]:
    """The scopes Google says it granted with `creds` (the token response's
    ``scope``), which is rarely just what was asked for: under
    ``include_granted_scopes`` it adds every scope the student granted us
    before, and on Google's per-scope consent screen a student can untick
    one. RFC 6749 §5.1 lets a server leave ``scope`` out when it equals the
    request, so an absent one means `requested`.

    The code exchange runs on a Flow built WITHOUT scopes (routes/auth.py,
    routes/calendar.py): oauthlib otherwise raises "Scope has changed" on
    any difference, which failed the exchange in exactly those two cases.
    This is the check instead."""
    raw = getattr(creds, "granted_scopes", None)
    if raw is None:
        return frozenset(requested)
    if isinstance(raw, str):
        raw = raw.split()
    return frozenset(str(s) for s in raw)


def covers_calendar(scopes) -> bool:
    """Whether a grant includes every calendar scope (config.GOOGLE_SCOPES).
    Only such a grant's tokens are stored, so a stored token is one that can
    reach the calendar."""
    return set(GOOGLE_SCOPES) <= set(scopes)


def _encode_state(data: dict) -> str:
    payload = json.dumps(data)
    return base64.urlsafe_b64encode(payload.encode()).decode()


def _decode_state(state: str) -> dict:
    try:
        payload = base64.urlsafe_b64decode(state.encode()).decode()
        return json.loads(payload)
    except Exception:
        return {}


def _generate_pkce_pair():
    code_verifier = base64.urlsafe_b64encode(secrets.token_bytes(32)).rstrip(b'=').decode()
    code_challenge = base64.urlsafe_b64encode(
        hashlib.sha256(code_verifier.encode()).digest()
    ).rstrip(b'=').decode()
    return code_verifier, code_challenge


def _clean_popup_id(s: str | None) -> str | None:
    if not s:
        return None
    return s if _POPUP_ID_RE.match(s) else None


def _clean_return_to(s: str | None) -> str | None:
    """Accept `return_to` only on the staging backend and only for a preview origin.

    The callback hands the one-shot auth_token to this origin, so anything looser
    is a token-exfiltration redirect. Production never honours it (its previews,
    if any, hold staging's SESSION_SECRET and couldn't use a prod token anyway).
    Read APP_ENV live, like _test_auth_enabled, so tests can flip it.
    """
    if not s or config.APP_ENV != "staging":
        return None
    return s if _PREVIEW_ORIGIN_RE.fullmatch(s) else None


def _encode_oauth_cookie(payload: dict) -> str:
    raw = json.dumps(payload, separators=(",", ":")).encode()
    payload_b64 = base64.urlsafe_b64encode(raw).decode().rstrip("=")
    if SESSION_SECRET:
        sig_bytes = _hmac.new(SESSION_SECRET.encode(), payload_b64.encode(), hashlib.sha256).digest()
        sig_b64 = base64.urlsafe_b64encode(sig_bytes).decode().rstrip("=")
        return f"{payload_b64}.{sig_b64}"
    # #174: the unsigned in-memory fallback is local-dev only. Outside local it
    # is a silent, insecure degradation (unsigned OAuth state) — fail closed.
    # (validate_config already blocks startup without SESSION_SECRET in prod;
    # this is defense in depth at the use site.)
    if not IS_LOCAL:
        raise RuntimeError(
            "SESSION_SECRET is required outside local dev; refusing to issue "
            "unsigned OAuth state."
        )
    nonce = payload.get("n", "")
    if nonce:
        _OAUTH_FALLBACK_STORE[nonce] = (_time.monotonic() + _OAUTH_COOKIE_MAX_AGE, payload)
        _prune_fallback_store()
    return payload_b64


def _decode_oauth_cookie(cookie_value: str | None) -> dict | None:
    if not cookie_value:
        return None
    if SESSION_SECRET:
        if "." not in cookie_value:
            return None
        try:
            payload_b64, sig_b64 = cookie_value.rsplit(".", 1)
        except ValueError:
            return None
        expected = _hmac.new(SESSION_SECRET.encode(), payload_b64.encode(), hashlib.sha256).digest()
        expected_b64 = base64.urlsafe_b64encode(expected).decode().rstrip("=")
        if not _hmac.compare_digest(expected_b64, sig_b64):
            return None
        try:
            padded = payload_b64 + "=" * (-len(payload_b64) % 4)
            payload = json.loads(base64.urlsafe_b64decode(padded.encode()).decode())
        except Exception:
            return None
        return payload if isinstance(payload, dict) else None
    # #174: the unsigned in-memory path is local-dev only. Outside local,
    # refuse to accept unsigned OAuth state (symmetric with the encode-side
    # guard) so no unsigned cookie is ever honored in production.
    if not IS_LOCAL:
        return None
    try:
        padded = cookie_value + "=" * (-len(cookie_value) % 4)
        payload = json.loads(base64.urlsafe_b64decode(padded.encode()).decode())
    except Exception:
        return None
    if not isinstance(payload, dict):
        return None
    nonce = payload.get("n")
    _prune_fallback_store()
    entry = _OAUTH_FALLBACK_STORE.get(nonce or "")
    if not entry:
        return None
    return entry[1]


def _prune_fallback_store() -> None:
    now = _time.monotonic()
    expired = [k for k, (exp, _) in _OAUTH_FALLBACK_STORE.items() if exp < now]
    for k in expired:
        _OAUTH_FALLBACK_STORE.pop(k, None)
