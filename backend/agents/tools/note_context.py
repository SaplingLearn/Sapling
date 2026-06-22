"""Read tool for the note-chat agent.

The agent runs with `ctx.deps.session_id` overloaded to carry the
active note_id (the note-chat route sets it on SaplingDeps before
running the agent). `read_active_note` pulls the note body and its
linked concepts so the chat reply stays grounded in what the student
actually wrote.
"""
from __future__ import annotations

from pydantic import BaseModel
from pydantic_ai import RunContext

from agents.deps import SaplingDeps
from services.notes_service import get_note, list_linked_concepts


class LinkedConcept(BaseModel):
    id: str
    concept_name: str
    mastery_tier: str
    mastery_score: float


class NoteContext(BaseModel):
    title: str
    body: str
    tags: list[str]
    linked_concepts: list[LinkedConcept]


async def read_active_note(note_id: str, user_id: str) -> NoteContext:
    note = await get_note(note_id=note_id, user_id=user_id)
    if not note:
        return NoteContext(title="", body="", tags=[], linked_concepts=[])
    concepts_raw = await list_linked_concepts(note_id=note_id, user_id=user_id)
    concepts = [
        LinkedConcept(
            id=c.get("id") or "",
            concept_name=c.get("concept_name") or "",
            mastery_tier=c.get("mastery_tier") or "unexplored",
            mastery_score=float(c.get("mastery_score") or 0.0),
        )
        for c in concepts_raw
    ]
    return NoteContext(
        title=note.get("title") or "",
        body=note.get("body") or "",
        tags=list(note.get("tags") or []),
        linked_concepts=concepts,
    )


async def read_active_note_tool(
    ctx: RunContext[SaplingDeps],
) -> NoteContext:
    """Pydantic AI wrapper.

    `note_id` rides on `ctx.deps.session_id` (the route sets it). The
    LLM never names whose note to read.
    """
    note_id = ctx.deps.session_id
    if not note_id:
        return NoteContext(title="", body="", tags=[], linked_concepts=[])
    return await read_active_note(note_id=note_id, user_id=ctx.deps.user_id)
