"""Document processing pipeline.

Coordinates classification, summary, concept extraction, and (when
applicable) syllabus extraction, then merges results into the user's
course graph by calling `apply_concepts_to_graph` directly.

There is no orchestrator agent here: the graph merge is a deterministic
function call with concept names already produced by the workers, so
we save a Gemini round-trip by skipping the agent wrapper entirely.

Concurrency model:
- Workers (summary, concepts, syllabus) run in parallel via
  asyncio.gather.
- Classification runs first because it gates whether syllabus
  extraction runs at all.
- The graph update is a direct async function call after workers complete.

Fallback contract (see docs/decisions/0001-adopt-pydantic-ai.md):
- If process_document raises any exception, routes/documents.py catches
  it, logs at WARNING, and runs _legacy_upload_pipeline
  (services/gemini_service.py-backed). The streaming route emits an
  error SSE event then falls through to the same legacy pipeline.
- If a worker fails inside _run_workers, the exception propagates up to
  process_document, then to the route, then to the legacy fallback.
- UsageLimitExceeded and UnexpectedModelBehavior are explicit fallback
  triggers, not user-facing errors.

Until the route stops calling _legacy_upload_pipeline (i.e., until we
delete services/gemini_service.py per ADR 0001's migration plan),
every new agent must respect this contract.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

from pydantic import BaseModel, Field

from agents import WORKER_LIMITS
from agents.deps import SaplingDeps
from agents.classifier import classifier_agent, DocumentClassification
from agents.summary import summary_agent, Summary
from agents.concept_extraction import concept_extraction_agent, ConceptList
from agents.syllabus_extraction import syllabus_extraction_agent, SyllabusAssignments
from agents.tools.graph import apply_concepts_to_graph


class DocumentProcessingResult(BaseModel):
    """The pipeline's final output (composed deterministically)."""

    classification: DocumentClassification
    summary: Summary
    concepts: ConceptList
    syllabus: SyllabusAssignments | None = Field(
        default=None,
        description="Populated only when classification.is_syllabus is True.",
    )
    graph_updated: bool = Field(
        default=False,
        description="True if any concepts were merged into the graph.",
    )


@dataclass
class _WorkerResults:
    classification: DocumentClassification
    summary: Summary
    concepts: ConceptList
    syllabus: SyllabusAssignments | None


async def _run_workers(text: str, deps: SaplingDeps) -> _WorkerResults:
    """Run classification first, then fan out the other workers in parallel.

    Syllabus extraction only runs if classification flagged the document
    as a syllabus. Saves a Gemini call on the common case.
    """
    cls_result = await classifier_agent.run(text, deps=deps, usage_limits=WORKER_LIMITS)
    classification = cls_result.output

    summary_task = summary_agent.run(text, deps=deps, usage_limits=WORKER_LIMITS)
    concepts_task = concept_extraction_agent.run(text, deps=deps, usage_limits=WORKER_LIMITS)
    syllabus_task = (
        syllabus_extraction_agent.run(text, deps=deps, usage_limits=WORKER_LIMITS)
        if classification.is_syllabus
        else None
    )

    if syllabus_task is not None:
        summary_r, concepts_r, syllabus_r = await asyncio.gather(
            summary_task, concepts_task, syllabus_task,
        )
        return _WorkerResults(
            classification=classification,
            summary=summary_r.output,
            concepts=concepts_r.output,
            syllabus=syllabus_r.output,
        )
    summary_r, concepts_r = await asyncio.gather(summary_task, concepts_task)
    return _WorkerResults(
        classification=classification,
        summary=summary_r.output,
        concepts=concepts_r.output,
        syllabus=None,
    )


async def process_document(text: str, deps: SaplingDeps) -> DocumentProcessingResult:
    """Run workers in parallel, then merge concepts into the graph directly.

    DocumentProcessingResult is composed deterministically here from worker
    outputs. The graph merge is a plain async function call — no orchestrator
    agent — because it has no decisions to make beyond passing the
    already-extracted concept names through.
    """
    workers = await _run_workers(text, deps)
    concept_names = [c.name for c in workers.concepts.concepts]
    merged = await apply_concepts_to_graph(
        deps.user_id, deps.course_id, concept_names,
    )
    return DocumentProcessingResult(
        classification=workers.classification,
        summary=workers.summary,
        concepts=workers.concepts,
        syllabus=workers.syllabus,
        graph_updated=merged > 0,
    )
