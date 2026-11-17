"""
Canonical `sapling_session` token minting (#381).

Wire format — this is exactly what `services/auth_guard._decode_session` verifies
and what the frontend session BFF (`frontend/src/lib/sessionToken.ts`) issues to
the browser:

    payload     = {"user_id": <str>, "exp": <unix seconds>, "typ": "session"|"handoff",
                   "iat": <unix seconds, truncated to the millisecond>,
                   "iat_precision": "ms"}
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

# `typ` claim values (#756). A `session` token is an API credential; a `handoff`
# token is the short-lived one the OAuth callback puts in the frontend redirect,
# good ONLY for the session BFF (frontend/src/app/api/auth/session) to exchange
# for a session — `auth_guard._decode_session` refuses it. A legacy token minted
# before the claim existed carries no `typ` and is read as a `session`.
TOKEN_TYPE_SESSION = "session"
TOKEN_TYPE_HANDOFF = "handoff"
TOKEN_TYPES = frozenset({TOKEN_TYPE_SESSION, TOKEN_TYPE_HANDOFF})

# Every token minted now says its `iat` is to the millisecond. Without it the
# guard cannot tell a millisecond iat that falls on X.000 (JSON may write it
# as the integer X) from a legacy whole-second one, which it must date
# anywhere in that second (auth_guard.issued_before). Verifiers ignore claims
# they do not read, so adding it changes nothing else.
IAT_PRECISION_CLAIM = "iat_precision"
IAT_PRECISION_MS = "ms"

# The session cookie's two names (M1, sec2). Over https (every deployed
# environment) the cookie is HOST-ONLY and carries the `__Host-` prefix: the
# browser then refuses it unless it is Secure, Path=/ and has no Domain, so a
# sibling subdomain (staging.*, api.staging.*) can neither receive nor
# overwrite it. Local http dev and the E2E stack cannot use the prefix (it
# requires Secure), so they keep the plain name. The frontend twin is
# frontend/src/lib/sessionCookie.ts.
HOST_SESSION_COOKIE_NAME = "__Host-sapling_session"
#: The plain name: http only (local dev, E2E) — and, in a deployed
#: environment, the LEGACY `Domain=.saplinglearn.com` cookie of a session
#: minted before the host-only cookie existed (read-only grace, see
#: `HOST_COOKIE_CLAIM`).
SESSION_COOKIE_NAME = "sapling_session"
#: Every name a session cookie may carry, the preferred one first.
SESSION_COOKIE_NAMES = (HOST_SESSION_COOKIE_NAME, SESSION_COOKIE_NAME)

# The claim the session BFF stamps on every session it mints for the
# host-only cookie (`"cookie": "host"`). A deployed backend still reads the
# legacy plain-named cookie, but only a token WITHOUT this claim: one the BFF
# minted before the host-only cookie shipped. Those all expire within
# SESSION_MAX_AGE_SECONDS of the frontend deploy, so the grace ends by itself,
# and a sibling subdomain cannot toss a current session (which carries the
# claim) in under the legacy name.
HOST_COOKIE_CLAIM = "cookie"
HOST_COOKIE_CLAIM_VALUE = "host"


def session_cookie_name(secure: bool) -> str:
    """The session cookie's name for a response that is (`secure`) or is not
    served over https: `__Host-sapling_session` or the plain name."""
    return HOST_SESSION_COOKIE_NAME if secure else SESSION_COOKIE_NAME

DEFAULT_TTL_SECONDS = 3600

# The longest a session may live, whatever ttl a caller asks for: the guard
# refuses a session whose `iat` is older than this (config.py).
MAX_SESSION_TTL_SECONDS = config.SESSION_MAX_AGE_SECONDS


def _now() -> float:
    """Current unix time TRUNCATED to the millisecond (a JWT NumericDate may be
    fractional). Never rounded: rounding up could date a session after a
    sign-out it preceded. Integer nanoseconds, so the truncation is exact.
    Seam so tests can freeze the clock and compare tokens byte-for-byte
    against a reference implementation."""
    return time.time_ns() // 1_000_000 / 1000


def mint_session(
    user_id: str,
    ttl: int = DEFAULT_TTL_SECONDS,
    *,
    secret: str | None = None,
    typ: str = TOKEN_TYPE_SESSION,
    claims: dict[str, str] | None = None,
) -> str:
    """Mint a signed token for `user_id`, valid for `ttl` seconds.

    `typ` is `session` (an API credential, the default) or `handoff` (the OAuth
    redirect's one-shot token, which only the session BFF accepts).
    `claims` adds string claims (the handoff's `jti` and `bh`); it can never
    override the five the format defines.

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
    if typ not in TOKEN_TYPES:
        raise ValueError(f"unknown token typ {typ!r}; expected one of {sorted(TOKEN_TYPES)}")
    # `iat` (issued at) is what server-side revocation (users.sessions_valid_after)
    # and the admin step-up window compare against. It carries milliseconds so
    # a session minted earlier in a sign-out's own second is still older than
    # it (auth_guard.issued_before); `exp` stays whole seconds. The lifetime is
    # capped at the session maximum.
    now = _now()
    ttl = min(int(ttl), MAX_SESSION_TTL_SECONDS)
    body = {
        "user_id": user_id, "exp": int(now) + ttl, "typ": typ, "iat": now,
        IAT_PRECISION_CLAIM: IAT_PRECISION_MS,
    }
    for name, value in (claims or {}).items():
        if name in body:
            raise ValueError(f"claim {name!r} is part of the token format; it cannot be overridden")
        body[name] = value
    payload = json.dumps(body).encode()
    payload_b64 = base64.urlsafe_b64encode(payload).decode().rstrip("=")
    sig = hmac.new(key.encode(), payload_b64.encode(), hashlib.sha256).digest()
    sig_b64 = base64.urlsafe_b64encode(sig).decode().rstrip("=")
    return f"{payload_b64}.{sig_b64}"
