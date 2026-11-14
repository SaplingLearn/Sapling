"""
backend/routes/study.py — the /api/study HTTP surface (the Study hub's Daily
Goal panel).

Each handler is a thin wrapper over the same-named function in
``services/study/`` (#118): it checks the caller, parses the request and
returns what the service answers. How the minutes are estimated is documented
with the code that does it, ``services/study/daily.py``.

Mounted behind the ``hide_study`` nav flag (``main.py``,
``services/feature_flags.py::NAV_FEATURE_API``). The client is
``frontend/src/lib/studyApi.ts``.
"""
from __future__ import annotations

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

import services.study as study_service
from services.auth_guard import require_self

router = APIRouter()


@router.get("/{user_id}/daily")
def get_daily(user_id: str, request: Request, tz_offset_min: int = 0):
    """Estimated study minutes for the last seven local days, plus the daily
    goal. ``tz_offset_min`` is JS ``Date#getTimezoneOffset`` (minutes behind
    UTC); a value outside real-world offsets is clamped, not refused."""
    require_self(user_id, request)
    return study_service.get_daily(user_id, tz_offset_min)


class DailyGoalBody(BaseModel):
    minutes: int = Field(ge=study_service.MIN_GOAL_MIN, le=study_service.MAX_GOAL_MIN)


@router.patch("/{user_id}/daily-goal")
def set_daily_goal(user_id: str, body: DailyGoalBody, request: Request):
    """Set the daily goal, in minutes a day."""
    require_self(user_id, request)
    return study_service.set_daily_goal(user_id, body.minutes)
