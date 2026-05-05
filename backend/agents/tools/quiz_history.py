"""Quiz-history read tool for the quiz agent.

Surfaces what the student previously got wrong on a concept and how
their last few attempts scored. The agent uses this for two things:

1. Targeting — write distractors that mirror the student's prior
   mistakes (the LLM-generated `summary` from `quiz_context`
   captures patterns rolled up across past attempts).
2. Adaptive difficulty — read the last few `quiz_attempts` rows and
   step difficulty down when the student has been struggling, up
   when they've been crushing it.

The pure async function is callable from routes/tests; the *_tool
wrapper registers on a Pydantic AI Agent.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from pydantic import BaseModel, Field
from pydantic_ai import RunContext

from agents.deps import SaplingDeps
from db.connection import table

logger = logging.getLogger(__name__)


# How many past attempts the agent gets to see. 5 is enough to spot a
# trend without flooding the prompt with state. Older attempts are
# already rolled into `summary` by the post-quiz context update job.
_RECENT_ATTEMPTS_LIMIT = 5


class RecentQuizAttempt(BaseModel):
    """One past attempt's headline numbers."""

    score: int = Field(ge=0)
    total: int = Field(ge=0)
    difficulty: str
    completed_at: str | None = None
    accuracy: float = Field(ge=0.0, le=1.0)


class QuizHistory(BaseModel):
    """The agent's view of a student's history on one concept."""

    # LLM-generated digest of past quiz mistakes/patterns for this
    # (user, concept). Populated by the background context-update job
    # in routes/quiz.py:submit_quiz. May be None on a first attempt.
    summary: str | None = None
    # Most recent attempts, newest first. Empty on first attempt.
    recent_attempts: list[RecentQuizAttempt] = Field(default_factory=list)


def _coerce_summary(ctx: Any) -> str | None:
    """quiz_context.context_json is free-form (whatever the post-submit
    LLM produced). Different prompt versions have stored either a flat
    string or a small dict. Coerce to a single string the agent can
    reason over, or None if there's nothing useful."""
    if not ctx:
        return None
    if isinstance(ctx, str):
        text = ctx.strip()
        return text or None
    if isinstance(ctx, dict):
        # Common shapes: {"summary": "..."}, {"notes": "..."},
        # {"misconceptions": [...], "weak_areas": [...]}.
        for key in ("summary", "notes", "context", "digest"):
            v = ctx.get(key)
            if isinstance(v, str) and v.strip():
                return v.strip()
        # Fall back to flattening list-of-strings entries so the agent
        # at least sees the misconceptions/weak_areas the prior job
        # extracted, even when no top-level summary string exists.
        parts: list[str] = []
        for key in ("misconceptions", "weak_areas", "common_errors"):
            for item in ctx.get(key) or []:
                if isinstance(item, str) and item.strip():
                    parts.append(f"- {item.strip()}")
        return "\n".join(parts) or None
    return None


async def read_recent_quiz_attempts(
    user_id: str,
    concept_node_id: str,
) -> QuizHistory:
    """Return the agent's view of a student's history on one concept.

    Reads two sources:

    - `quiz_context` (one row per (user, concept)): the rolling
      LLM-generated digest of what the student has been getting
      wrong. This is the same blob legacy `routes/quiz.py` used to
      stuff into the prompt template.
    - `quiz_attempts` (one row per attempt, filtered to completed
      attempts): the last N completed attempts, newest first, with
      accuracy precomputed so the agent doesn't have to.

    Wraps the sync Supabase reads in `asyncio.to_thread` so we don't
    block the event loop. Failures degrade silently — the agent can
    still generate a quiz without history (just less adaptive).
    """

    def _fetch_summary() -> Any:
        try:
            rows = table("quiz_context").select(
                "context_json",
                filters={
                    "user_id": f"eq.{user_id}",
                    "concept_node_id": f"eq.{concept_node_id}",
                },
                limit=1,
            )
            return rows[0]["context_json"] if rows else None
        except Exception:
            logger.exception(
                "read_recent_quiz_attempts: quiz_context fetch failed "
                "user=%s concept=%s",
                user_id,
                concept_node_id,
            )
            return None

    def _fetch_attempts() -> list[dict[str, Any]]:
        try:
            return (
                table("quiz_attempts").select(
                    "score,total,difficulty,completed_at",
                    filters={
                        "user_id": f"eq.{user_id}",
                        "concept_node_id": f"eq.{concept_node_id}",
                        # Only count completed attempts. PostgREST `not.is.null`
                        # filters out rows where completed_at is NULL, which is
                        # how `routes/quiz.py:generate_quiz` marks an in-flight
                        # attempt before submission.
                        "completed_at": "not.is.null",
                    },
                    order="completed_at.desc",
                    limit=_RECENT_ATTEMPTS_LIMIT,
                )
                or []
            )
        except Exception:
            logger.exception(
                "read_recent_quiz_attempts: quiz_attempts fetch failed "
                "user=%s concept=%s",
                user_id,
                concept_node_id,
            )
            return []

    summary_raw, attempt_rows = await asyncio.gather(
        asyncio.to_thread(_fetch_summary),
        asyncio.to_thread(_fetch_attempts),
    )

    attempts: list[RecentQuizAttempt] = []
    for r in attempt_rows:
        try:
            score = int(r.get("score") or 0)
            total = int(r.get("total") or 0)
        except (TypeError, ValueError):
            continue
        if total <= 0:
            # Skip rows that look incomplete — accuracy is undefined and
            # the agent shouldn't have to guess.
            continue
        accuracy = max(0.0, min(1.0, score / total))
        attempts.append(
            RecentQuizAttempt(
                score=score,
                total=total,
                difficulty=str(r.get("difficulty") or ""),
                completed_at=r.get("completed_at"),
                accuracy=round(accuracy, 4),
            )
        )

    return QuizHistory(
        summary=_coerce_summary(summary_raw),
        recent_attempts=attempts,
    )


async def read_recent_quiz_attempts_tool(
    ctx: RunContext[SaplingDeps],
    concept_node_id: str,
) -> QuizHistory:
    """Pydantic AI tool wrapper.

    `concept_node_id` is supplied by the agent (which receives it in
    the user message). user_id comes from deps so a tool-call can't
    cross users.
    """
    return await read_recent_quiz_attempts(ctx.deps.user_id, concept_node_id)
