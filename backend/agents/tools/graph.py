"""Graph-update helpers and Pydantic AI tool wrappers.

One tool is exposed:
- apply_graph_update_tool  — registers new concepts (new_nodes, initial_mastery 0.0)

It appends its payload to ctx.deps.graph_updates so the route can persist
graph_update_json on the assistant message, enabling end_session to derive
concepts_covered correctly for agent-path chats.

PKG-14b (spec §11.2): the legacy tutor's mastery-write tool is gone. After
the cutover only graded evidence through `apply_graph_update` moves a mastery
score (spec §1, §5); the legacy tutor — the kill-switch path — records none.
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
    """Register new concepts in the student's knowledge graph.

    Call this when a new topic comes up that isn't already tracked.
    """
    new_nodes = [
        {"concept_name": name.strip(), "initial_mastery": 0.0}
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
    ctx.deps.graph_updates.append({"new_nodes": new_nodes})
    return f"Graph updated: {len(new_nodes)} concept(s) merged."
