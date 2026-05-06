# 0007: Drop the document orchestrator agent

- Status: accepted
- Date: 2026-05-04
- Supersedes: none (refines 0001)

## Context

PR #67 originally landed with a `document_agent` that wrapped the graph-update step in an LLM-driven Agent. The route called `document_agent.run_stream_events(...)`; the agent had one tool (`apply_graph_update_tool`); the tool merged concept names into the user's course graph.

In practice the agent had zero decisions to make. By the time the orchestrator ran, classification, summary, concepts, and (when applicable) syllabus had all completed. Concept names were already extracted. The orchestrator's job was: "call this one tool with these arguments." We were paying for a Gemini Pro round-trip (~1–2s plus Pro tokens) to invoke a deterministic function.

The agent loop is justified when (a) the LLM chooses *which* tools to call, (b) the LLM iterates with intermediate tool results, or (c) you need retry-on-validation. None applied.

## Decision

Drop `document_agent` and `GraphUpdateConfirmation`. Replace the agent loop in both upload routes with a direct call to a new `apply_concepts_to_graph(user_id, course_id, concept_names) -> int` async function in `backend/agents/tools/graph.py`. The Pydantic AI tool wrapper (`apply_graph_update_tool`) stays — future agents that legitimately need a tool surface can register it.

The streaming `/upload` route emits two new SSE events around the direct call: `progress:graph_update` and `progress:graph_updated`. The user's progress experience is unchanged.

## Consequences

- (+) One fewer Gemini call per upload. Saves ~1–2s wall-clock and the Gemini Pro tokens.
- (+) One fewer failure surface. The orchestrator agent is gone; `UsageLimitExceeded` and `UnexpectedModelBehavior` no longer apply to a step that never had a real loop.
- (+) Cleaner mental model. "Agent" in `backend/agents/` now means "produces a typed output from text" — there's no more "agent that exists only to wrap a function."
- (+) `apply_concepts_to_graph` is callable from anywhere, not just from agent contexts. Future routes (background workers, the legacy fallback) can use the same primitive.
- (−) If a future need arises to make graph-update logic LLM-driven (e.g. "decide which concepts to merge based on existing graph state"), we'd reintroduce an agent — same shape we just removed. The tool wrapper stays in place specifically to make that re-introduction trivial.
- (−) The "agentic upload" framing is now slightly less accurate: workers are agents, the merge step is not. The pipeline is still typed, parallel, and observable; it's just honest about which steps need an LLM.

## Rule going forward

If an agent's job is "call this tool with these arguments and return," it's not an agent. Use a direct function call. Reserve agent loops for steps where the LLM has a real decision.
