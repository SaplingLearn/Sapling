"""Graph-update helpers and Pydantic AI tool wrappers.

Two tools are exposed:
- apply_graph_update_tool  — registers new concepts (new_nodes, initial_mastery 0.0)
- update_mastery_tool      — adjusts mastery on existing concepts (updated_nodes + delta)

Both append their payload to ctx.deps.graph_updates so the route can
persist graph_update_json on the assistant message, enabling end_session
to derive concepts_covered correctly for agent-path chats.
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


class ConceptMasteryUpdate(BaseModel):
    concept_name: str = Field(
        description="Exact name of the concept whose mastery score to change."
    )
    mastery_delta: float = Field(
        description=(
            "Fractional mastery change, −1.0 to +1.0. "
            "Use +0.1 to +0.3 when the student answers correctly; "
            "−0.05 to −0.1 when they reveal a gap or misconception."
        )
    )
    reason: str = Field(
        default="",
        description="Short phrase shown in the mastery-event log (e.g. 'answered correctly').",
    )
    event_type: str = Field(
        default="interaction",
        description="Event category label: 'interaction', 'correction', or 'quiz'.",
    )


class MasteryUpdateInput(BaseModel):
    """Typed input for the update_mastery tool."""

    updates: list[ConceptMasteryUpdate] = Field(
        description=(
            "One entry per concept whose mastery changed this turn. "
            "Only include concepts that already exist in the graph "
            "(or were just added via apply_graph_update_tool)."
        )
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
    To raise or lower mastery on an existing concept, call update_mastery_tool.
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
    ctx.deps.graph_updates.append({"new_nodes": new_nodes})
    return f"Graph updated: {len(new_nodes)} concept(s) merged."


async def update_mastery_tool(
    ctx: RunContext[SaplingDeps],
    update: MasteryUpdateInput,
) -> str:
    """Adjust mastery scores for concepts the student engaged with this turn.

    Positive delta (e.g. +0.15) when they demonstrate understanding;
    negative (e.g. −0.08) when they reveal a gap. Concepts must already
    exist in the graph — call apply_graph_update_tool first if needed.
    """
    updated_nodes = [
        {
            "concept_name": u.concept_name,
            "mastery_delta": u.mastery_delta,
            "reason": u.reason,
            "event_type": u.event_type,
        }
        for u in update.updates
        if u.concept_name and u.concept_name.strip()
    ]
    if not updated_nodes:
        return "Mastery update skipped: no concepts provided."

    changes = await asyncio.to_thread(
        apply_graph_update,
        ctx.deps.user_id,
        {"updated_nodes": updated_nodes},
        ctx.deps.course_id,
    )

    # Only persist concepts that actually produced a change. A concept the
    # model named but that doesn't exist in the graph yields no `changes`
    # and is never written, so it must not leak into graph_update_json (it
    # would over-report concepts_covered in end_session). Rebuild the
    # appended updated_nodes from the concepts that genuinely changed.
    if changes:
        changed_names = {c["concept"] for c in changes}
        persisted_nodes = [
            n for n in updated_nodes if n["concept_name"] in changed_names
        ]
        if persisted_nodes:
            ctx.deps.graph_updates.append({"updated_nodes": persisted_nodes})
        # Surface the real before/after deltas for parity with the legacy path.
        ctx.deps.mastery_changes.extend(changes)
        parts = [f"{c['concept']} {c['before']:.2f}→{c['after']:.2f}" for c in changes]
        return f"Mastery updated: {', '.join(parts)}."
    return (
        f"Mastery update processed ({len(updated_nodes)} concept(s)); "
        "no score change — concept may not exist yet. Call apply_graph_update_tool first."
    )
