"""/api/admin/accounts — admin account tools: seed by major, wipe.

Contract: docs/superpowers/specs/2026-11-08-admin-account-tools-design.md.

Every handler runs ``require_admin`` first. The destructive actions also need
a body ``confirm`` equal to the action word, and a per-user in-process lock
(``services/account_ops_lock.py``) turns a concurrent second operation on the
same account into a 409. Both actions are audited twice: ``admin_audit_log``
(who did what to whom) and an ``events`` audit row.

Handlers are plain ``def`` (FastAPI runs them in its threadpool): the work is
a few hundred synchronous PostgREST calls and must not block the event loop.
"""
from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

import config
from db.connection import table
from services.account_ops_lock import AccountBusy, account_op
from services.account_seed import seeder
from services.account_wipe import wipe_account_data
from services.admin_audit import log_admin_action
from services.auth_guard import get_session_user_id, require_admin
from services.events_service import log_event

logger = logging.getLogger(__name__)

router = APIRouter()

_NO_SYNC = {"configured": False, "peer_env": None}


# Fields are optional so a missing one is the contract's 400, not a 422.
class SeedAccountBody(BaseModel):
    major: Optional[str] = None
    confirm: Optional[str] = None


class WipeAccountBody(BaseModel):
    confirm: Optional[str] = None


def _require_confirm(given: Optional[str], word: str) -> None:
    if given != word:
        raise HTTPException(status_code=400, detail=f'confirm must be "{word}"')


def _require_user(user_id: str) -> None:
    if not table("users").select("id", filters={"id": f"eq.{user_id}"}, limit=1):
        raise HTTPException(status_code=404, detail="User not found")


def _sync_status() -> dict:
    try:
        from services.account_sync_client import peer_status
    except ImportError:
        return dict(_NO_SYNC)
    try:
        return peer_status()
    except Exception:  # noqa: BLE001 — /meta must render even if the peer probe breaks
        logger.warning("account tools: peer status probe failed", exc_info=True)
        return dict(_NO_SYNC)


@router.get("/meta")
def account_tools_meta(request: Request):
    require_admin(request)
    majors = [
        {
            "key": pack.key,
            "label": pack.label,
            "courses": [{"code": c.code, "name": c.name} for c in pack.courses],
        }
        for pack in seeder.packs().values()
    ]
    return {"env": config.APP_ENV, "majors": majors, "sync": _sync_status()}


@router.post("/{user_id}/seed")
def seed_account(user_id: str, body: SeedAccountBody, request: Request):
    require_admin(request)
    actor = get_session_user_id(request)
    _require_confirm(body.confirm, "SEED")
    if body.major not in seeder.packs():
        raise HTTPException(status_code=400, detail=f"Unknown major {body.major!r}")
    _require_user(user_id)

    try:
        with account_op(user_id):
            result = seeder.seed_account(user_id, body.major)
    except AccountBusy:
        raise HTTPException(
            status_code=409, detail="Another account operation is running for this user",
        ) from None
    except LookupError:
        raise HTTPException(status_code=404, detail="User not found") from None
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None

    payload = {
        "major": body.major,
        "wiped": result["wiped"],
        "created": result["created"],
    }
    log_admin_action(
        actor_id=actor, action="account.seed", target_type="user",
        target_id=user_id, payload=payload,
    )
    log_event(
        "account.seed", category="audit", user_id=actor,
        payload={
            "target_user_id": user_id,
            "major": body.major,
            "wiped": sum(result["wiped"].values()),
            "created": sum(result["created"].values()),
        },
    )
    return result


@router.post("/{user_id}/wipe")
def wipe_account(user_id: str, body: WipeAccountBody, request: Request):
    require_admin(request)
    actor = get_session_user_id(request)
    _require_confirm(body.confirm, "WIPE")
    _require_user(user_id)

    try:
        with account_op(user_id):
            wiped = wipe_account_data(user_id)
    except AccountBusy:
        raise HTTPException(
            status_code=409, detail="Another account operation is running for this user",
        ) from None

    log_admin_action(
        actor_id=actor, action="account.wipe", target_type="user",
        target_id=user_id, payload={"wiped": wiped},
    )
    log_event(
        "account.wipe", category="audit", user_id=actor,
        payload={"target_user_id": user_id, "wiped": sum(wiped.values())},
    )
    logger.info("account wipe: user=%s by=%s rows=%d", user_id, actor, sum(wiped.values()))
    return {"wiped": wiped}
