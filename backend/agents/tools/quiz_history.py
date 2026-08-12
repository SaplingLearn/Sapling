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
from services.encryption import decrypt_json_column

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


# String fields worth surfacing, in display order. `questions_seen_summary`
# and `notes` are what agents/quiz_context.py::QuizContext actually writes;
# summary/context/digest cover older free-form rows.
_SUMMARY_STRING_KEYS = ("summary", "questions_seen_summary", "notes", "context", "digest")

# List-of-strings fields, with a label so the agent knows what each block is.
# `weak_areas`/`common_mistakes` are the live QuizContext field names;
# misconceptions/common_errors cover older rows.
_SUMMARY_LIST_KEYS = (
    ("weak_areas", "Weak areas"),
    ("common_mistakes", "Common mistakes"),
    ("misconceptions", "Misconceptions"),
    ("common_errors", "Common errors"),
)


def _coerce_summary(ctx: Any) -> str | None:
    """quiz_context.context_json is free-form (whatever the post-submit
    LLM produced). Coerce to a single string the agent can reason over,
    or None if there's nothing useful.

    #529/B4: this must consume the WHOLE QuizContext shape. The old
    version returned the first matching string key — for a live
    QuizContext row that was `notes` alone, silently dropping
    weak_areas / common_mistakes / questions_seen_summary (and its list
    fallback looked for `common_errors`, a key QuizContext never writes).
    """
    if not ctx:
        return None
    if isinstance(ctx, str):
        text = ctx.strip()
        return text or None
    if isinstance(ctx, dict):
        parts: list[str] = []
        for key in _SUMMARY_STRING_KEYS:
            v = ctx.get(key)
            if isinstance(v, str) and v.strip():
                parts.append(v.strip())
        for key, label in _SUMMARY_LIST_KEYS:
            items = [
                item.strip()
                for item in (ctx.get(key) or [])
                if isinstance(item, str) and item.strip()
            ]
            if items:
                parts.append(label + ":\n" + "\n".join(f"- {i}" for i in items))
        return "\n\n".join(parts) or None
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
            return decrypt_json_column(rows[0]["context_json"]) if rows else None
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
        raw_score = r.get("score")
        raw_total = r.get("total")
        if raw_score is None or raw_total is None:
            # `submit_quiz` writes score+total atomically, so a row with
            # `completed_at IS NOT NULL` but a null score/total is
            # corruption (or an out-of-band edit). Drop it rather than
            # coercing to 0/0 — feeding the LLM a bogus 0% accuracy
            # could trigger a spurious adaptive downshift.
            logger.warning(
                "read_recent_quiz_attempts: dropping row with null "
                "score/total (score=%r, total=%r) user=%s concept=%s",
                raw_score,
                raw_total,
                user_id,
                concept_node_id,
            )
            continue
        try:
            score = int(raw_score)
            total = int(raw_total)
        except (TypeError, ValueError):
            continue
        if total <= 0:
            # Skip rows that look incomplete — accuracy is undefined and
            # the agent shouldn't have to guess.
            continue
        if score < 0 or score > total:
            # Corrupt row (score outside [0, total]). Drop entirely
            # rather than passing impossible numbers to the LLM —
            # `score=7, total=5` would prompt the agent to wonder
            # whether to trust the data at all.
            logger.warning(
                "read_recent_quiz_attempts: dropping corrupt row "
                "(score=%d outside [0, total=%d]) user=%s concept=%s",
                score,
                total,
                user_id,
                concept_node_id,
            )
            continue
        accuracy = score / total
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
    """Returns this student's history on one concept: a `summary`
    string digesting their prior mistakes (mine for distractor
    inspiration) and `recent_attempts` — the last 5 completed quiz
    attempts on this concept, newest first, with `accuracy` precomputed
    so you can apply the adaptive-difficulty rule directly. Empty
    history on first attempt. Pass the `concept_node_id` from the
    user message; user identity is taken from context.
    """
    # user_id comes from ctx.deps so a tool call can't cross users.
    history = await read_recent_quiz_attempts(ctx.deps.user_id, concept_node_id)
    if history.summary:
        # #150: the summary is LLM-digested from the student's own quiz
        # answers — free text that can carry injected directives back into
        # a later prompt. Envelope it at this LLM boundary.
        from services.prompt_safety import wrap_untrusted

        history = history.model_copy(
            update={
                "summary": wrap_untrusted(
                    history.summary, source="student quiz-mistake digest"
                )
            }
        )
    return history
