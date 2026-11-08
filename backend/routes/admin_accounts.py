"""/api/admin/accounts — admin account tools: seed by major, wipe, and the
read-only summary the UI's review step shows before either runs.

Contract: docs/superpowers/specs/2026-11-08-admin-account-tools-design.md.

Every handler runs ``require_admin`` first. The destructive actions also need
a body ``confirm`` equal to the action word, and a per-user in-process lock
(``services/account_ops_lock.py``) turns a concurrent second operation on the
same account into a 409. Both actions are audited twice: ``admin_audit_log``
(who did what to whom) and an ``events`` audit row. Once the lock is held,
EVERY outcome is audited — ``outcome="ok"`` or ``outcome="failed"`` with a
``reason`` enum — because a failed seed/wipe may already have wiped the
account, and that must be traceable to the click that did it. Audit payloads
carry ids, counts and enums only, never free text.

Handlers are plain ``def`` (FastAPI runs them in its threadpool): the work is
a few hundred synchronous PostgREST calls and must not block the event loop.
"""
from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

import config
from services.account_bundle import account_exists
from services.account_ops_lock import AccountBusy, account_op
from services.account_seed import seeder
from services.account_summary import summarize_account
from services.account_wipe import AccountWipeIncomplete, wipe_account_data
from services.admin_audit import log_admin_action
from services.auth_guard import get_session_user_id, require_admin
from services.events_service import log_event

logger = logging.getLogger(__name__)

router = APIRouter()

_NO_SYNC = {"configured": False, "peer_env": None}

_BUSY = "Another account operation is running for this user"
_WIPE_INCOMPLETE = "wipe incomplete — re-run"


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
    # account_exists filters deleted_at: a soft-deleted account is not a target.
    if not account_exists(user_id):
        raise HTTPException(status_code=404, detail="User not found")


def _audit_failure(actor: str, action: str, user_id: str, reason: str, **extra) -> None:
    """Both trails for a failed operation. `reason` is an enum string and
    `extra` holds ids/enums only — never an exception message."""
    payload = {"outcome": "failed", "reason": reason, **extra}
    log_admin_action(
        actor_id=actor, action=action, target_type="user", target_id=user_id, payload=payload,
    )
    log_event(action, category="audit", user_id=actor,
              payload={"target_user_id": user_id, **payload})


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


@router.get("/{user_id}/summary")
def account_summary(user_id: str, request: Request):
    """What the account holds now — the review step shown before Seed / Wipe
    (`services/account_summary.py`). Read-only: no lock, no audit row."""
    require_admin(request)
    summary = summarize_account(user_id)
    if not summary["exists"]:
        raise HTTPException(status_code=404, detail="User not found")
    return summary


@router.post("/{user_id}/seed")
def seed_account(user_id: str, body: SeedAccountBody, request: Request):
    require_admin(request)
    actor = get_session_user_id(request)
    _require_confirm(body.confirm, "SEED")
    if body.major not in seeder.packs():
        raise HTTPException(status_code=400, detail=f"Unknown major {body.major!r}")
    _require_user(user_id)

    action = "account.seed"
    try:
        with account_op(user_id):
            try:
                result = seeder.seed_account(user_id, body.major)
            except seeder.UnknownAccount:
                _audit_failure(actor, action, user_id, "user_not_found", major=body.major)
                raise HTTPException(status_code=404, detail="User not found") from None
            except seeder.UnknownMajor:
                _audit_failure(actor, action, user_id, "unknown_major", major=body.major)
                raise HTTPException(status_code=400, detail=f"Unknown major {body.major!r}") from None
            except seeder.NoCurrentTerm:
                # Checked before the wipe: nothing was changed.
                _audit_failure(actor, action, user_id, "no_current_term", major=body.major)
                raise HTTPException(
                    status_code=503,
                    detail=f"No current term is configured on {config.APP_ENV}; cannot seed",
                ) from None
            except AccountWipeIncomplete:
                logger.exception("account seed: wipe did not finish for %s", user_id)
                _audit_failure(actor, action, user_id, "wipe_incomplete", major=body.major)
                raise HTTPException(status_code=503, detail=_WIPE_INCOMPLETE) from None
            except Exception:
                # Possibly after the wipe: audit, then let the 500 handler see it.
                _audit_failure(actor, action, user_id, "error", major=body.major)
                raise
    except AccountBusy:
        raise HTTPException(status_code=409, detail=_BUSY) from None

    payload = {
        "outcome": "ok",
        "major": body.major,
        "wiped": result["wiped"],
        "created": result["created"],
    }
    log_admin_action(
        actor_id=actor, action=action, target_type="user",
        target_id=user_id, payload=payload,
    )
    log_event(
        action, category="audit", user_id=actor,
        payload={
            "target_user_id": user_id,
            "outcome": "ok",
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

    action = "account.wipe"
    try:
        with account_op(user_id):
            try:
                wiped = wipe_account_data(user_id)
            except AccountWipeIncomplete:
                logger.exception("account wipe: did not finish for %s", user_id)
                _audit_failure(actor, action, user_id, "wipe_incomplete")
                raise HTTPException(status_code=503, detail=_WIPE_INCOMPLETE) from None
            except Exception:
                _audit_failure(actor, action, user_id, "error")
                raise
    except AccountBusy:
        raise HTTPException(status_code=409, detail=_BUSY) from None

    log_admin_action(
        actor_id=actor, action=action, target_type="user",
        target_id=user_id, payload={"outcome": "ok", "wiped": wiped},
    )
    log_event(
        action, category="audit", user_id=actor,
        payload={"target_user_id": user_id, "outcome": "ok", "wiped": sum(wiped.values())},
    )
    logger.info("account wipe: user=%s by=%s rows=%d", user_id, actor, sum(wiped.values()))
    return {"wiped": wiped}
