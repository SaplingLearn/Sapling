"""
Canonical `sapling_session` token minting (#381).

Wire format — this is exactly what `services/auth_guard._decode_session` verifies
and what the frontend session BFF (`frontend/src/lib/sessionToken.ts`) issues to
the browser:

    payload     = {"user_id": <str>, "exp": <unix seconds>}
    payload_b64 = base64url(json.dumps(payload)).rstrip("=")
    sig_b64     = base64url(HMAC_SHA256(SESSION_SECRET, payload_b64)).rstrip("=")
    token       = f"{payload_b64}.{sig_b64}"

Before #381 those five lines were re-implemented in three separate places
(`routes/auth.py`'s OAuth redirect handoff, `db/e2e_staging_http.py`, and
`tests/integration/conftest.py`). Every copy is a chance for the minted format to
drift away from the verifier, so everything that mints a token now calls
`mint_session` here.

(`tests/test_auth_session_contract.py::_mint` deliberately stays an independent
re-implementation — its entire job is to pin the cross-service contract from the
outside, which it could not do by calling the code under test.)

SECURITY — this module only *formats and signs*. It performs no authentication
and no authorization: reaching it means the caller has already decided the
subject is entitled to a session. No request-path code may call it without such
a check. The single test-only HTTP surface that exposes it,
`routes/auth.py::mint_test_session`, is hard-gated on `APP_ENV in {local, test}`
and 404s everywhere else.
"""

import base64
import hashlib
import hmac
import json
import time

import config

# The cookie `auth_guard._decode_session` reads and the frontend BFF sets.
SESSION_COOKIE_NAME = "sapling_session"

DEFAULT_TTL_SECONDS = 3600


def _now() -> int:
    """Current unix time. Seam so tests can freeze the clock and compare tokens
    byte-for-byte against a reference implementation."""
    return int(time.time())


def mint_session(user_id: str, ttl: int = DEFAULT_TTL_SECONDS, *, secret: str | None = None) -> str:
    """Mint a signed session token for `user_id`, valid for `ttl` seconds.

    `secret` defaults to the live `config.SESSION_SECRET` (read at call time, not
    captured at import, so tests and env overrides take effect). An empty secret
    raises instead of silently signing with a zero-length key: `_decode_session`
    rejects every token when `SESSION_SECRET` is falsy, so such a token could
    never authenticate and the failure would surface far from its cause.
    """
    key = secret if secret is not None else (config.SESSION_SECRET or "")
    if not key:
        raise RuntimeError(
            "SESSION_SECRET is not configured; refusing to mint an unsigned session token."
        )
    payload = json.dumps({"user_id": user_id, "exp": _now() + int(ttl)}).encode()
    payload_b64 = base64.urlsafe_b64encode(payload).decode().rstrip("=")
    sig = hmac.new(key.encode(), payload_b64.encode(), hashlib.sha256).digest()
    sig_b64 = base64.urlsafe_b64encode(sig).decode().rstrip("=")
    return f"{payload_b64}.{sig_b64}"
