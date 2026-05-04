"""Graph-update helpers and a Pydantic AI tool wrapper.

The core merge logic lives in `apply_concepts_to_graph` — a plain async
function callable from routes directly. `apply_graph_update_tool` is a
thin Pydantic AI wrapper around it for future agents that need a tool
to register on an `Agent`. Neither contains LLM-specific logic; that
stays in `services.graph_service`.
"""

from __future__ import annotations

import asyncio

from pydantic import BaseModel, Field
from pydantic_ai import RunContext

from agents.deps import SaplingDeps
from services.graph_service import apply_graph_update


class GraphUpdateInput(BaseModel):
    """Typed input shape for the apply_graph_update tool."""

    concepts: list[str] = Field(
        description="Concept names to merge into the user's knowledge "
                    "graph for the current course."
    )


async def apply_concepts_to_graph(
    user_id: str,
    course_id: str | None,
    concept_names: list[str],
) -> int:
    """Merge concepts into the user's course graph. Returns the count merged.

    Pure async — no Pydantic AI dependency, callable from routes directly.
    `apply_graph_update` is sync, so we run it in a thread to avoid
    blocking the event loop.
    """
    new_nodes = [
        {"concept_name": name, "initial_mastery": 0.0}
        for name in concept_names
        if name and name.strip()
    ]
    if not new_nodes:
        return 0
    await asyncio.to_thread(
        apply_graph_update,
        user_id,
        {"new_nodes": new_nodes},
        course_id,
    )
    return len(new_nodes)


async def apply_graph_update_tool(
    ctx: RunContext[SaplingDeps],
    update: GraphUpdateInput,
) -> str:
    """Pydantic AI tool wrapper around apply_concepts_to_graph.

    Returns a short summary string for the agent to confirm the operation.
    """
    count = await apply_concepts_to_graph(
        ctx.deps.user_id, ctx.deps.course_id, update.concepts,
    )
    if count == 0:
        return "Graph update skipped: no concepts to add."
    return f"Graph updated: {count} concept(s) merged."
