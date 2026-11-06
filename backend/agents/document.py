"""Document processing pipeline.

Coordinates classification, summary, concept extraction, and (when
applicable) syllabus extraction, then composes the result.

Uploading a document NEVER writes to the knowledge graph. The extracted
concepts are persisted on the document row (`documents.concept_notes`)
and reach `graph_nodes` only when the student explicitly asks for it via
the scan-concepts routes — an upload must not seed the course graph with
concepts nobody chose to add.

There is no orchestrator agent here: the result is composed
deterministically from worker output, so we save a model round-trip by
skipping the agent wrapper entirely.

Concurrency model:
- Workers (summary, concepts, syllabus) run in parallel via
  asyncio.gather.
- Classification runs first because it gates whether syllabus
  extraction runs at all.

Failure contract (ADR 0024 — this pipeline is the ONLY upload pipeline;
ADR 0001's legacy fallback was retired in #151b):
- If a worker fails inside _run_workers, the exception propagates up to
  process_document and then to the route.
- routes/documents.py maps failures to the client: /upload/sync raises a
  retry-friendly 502 (guardrail trips log at WARNING, anything else logs
  the full exception); the streaming route emits a terminal
  error:failed + status:done SSE pair.
- UsageLimitExceeded and UnexpectedModelBehavior are the expected
  guardrail failures, not bugs — routes must keep them distinguishable
  from bare exceptions in logs.

Internal API: the `_step_*` functions defined below are wrapped with
@durable_step and are meant to be called ONLY from within the
@durable_workflow-decorated `process_document`, via `_run_workers`. For
the pinned dbos==2.28.0, calling a `_step_*` outside a workflow context is
NOT undefined: `dbos/_core.py::decorate_step`'s wrapper checks
`ctx.is_workflow()` and, when there's no ambient workflow context, falls
straight through to `return func(*args, **kwargs)` — the plain function
runs for real, synchronously, with no DBOS registry lookup and no error
(verified at `dbos/_core.py:2126-2152`). That's well-defined but still
wrong to rely on here: the call would execute but get NONE of DBOS's
checkpoint/resume behavior, silently losing durability for that call.
Don't import them from routes or other modules; call only from
`_run_workers`/`process_document`.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

from pydantic import BaseModel, Field

from agents import NOTES_LIMITS, WORKER_LIMITS
from agents.deps import SaplingDeps
from agents.classifier import classifier_agent, DocumentClassification
from agents.summary import summary_agent, Summary
from agents.document_notes import document_notes_agent, ComprehensiveNotes
from agents.concept_extraction import concept_extraction_agent, ConceptList
from agents.syllabus_extraction import syllabus_extraction_agent, SyllabusAssignments
from agents.usage import record_agent_usage
from services.durable import workflow as durable_workflow, step as durable_step


class DocumentProcessingResult(BaseModel):
    """The pipeline's final output (composed deterministically)."""

    classification: DocumentClassification
    summary: Summary
    notes: ComprehensiveNotes
    concepts: ConceptList
    syllabus: SyllabusAssignments | None = Field(
        default=None,
        description="Populated only when classification.is_syllabus is True.",
    )
    graph_updated: bool = Field(
        default=False,
        description=(
            "Always False: uploading a document never merges concepts into "
            "the graph. Kept on the wire so SSE/JSON clients and the "
            "function-mode fixtures keep their existing shape."
        ),
    )


@dataclass
class _WorkerResults:
    classification: DocumentClassification
    summary: Summary
    notes: ComprehensiveNotes
    concepts: ConceptList
    syllabus: SyllabusAssignments | None


# Each agent run is wrapped as a durable step so DBOS (when enabled) can
# resume the workflow at the last completed worker on a worker-crash retry,
# instead of re-running every agent from scratch. When DBOS is disabled
# (the default), `durable_step` is a no-op and these are plain async funcs.

@durable_step
async def _step_classify(text: str, deps: SaplingDeps) -> DocumentClassification:
    result = record_agent_usage(
        await classifier_agent.run(text, deps=deps, usage_limits=WORKER_LIMITS),
        feature="document", task="classifier", user_id=deps.user_id,
    )
    return result.output


@durable_step
async def _step_summary(text: str, deps: SaplingDeps) -> Summary:
    result = record_agent_usage(
        await summary_agent.run(text, deps=deps, usage_limits=WORKER_LIMITS),
        feature="document", task="summary", user_id=deps.user_id,
    )
    return result.output


@durable_step
async def _step_notes(text: str, deps: SaplingDeps) -> ComprehensiveNotes:
    result = record_agent_usage(
        await document_notes_agent.run(text, deps=deps, usage_limits=NOTES_LIMITS),
        feature="document", task="document_notes", user_id=deps.user_id,
    )
    return result.output


@durable_step
async def _step_concepts(text: str, deps: SaplingDeps) -> ConceptList:
    result = record_agent_usage(
        await concept_extraction_agent.run(text, deps=deps, usage_limits=WORKER_LIMITS),
        feature="document", task="concepts", user_id=deps.user_id,
    )
    return result.output


@durable_step
async def _step_syllabus(text: str, deps: SaplingDeps) -> SyllabusAssignments:
    result = record_agent_usage(
        await syllabus_extraction_agent.run(text, deps=deps, usage_limits=WORKER_LIMITS),
        feature="document", task="syllabus", user_id=deps.user_id,
    )
    return result.output


async def _run_workers(text: str, deps: SaplingDeps) -> _WorkerResults:
    """Run classification first, then fan out the other workers in parallel.

    Syllabus extraction only runs if classification flagged the document
    as a syllabus. Saves a Gemini call on the common case.

    Each worker is wrapped as a `@durable_step`, so a DBOS-enabled
    deployment checkpoints completion of each one and resumes mid-pipeline
    after a crash.
    """
    classification = await _step_classify(text, deps)

    summary_task = _step_summary(text, deps)
    notes_task = _step_notes(text, deps)
    concepts_task = _step_concepts(text, deps)
    syllabus_task = _step_syllabus(text, deps) if classification.is_syllabus else None

    if syllabus_task is not None:
        summary, notes, concepts, syllabus = await asyncio.gather(
            summary_task, notes_task, concepts_task, syllabus_task,
        )
        return _WorkerResults(
            classification=classification,
            summary=summary, notes=notes, concepts=concepts, syllabus=syllabus,
        )
    summary, notes, concepts = await asyncio.gather(summary_task, notes_task, concepts_task)
    return _WorkerResults(
        classification=classification,
        summary=summary, notes=notes, concepts=concepts, syllabus=None,
    )


@durable_workflow
async def process_document(text: str, deps: SaplingDeps) -> DocumentProcessingResult:
    """Run the workers in parallel and compose their output.

    DocumentProcessingResult is composed deterministically here from worker
    outputs. Nothing in this pipeline touches the knowledge graph: the
    extracted concepts travel on the result (and from there onto
    `documents.concept_notes`), and only an explicit scan-concepts request
    turns them into `graph_nodes`.

    Wrapped in `@durable_workflow` from services.durable: a no-op when
    DBOS_ENABLED is unset (the default), a real DBOS workflow when the
    operator opts in. See ADR 0011 for the activation procedure.
    """
    workers = await _run_workers(text, deps)
    return DocumentProcessingResult(
        classification=workers.classification,
        summary=workers.summary,
        notes=workers.notes,
        concepts=workers.concepts,
        syllabus=workers.syllabus,
    )
