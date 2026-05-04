"""Tool wrappers around graph_service for use by Pydantic AI agents.

The functions here adapt graph_service signatures into typed tool
interfaces an LLM can call. They do NOT contain LLM-specific logic —
that stays in graph_service.
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


async def apply_graph_update_tool(
    ctx: RunContext[SaplingDeps],
    update: GraphUpdateInput,
) -> str:
    """Merge concepts into the user's course graph.

    Returns a short summary string for the agent to confirm the
    operation. apply_graph_update is sync, so we run it in a thread
    to avoid blocking the event loop.
    """
    new_nodes = [
        {"concept_name": name, "initial_mastery": 0.0}
        for name in update.concepts
        if name and name.strip()
    ]
    if not new_nodes:
        return "Graph update skipped: no concepts to add."

    await asyncio.to_thread(
        apply_graph_update,
        ctx.deps.user_id,
        {"new_nodes": new_nodes},
        ctx.deps.course_id,
    )
    return f"Graph updated: {len(new_nodes)} concept(s) merged."
