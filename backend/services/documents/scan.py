"""
backend/services/documents/scan.py

Concept scan (#118, moved from routes/documents.py): extend a course's
concept graph with concept_scan_agent, seeded by the course label, the
concepts already in the graph and optionally one document.
"""
from __future__ import annotations

import logging
import uuid

from pydantic_ai.exceptions import UsageLimitExceeded, UnexpectedModelBehavior

from agents import WORKER_LIMITS
from agents._run import run_agent_sync
from agents.concept_scan import concept_scan_agent
from agents.deps import SaplingDeps
from agents.usage import record_agent_usage
from db.connection import table
from services.documents.errors import ConceptScanFailed
from services.graph_service import apply_graph_update
from services.request_context import current_request_id

logger = logging.getLogger(__name__)


def _scan_user_message(
    *,
    course_label: str,
    existing_concepts: list[str],
    doc_filename: str | None = None,
    doc_summary: str | None = None,
    doc_concept_notes: list[dict] | None = None,
) -> str:
    """Build the concept_scan agent's user message: course label + existing
    concepts + (optional) document context."""
    existing_block = (
        "\n".join(f"- {c}" for c in existing_concepts) if existing_concepts else "(none yet)"
    )
    lines = [
        f'Course: "{course_label}"',
        "Concepts already in the graph:",
        existing_block,
    ]
    if doc_filename or doc_summary or doc_concept_notes:
        notes_block = (
            "\n".join(
                f"  - {n.get('name', '?')}: {n.get('description', '')[:200]}"
                for n in (doc_concept_notes or [])
            )
            or "  (none)"
        )
        lines += [
            "",
            "New document being scanned:",
            f"  Title: {doc_filename or '(untitled)'}",
            f"  Summary: {doc_summary or '(none)'}",
            "  Concepts already extracted from this document:",
            notes_block,
        ]
    return "\n".join(lines)


async def _extend_via_agent(
    *,
    user_id: str,
    course_id: str,
    course_label: str,
    existing_concepts: list[str],
    doc_filename: str | None = None,
    doc_summary: str | None = None,
    doc_concept_notes: list[dict] | None = None,
) -> list[str]:
    """Run concept_scan_agent and return new concept names. Raises on agent
    failure; the sync dispatcher (_extend_concepts) degrades to []."""
    deps = SaplingDeps(
        user_id=user_id,
        course_id=course_id,
        supabase=None,
        request_id=current_request_id() or str(uuid.uuid4()),
    )
    message = _scan_user_message(
        course_label=course_label,
        existing_concepts=existing_concepts,
        doc_filename=doc_filename,
        doc_summary=doc_summary,
        doc_concept_notes=doc_concept_notes,
    )
    result = record_agent_usage(
        await concept_scan_agent.run(
            message, deps=deps, usage_limits=WORKER_LIMITS,
        ),
        feature="document", task="concept_scan",
    )
    return list(result.output.concepts)


def _extend_concepts(
    user_id: str,
    course_id: str,
    *,
    course_label: str,
    existing_concepts: list[str],
    doc_filename: str | None = None,
    doc_summary: str | None = None,
    doc_concept_notes: list[dict] | None = None,
) -> list[str]:
    """Concept extension via concept_scan_agent — the only scan path since
    #151b (ADR 0024 retired the legacy call_gemini_json fallback).

    Sync entry point for the sync /scan-concepts handlers: drives the async
    agent via run_agent_sync. Best-effort enrichment (D4): any agent failure
    degrades to "no new concepts" with a warning log, so the scan response
    reports {"concepts": [], "added": 0, "existing": N} instead of 500ing a
    route whose whole job is optional graph enrichment.
    """
    try:
        return run_agent_sync(
            _extend_via_agent(
                user_id=user_id,
                course_id=course_id,
                course_label=course_label,
                existing_concepts=existing_concepts,
                doc_filename=doc_filename,
                doc_summary=doc_summary,
                doc_concept_notes=doc_concept_notes,
            )
        )
    except (UsageLimitExceeded, UnexpectedModelBehavior) as e:
        logger.warning(
            "concept_scan agent guardrails tripped; degrading to no new concepts",
            exc_info=e,
        )
    except Exception:
        logger.warning(
            "concept_scan agent failed; degrading to no new concepts",
            exc_info=True,
        )
    return []


def _course_label(course_id: str) -> str:
    """Best-effort human label for a course (for prompts and toasts)."""
    rows = table("courses").select(
        "course_code,course_name", filters={"id": f"eq.{course_id}"}, limit=1,
    ) or []
    if not rows:
        return "Course"
    row = rows[0]
    code = (row.get("course_code") or "").strip()
    name = (row.get("course_name") or "").strip()
    if code and name:
        return f"{code} — {name}"
    return code or name or "Course"


def _scan_concepts_for_course(
    user_id: str,
    course_id: str,
    *,
    doc_filename: str | None = None,
    doc_summary: str | None = None,
    doc_concept_notes: list[dict] | None = None,
) -> dict:
    """Shared scan logic. Pulls existing course concepts, asks the LLM to
    extend the set, and writes new nodes via apply_graph_update."""
    existing_rows = table("graph_nodes").select(
        "id,concept_name", filters={"user_id": f"eq.{user_id}", "course_id": f"eq.{course_id}"},
    ) or []
    existing_concepts = [r["concept_name"] for r in existing_rows if r.get("concept_name")]

    concepts = _extend_concepts(
        user_id,
        course_id,
        course_label=_course_label(course_id),
        existing_concepts=existing_concepts,
        doc_filename=doc_filename,
        doc_summary=doc_summary,
        doc_concept_notes=doc_concept_notes,
    )
    if not concepts:
        return {"concepts": [], "added": 0, "existing": len(existing_concepts)}

    before_count = len(existing_rows)
    try:
        new_nodes = [{"concept_name": name, "initial_mastery": 0.0} for name in concepts]
        apply_graph_update(user_id, {"new_nodes": new_nodes}, course_id=course_id)
    except Exception:
        logger.exception("Concept scan failed for course=%s", course_id)
        raise ConceptScanFailed("Concept scan failed.")

    after_rows = table("graph_nodes").select(
        "id", filters={"user_id": f"eq.{user_id}", "course_id": f"eq.{course_id}"},
    ) or []
    return {
        "concepts": concepts,
        "added": max(0, len(after_rows) - before_count),
        "existing": len(existing_concepts),
    }
