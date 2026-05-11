"""HTTP routes for the notetaker.

CRUD lives here; agent-backed actions (summarize, extract concepts, chat,
generate quiz, send to tutor) come in Phase 4 below.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from agents.deps import SaplingDeps
from agents.note_concepts import note_concepts_agent
from agents.note_summary import note_summary_agent
from agents.tools.graph import apply_concepts_to_graph
from db.connection import table
from services.auth_guard import get_session_user_id, require_self
from services.notes_service import (
    create_note,
    delete_note,
    get_note,
    link_concept,
    list_linked_concepts,
    list_notes,
    save_summary,
    unlink_concept,
    update_note,
)
from services.request_context import current_request_id

router = APIRouter()


class CreateNoteBody(BaseModel):
    user_id: str
    course_id: str
    title: str = ""
    body: str = ""
    tags: list[str] = Field(default_factory=list)


class UpdateNoteBody(BaseModel):
    user_id: str
    title: str | None = None
    body: str | None = None
    tags: list[str] | None = None
    course_id: str | None = None


@router.get("/user/{user_id}")
async def list_user_notes(
    user_id: str,
    request: Request,
    course_id: str | None = None,
):
    require_self(user_id, request)
    notes = await list_notes(user_id=user_id, course_id=course_id)
    return {"notes": notes}


@router.post("")
async def create(body: CreateNoteBody, request: Request):
    require_self(body.user_id, request)
    note = await create_note(
        user_id=body.user_id,
        course_id=body.course_id,
        title=body.title,
        body=body.body,
        tags=body.tags,
    )
    return note


@router.get("/{note_id}")
async def read(note_id: str, request: Request, user_id: str):
    require_self(user_id, request)
    note = await get_note(note_id=note_id, user_id=user_id)
    if not note:
        raise HTTPException(status_code=404, detail="Note not found.")
    return note


@router.patch("/{note_id}")
async def patch(note_id: str, body: UpdateNoteBody, request: Request):
    require_self(body.user_id, request)
    patch_dict: dict = {}
    if body.title is not None:
        patch_dict["title"] = body.title
    if body.body is not None:
        patch_dict["body"] = body.body
    if body.tags is not None:
        patch_dict["tags"] = body.tags
    if body.course_id is not None:
        patch_dict["course_id"] = body.course_id
    if not patch_dict:
        raise HTTPException(status_code=400, detail="No fields to update.")
    updated = await update_note(
        note_id=note_id, user_id=body.user_id, patch=patch_dict
    )
    if not updated:
        raise HTTPException(status_code=404, detail="Note not found.")
    return updated


@router.delete("/{note_id}")
async def remove(note_id: str, request: Request, user_id: str):
    require_self(user_id, request)
    await delete_note(note_id=note_id, user_id=user_id)
    return {"deleted": True}


class LinkConceptBody(BaseModel):
    user_id: str
    concept_node_id: str


@router.get("/{note_id}/concepts")
async def list_concepts(note_id: str, request: Request, user_id: str):
    require_self(user_id, request)
    concepts = await list_linked_concepts(note_id=note_id, user_id=user_id)
    return {"concepts": concepts}


@router.post("/{note_id}/concepts")
async def link_concept_route(
    note_id: str, body: LinkConceptBody, request: Request
):
    require_self(body.user_id, request)
    ok = await link_concept(
        note_id=note_id,
        user_id=body.user_id,
        concept_node_id=body.concept_node_id,
    )
    if not ok:
        raise HTTPException(status_code=404, detail="Note not found.")
    return {"linked": True}


@router.delete("/{note_id}/concepts/{concept_node_id}")
async def unlink_concept_route(
    note_id: str,
    concept_node_id: str,
    request: Request,
    user_id: str,
):
    require_self(user_id, request)
    ok = await unlink_concept(
        note_id=note_id, user_id=user_id, concept_node_id=concept_node_id
    )
    if not ok:
        raise HTTPException(status_code=404, detail="Note not found.")
    return {"unlinked": True}


class AgentActionBody(BaseModel):
    user_id: str


async def _lookup_concept_nodes_by_name(
    user_id: str, course_id: str | None, names: list[str]
) -> list[dict]:
    """Find graph_nodes for the freshly-merged concepts so we can link
    them to the note. Case-sensitive equality match — apply_graph_update
    normalizes on insert, so the names we get back from the agent should
    round-trip; if a node is missing here it means the merge skipped a
    duplicate, which is fine to silently drop."""
    import asyncio as _asyncio
    if not names:
        return []
    in_clause = "in.(" + ",".join(names) + ")"
    filters = {"user_id": f"eq.{user_id}", "concept_name": in_clause}
    if course_id:
        filters["course_id"] = f"eq.{course_id}"

    def _fetch() -> list[dict]:
        return table("graph_nodes").select(
            "id,concept_name", filters=filters
        ) or []
    return await _asyncio.to_thread(_fetch)


def _deps_for(user_id: str, course_id: str | None, note_id: str | None) -> SaplingDeps:
    from db.connection import _client  # type: ignore  # only for opaque pass-through
    return SaplingDeps(
        user_id=user_id,
        course_id=course_id,
        supabase=_client,
        request_id=current_request_id() or "",
        session_id=note_id,
    )


@router.post("/{note_id}/summarize")
async def summarize(note_id: str, body: AgentActionBody, request: Request):
    require_self(body.user_id, request)
    note = await get_note(note_id=note_id, user_id=body.user_id)
    if not note:
        raise HTTPException(status_code=404, detail="Note not found.")
    user_prompt = (
        f"Title: {note.get('title') or '(untitled)'}\n\n"
        f"Body:\n{note.get('body') or '(empty)'}"
    )
    deps = _deps_for(body.user_id, note.get("course_id"), note_id)
    result = await note_summary_agent.run(user_prompt, deps=deps)
    summary_text = result.output.summary
    await save_summary(note_id=note_id, user_id=body.user_id, summary=summary_text)
    return {"summary": summary_text}


@router.post("/{note_id}/extract-concepts")
async def extract_concepts(
    note_id: str, body: AgentActionBody, request: Request
):
    require_self(body.user_id, request)
    note = await get_note(note_id=note_id, user_id=body.user_id)
    if not note:
        raise HTTPException(status_code=404, detail="Note not found.")
    user_prompt = (
        f"Title: {note.get('title') or '(untitled)'}\n\n"
        f"Body:\n{note.get('body') or '(empty)'}"
    )
    deps = _deps_for(body.user_id, note.get("course_id"), note_id)
    result = await note_concepts_agent.run(user_prompt, deps=deps)
    names = [n.strip() for n in (result.output.concepts or []) if n and n.strip()]
    course_id = note.get("course_id")
    await apply_concepts_to_graph(
        user_id=body.user_id, course_id=course_id, concept_names=names
    )
    nodes = await _lookup_concept_nodes_by_name(
        user_id=body.user_id, course_id=course_id, names=names
    )
    for n in nodes:
        await link_concept(
            note_id=note_id, user_id=body.user_id,
            concept_node_id=n["id"],
        )
    return {"concepts": names, "linked": len(nodes)}
