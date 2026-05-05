# Refactor #3 — Chat Tutor: orchestration plan

This folder contains the prompts for migrating `backend/routes/learn.py`'s
chat tutor onto a Pydantic AI `chat_tutor_agent` per ADR 0001's migration
plan and ADR 0005's prioritization. After this ships, `services/gemini_service.py`
gets deleted (it stays alive only as the quiz fallback today).

## Sequencing

Five sub-agents. Run A, B, D in parallel (non-overlapping files); C runs
solo after A+B finish (depends on both); E runs solo after C is on `main`
or when you're ready to wire the frontend.

```
Phase 1 (parallel):
  Sub-agent A   → backend/agents/tools/* (new tools)
  Sub-agent B   → backend/agents/chat_tutor.py (new agent)
  Sub-agent D   → backend/tests/evals/chat_tutor.py (eval set)

Phase 2 (sequential):
  Sub-agent C   → backend/routes/learn.py + tests/test_learn_routes.py

Phase 3 (separate PR — optional / can defer):
  Sub-agent E   → frontend/src/components/screens/Learn.tsx wiring
```

## Branch + ADR

Before dispatching, create a fresh branch:
```bash
git fetch origin && git checkout -b refactor/3-chat-tutor origin/main
```

After Phase 2 lands, write `docs/decisions/0014-refactor-3-chat-tutor-shipped.md`
using the template in `06-adr-template.md`.

## What this refactor delivers

| Before | After |
|---|---|
| `routes/learn.py::build_system_prompt` builds a single ~2000-char string with course context, recent sessions, graph state, and mode-specific guidance. | A `chat_tutor_agent` with three tools the LLM calls only when needed. |
| `services/gemini_service.py::call_gemini_multiturn` makes the chat call. | `chat_tutor_agent.run_stream_events(...)` — typed events, streaming text, tool calls observable in Logfire. |
| Three modes (Socratic, Expository, TeachBack) handled by branching prompt strings. | Mode-aware system prompt selected per call; agent shape unchanged across modes. |
| Multi-turn history reconstructed by the route from `messages` table on every call. | Same history, but passed to `chat_tutor_agent.run(message_history=...)` — Pydantic AI's typed `ModelMessage` shape. |
| Mastery + concept updates done procedurally after every chat. | Done via `apply_concepts_to_graph_tool` (already exists from refactor #1). |

## Constraints (apply to every sub-agent)

- **Wire format unchanged**: the `messages` table shape and the SSE event names the frontend already consumes are the contract. Don't introduce a new event name without updating the frontend in lockstep (Sub-agent E).
- **Encryption boundary preserved**: `messages.content` is encrypted at rest per CLAUDE.md. Use `encrypt_if_present` at insert and `decrypt_if_present` at read, same as today's route.
- **Legacy fallback preserved per ADR 0001**: rename the existing chat function to `_legacy_chat` and keep it callable. The new path falls back to it on `UsageLimitExceeded` / `UnexpectedModelBehavior` / any other exception. Don't delete `services/gemini_service.py` in this refactor — that's a separate small PR after #3 ships.
- **`require_self`** stays. `SaplingDeps.request_id` adopts the middleware ID via `current_request_id()` (same pattern as refactor #1 and #2).
- **`use_shared_context` toggle**: when False, the agent must NOT call `read_misconceptions_for_course` or any other class-aggregate tool. Today's route gates context inclusion at the prompt level; the new agent gates it at tool registration / prompt instruction.
- **`model_pref` toggle**: already on the body via main commit `90ba796`. Mirror PR #71's `_resolve_model_pref` pattern from `routes/quiz.py` — symmetric across both routes.

## What's already in place from prior refactors

- `agents/_providers.py::model_for(task)` — add `"chat_tutor"` to the task list.
- `SaplingDeps` — same shape, threads through.
- Tool wrapper pattern — `agents/tools/graph.py` and `agents/tools/graph_read.py` are templates.
- Eval replay infra — `tests/evals/_replay.py::run_with_cassette` is reusable.
- Logfire scrubber + prompt versioning — automatic.
- `services/agent_events.py::SaplingEvent` + `map_to_sapling_event` — reuse for the streaming chat events.
- Frontend SSE consumer — `frontend/src/lib/sse.ts` is generic.

## Read before dispatching

- `docs/decisions/0001-adopt-pydantic-ai.md` — fallback contract.
- `docs/decisions/0003-implementation-conventions.md` — small output schemas, per-call usage_limits.
- `docs/decisions/0005-refactor-2-quiz-generation.md` — explicitly defers chat tutor as #3.
- `docs/decisions/0013-refactor-2-quiz-shipped.md` — addenda capture every gotcha that hit during refactor #2; expect similar shape here.
- `backend/routes/learn.py` — current route. `build_system_prompt` is at ~line 152.
- `backend/services/gemini_service.py::call_gemini_multiturn` — what the legacy path uses.
