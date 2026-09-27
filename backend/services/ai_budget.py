"""Per-student AI cost guard: caps, degradation ladder, rate limit (spec §3.5, §13 A20). PKG-06b.

Outside backend/learning/ (spec §2, §12): reads llm_usage, never calls a model. Every grader,
grader_second, decision, loop_tutor* and session_close run site calls ``ai_budget.check(`` first
(invariant 23) and turns ``level == "hard"`` into "no model call", never into a verdict (spec §3.5
validity rule, invariant 28). ONE paged llm_usage read since the UTC month start, cached per request
id — no lru_cache (CLAUDE.md #98); tests/conftest.py resets the module state around every test.
"""

from __future__ import annotations

import logging
import threading
from datetime import datetime, timezone
from typing import Literal, NamedTuple

from learning.policy import Band
from services.events_service import log_event

logger = logging.getLogger("sapling.ai_budget")

Kind = Literal["tutor", "grader", "decision", "close"]
Scope = Literal[
    "daily_usd",
    "monthly_usd",
    "daily_tokens",
    "session_requests",
    "session_deep",
    "daily_grades",
    "rate_limit",
    "platform",
]
EventLevel = Literal["soft", "hard", "grader_cap"]

BUDGET_CAPPED_EVENT = "ai.budget_capped"  # spec §6


class _EmitKey(NamedTuple):
    user: str
    scope: str
    level: str
    day: str


_lock = threading.Lock()
_emitted: set[_EmitKey] = set()


def _utcnow() -> datetime:
    """The module clock; tests monkeypatch it."""
    return datetime.now(timezone.utc)


def _emit_capped(
    user_id: str | None,
    scope: Scope,
    level: EventLevel,
    *,
    band: Band | None = None,
    spent_usd: float | None = None,
    cap_usd: float | None = None,
) -> None:
    """ai.budget_capped, at most once per process per (user, scope, level, UTC day) (spec §3.5)."""
    day = _utcnow().date().isoformat()
    key = _EmitKey(user_id or "platform", scope, level, day)
    with _lock:
        if key in _emitted:
            return
        _emitted.difference_update({k for k in _emitted if k.day != day})  # keep only today's keys
        _emitted.add(key)
    payload = {
        "user_id": user_id,
        "scope": scope,
        "band": band,
        "level": level,
        "spent_usd": spent_usd,
        "cap_usd": cap_usd,
    }
    log_event(
        BUDGET_CAPPED_EVENT,
        category="usage",
        user_id=user_id,
        payload={k: v for k, v in payload.items() if v is not None},
    )


def reset_for_tests() -> None:
    """Clear the per-process state (tests/conftest.py::_reset_ai_budget)."""
    with _lock:
        _emitted.clear()
