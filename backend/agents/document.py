"""Document processing pipeline.

Coordinates classification, summary, concept extraction, and (when
applicable) syllabus extraction, then merges results into the user's
course graph via `_step_apply_graph`, a durable step that calls
`apply_concepts_to_graph`.

There is no orchestrator agent here: the graph merge is a deterministic
function call with concept names already produced by the workers, so
we save a Gemini round-trip by skipping the agent wrapper entirely.

Concurrency model:
- Workers (summary, concepts, syllabus) run in parallel via
  asyncio.gather.
- Classification runs first because it gates whether syllabus
  extraction runs at all.
- The graph update runs as a durable step (`_step_apply_graph`) after
  workers complete, so a DBOS resume does not re-run the merge.

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
@durable_workflow-decorated `process_document` — either directly
(`_step_apply_graph`) or via `_run_workers` (the other four). For the
pinned dbos==2.28.0, calling a `_step_*` outside a workflow context is
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

from agents import WORKER_LIMITS
from agents.deps import SaplingDeps
from agents.classifier import classifier_agent, DocumentClassification
from agents.summary import summary_agent, Summary
from agents.concept_extraction import concept_extraction_agent, ConceptList
from agents.syllabus_extraction import syllabus_extraction_agent, SyllabusAssignments
from agents.tools.graph import apply_concepts_to_graph
from agents.usage import record_agent_usage
from services.durable import workflow as durable_workflow, step as durable_step


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


@durable_step
async def _step_apply_graph(
    user_id: str, course_id: str | None, concept_names: list[str],
) -> int:
    """Merge extracted concepts into the graph as a durable step, so a
    DBOS resume does not re-run the merge (it's the pipeline's one
    real-Supabase side effect besides persistence, which happens outside
    process_document entirely — see routes/documents.py).

    Calls `apply_concepts_to_graph` by its bare (module-global) name
    rather than binding it to a local/default-arg at decoration time —
    that matters because a plain global reference inside a function body
    is looked up fresh from the function's `__globals__` (this module's
    namespace) on EVERY call, not captured once when the function is
    defined. That is what lets tests/test_dbos_resume.py's
    `document_module.apply_concepts_to_graph = AsyncMock(...)`
    monkeypatch take effect here: it reassigns the SAME name in this
    module's namespace that this call resolves at call time. (A default
    argument like `apply_fn=apply_concepts_to_graph` would instead freeze
    in the ORIGINAL function object at decoration time and silently not
    observe the monkeypatch.) routes/documents.py's streaming route
    imports and calls the same `apply_concepts_to_graph` independently,
    inline and non-durable per ADR 0011's streaming-route asymmetry —
    a separate binding this monkeypatch doesn't touch, and doesn't need to.
    """
    return await apply_concepts_to_graph(user_id, course_id, concept_names)


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
    concepts_task = _step_concepts(text, deps)
    syllabus_task = _step_syllabus(text, deps) if classification.is_syllabus else None

    if syllabus_task is not None:
        summary, concepts, syllabus = await asyncio.gather(
            summary_task, concepts_task, syllabus_task,
        )
        return _WorkerResults(
            classification=classification,
            summary=summary, concepts=concepts, syllabus=syllabus,
        )
    summary, concepts = await asyncio.gather(summary_task, concepts_task)
    return _WorkerResults(
        classification=classification,
        summary=summary, concepts=concepts, syllabus=None,
    )


@durable_workflow
async def process_document(text: str, deps: SaplingDeps) -> DocumentProcessingResult:
    """Run workers in parallel, then merge concepts into the graph via the
    durable `_step_apply_graph`.

    DocumentProcessingResult is composed deterministically here from worker
    outputs. The graph merge has no orchestrator agent — no decisions to
    make beyond passing the already-extracted concept names through — but
    IS wrapped as a checkpointed step (`_step_apply_graph`) so a DBOS
    resume of this workflow doesn't repeat the merge.

    Wrapped in `@durable_workflow` from services.durable: a no-op when
    DBOS_ENABLED is unset (the default), a real DBOS workflow when the
    operator opts in. See ADR 0011 for the activation procedure.
    """
    workers = await _run_workers(text, deps)
    concept_names = [c.name for c in workers.concepts.concepts]
    merged = await _step_apply_graph(deps.user_id, deps.course_id, concept_names)
    return DocumentProcessingResult(
        classification=workers.classification,
        summary=workers.summary,
        concepts=workers.concepts,
        syllabus=workers.syllabus,
        graph_updated=merged > 0,
    )
