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

One pipeline (#835): `run_document_agents` is the ONLY sequence of agent
calls an upload makes. It yields a `PipelineStep` at each phase boundary
(classify, classified, extracted, merged, done) so each caller reports
progress its own way: the streaming route turns the steps into SSE events
(services/document_pipeline.py::step_events), the `document.process` worker
records them as stages on the upload row (services/document_jobs.py), and
`process_document` (the `/upload/sync` path) just waits for `done`.

Internal API: the `_step_*` functions defined below are wrapped with
@durable_step and are called ONLY by `run_document_agents`. Inside the
@durable_workflow-decorated `process_document` they are real durable steps;
from the streaming route and the worker (no workflow) they run as plain
calls, which is what those paths always did. For the
pinned dbos==2.28.0, calling a `_step_*` outside a workflow context is
NOT undefined: `dbos/_core.py::decorate_step`'s wrapper checks
`ctx.is_workflow()` and, when there's no ambient workflow context, falls
straight through to `return func(*args, **kwargs)` — the plain function
runs for real, synchronously, with no DBOS registry lookup and no error
(verified at `dbos/_core.py:2126-2152`). That's well-defined but still
wrong to rely on here: the call would execute but get NONE of DBOS's
checkpoint/resume behavior, silently losing durability for that call.
Don't import them from routes or other modules; call only from
`run_document_agents`.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import AsyncIterator

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


#: PipelineStep names, in the order `run_document_agents` yields them.
CLASSIFY = "classify"        # about to classify
CLASSIFIED = "classified"    # classification known (category, is_syllabus)
EXTRACTED = "extracted"      # summary/concepts(/syllabus) done (concept_count)
MERGED = "merged"            # concepts merged into the graph (merged)
DONE = "done"                # the composed result (result, merged)


@dataclass(frozen=True)
class PipelineStep:
    """One phase boundary of the upload pipeline."""

    name: str
    category: str | None = None
    is_syllabus: bool = False
    concept_count: int = 0
    merged: int = 0
    result: DocumentProcessingResult | None = None


# Each agent run is wrapped as a durable step so DBOS (when enabled) can
# resume the workflow at the last completed worker on a worker-crash retry,
# instead of re-running every agent from scratch. When DBOS is disabled
# (the default), `durable_step` is a no-op and these are plain async funcs.

@durable_step
async def _step_classify(text: str, deps: SaplingDeps) -> DocumentClassification:
    result = record_agent_usage(
        await classifier_agent.run(text, deps=deps, usage_limits=WORKER_LIMITS),
        feature="document", task="classifier", user_id=deps.user_id, request_id=deps.request_id,
    )
    return result.output


@durable_step
async def _step_summary(text: str, deps: SaplingDeps) -> Summary:
    result = record_agent_usage(
        await summary_agent.run(text, deps=deps, usage_limits=WORKER_LIMITS),
        feature="document", task="summary", user_id=deps.user_id, request_id=deps.request_id,
    )
    return result.output


@durable_step
async def _step_concepts(text: str, deps: SaplingDeps) -> ConceptList:
    result = record_agent_usage(
        await concept_extraction_agent.run(text, deps=deps, usage_limits=WORKER_LIMITS),
        feature="document", task="concepts", user_id=deps.user_id, request_id=deps.request_id,
    )
    return result.output


@durable_step
async def _step_syllabus(text: str, deps: SaplingDeps) -> SyllabusAssignments:
    result = record_agent_usage(
        await syllabus_extraction_agent.run(text, deps=deps, usage_limits=WORKER_LIMITS),
        feature="document", task="syllabus", user_id=deps.user_id, request_id=deps.request_id,
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
    observe the monkeypatch.) The streaming route and the worker reach
    this same step through `run_document_agents`, outside any workflow, so
    for them it is a plain (non-durable) call — ADR 0011's streaming-route
    asymmetry, unchanged.
    """
    return await apply_concepts_to_graph(user_id, course_id, concept_names)


async def run_document_agents(
    text: str, deps: SaplingDeps,
) -> AsyncIterator[PipelineStep]:
    """The upload pipeline: classify first (it gates syllabus extraction),
    then summary + concepts (+ syllabus) in parallel, then merge the concepts
    into the course graph. Yields a PipelineStep at each boundary, ending
    with DONE carrying the composed DocumentProcessingResult. Any agent
    failure propagates to the caller (see the failure contract above).

    Usage is recorded per agent run with the deps' user and request id (the
    worker and the SSE generator run outside the request contextvar)."""
    yield PipelineStep(CLASSIFY)
    classification = await _step_classify(text, deps)
    yield PipelineStep(CLASSIFIED, category=classification.category,
                       is_syllabus=classification.is_syllabus)

    summary_task = _step_summary(text, deps)
    concepts_task = _step_concepts(text, deps)
    syllabus = None
    if classification.is_syllabus:
        summary, concepts, syllabus = await asyncio.gather(
            summary_task, concepts_task, _step_syllabus(text, deps),
        )
    else:
        summary, concepts = await asyncio.gather(summary_task, concepts_task)
    yield PipelineStep(EXTRACTED, concept_count=len(concepts.concepts))

    merged = await _step_apply_graph(
        deps.user_id, deps.course_id, [c.name for c in concepts.concepts],
    )
    yield PipelineStep(MERGED, merged=merged)
    yield PipelineStep(DONE, merged=merged, result=DocumentProcessingResult(
        classification=classification,
        summary=summary,
        concepts=concepts,
        syllabus=syllabus,
        graph_updated=merged > 0,
    ))


@durable_workflow
async def process_document(text: str, deps: SaplingDeps) -> DocumentProcessingResult:
    """`run_document_agents` to its end, for `/upload/sync`.

    The graph merge has no orchestrator agent — no decisions to make beyond
    passing the already-extracted concept names through — but IS a
    checkpointed step (`_step_apply_graph`) so a DBOS resume of this
    workflow doesn't repeat the merge.

    Wrapped in `@durable_workflow` from services.durable: a no-op when
    DBOS_ENABLED is unset (the default), a real DBOS workflow when the
    operator opts in. See ADR 0011 for the activation procedure.
    """
    steps = run_document_agents(text, deps)
    try:
        async for step in steps:
            if step.name == DONE:
                return step.result
    finally:
        await steps.aclose()
    raise RuntimeError("document pipeline ended without a result")  # pragma: no cover
