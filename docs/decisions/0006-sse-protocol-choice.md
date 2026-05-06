# 0006: SSE protocol — sse-starlette + custom mapper, not VercelAIAdapter

- Status: accepted
- Date: 2026-05-04
- Supersedes: none

## Context

PR #67's research plan (the document upload re-architecture) recommended `pydantic_ai.ui.vercel_ai.VercelAIAdapter.dispatch_request(request, agent=agent)` for streaming. This is the path of least resistance — Pydantic AI ships an adapter that emits Vercel AI's wire protocol, the React frontend can use Vercel's `useChat`-style hooks directly, and there's no custom code to maintain.

We deviated. Streaming runs through `sse-starlette`'s `EventSourceResponse` plus a custom `SaplingEvent` schema and a `map_to_sapling_event(event)` function in `backend/services/agent_events.py` that translates Pydantic AI's event types by class name (not by import). The frontend consumes the stream via a custom `streamSSE` async generator in `frontend/src/lib/sse.ts`.

## Decision

Keep the custom path. Do not adopt `VercelAIAdapter`.

## Consequences

- (+) Stable Sapling-domain events (`progress:classify`, `progress:classified`, `progress:graph_update`, `result:finalize`, `status:done`) survive Pydantic AI version churn. The mapper dispatches by `type(event).__name__`, so an upstream class rename (e.g. `FunctionToolCallEvent` → `ToolCallEvent`) does not break the wire format.
- (+) The frontend isn't coupled to Vercel AI's protocol or hooks. Tomorrow we can swap to a different agent framework or generate events from non-agent code (e.g. legacy fallback) without rewriting the React consumer.
- (+) `streamSSE` is a 90-line generic helper reusable for the chat tutor stream (refactor #4) and any future SSE endpoint. Vitest covers it (9 tests in `frontend/src/lib/sse.test.ts`).
- (−) We hand-roll the wire format. Bugs like the `\r\n\r\n` separator advance mismatch (caught and fixed in `b6f395e`) wouldn't have happened with the adapter.
- (−) Vercel AI's `useChat` integration is unavailable; we wrote `uploadDocumentStream` ourselves. Acceptable because the upload UX is a one-shot stream, not a multi-turn chat — we'd be importing 80% unused surface area.
- (−) When we eventually build the chat tutor (refactor #4), we'll need to reuse this seam rather than getting Vercel's chat abstractions for free.
