"""The OAuth handoff token: single use, and bound to the browser that started
the sign-in (M2, sec2).

The Google callback (``routes/auth.py::google_callback``) does not set the
session cookie: it redirects to the FRONTEND's ``/auth/callback`` with a
short-lived ``typ=handoff`` token, which the session BFF
(``frontend/src/app/api/auth/session``) exchanges for the session cookie. Before
this module, the exchange only checked the HMAC, the type and the expiry, so a
handoff was a bearer credential for its whole TTL: an attacker could sign in
themselves, keep their own ``/auth/callback?...&auth_token=<handoff>`` link and
send it to a victim, whose browser then exchanged it and held a 7-day session
AS THE ATTACKER (login CSRF / session fixation). Two properties close that:

* **Bound to the browser.** The frontend starts every sign-in at
  ``/auth/start``, which sets an HttpOnly nonce cookie on the frontend host and
  sends ``binding = base64url(sha256(nonce))`` to ``GET /api/auth/google``. The
  binding is sealed into the signed OAuth state cookie, and the callback signs
  it into the handoff (claim ``bh``). The exchange recomputes the binding from
  the nonce cookie of the browser presenting the handoff: a handoff opened in
  any other browser (no nonce, or a different one) is refused.
* **Single use, across replicas.** Every handoff carries a random ``jti``. The
  exchange consumes it in ``public.auth_handoff_consumptions`` (a primary key on
  the jti's SHA-256, through ``consume_auth_handoff()``), so a second exchange
  of the same handoff, on any replica, is refused. The OAuth state nonce's
  ``pg_lease.consume_once`` is the same idea, but it is behind the default-off
  ``stateless_locks`` flag and fails OPEN (it guards double submits); this is
  an authentication decision, so it always uses the database and fails CLOSED.

The exchange itself is ``POST /api/auth/handoff/exchange`` (server to server:
the BFF calls it with the handoff and the nonce cookie's value, and signs the
session only on a 200).
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import re
import secrets
import time

from services.session_tokens import TOKEN_TYPE_HANDOFF, mint_session

logger = logging.getLogger(__name__)

#: The handoff's single-use id and browser-binding claims.
JTI_CLAIM = "jti"
BINDING_CLAIM = "bh"

#: base64url(sha256(...)) without padding: always 43 characters.
BINDING_RE = re.compile(r"^[A-Za-z0-9_-]{43}$")
#: The nonce cookie's value: 32 random bytes, base64url (43 chars). Bounded so
#: a hostile body cannot make us hash megabytes.
_NONCE_RE = re.compile(r"^[A-Za-z0-9_-]{32,128}$")

#: The SQL function the migration adds (20261116..._auth_handoff_consumptions).
CONSUME_FN = "consume_auth_handoff"
#: Bound on the consume round trip.
CONSUME_TIMEOUT_S = 3.0
#: A consumed jti is remembered past its token's expiry by this much (clock
#: skew between this process and the database).
_CONSUME_SLACK_S = 120


class HandoffRefused(Exception):
    """The handoff is not exchangeable (bad, expired, unbound, wrong browser,
    or already used). One generic answer to the caller: which check failed is
    logged, never returned."""


class HandoffStoreUnavailable(Exception):
    """The single-use store could not answer: the exchange fails closed."""


#: The sign-in nonce cookie the frontend's /auth/start sets (twin of
#: frontend/src/lib/signinNonce.ts): `__Host-` over https, plain over http.
SIGNIN_COOKIE_NAME = "sapling_signin"
HOST_SIGNIN_COOKIE_NAME = "__Host-sapling_signin"


def signin_cookie_name(secure: bool) -> str:
    """The sign-in nonce cookie's name over https (`secure`) or http."""
    return HOST_SIGNIN_COOKIE_NAME if secure else SIGNIN_COOKIE_NAME


def binding_for_nonce(nonce: str) -> str:
    """``base64url(sha256(nonce))`` without padding — the twin of the
    frontend's ``signinBinding`` (``frontend/src/lib/signinNonce.ts``)."""
    digest = hashlib.sha256(nonce.encode("utf-8")).digest()
    return base64.urlsafe_b64encode(digest).decode().rstrip("=")


def clean_binding(value: str | None) -> str | None:
    """A well-formed binding, or None."""
    if not value or not BINDING_RE.fullmatch(value):
        return None
    return value


def new_signin_nonce() -> str:
    """A fresh nonce for the frontend's sign-in cookie (test-login only: the
    real one is minted by the frontend's ``/auth/start``)."""
    return secrets.token_urlsafe(32)


def mint_handoff(user_id: str, *, ttl: int, secret: str, binding: str | None) -> str:
    """A ``typ=handoff`` token for ``user_id`` with a fresh ``jti`` and, when
    the sign-in was started by ``/auth/start``, its ``bh`` binding. A handoff
    without a binding is still minted (an older frontend that never sends one
    keeps signing in until it is redeployed), but the current BFF refuses to
    exchange it."""
    claims = {JTI_CLAIM: secrets.token_urlsafe(18)}
    if binding:
        claims[BINDING_CLAIM] = binding
    return mint_session(user_id, ttl=ttl, secret=secret, typ=TOKEN_TYPE_HANDOFF, claims=claims)


def mint_test_handoff(user_id: str, *, ttl: int, secret: str) -> tuple[str, str]:
    """(handoff, nonce) for POST /api/auth/test-login: a handoff bound to a
    fresh nonce, which the E2E journey sets as its browser's sign-in cookie
    (``signin_cookie_name``) before it opens /auth/callback."""
    nonce = new_signin_nonce()
    return mint_handoff(user_id, ttl=ttl, secret=secret, binding=binding_for_nonce(nonce)), nonce


def _b64url_decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def verify_handoff(token: str, *, secret: str, now: float | None = None) -> dict:
    """The payload of a validly signed, unexpired ``typ=handoff`` token that
    carries a ``jti`` and a ``bh``. Raises ``HandoffRefused`` otherwise."""
    if not secret or not isinstance(token, str) or token.count(".") != 1 or len(token) > 4096:
        raise HandoffRefused("malformed")
    payload_b64, sig_b64 = token.split(".")
    expected = hmac.new(secret.encode(), payload_b64.encode(), hashlib.sha256).digest()
    expected_b64 = base64.urlsafe_b64encode(expected).decode().rstrip("=")
    if not hmac.compare_digest(sig_b64, expected_b64):
        raise HandoffRefused("signature")
    try:
        payload = json.loads(_b64url_decode(payload_b64).decode())
    except Exception:
        raise HandoffRefused("payload") from None
    if not isinstance(payload, dict):
        raise HandoffRefused("payload")
    current = time.time() if now is None else now
    exp = payload.get("exp")
    if not isinstance(exp, (int, float)) or isinstance(exp, bool) or exp < current:
        raise HandoffRefused("expired")
    if payload.get("typ") != TOKEN_TYPE_HANDOFF:
        raise HandoffRefused("not a handoff")
    if not isinstance(payload.get("user_id"), str) or not payload["user_id"]:
        raise HandoffRefused("no subject")
    jti = payload.get(JTI_CLAIM)
    if not isinstance(jti, str) or not 16 <= len(jti) <= 128:
        raise HandoffRefused("no jti")
    if clean_binding(payload.get(BINDING_CLAIM)) is None:
        raise HandoffRefused("unbound")
    return payload


def _consume_jti(jti: str, ttl_s: int) -> bool:
    """True the first time ``jti`` is consumed (on any replica), False on a
    replay. Raises ``HandoffStoreUnavailable`` when the store cannot answer.
    The table holds the jti's SHA-256, never the jti."""
    from db.connection import rpc
    from db.scope import service_scope

    key = hashlib.sha256(jti.encode("utf-8")).hexdigest()
    try:
        with service_scope():  # auth_handoff_consumptions is service-only
            answer = rpc(
                CONSUME_FN, {"p_jti_hash": key, "p_ttl_sec": int(ttl_s)}, timeout=CONSUME_TIMEOUT_S,
            )
    except Exception as exc:
        logger.warning("handoff exchange: %s() failed (%s)", CONSUME_FN, type(exc).__name__)
        raise HandoffStoreUnavailable(str(type(exc).__name__)) from exc
    if isinstance(answer, list):
        answer = answer[0] if answer else None
    if isinstance(answer, dict) and len(answer) == 1:
        answer = next(iter(answer.values()))
    if not isinstance(answer, bool):
        raise HandoffStoreUnavailable(f"unexpected answer {type(answer).__name__}")
    return answer


def exchange_handoff(token: str, nonce: str | None, *, secret: str) -> str:
    """The user id a handoff signs in, after checking it is genuine, bound to
    THIS browser's sign-in nonce, and has never been exchanged before (it is
    consumed now). Raises ``HandoffRefused`` or ``HandoffStoreUnavailable``.

    The binding is checked BEFORE the jti is consumed: a handoff presented by
    the wrong browser is refused without spending it."""
    payload = verify_handoff(token, secret=secret)
    if not nonce or not _NONCE_RE.fullmatch(nonce):
        raise HandoffRefused("no sign-in nonce in this browser")
    if not hmac.compare_digest(binding_for_nonce(nonce), payload[BINDING_CLAIM]):
        raise HandoffRefused("bound to another browser")
    ttl = max(1, int(payload["exp"] - time.time()) + _CONSUME_SLACK_S)
    if not _consume_jti(payload[JTI_CLAIM], ttl):
        raise HandoffRefused("already exchanged")
    return payload["user_id"]
