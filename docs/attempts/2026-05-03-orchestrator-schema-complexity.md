# Orchestrator output schema rejected by Gemini

- Date: 2026-05-03
- Related: docs/decisions/0001-adopt-pydantic-ai.md, docs/decisions/0003-implementation-conventions.md

## What I tried

Designed the document orchestrator's output type as a complete `DocumentProcessingResult` Pydantic model: classification + summary + concepts + optional syllabus + `graph_updated` flag. The intent was one source of truth for the route — call `document_agent.run()` and return its output verbatim.

## Why it didn't work

Gemini's structured-output API rejected the schema. The combination of nested optional models, lists of constrained-field objects, and per-field descriptions tripped its complexity tolerance and every call returned a schema-validation error from the provider before any model output was attempted. The agent never got to do real work — just emitted shape errors.

## What I'd try next

The current pattern is the answer: keep agent output types small (`GraphUpdateConfirmation` is two fields — `graph_updated: bool` + a short note), and compose the full result deterministically from worker outputs in route/orchestrator code. For ADR 0004's `quiz_agent` and the eventual chat-tutor refactor, design output types defensively — under ~5 fields, avoid nested models, prefer flat enums to constrained strings. If a rich output is needed, decompose into multiple agent runs or post-compose in code rather than asking Gemini to emit it whole.
