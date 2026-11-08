"""Server-to-server half of the cross-environment account copy.

`/api/internal/account-sync/{ping,export,import}` are called ONLY by the other
environment's backend (`services/account_sync_client.py`), never by a browser.
There is no `sapling_session` on the other end — just a shared bearer token,
`ACCOUNT_SYNC_INBOUND_TOKEN` (`config.account_sync_inbound_token`), checked
exactly as `routes/internal_metrics.py` checks Canopy's: unset → 404 before
any compare, then one constant-time compare over the whole header and one
generic 401. Every route is `include_in_schema=False`.

Audit: these routes have no actor (the admin who clicked is on the OTHER
environment, and is audited there via `log_admin_action`).
`admin_audit_log.actor_id` is NOT NULL with an FK to `users`, so nothing is
written there; each export/import logs an `events` audit row with NO actor
(`user_id=None`) and the account in the payload as `target_user_id`. It must
not be attributed to the student: an `events` row with their `user_id` counts
them as active (canopy_metrics `active_users`, the admin DAU rollups) on a day
they did nothing, and its PostHog mirror would name them for an admin's click.

The export body is the account's data DECRYPTED — it is exactly as sensitive
as the database, which is why the token is the whole gate and the transport is
HTTPS between the two deploys.
"""

from __future__ import annotations

import hmac
import logging

from fastapi import APIRouter, Header, HTTPException, Query, Request
from fastapi.concurrency import run_in_threadpool

import config
from services import account_bundle
from services.account_bundle import AccountNotFound, BundleError
from services.account_ops_lock import AccountBusy, account_op
from services.account_sync_client import ACCOUNT_NOT_FOUND
from services.account_wipe import AccountWipeIncomplete
from services.events_service import log_event

logger = logging.getLogger("sapling.internal_account_sync")

router = APIRouter()


def _authorize(authorization: str | None) -> None:
    """404 when the feature is off, one generic 401 for every bad credential."""
    expected = config.account_sync_inbound_token()
    if not expected:
        # Unset/blank -> DISABLED, indistinguishable from an unrouted path. MUST
        # come before the compare: against an empty token, "Bearer " would match.
        raise HTTPException(status_code=404)
    presented = (authorization or "").encode("utf-8")
    if not hmac.compare_digest(presented, f"Bearer {expected}".encode("utf-8")):
        raise HTTPException(status_code=401, detail="Unauthorized")


def _require_user_id(user_id: str | None) -> str:
    # Optional at the FastAPI layer and checked here, AFTER _authorize: a
    # required Query/Body would answer 422 to an unauthenticated caller before
    # the token was ever looked at.
    if not user_id or not user_id.strip():
        raise HTTPException(status_code=400, detail="user_id is required")
    return user_id.strip()


@router.get("/ping", include_in_schema=False)
def ping(authorization: str | None = Header(default=None)) -> dict:
    """`{"env": APP_ENV}` — lets the caller refuse a self-copy and label the peer."""
    _authorize(authorization)
    return {"env": config.APP_ENV}


@router.get("/export", include_in_schema=False)
def export(
    user_id: str | None = Query(default=None),
    authorization: str | None = Header(default=None),
) -> dict:
    """The account's plaintext bundle (`services/account_bundle.export_account`)."""
    _authorize(authorization)
    user_id = _require_user_id(user_id)
    try:
        # Held so an export cannot read an account mid-wipe/seed here.
        with account_op(user_id):
            bundle = account_bundle.export_account(user_id)
    except AccountBusy:
        raise HTTPException(status_code=409, detail="operation already running for this account")
    except AccountNotFound:
        raise HTTPException(status_code=404, detail=ACCOUNT_NOT_FOUND)
    except BundleError as exc:
        logger.warning("account sync export refused: %s", exc)
        raise HTTPException(status_code=400, detail=str(exc))
    log_event(
        "account.export", category="audit", user_id=None,
        payload={"target_user_id": user_id,
                 "tables": {name: len(rows) for name, rows in bundle["tables"].items()}},
    )
    return bundle


def _import_locked(user_id: str, bundle: dict) -> dict:
    with account_op(user_id):
        return account_bundle.import_account(user_id, bundle)


@router.post("/import", include_in_schema=False)
async def import_(
    request: Request,
    user_id: str | None = Query(default=None),
    authorization: str | None = Header(default=None),
) -> dict:
    """Overwrite this environment's copy of the account with the body's bundle.

    `{"counts": {<table>: n}}`. 404 `account_not_found` when the person never
    signed in here (copy never creates accounts), 409 when another account
    operation is running for them, 400 when the bundle cannot be applied.

    Async only so the body is read AFTER the token check (an unauthenticated
    caller never gets a megabyte parsed); the import itself is blocking
    PostgREST work and runs in the threadpool.
    """
    _authorize(authorization)
    user_id = _require_user_id(user_id)
    try:
        bundle = await request.json()
    except ValueError:
        raise HTTPException(status_code=400, detail="body is not JSON")
    if not isinstance(bundle, dict):
        raise HTTPException(status_code=400, detail="body is not a bundle object")
    try:
        counts = await run_in_threadpool(_import_locked, user_id, bundle)
    except AccountBusy:
        raise HTTPException(status_code=409, detail="operation already running for this account")
    except AccountNotFound:
        raise HTTPException(status_code=404, detail=ACCOUNT_NOT_FOUND)
    except BundleError as exc:
        logger.warning("account sync import refused: %s", exc)
        raise HTTPException(status_code=400, detail=str(exc))
    except AccountWipeIncomplete:
        # Raised before any row is written; re-running the copy resumes the wipe.
        logger.exception("account sync import: wipe did not finish")
        raise HTTPException(status_code=503, detail="the wipe did not finish; re-run the copy")
    source_env = bundle.get("source_env")
    log_event(
        "account.import", category="audit", user_id=None,
        payload={"target_user_id": user_id,
                 "source_env": source_env if isinstance(source_env, str) else None,
                 "counts": counts},
    )
    return {"counts": counts}
