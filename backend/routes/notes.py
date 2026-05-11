"""HTTP routes for the notetaker.

CRUD lives here; agent-backed actions (summarize, extract concepts, chat,
generate quiz, send to tutor) come in Phase 4 below.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from services.auth_guard import get_session_user_id, require_self
from services.notes_service import (
    create_note,
    delete_note,
    get_note,
    link_concept,
    list_linked_concepts,
    list_notes,
    unlink_concept,
    update_note,
)

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
