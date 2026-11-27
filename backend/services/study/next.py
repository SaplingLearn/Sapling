"""W8.3: Study Hub's learner-next read (Focus / Quick Reviews).

Returns the three uncapped buckets from ``services.learner_next.learner_next``
so Hub Focus and Quick Reviews share the same FSRS-due / misconception /
ready set as ``GET /api/quiz/plan`` (before that route's per-course cap).

Gated like the quiz plan: ``learning_loop`` then ``quiz_concept_plan`` via
``quiz_learning.quiz_flags``. Off → 404 (the hub keeps its graph-tier queue).
A failed state read → 503.
"""
from __future__ import annotations

import logging

from fastapi import HTTPException

from services import learner_next as ln
from services import quiz_learning

logger = logging.getLogger("routes.study")


def get_next(user_id: str, course_id: str | None = None) -> dict:
    """``{due, misconceptions, ready}`` for the Study hub.

    Each entry matches one ``GET /api/quiz/plan`` concept dict. Uncapped —
    Quiz applies ``QUIZ_PLAN_MAX_CONCEPTS`` on its own path.
    """
    (plan_on,) = quiz_learning.quiz_flags(user_id, quiz_learning.CONCEPT_PLAN_FLAG)
    if not plan_on:
        raise HTTPException(status_code=404, detail="study next not enabled")
    try:
        return ln.learner_next(user_id, course_id)
    except Exception as exc:
        logger.warning("study: next unavailable (%s)", type(exc).__name__)
        raise HTTPException(
            status_code=503,
            detail="The study next plan is unavailable right now.",
        ) from exc
