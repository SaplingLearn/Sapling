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
→ 404, 409 → 409, 400 (the peer's BundleError) → 400 with its detail, anything
else → 502.
"""

from __future__ import annotations

import logging
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


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _ping(url: str, token: str) -> str | None:
    """The peer's APP_ENV, or None on any failure. Never raises."""
    try:
        resp = httpx.get(f"{url}{SYNC_PATH}/ping", headers=_headers(token), timeout=_PING_TIMEOUT)
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
    try:
        resp = httpx.get(
            f"{url}{SYNC_PATH}/summary", params={"user_id": user_id},
            headers=_headers(token), timeout=_SUMMARY_TIMEOUT,
        )
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
    export.
    """
    url, token, peer_env = _peer()
    bundle = account_bundle.export_account(user_id)
    try:
        resp = httpx.post(
            f"{url}{SYNC_PATH}/import", params={"user_id": user_id}, json=bundle,
            headers=_headers(token), timeout=_TRANSFER_TIMEOUT,
        )
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
    try:
        resp = httpx.get(
            f"{url}{SYNC_PATH}/export", params={"user_id": user_id},
            headers=_headers(token), timeout=_TRANSFER_TIMEOUT,
        )
    except httpx.HTTPError as exc:
        raise PeerError(502, f"{peer_env} export failed: {type(exc).__name__}") from exc
    _raise_for_peer(resp, peer_env, missing=f"account does not exist on {peer_env}")
    try:
        bundle = resp.json()
    except ValueError as exc:
        raise PeerError(502, f"{peer_env} export was not JSON") from exc
    counts = account_bundle.import_account(user_id, bundle)
    return {"peer_env": peer_env, "counts": counts}
