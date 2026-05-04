"""Read-side graph tools for Pydantic AI agents.

Per ADR 0004: the agent needs to pull mastery state + course-level
misconceptions when planning a quiz. These are the tool surfaces.
The pure-async functions are callable directly from routes;
the *_tool wrappers register on a Pydantic AI Agent.
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


# ── read_concepts_for_user ────────────────────────────────────────────────


class ConceptMastery(BaseModel):
    """Per-concept mastery state for the user in a course."""

    concept_name: str
    mastery: float = Field(ge=0.0, le=1.0)
    last_reviewed_at: str | None = None


async def read_concepts_for_user(
    user_id: str,
    course_id: str | None,
) -> list[ConceptMastery]:
    """Return the user's concept mastery for a course (or globally if
    course_id is None). Sorted by mastery ASC so the weakest concepts
    appear first — quiz_agent uses this ordering to focus on weak areas.

    Pure async, callable from routes. Wraps the underlying sync
    Supabase read in asyncio.to_thread so it doesn't block the loop.

    NOTE: The underlying `graph_nodes` table stores the mastery value as
    `mastery_score` and the timestamp as `last_studied_at`. We map them
    here to the agent-facing names (`mastery`, `last_reviewed_at`) so the
    tool contract stays stable even if storage column names change.
    """

    def _fetch() -> list[dict[str, Any]]:
        filters = {"user_id": f"eq.{user_id}"}
        if course_id:
            filters["course_id"] = f"eq.{course_id}"
        try:
            return (
                table("graph_nodes").select(
                    "concept_name,mastery_score,last_studied_at",
                    filters=filters,
                    order="mastery_score.asc",
                )
                or []
            )
        except Exception:
            logger.exception(
                "read_concepts_for_user failed for user=%s course=%s",
                user_id,
                course_id,
            )
            return []

    rows = await asyncio.to_thread(_fetch)
    return [
        ConceptMastery(
            concept_name=r.get("concept_name") or "",
            mastery=float(r.get("mastery_score") or 0.0),
            last_reviewed_at=r.get("last_studied_at"),
        )
        for r in rows
        if r.get("concept_name")
    ]


async def read_concepts_for_user_tool(
    ctx: RunContext[SaplingDeps],
) -> list[ConceptMastery]:
    """Pydantic AI tool wrapper. Reads from ctx.deps."""
    return await read_concepts_for_user(ctx.deps.user_id, ctx.deps.course_id)


# ── read_misconceptions_for_course ────────────────────────────────────────


class Misconception(BaseModel):
    """A class-level misconception observed across student sessions."""

    text: str
    related_concept: str | None = None


async def read_misconceptions_for_course(
    course_id: str | None,
) -> list[Misconception]:
    """Return aggregated misconception strings for a course. Anonymized
    (sourced from class-wide patterns, not from any single student).
    Returns [] when course_id is None or the underlying table is empty.

    Source: `course_concept_stats` rows for the course. Each row
    represents one concept and carries a `common_misconceptions` array
    (populated by the hash-gated aggregation in
    `services/course_context_service.py`). We flatten each array entry
    into its own Misconception, tagging `related_concept` with the
    concept name so the agent can route distractors per-concept.

    The spec referenced a hypothetical `misconceptions` table — that
    table does not exist in this schema. `course_concept_stats` is the
    real source of class-wide misconception strings, so we read that.
    The tool contract (returning Misconception[]) is unchanged.
    """
    if not course_id:
        return []

    def _fetch() -> list[dict[str, Any]]:
        try:
            return (
                table("course_concept_stats").select(
                    "concept_name,common_misconceptions",
                    filters={"course_id": f"eq.{course_id}"},
                    order="updated_at.desc",
                    limit=20,
                )
                or []
            )
        except Exception:
            logger.exception(
                "read_misconceptions_for_course failed for course=%s",
                course_id,
            )
            return []

    rows = await asyncio.to_thread(_fetch)
    out: list[Misconception] = []
    seen: set[str] = set()
    for r in rows:
        concept = r.get("concept_name") or None
        for m in r.get("common_misconceptions") or []:
            text = (m or "").strip() if isinstance(m, str) else ""
            if not text:
                continue
            key = text.lower()
            if key in seen:
                continue
            seen.add(key)
            out.append(Misconception(text=text, related_concept=concept))
    return out


async def read_misconceptions_for_course_tool(
    ctx: RunContext[SaplingDeps],
) -> list[Misconception]:
    """Pydantic AI tool wrapper. Reads from ctx.deps."""
    return await read_misconceptions_for_course(ctx.deps.course_id)
