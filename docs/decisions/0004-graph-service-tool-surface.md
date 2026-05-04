# 0004: Graph service is the next agent-tool migration target

- Status: accepted
- Date: 2026-05-03
- Supersedes: none

## Context

`apply_graph_update` is currently called procedurally from `backend/routes/documents.py` (now via the orchestrator's tool wrapper at `backend/agents/tools/graph.py`, but also as a backstop after the agent run and from the two `/scan-concepts` endpoints) and from `backend/routes/learn.py` in three places. `backend/routes/quiz.py` writes to `graph_nodes` directly without going through `apply_graph_update` — itself a sharp edge documented in `docs/architecture.md` that this consolidation is meant to address. Each call site assembles its own arguments and handles its own errors. The chat tutor and the quiz generator both have ad-hoc augmentation steps (misconceptions concatenated onto the quiz prompt at `routes/quiz.py:82`, course context built into `build_system_prompt` for the tutor) that grew procedurally and are candidates for tool-shaped agents.

## Decision

The next refactor (Week 2 of the broader migration) treats `graph_service` as a unified tool surface. We extract two more wrappers in `backend/agents/tools/graph.py`: one for `read_concepts_for_user`, one for `read_misconceptions_for_course`. Both helpers are new — `graph_service.py` exposes the underlying data through ad-hoc queries today; we add typed read helpers as part of the work. We expose them as tools to a new `quiz_agent` (Prompt cycle next week) and a refactored `chat_tutor_agent` (cycle after). `update_course_context` and `course_context_service` stay procedural — hash-gated aggregation is not LLM work and should not be agentified.

## Consequences

- (+) Quiz generation gets typed misconception input via tool, not string augmentation.
- (+) Chat tutor's prompt building shrinks; tools replace `build_system_prompt` augmentation.
- (+) `services/graph_service.py` stays the truth source; tool wrappers are thin.
- (−) Multiple call sites of `apply_graph_update` (documents.py orchestrator + backstop + two `/scan-concepts`, learn.py x3, plus the quiz path that needs to start using it) will each migrate at different times. Procedural callers stay alive until the agent that replaces them ships.
- (−) Two more agents to maintain, each with their own eval set (template from Prompt 14: `backend/tests/evals/document_classification.py`).
