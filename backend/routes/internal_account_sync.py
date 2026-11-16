"""Server-to-server half of the cross-environment account copy.

`/api/internal/account-sync/{ping,summary,export,import}` are called ONLY by the other
environment's backend (`services/account_sync_client.py`), never by a browser.
There is no `sapling_session` on the other end — just a shared bearer token,
`ACCOUNT_SYNC_INBOUND_TOKEN` (`config.account_sync_inbound_token`; a set value
under 32 bytes refuses boot), checked exactly as `routes/internal_metrics.py`
checks Canopy's: unset → 404 before any compare, then one constant-time
compare over the whole header and one generic 401. Every route is
`include_in_schema=False`.

Signed requests. After the bearer check every route also requires the
client's `X-Sapling-Sync-Timestamp` + `X-Sapling-Sync-Signature`
(`account_sync_client.sign_request` / `verify_signature`: HMAC-SHA256 keyed
with the token over method, raw path + query exactly as received, timestamp
and sha256 of the body; the timestamp must be within ±300 s). A missing,
wrong or stale signature is the same generic 401 as a bad token. There is no
grace for unsigned requests: both ends ship from this repo, so the receiving
environment must be deployed before (or with) the sending one.

Direction rule: production (`APP_ENV=production`) accepts NO inbound import —
`/import` answers 403 right after the bearer check, before the body is read.
A copy into production is production's own pull (it GETs the peer's
`/export` and imports locally), never a push to this route. Export, summary
and ping are unchanged on every environment.

Audit: these routes have no actor (the admin who clicked is on the OTHER
environment, and is audited there via `log_admin_action`).
`admin_audit_log.actor_id` is NOT NULL with an FK to `users`, so nothing is
written there; each export/import logs an `events` audit row with NO actor
(`user_id=None`) and the account in the payload as `target_user_id`. It must
not be attributed to the student: an `events` row with their `user_id` counts
them as active (canopy_metrics `active_users`, the admin DAU rollups) on a day
they did nothing, and its PostHog mirror would name them for an admin's click.

The export body is the account's data DECRYPTED — it is exactly as sensitive
as the database, which is why the token (plus its signature) is the whole
gate and the transport is HTTPS between the two deploys.
"""

from __future__ import annotations

import hmac
import json
import logging

from fastapi import APIRouter, Header, HTTPException, Query, Request
from fastapi.concurrency import run_in_threadpool

import config
from services import account_bundle
from services.account_bundle import AccountNotFound, BundleError
from services.account_ops_lock import AccountBusy, account_op
from services.account_summary import summarize_account
from services.account_sync_client import (
    ACCOUNT_NOT_FOUND,
    PRODUCTION_REFUSES_IMPORT,
    SIGNATURE_HEADER,
    TIMESTAMP_HEADER,
    refuses_inbound_import,
    verify_signature,
)
from services.account_wipe import AccountWipeIncomplete
from services.events_service import log_event

logger = logging.getLogger("sapling.internal_account_sync")

router = APIRouter()


def _check_bearer(authorization: str | None) -> str:
    """404 when the feature is off, one generic 401 for every bad credential.
    Returns the token (the signature key)."""
    expected = config.account_sync_inbound_token()
    if not expected:
        # Unset/blank -> DISABLED, indistinguishable from an unrouted path. MUST
        # come before the compare: against an empty token, "Bearer " would match.
        raise HTTPException(status_code=404)
    presented = (authorization or "").encode("utf-8")
    if not hmac.compare_digest(presented, f"Bearer {expected}".encode("utf-8")):
        raise HTTPException(status_code=401, detail="Unauthorized")
    return expected


def _request_target(request: Request) -> bytes:
    """The request target as received: raw path, plus `?query` when present.

    ASGI's `raw_path` excludes the query string (uvicorn and Starlette's
    TestClient both split it off), so it is re-joined here exactly as the
    client's `httpx.URL.raw_path` carries it.
    """
    raw_path = request.scope.get("raw_path") or request.scope["path"].encode("utf-8")
    query = request.scope.get("query_string") or b""
    return raw_path + b"?" + query if query else raw_path


def _check_signature(request: Request, token: str, body: bytes = b"") -> None:
    """The same generic 401 as a bad token for a missing, wrong or stale signature."""
    if not verify_signature(
        token, request.method, _request_target(request), body,
        request.headers.get(TIMESTAMP_HEADER), request.headers.get(SIGNATURE_HEADER),
    ):
        raise HTTPException(status_code=401, detail="Unauthorized")


def _authorize(request: Request, authorization: str | None) -> None:
    """Bearer then signature, for the body-less GET routes (signed over b"")."""
    _check_signature(request, _check_bearer(authorization))


def _require_user_id(user_id: str | None) -> str:
    # Optional at the FastAPI layer and checked here, AFTER _authorize: a
    # required Query/Body would answer 422 to an unauthenticated caller before
    # the token was ever looked at.
    if not user_id or not user_id.strip():
        raise HTTPException(status_code=400, detail="user_id is required")
    return user_id.strip()


@router.get("/ping", include_in_schema=False)
def ping(request: Request, authorization: str | None = Header(default=None)) -> dict:
    """`{"env": APP_ENV}` — lets the caller refuse a self-copy, refuse a push to
    production, and label the peer."""
    _authorize(request, authorization)
    return {"env": config.APP_ENV}


@router.get("/export", include_in_schema=False)
def export(
    request: Request,
    user_id: str | None = Query(default=None),
    authorization: str | None = Header(default=None),
) -> dict:
    """The account's plaintext bundle (`services/account_bundle.export_account`)."""
    _authorize(request, authorization)
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


@router.get("/summary", include_in_schema=False)
def summary(
    request: Request,
    user_id: str | None = Query(default=None),
    authorization: str | None = Header(default=None),
) -> dict:
    """What the account holds here (`services/account_summary.summarize_account`):
    counts, courses and XP only, never content. Feeds the copy review on the
    other environment. Read-only — no lock and no audit row; 404
    `account_not_found` when the account does not exist here."""
    _authorize(request, authorization)
    user_id = _require_user_id(user_id)
    result = summarize_account(user_id)
    if not result["exists"]:
        raise HTTPException(status_code=404, detail=ACCOUNT_NOT_FOUND)
    return result


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

    `{"counts": {<table>: n}}`. 403 on production (never an import target;
    checked after the bearer, before the body is read), 404 `account_not_found`
    when the person never signed in here (copy never creates accounts), 409 when
    another account operation is running for them, 400 when the bundle cannot
    be applied.

    Async only so the body is read AFTER the token check (an unauthenticated
    caller never gets a megabyte read); the raw bytes are then signature-checked
    BEFORE they are parsed. The import itself is blocking PostgREST work and
    runs in the threadpool.
    """
    token = _check_bearer(authorization)
    if refuses_inbound_import(config.APP_ENV):
        raise HTTPException(status_code=403, detail=PRODUCTION_REFUSES_IMPORT)
    raw = await request.body()
    _check_signature(request, token, raw)
    user_id = _require_user_id(user_id)
    try:
        bundle = json.loads(raw)
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
