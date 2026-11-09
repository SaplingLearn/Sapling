"""The upload pipeline's progress vocabulary, once (#835, #118).

`agents.document.run_document_agents` is the one sequence of agent calls an
upload makes, and it yields a `PipelineStep` at each phase boundary. This
module turns those steps into the SSE progress events the frontend reads, so
the two places that report an upload's progress say exactly the same thing:

* the streaming route (routes/documents.py) maps each step as it happens;
* a queued upload (services/document_jobs.py) is run by the worker, which
  records the steps as stages on the `document_uploads` row; the request
  watching that row replays each stage's events from here.

Text extraction comes before the pipeline and has its own pair of events
(`extracting_text_event` / `extracted_text_event`), sent by the streaming
route only on its async-OCR path and always by a queued upload.
"""
from __future__ import annotations

from agents.document import (
    CLASSIFIED,
    CLASSIFY,
    DONE,
    EXTRACTED,
    MERGED,
    PipelineStep,
    run_document_agents,
)
from services.agent_events import SaplingEvent

__all__ = [
    "CLASSIFIED", "CLASSIFY", "DONE", "EXTRACTED", "MERGED", "PipelineStep",
    "extracted_text_event", "extracting_text_event", "run_document_agents", "step_events",
]


def extracting_text_event() -> SaplingEvent:
    return SaplingEvent(type="progress", step="extracting_text",
                        message="Extracting text from document...")


def extracted_text_event(char_count: int) -> SaplingEvent:
    return SaplingEvent(type="progress", step="extracted_text",
                        message=f"Extracted {char_count:,} chars.")


def step_events(step: PipelineStep) -> list[SaplingEvent]:
    """The progress events for one pipeline step (none for DONE: the caller
    sends the `result` itself, after persisting or with the stored one)."""
    if step.name == CLASSIFY:
        return [SaplingEvent(type="progress", step="classify",
                             message="Classifying document...")]
    if step.name == CLASSIFIED:
        return [
            SaplingEvent(type="progress", step="classified",
                         message=f"Classified as {step.category}.",
                         data={"category": step.category, "is_syllabus": step.is_syllabus}),
            SaplingEvent(type="progress", step="extract",
                         message="Extracting summary, concepts"
                                 + (" and syllabus" if step.is_syllabus else "")
                                 + " in parallel..."),
        ]
    if step.name == EXTRACTED:
        return [
            SaplingEvent(type="progress", step="extracted",
                         message=f"Extracted {step.concept_count} concept(s)."),
            SaplingEvent(type="progress", step="graph_update",
                         message="Merging concepts into the course graph..."),
        ]
    if step.name == MERGED:
        return [SaplingEvent(type="progress", step="graph_updated",
                             message=f"Merged {step.merged} concept(s).")]
    return []
