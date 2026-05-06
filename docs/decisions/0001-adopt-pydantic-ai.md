# 0001: Adopt Pydantic AI as the agent framework

- Status: accepted
- Date: 2026-05-03
- Supersedes: none

## Context

Today every LLM call in the backend goes through `services/gemini_service.py` as bare `google-genai` calls returning unstructured strings that callers parse downstream. As features grow — document classification, concept extraction, quiz generation, syllabus parsing, tutor chat — the seam is leaking: output parsing, retries, structured output, and tool calling are reimplemented per route. Streaming progress to the client is custom per endpoint. The pattern doesn't scale to where the product is going.

## Decision

Adopt Pydantic AI (`pydantic-ai-slim[google]`) as a thin framework wrapping `google-genai`. New agents live in `backend/agents/`. The existing `services/gemini_service.py` stays as-is during migration; agents are introduced one refactor at a time. Streaming uses `agent.run_stream_events()`. Multi-step flows use agent delegation. Observability uses Logfire. Model selection stays Gemini-only — we are not paying for provider portability we don't need.

## Consequences

- (+) Typed inputs and outputs via Pydantic models — fewer parsing bugs.
- (+) Tool-calling unifies the pattern currently reimplemented in `learn.py` and `quiz.py`.
- (+) `run_stream_events()` gives typed events the frontend can render directly.
- (+) Logfire gives free traces across agents, tools, and LLM calls.
- (−) New dependency to keep current. Pydantic AI is moving fast (issue #2293 on thought-signature handling is open as of writing).
- (−) Two paradigms coexist during migration. `gemini_service.py` is the legacy fallback until refactor #3 ships.
- (−) Free tier is gone for Gemini as of Dec 2025 — billing must be enabled before agents go to prod.
