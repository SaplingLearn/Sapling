"""The client half of the cross-environment account copy (staging ↔ prod).

Talks to the OTHER environment's `/api/internal/account-sync/*` routes
(`routes/internal_account_sync.py` on that deploy) with `ACCOUNT_SYNC_PEER_URL`
+ `ACCOUNT_SYNC_PEER_TOKEN`. This is a REST call to our own other deploy, not
Supabase access, so it uses `httpx` directly (CLAUDE.md's third-party-REST
exception) and stays this small.

- `push(user_id)`: export here, POST the bundle to the peer's import.
- `pull(user_id)`: GET the peer's export, import it here.
- `peer_summary(user_id)`: GET the peer's read-only account summary (the
  copy review's "what the destination holds now").

Both probe the peer first (`ping`) to learn which environment it is: a peer
that reports OUR `APP_ENV` is a misconfiguration pointing at ourselves, and is
refused (409) before anything is wiped. Failures raise `PeerError` carrying
the status the admin route should answer: the peer's 404 `account_not_found`
→ 404, 409 → 409, 400 (the peer's BundleError) → 400 with its detail, 403 (a
production peer refusing an import) → 403, anything else → 502.

Direction rules. Production never accepts an inbound import
(`refuses_inbound_import`): its `/import` route answers 403, and `push`
refuses a peer that reports production BEFORE exporting anything, so a copy
INTO production happens only as production's own `pull` (production GETs the
peer's export and imports it locally via `account_bundle.import_account`,
never through the route). Production's `push` (prod → staging) and a pull of
production's export are unaffected. The recommended deploy
(backend/.env.example) goes further: only production holds a peer URL +
token, so only production starts a copy.

Every request is signed (`sign_request`; the routes check it with
`verify_signature`): `X-Sapling-Sync-Timestamp` (unix seconds) and
`X-Sapling-Sync-Signature`, the hex HMAC-SHA256 keyed with the bearer token
over `METHOD\\nRAW_PATH_WITH_QUERY\\nTIMESTAMP\\nsha256_hex(body)`. The bearer
token is still checked first; the signature binds it to the method, path,
account, body and a ±`SIGNATURE_MAX_SKEW_SECONDS` window, so a captured
request cannot be replayed later or re-aimed at another account. The client
signs the exact bytes it sends: each URL (query included) is built once as an
`httpx.URL` whose `raw_path` is signed, and the import body is serialized once
and sent as `content=`.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import time
from typing import Any

import httpx

import config
from services import account_bundle
from services.account_summary import empty_summary

logger = logging.getLogger(__name__)

SYNC_PATH = "/api/internal/account-sync"

_PING_TIMEOUT = httpx.Timeout(3.0)
# Export/import of a full account walks ~20 tables over PostgREST on the far
# side and can take tens of seconds.
_TRANSFER_TIMEOUT = httpx.Timeout(120.0, connect=10.0)
# A summary is a dozen count queries on the far side.
_SUMMARY_TIMEOUT = httpx.Timeout(30.0, connect=5.0)

# The internal routes' "no such account" detail. Distinguishes that 404 from
# the bare 404 a disabled (token-unset) or unrouted peer answers.
ACCOUNT_NOT_FOUND = "account_not_found"


# The environment that never accepts an inbound import (`APP_ENV`, lower-case).
PRODUCTION_ENV = "production"
PRODUCTION_REFUSES_IMPORT = (
    "production does not accept inbound account imports; pull from production instead"
)

TIMESTAMP_HEADER = "X-Sapling-Sync-Timestamp"
SIGNATURE_HEADER = "X-Sapling-Sync-Signature"
# How far a signed timestamp may sit from the receiver's clock, either way.
SIGNATURE_MAX_SKEW_SECONDS = 300


def refuses_inbound_import(env: str | None) -> bool:
    """Whether an environment named `env` refuses `/import` (production only)."""
    return (env or "").strip().lower() == PRODUCTION_ENV


def _as_bytes(value: str | bytes) -> bytes:
    return value if isinstance(value, bytes) else value.encode("utf-8")


def _canonical(method: str, raw_path: str | bytes, body: bytes, ts: int) -> bytes:
    # METHOD \n raw path (query included, as on the wire) \n ts \n sha256_hex(body)
    return b"\n".join((
        method.upper().encode("ascii"),
        _as_bytes(raw_path),
        str(int(ts)).encode("ascii"),
        hashlib.sha256(body).hexdigest().encode("ascii"),
    ))


def sign_request(token: str, method: str, raw_path: str | bytes, body: bytes, ts: int) -> str:
    """Hex HMAC-SHA256 of one internal sync request, keyed with the bearer token.

    `raw_path` is the request target exactly as sent: the percent-encoded path
    plus `?query` when there is one. `body` is the exact body bytes (b"" for a
    GET). The one canonical string both ends use.
    """
    return hmac.new(
        _as_bytes(token), _canonical(method, raw_path, body, ts), hashlib.sha256,
    ).hexdigest()


def verify_signature(
    token: str, method: str, raw_path: str | bytes, body: bytes,
    timestamp: str | None, signature: str | None, *, now: float | None = None,
) -> bool:
    """Whether `signature` signs this request under `token` at a fresh `timestamp`.

    False for a missing, non-integer or stale (beyond ±SIGNATURE_MAX_SKEW_SECONDS
    of `now`) timestamp and for a missing or wrong signature. Constant-time compare.
    """
    if not timestamp or not signature:
        return False
    ts_text = timestamp.strip()
    if not ts_text.isascii() or not ts_text.isdigit() or len(ts_text) > 12:
        return False
    ts = int(ts_text)
    current = time.time() if now is None else now
    if abs(current - ts) > SIGNATURE_MAX_SKEW_SECONDS:
        return False
    expected = sign_request(token, method, raw_path, body, ts).encode("ascii")
    return hmac.compare_digest(signature.strip().encode("utf-8"), expected)


class PeerError(RuntimeError):
    """The peer could not do what was asked. `status` is the code to answer."""

    def __init__(self, status: int, detail: str):
        super().__init__(detail)
        self.status = status
        self.detail = detail


def _configured() -> tuple[str, str] | None:
    url, token = config.account_sync_peer_url(), config.account_sync_peer_token()
    return (url, token) if url and token else None


def is_configured() -> bool:
    """Peer URL and peer token are both set (no network)."""
    return _configured() is not None


def _target(url: str, route: str, user_id: str | None = None) -> httpx.URL:
    """The peer URL for `route`, query included. Built once and passed to httpx
    as-is, so the `raw_path` signed is the request target sent."""
    params = {"user_id": user_id} if user_id is not None else None
    return httpx.URL(f"{url}{SYNC_PATH}/{route}", params=params)


def _headers(token: str, method: str, target: httpx.URL, body: bytes = b"") -> dict[str, str]:
    ts = int(time.time())
    return {
        "Authorization": f"Bearer {token}",
        TIMESTAMP_HEADER: str(ts),
        SIGNATURE_HEADER: sign_request(token, method, target.raw_path, body, ts),
    }


def _ping(url: str, token: str) -> str | None:
    """The peer's APP_ENV, or None on any failure. Never raises."""
    try:
        target = _target(url, "ping")
        resp = httpx.get(target, headers=_headers(token, "GET", target), timeout=_PING_TIMEOUT)
        if resp.status_code != 200:
            return None
        env = resp.json().get("env")
        return env if isinstance(env, str) and env else None
    except Exception:  # noqa: BLE001 — a status probe must never fail its page
        logger.info("account sync: peer ping failed", exc_info=True)
        return None


def peer_status() -> dict[str, Any]:
    """`{"configured": bool, "peer_env": str | None}` for the admin meta route.

    `peer_env` is None when not configured or the peer is unreachable / refuses
    our token. Never raises.
    """
    conf = _configured()
    if conf is None:
        return {"configured": False, "peer_env": None}
    return {"configured": True, "peer_env": _ping(*conf)}


def _peer() -> tuple[str, str, str]:
    """(url, token, peer_env) for a transfer, or raise PeerError."""
    conf = _configured()
    if conf is None:
        raise PeerError(503, "account sync is not configured on this environment")
    url, token = conf
    peer_env = _ping(url, token)
    if peer_env is None:
        raise PeerError(502, "peer environment is unreachable or rejected our token")
    if peer_env == config.APP_ENV:
        raise PeerError(409, f"peer reports the same environment ({peer_env}); refusing a self-copy")
    return url, token, peer_env


def _peer_detail(resp: httpx.Response) -> str:
    try:
        detail = resp.json().get("detail")
    except Exception:  # noqa: BLE001
        detail = None
    return detail if isinstance(detail, str) else ""


def _raise_for_peer(resp: httpx.Response, peer_env: str, *, missing: str) -> None:
    if resp.status_code < 400:
        return
    detail = _peer_detail(resp)
    if resp.status_code == 404 and detail == ACCOUNT_NOT_FOUND:
        raise PeerError(404, missing)
    if resp.status_code == 403:
        # A production peer refusing an inbound import. `push` refuses one
        # before sending; this is the peer's own word for the same rule.
        raise PeerError(403, f"{peer_env}: {detail[:300] or 'refused'}")
    if resp.status_code == 409:
        raise PeerError(409, f"{peer_env}: {detail[:200] or 'operation already running'}")
    if resp.status_code == 400:
        # The peer's BundleError (its internal routes map that, and only that,
        # to 400): a schema mismatch ("migrate it first"), a version skew, a
        # course its catalog lacks. The admin must act on it, so it surfaces
        # as the same 400 a local BundleError gets, with the peer's detail.
        raise PeerError(400, f"{peer_env}: {detail[:300] or 'the bundle was refused'}")
    raise PeerError(502, f"{peer_env} answered {resp.status_code}: {detail[:300]}".rstrip(": "))


def peer_summary(user_id: str) -> dict[str, Any]:
    """`{"env": peer_env, "summary": <account_summary shape>}` for the copy review.

    The peer's 404 `account_not_found` is an answer, not an error: the summary
    comes back `exists=False` so the review can say the account hasn't signed
    in there (and the copy would fail). Every other failure raises `PeerError`
    with the same mapping as a transfer (an old peer without the route → its
    bare 404 → 502).
    """
    url, token, peer_env = _peer()
    target = _target(url, "summary", user_id)
    try:
        resp = httpx.get(target, headers=_headers(token, "GET", target), timeout=_SUMMARY_TIMEOUT)
    except httpx.HTTPError as exc:
        raise PeerError(502, f"{peer_env} summary failed: {type(exc).__name__}") from exc
    if resp.status_code == 404 and _peer_detail(resp) == ACCOUNT_NOT_FOUND:
        return {"env": peer_env, "summary": empty_summary(exists=False)}
    _raise_for_peer(resp, peer_env, missing=f"account does not exist on {peer_env}")
    try:
        body = resp.json()
    except ValueError as exc:
        raise PeerError(502, f"{peer_env} summary was not JSON") from exc
    if not isinstance(body, dict) or not isinstance(body.get("exists"), bool) \
            or not isinstance(body.get("counts"), dict):
        raise PeerError(502, f"{peer_env} summary had an unexpected shape")
    return {"env": peer_env, "summary": body}


def push(user_id: str) -> dict[str, Any]:
    """Overwrite the peer's copy of the account with ours.

    Returns `{"peer_env", "counts"}` — counts as reported by the peer's import.
    Raises `PeerError`, or the local `AccountNotFound` / `BundleError` from the
    export. A peer that reports production is refused (403) before anything is
    exported or sent: production accepts no inbound import, so a copy into
    production is production's own `pull`.
    """
    url, token, peer_env = _peer()
    if refuses_inbound_import(peer_env):
        raise PeerError(
            403,
            f"{peer_env} does not accept inbound account imports; to copy into {peer_env}, "
            f"pull from {peer_env}'s admin account tools instead",
        )
    bundle = account_bundle.export_account(user_id)
    # Serialized once: the signature covers exactly these bytes.
    body = json.dumps(bundle).encode("utf-8")
    target = _target(url, "import", user_id)
    headers = {**_headers(token, "POST", target, body), "Content-Type": "application/json"}
    try:
        resp = httpx.post(target, content=body, headers=headers, timeout=_TRANSFER_TIMEOUT)
    except httpx.HTTPError as exc:
        raise PeerError(502, f"{peer_env} import failed: {type(exc).__name__}") from exc
    _raise_for_peer(resp, peer_env, missing=f"account must sign in on {peer_env} first")
    counts = (resp.json() or {}).get("counts")
    return {"peer_env": peer_env, "counts": counts if isinstance(counts, dict) else {}}


def pull(user_id: str) -> dict[str, Any]:
    """Overwrite our copy of the account with the peer's.

    Returns `{"peer_env", "counts"}`. Raises `PeerError`, or the local
    `AccountNotFound` / `BundleError` from the import.
    """
    url, token, peer_env = _peer()
    target = _target(url, "export", user_id)
    try:
        resp = httpx.get(target, headers=_headers(token, "GET", target), timeout=_TRANSFER_TIMEOUT)
    except httpx.HTTPError as exc:
        raise PeerError(502, f"{peer_env} export failed: {type(exc).__name__}") from exc
    _raise_for_peer(resp, peer_env, missing=f"account does not exist on {peer_env}")
    try:
        bundle = resp.json()
    except ValueError as exc:
        raise PeerError(502, f"{peer_env} export was not JSON") from exc
    counts = account_bundle.import_account(user_id, bundle)
    return {"peer_env": peer_env, "counts": counts}
