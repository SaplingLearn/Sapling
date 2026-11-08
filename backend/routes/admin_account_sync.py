"""Admin "copy this account to/from the other environment" (staging ↔ prod).

`POST /api/admin/accounts/{user_id}/copy` (mounted by `main.py` under
`/api/admin/accounts`, beside the seed/wipe routes in `routes/admin_accounts.py`).
Body `{"direction": "push" | "pull", "confirm": "COPY"}` →
`{"direction", "peer_env", "counts": {<table>: n}}`.

- push: overwrite the PEER's copy of the account with this environment's.
- pull: overwrite THIS environment's copy with the peer's.

The transfer itself is `services/account_sync_client.py`; what moves (and
how it is re-encrypted and remapped) is `services/account_bundle.py`.

`GET /api/admin/accounts/{user_id}/copy-preview?direction=push|pull` is the
read-only review the UI shows before the copy: both sides' account summaries.

Errors (the spec's contract): 400 bad confirm/direction or a bundle the
target cannot apply, 403 not an admin, 404 unknown account here or on the
peer, 409 another operation running for the account (here or on the peer) or
a self-copy, 502 peer error, 503 sync not configured.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Body, HTTPException, Request

import config
from services import account_bundle, account_sync_client
from services.account_bundle import AccountNotFound, BundleError
from services.account_ops_lock import AccountBusy, account_op
from services.account_summary import summarize_account
from services.account_sync_client import PeerError
from services.account_wipe import AccountWipeIncomplete
from services.admin_audit import log_admin_action
from services.auth_guard import get_session_user_id, require_admin
from services.events_service import log_event

logger = logging.getLogger("sapling.admin_account_sync")

router = APIRouter()

CONFIRM_WORD = "COPY"
DIRECTIONS = ("push", "pull")


@router.get("/{user_id}/copy-preview")
def copy_preview(user_id: str, request: Request, direction: str | None = None) -> dict:
    """What a copy would overwrite, for the UI's review step. Read-only.

    `{"direction", "source": {"env", "summary"}, "destination": {"env", "summary"}}`
    — push: source = here, destination = the peer; pull: the reverse. A
    summary with `exists=False` means the account has never signed in on that
    environment and the copy itself would 404.

    Errors as the copy's: 400 bad direction, 404 unknown account here, 503 not
    configured, and the peer's failures mapped by `account_sync_client`
    (409 self-copy, 502 unreachable / peer error).
    """
    require_admin(request)
    if direction not in DIRECTIONS:
        raise HTTPException(status_code=400, detail="direction must be 'push' or 'pull'")
    if not account_sync_client.is_configured():
        raise HTTPException(status_code=503, detail="account sync is not configured")
    local = summarize_account(user_id)
    if not local["exists"]:
        raise HTTPException(
            status_code=404, detail=f"account does not exist on {config.APP_ENV}",
        )
    try:
        remote = account_sync_client.peer_summary(user_id)
    except PeerError as exc:
        raise HTTPException(status_code=exc.status, detail=exc.detail) from None
    here = {"env": config.APP_ENV, "summary": local}
    source, destination = (here, remote) if direction == "push" else (remote, here)
    return {"direction": direction, "source": source, "destination": destination}


@router.post("/{user_id}/copy")
def copy_account(user_id: str, request: Request, body: Any = Body(default=None)) -> dict:
    # Admin FIRST, before the body is even looked at: a non-admin learns
    # nothing from a validation error. (Hence `Any` instead of a model.)
    require_admin(request)
    actor = get_session_user_id(request)

    if not isinstance(body, dict):
        raise HTTPException(status_code=400, detail="body must be an object")
    direction = body.get("direction")
    if direction not in DIRECTIONS:
        raise HTTPException(status_code=400, detail="direction must be 'push' or 'pull'")
    if body.get("confirm") != CONFIRM_WORD:
        raise HTTPException(status_code=400, detail=f"confirm must be {CONFIRM_WORD!r}")

    if not account_sync_client.is_configured():
        raise HTTPException(status_code=503, detail="account sync is not configured")
    if not account_bundle.account_exists(user_id):
        raise HTTPException(
            status_code=404, detail=f"account does not exist on {config.APP_ENV}",
        )

    action = f"account.copy_{direction}"
    try:
        with account_op(user_id):
            try:
                result = (account_sync_client.push if direction == "push"
                          else account_sync_client.pull)(user_id)
            except PeerError as exc:
                _audit(actor, action, user_id, {"outcome": "failed", "status": exc.status})
                raise HTTPException(status_code=exc.status, detail=exc.detail) from None
            except AccountNotFound:
                _audit(actor, action, user_id, {"outcome": "failed", "status": 404})
                raise HTTPException(
                    status_code=404, detail=f"account does not exist on {config.APP_ENV}",
                ) from None
            except BundleError as exc:
                _audit(actor, action, user_id, {"outcome": "failed", "status": 400})
                raise HTTPException(status_code=400, detail=str(exc)) from None
            except AccountWipeIncomplete:
                # Pull only (a push's wipe runs on the peer). Nothing was imported yet.
                logger.exception("account copy: local wipe did not finish for %s", user_id)
                _audit(actor, action, user_id, {"outcome": "failed", "status": 503})
                raise HTTPException(
                    status_code=503, detail="the wipe did not finish; re-run the copy",
                ) from None
            except Exception:
                # Unexpected — possibly after a pull's local wipe. Audit, then
                # re-raise so the 500 handler still sees (and reports) it.
                _audit(actor, action, user_id, {"outcome": "failed", "status": 500})
                raise
    except AccountBusy:
        raise HTTPException(
            status_code=409, detail="an operation is already running for this account",
        ) from None

    peer_env, counts = result["peer_env"], result["counts"]
    _audit(actor, action, user_id, {"outcome": "ok", "peer_env": peer_env, "counts": counts})
    return {"direction": direction, "peer_env": peer_env, "counts": counts}


def _audit(actor: str, action: str, user_id: str, payload: dict) -> None:
    """Both trails: the admin audit log (who did it) and an events audit row.

    Failures are audited too — a failed pull/push may already have wiped the
    target, and that must be traceable to the click that did it.
    """
    log_admin_action(actor, action, "user", user_id, payload)
    log_event(action, category="audit", user_id=actor,
              payload={"target_user_id": user_id, **payload})
