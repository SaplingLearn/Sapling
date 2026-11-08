"""Admin LLM controls (#119): per-user daily token budgets and the drill state.

Mounted at `/api/admin/llm` (admin_service_route: `llm_budgets` and
`llm_usage` are service-only). Every endpoint also calls `require_admin`.

* ``GET    /budgets``                      the default, role and user rows
* ``PUT    /budgets``                      set one row (default / role / user)
* ``DELETE /budgets/{scope}/{subject}``    drop a role or user override
* ``GET    /budgets/status/{user_id}``     what the gate would see for a user
* ``GET    /drill``                        drill flag, fallback flag, breakers

A budget only bites while the `llm_budget` flag is on for the student
(services/llm_budget.py); editing rows with the flag off changes nothing.
`daily_token_limit: null` means unlimited, `0` means no LLM work at all.
"""
from __future__ import annotations

from typing import Literal, Optional

import httpx
from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, Field, model_validator

from db.connection import table
from services import feature_flags, llm_budget
from services.admin_audit import log_admin_action
from services.auth_guard import get_session_user_id, require_admin

router = APIRouter()

_COLUMNS = "scope,subject,daily_token_limit,note,updated_by,updated_at"


class BudgetBody(BaseModel):
    scope: Literal["default", "role", "user"]
    #: roles.slug for a role, users.id for a user; omitted / "" for the default.
    subject: str = Field(default="", max_length=200)
    daily_token_limit: Optional[int] = Field(default=None, ge=0, le=10_000_000_000)
    note: Optional[str] = Field(default=None, max_length=500)

    @model_validator(mode="after")
    def _subject_matches_scope(self):
        self.subject = self.subject.strip()
        if (self.scope == "default") != (self.subject == ""):
            raise ValueError("subject must be empty for the default and set for a role or user")
        return self


def _rows() -> list[dict]:
    return table("llm_budgets").select(_COLUMNS, order="scope.asc,subject.asc") or []


def _view(rows: list[dict]) -> dict:
    default = next((r for r in rows if r.get("scope") == "default"), None)
    return {
        "flag": feature_flags.flag_variant(llm_budget.FLAG_KEY, None),
        "default": default,
        "roles": [r for r in rows if r.get("scope") == "role"],
        "users": [r for r in rows if r.get("scope") == "user"],
    }


def _subject_exists(scope: str, subject: str) -> bool:
    if scope == "default":
        return True
    name, column = ("roles", "slug") if scope == "role" else ("users", "id")
    try:
        return bool(table(name).select("id", filters={column: f"eq.{subject}"}))
    except httpx.HTTPStatusError as exc:
        if 400 <= exc.response.status_code < 500:
            return False
        raise


@router.get("/budgets")
def list_budgets(request: Request, response: Response):
    require_admin(request)
    response.headers["Cache-Control"] = "private"
    return _view(_rows())


@router.put("/budgets")
def set_budget(body: BudgetBody, request: Request):
    require_admin(request)
    actor = get_session_user_id(request)
    if not _subject_exists(body.scope, body.subject):
        raise HTTPException(status_code=404, detail=f"Unknown {body.scope}")
    before = table("llm_budgets").select(
        "daily_token_limit",
        filters={"scope": f"eq.{body.scope}", "subject": f"eq.{body.subject}"},
    ) or []
    table("llm_budgets").upsert(
        {"scope": body.scope, "subject": body.subject,
         "daily_token_limit": body.daily_token_limit, "note": body.note,
         "updated_by": actor},
        on_conflict="scope,subject",
    )
    log_admin_action(
        actor_id=actor, action="llm_budget.update", target_type="llm_budget",
        target_id=f"{body.scope}:{body.subject}",
        payload={"before": before[0]["daily_token_limit"] if before else None,
                 "after": body.daily_token_limit, "existed": bool(before)},
    )
    llm_budget.clear_llm_budget_cache()
    return _view(_rows())


@router.delete("/budgets/{scope}/{subject}")
def delete_budget(scope: Literal["role", "user"], subject: str, request: Request):
    """Drop an override. The default row cannot be deleted — set it to null
    (unlimited) instead, so "no default" is never an accident."""
    require_admin(request)
    actor = get_session_user_id(request)
    removed = table("llm_budgets").delete(
        filters={"scope": f"eq.{scope}", "subject": f"eq.{subject}"},
    ) or []
    if not removed:
        raise HTTPException(status_code=404, detail="No such budget override")
    log_admin_action(
        actor_id=actor, action="llm_budget.delete", target_type="llm_budget",
        target_id=f"{scope}:{subject}",
        payload={"before": removed[0].get("daily_token_limit")},
    )
    llm_budget.clear_llm_budget_cache()
    return _view(_rows())


@router.get("/budgets/status/{user_id}")
def budget_status(user_id: str, request: Request, response: Response):
    """The resolved limit and today's usage for one user, read fresh, plus
    whether the flag would enforce it for them."""
    require_admin(request)
    response.headers["Cache-Control"] = "private"
    try:
        status = llm_budget.read_status(user_id)
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Budget status unavailable") from exc
    return {
        "user_id": user_id,
        "flag": feature_flags.flag_variant(llm_budget.FLAG_KEY, user_id),
        "limit": status.limit,
        "used": status.used,
        "source": status.source,
        "exceeded": status.exceeded,
        "reset_at": status.reset_at.isoformat(),
    }


@router.get("/drill")
def drill_state(request: Request, response: Response):
    """The outage drill as this worker sees it (docs/ops/llm-outage-drill.md):
    the `llm_outage_drill` flag's global variant, the providers it forces down
    here (none when this process's production interlock refuses it), and
    this process's breakers."""
    require_admin(request)
    response.headers["Cache-Control"] = "private"
    from agents import _resilience

    return {
        "forced_outage": _resilience.forced_outage_status(),
        "llm_fallback": feature_flags.flag_variant(_resilience.FALLBACK_FLAG, None),
        "breakers": _resilience.breaker_states(),
    }
