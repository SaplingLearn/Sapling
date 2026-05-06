# 0003: Implementation conventions discovered during the document refactor

- Status: accepted
- Date: 2026-05-03
- Supersedes: none

## Context

During Prompts 08-14 of the document-upload refactor, four conventions emerged that ADR 0001 didn't anticipate. Individually none warrants its own ADR, but together they shape how subsequent agent refactors should be built. Logging them here so the next refactor inherits them instead of relitigating each one.

## Decision

- (1) Agent system prompts live inline in the agent's `.py` file (`backend/agents/classifier.py`, `backend/agents/document.py`, etc.), not externalized to `backend/prompts/`. Externalization is deferred until a single prompt grows past ~30 lines or two agents need to share one. Today the longest is the orchestrator's, at ~10 lines.
- (2) `usage_limits=` is passed per-`.run()` / `.run_stream_events()` call, not configured on the `Agent` constructor. `WORKER_LIMITS` and `ORCHESTRATOR_LIMITS` are exported from `backend/agents/__init__.py` and imported at every call site. Same agent, different limits in different contexts (production worker vs. eval harness) without forking.
- (3) The streaming upload route uses `asyncio.create_task(asyncio.to_thread(...))` for post-roll side effects (cache invalidation, course-context refresh, achievement check). FastAPI `BackgroundTasks` runs after response close, which never fires for SSE — the stream IS the response. The non-streaming `/process` route still uses `BackgroundTasks`. See `backend/routes/documents.py:579`.
- (4) The orchestrator's structured output is intentionally minimal (`GraphUpdateConfirmation`, two fields) rather than the full `DocumentProcessingResult`. Gemini's structured-output API rejects the "echo all worker outputs" schema as too complex (see `docs/attempts/2026-05-03-orchestrator-schema-complexity.md`). Routes compose the full result deterministically from worker outputs; only `graph_updated` comes from the agent.

## Consequences

- (+) New agents inherit defaults instead of rediscovering them.
- (+) Per-call usage limits make eval harnesses easy and keep agent definitions context-free.
- (+) The legacy-fallback contract (orchestrator failure → `_legacy_upload_pipeline`) survives because routes never assume the agent's output is complete on its own.
- (−) Inline prompts (1) will need extraction once they grow; this is a punt, not a destination. Threshold to revisit: any single prompt past 30 lines, or any prompt shared across two agents.
- (−) The "small orchestrator output schema" trick (4) is Gemini-specific. If ADR 0001's "Gemini-only" stance ever reverses, this convention will need revisiting.
