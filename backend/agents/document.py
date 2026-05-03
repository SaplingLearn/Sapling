"""Document orchestrator agent.

Coordinates classification, summary, concept extraction, and (when
applicable) syllabus extraction, then merges results into the user's
course graph. Replaces the sequential pipeline in
routes/documents.py::upload_document.

Concurrency model:
- Workers (summary, concepts, syllabus) run in parallel via
  asyncio.gather.
- Classification runs first because it gates whether syllabus
  extraction runs at all.
- The graph update runs as a tool the orchestrator can call after
  workers complete. If the orchestrator skips the tool call,
  routes/documents.py applies the update procedurally as a fallback.

Fallback contract (see docs/decisions/0001-adopt-pydantic-ai.md):
- If document_agent.run() raises any exception, routes/documents.py
  catches it, logs at WARNING, and runs _legacy_upload_pipeline
  (services/gemini_service.py-backed). The streaming route emits an
  error SSE event then falls through to the same legacy pipeline.
- If a worker fails inside _run_workers, the exception propagates up
  to process_document, then to the route, then to the legacy fallback.
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
from pydantic_ai import Agent
from pydantic_ai.models.google import GoogleModel
from pydantic_ai.providers.google import GoogleProvider

from agents import WORKER_LIMITS, ORCHESTRATOR_LIMITS
from agents.deps import SaplingDeps
from agents.classifier import classifier_agent, DocumentClassification
from agents.summary import summary_agent, Summary
from agents.concept_extraction import concept_extraction_agent, ConceptList
from agents.syllabus_extraction import syllabus_extraction_agent, SyllabusAssignments
from agents.tools.graph import apply_graph_update_tool
from config import GEMINI_API_KEY


class DocumentProcessingResult(BaseModel):
    """The orchestrator's final output (composed deterministically)."""

    classification: DocumentClassification
    summary: Summary
    concepts: ConceptList
    syllabus: SyllabusAssignments | None = Field(
        default=None,
        description="Populated only when classification.is_syllabus is True.",
    )
    graph_updated: bool = Field(
        default=False,
        description="True if the orchestrator called the graph update tool.",
    )


class GraphUpdateConfirmation(BaseModel):
    """The orchestrator agent's structured output.

    Kept deliberately small: Gemini's structured-output API rejects
    schemas with too many constrained states. We compose the full
    DocumentProcessingResult in process_document() instead, and use
    the agent only for the graph-update tool call.
    """

    graph_updated: bool = Field(
        description="True if apply_graph_update_tool was called.",
    )
    note: str = Field(
        default="",
        max_length=200,
        description="Short free-text note from the orchestrator.",
    )


_provider = GoogleProvider(api_key=GEMINI_API_KEY or "dummy-key-for-import")

document_agent = Agent[SaplingDeps, GraphUpdateConfirmation](
    model=GoogleModel("gemini-2.5-pro", provider=_provider),
    deps_type=SaplingDeps,
    output_type=GraphUpdateConfirmation,
    system_prompt=(
        "You orchestrate the final step of document ingestion. The "
        "user message contains a list of concept names already "
        "extracted from the document.\n\n"
        "Your job: call apply_graph_update_tool exactly once with "
        "those concept names to merge them into the student's course "
        "graph. Pass the concept names verbatim. Then return "
        "graph_updated=true and a short confirmation note.\n\n"
        "If the concept list is empty, do not call the tool; return "
        "graph_updated=false."
    ),
    tools=[apply_graph_update_tool],
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
    """Run workers in parallel, then ask the orchestrator to merge concepts
    into the graph via its registered tool.

    DocumentProcessingResult is composed deterministically here from worker
    outputs — only graph_updated comes from the orchestrator. This keeps
    the orchestrator's structured-output schema small enough for Gemini
    (the prior 'echo all worker outputs' design hit Gemini's schema-
    complexity limit and rejected every call).
    """
    workers = await _run_workers(text, deps)

    concept_names = [c.name for c in workers.concepts.concepts]
    confirmation = await document_agent.run(
        "Merge these concepts into the student's course graph: "
        f"{concept_names}",
        deps=deps,
        usage_limits=ORCHESTRATOR_LIMITS,
    )

    return DocumentProcessingResult(
        classification=workers.classification,
        summary=workers.summary,
        concepts=workers.concepts,
        syllabus=workers.syllabus,
        graph_updated=confirmation.output.graph_updated,
    )
