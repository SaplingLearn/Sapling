"""The one seam that mints the user-scoped PostgREST JWT (#115, RLS step 2).

docs/security/rls-step2-plan.md §2. Under the ``db_user_scope`` flag a request
reaches PostgREST as the student, not as service_role: ``db/connection.py``
sends ``Authorization: Bearer <this token>`` and keeps ``apikey`` as the
project's anon/publishable key (Supabase refuses a minted JWT in ``apikey``).
PostgREST switches to the ``role`` claim and exposes the claims to the
policies, whose identity anchor is ``app_auth.uid()`` (``sub``, but only when
``iss`` is ``sapling-api``).

Claims (plan §2.1): ``iss=sapling-api, sub=<users.id>, role=authenticated,
aud=authenticated, iat, exp=iat+300``. The token never leaves the backend.
The one browser-bound token, :func:`mint_realtime` (RLS step 2e, GET
/api/auth/realtime-token), has its own issuer that only room_messages SELECT
trusts.

Key: ``SUPABASE_JWT_SIGNING_KEY`` holds ONE JWK (JSON). ``kty: oct`` signs
HS256 with its ``k`` (local + CI: the Supabase CLI's default secret);
``kty: EC`` (P-256, with ``d``) signs ES256 (staging/prod after step 2d
imports our own key). A ``kid`` in the JWK is put in the JWT header. Read at
call time (not import), so a test or an operator change takes effect without a
restart; the parsed key is cached per raw value.

No JWT library is in requirements.lock, so this is stdlib ``hmac`` for HS256
and the already-locked ``cryptography`` for ES256 (DER signature converted to
the raw ``r||s`` JOSE wants). Nothing here does I/O.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import threading
import time
from typing import Callable, Optional

SIGNING_KEY_ENV = "SUPABASE_JWT_SIGNING_KEY"
ANON_KEY_ENV = "SUPABASE_ANON_KEY"

ISSUER = "sapling-api"
ROLE = "authenticated"
AUDIENCE = "authenticated"
#: Lifetime of one minted token (plan §2.1: 5 minutes).
TOKEN_TTL_S = 300
#: A cached token is re-minted once it has less than this left, so a request
#: never sends one that expires mid-flight (PostgREST checks exp per request).
REFRESH_MARGIN_S = 60
_TOKEN_CACHE_MAX = 10_000

#: RLS step 2e (docs/security/realtime-jwt-bridge-design.md): the token the
#: BROWSER's Supabase Realtime client authenticates with. A different issuer
#: on purpose: only ``app_auth.realtime_uid()`` trusts it, and the only policy
#: using that is SELECT on room_messages (members only), so a token lifted out
#: of the page reads its own rooms' messages and nothing else.
#: ``app_auth.uid()`` (every other policy) keeps rejecting it.
REALTIME_ISSUER = "sapling-realtime"
#: Lifetime of one realtime token (design doc: ~1 hour). The client re-fetches
#: before ``exp`` and calls ``realtime.setAuth`` again; Realtime closes a
#: channel whose token has expired.
REALTIME_TOKEN_TTL_S = 3600


class SigningKeyError(RuntimeError):
    """``SUPABASE_JWT_SIGNING_KEY`` (or the anon key) is missing or unusable.
    Under ``enforce`` this fails the request closed (503); it is never a
    reason to fall back to the service role."""


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _b64url_decode(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


class _Key:
    __slots__ = ("alg", "kid", "sign", "fingerprint")

    def __init__(self, alg: str, kid: Optional[str], sign: Callable[[bytes], bytes],
                 fingerprint: str) -> None:
        self.alg = alg
        self.kid = kid
        self.sign = sign
        self.fingerprint = fingerprint


def _parse_jwk(raw: str) -> _Key:
    try:
        jwk = json.loads(raw)
    except ValueError as exc:
        raise SigningKeyError(f"{SIGNING_KEY_ENV} is not valid JSON (expected one JWK)") from exc
    if not isinstance(jwk, dict):
        raise SigningKeyError(f"{SIGNING_KEY_ENV} must be a JSON object (one JWK)")
    kty = jwk.get("kty")
    kid = jwk.get("kid") if isinstance(jwk.get("kid"), str) and jwk.get("kid") else None
    # Fingerprint of the raw value: the token cache keys on it, so rotating the
    # key never serves a token signed by the previous one.
    fingerprint = hashlib.sha256(raw.encode()).hexdigest()[:16]
    if kty == "oct":
        k = jwk.get("k")
        if not isinstance(k, str) or not k:
            raise SigningKeyError(f"{SIGNING_KEY_ENV}: an oct JWK needs a non-empty 'k'")
        try:
            secret = _b64url_decode(k)
        except Exception as exc:
            raise SigningKeyError(f"{SIGNING_KEY_ENV}: 'k' is not base64url") from exc
        if len(secret) < 32:
            raise SigningKeyError(f"{SIGNING_KEY_ENV}: an HS256 secret must be >= 32 bytes")
        return _Key("HS256", kid, lambda msg: hmac.new(secret, msg, hashlib.sha256).digest(),
                    fingerprint)
    if kty == "EC":
        if jwk.get("crv") != "P-256":
            raise SigningKeyError(f"{SIGNING_KEY_ENV}: only EC crv P-256 (ES256) is supported")
        try:
            from cryptography.hazmat.primitives import hashes
            from cryptography.hazmat.primitives.asymmetric import ec
            from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature

            d = int.from_bytes(_b64url_decode(jwk["d"]), "big")
            x = int.from_bytes(_b64url_decode(jwk["x"]), "big")
            y = int.from_bytes(_b64url_decode(jwk["y"]), "big")
            private = ec.EllipticCurvePrivateNumbers(
                d, ec.EllipticCurvePublicNumbers(x, y, ec.SECP256R1())
            ).private_key()
        except KeyError as exc:
            raise SigningKeyError(f"{SIGNING_KEY_ENV}: an EC JWK needs d, x and y") from exc
        except Exception as exc:
            raise SigningKeyError(f"{SIGNING_KEY_ENV}: unusable EC key ({type(exc).__name__})") from exc

        def _sign_es256(msg: bytes) -> bytes:
            r, s = decode_dss_signature(private.sign(msg, ec.ECDSA(hashes.SHA256())))
            return r.to_bytes(32, "big") + s.to_bytes(32, "big")

        return _Key("ES256", kid, _sign_es256, fingerprint)
    raise SigningKeyError(f"{SIGNING_KEY_ENV}: unsupported kty {kty!r} (expected 'oct' or 'EC')")


_lock = threading.Lock()
_parsed: tuple[str, _Key] | None = None
#: (key fingerprint, subject) -> (exp unix seconds, token)
_tokens: dict[tuple[str, str], tuple[int, str]] = {}


def signing_key() -> _Key:
    """The parsed signing key, from the env at call time. Raises SigningKeyError."""
    global _parsed
    raw = (os.getenv(SIGNING_KEY_ENV) or "").strip()
    if not raw:
        raise SigningKeyError(f"{SIGNING_KEY_ENV} is not set")
    with _lock:
        if _parsed is not None and _parsed[0] == raw:
            return _parsed[1]
    key = _parse_jwk(raw)
    with _lock:
        _parsed = (raw, key)
    return key


def anon_key() -> str:
    """The project's anon/publishable key for the ``apikey`` header. Raises
    SigningKeyError when unset: a scoped request without it would be refused
    by the gateway, and the service key is never an acceptable stand-in."""
    value = (os.getenv(ANON_KEY_ENV) or "").strip()
    if not value:
        raise SigningKeyError(f"{ANON_KEY_ENV} is not set")
    return value


def _now() -> int:
    """Seam so tests can move the clock."""
    return int(time.time())


def mint(subject: str, *, now: int | None = None) -> str:
    """Sign a fresh token for ``subject`` (a users.id). Uncached."""
    return _sign(subject, ISSUER, TOKEN_TTL_S, now)[0]


def mint_realtime(subject: str, *, now: int | None = None) -> tuple[str, int]:
    """Sign a browser Realtime token for ``subject``: ``(token, exp)``.
    Uncached (one per GET /api/auth/realtime-token, about one an hour per open
    study room). Same key as :func:`mint`; ``iss`` is REALTIME_ISSUER. ``exp``
    is the claim actually signed into the token, never recomputed, so the
    ``expires_at`` the browser schedules its refresh on cannot drift from it."""
    return _sign(subject, REALTIME_ISSUER, REALTIME_TOKEN_TTL_S, now)


def _sign(subject: str, issuer: str, ttl_s: int, now: int | None) -> tuple[str, int]:
    """Sign one token; returns ``(token, exp)`` with ``exp`` the signed claim."""
    if not subject or not isinstance(subject, str):
        raise ValueError("a user-scoped token needs a subject")
    key = signing_key()
    iat = _now() if now is None else now
    header = {"alg": key.alg, "typ": "JWT"}
    if key.kid:
        header["kid"] = key.kid
    claims = {
        "iss": issuer, "sub": subject, "role": ROLE, "aud": AUDIENCE,
        "iat": iat, "exp": iat + ttl_s,
    }
    signing_input = (
        _b64url(json.dumps(header, separators=(",", ":")).encode())
        + "."
        + _b64url(json.dumps(claims, separators=(",", ":")).encode())
    )
    return signing_input + "." + _b64url(key.sign(signing_input.encode())), claims["exp"]


def token_for(subject: str) -> str:
    """A token for ``subject``, reused until REFRESH_MARGIN_S before it expires.
    Signing is pure CPU (tens of microseconds); the cache just keeps it off
    every single PostgREST call."""
    key = signing_key()
    now = _now()
    cache_key = (key.fingerprint, subject)
    with _lock:
        hit = _tokens.get(cache_key)
        if hit and hit[0] - REFRESH_MARGIN_S > now:
            return hit[1]
    token = mint(subject, now=now)
    with _lock:
        if len(_tokens) >= _TOKEN_CACHE_MAX:
            for k in [k for k, (exp, _) in _tokens.items() if exp - REFRESH_MARGIN_S <= now]:
                del _tokens[k]
            if len(_tokens) >= _TOKEN_CACHE_MAX:
                _tokens.clear()
        _tokens[cache_key] = (now + TOKEN_TTL_S, token)
    return token


def clear_token_cache() -> None:
    """Forget every cached token and the parsed key (tests, key rotation)."""
    global _parsed
    with _lock:
        _tokens.clear()
        _parsed = None


def config_problems() -> list[str]:
    """What would stop user-scoped requests from working, as text; [] when
    both keys are present and the signing key parses. Never raises."""
    problems = []
    try:
        signing_key()
    except SigningKeyError as exc:
        problems.append(str(exc))
    if not (os.getenv(ANON_KEY_ENV) or "").strip():
        problems.append(f"{ANON_KEY_ENV} is not set")
    return problems
