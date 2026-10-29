"""HTTP routes for the editable library summary doc (/api/summary-docs).

Sync `def` handlers throughout, matching routes/documents.py — this
feature extends the upload pipeline that module owns, and
_persist_document (which creates the one summary doc an upload produces)
is itself sync. That includes the ask/keep/undo suggestion-review
endpoints below, even though create_suggestion's docstring warns an
`async def` caller to wrap it in `asyncio.to_thread(...)` — FastAPI runs
sync handlers in a worker thread with no event loop already running, so
`run_agent_sync`'s internal `asyncio.run()` is safe to call directly here.
"""
from __future__ import annotations

import base64

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from services.auth_guard import require_self
from services.summary_docs_service import (
    add_source,
    create_suggestion,
    get_summary_doc,
    keep_suggestion,
    list_versions,
    remove_source,
    restore_version,
    undo_suggestion,
    update_content,
)

router = APIRouter()


@router.get("/{summary_doc_id}")
def get_doc(summary_doc_id: str, request: Request, user_id: str):
    require_self(user_id, request)
    doc = get_summary_doc(summary_doc_id, user_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="Summary doc not found.")
    return doc


class UpdateContentBody(BaseModel):
    user_id: str
    content: dict


@router.patch("/{summary_doc_id}")
def patch_content(summary_doc_id: str, body: UpdateContentBody, request: Request):
    require_self(body.user_id, request)
    doc = update_content(summary_doc_id, body.user_id, body.content)
    if doc is None:
        raise HTTPException(status_code=404, detail="Summary doc not found.")
    return doc


class AddSourceBody(BaseModel):
    user_id: str
    document_id: str


@router.post("/{summary_doc_id}/sources")
def post_source(summary_doc_id: str, body: AddSourceBody, request: Request):
    require_self(body.user_id, request)
    doc = add_source(summary_doc_id, body.user_id, body.document_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="Summary doc not found.")
    return doc


@router.delete("/{summary_doc_id}/sources/{document_id}")
def delete_source(summary_doc_id: str, document_id: str, request: Request, user_id: str):
    require_self(user_id, request)
    result = remove_source(summary_doc_id, user_id, document_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Summary doc not found.")
    if result == "primary":
        raise HTTPException(
            status_code=400,
            detail="Can't remove the document this summary was created from.",
        )
    return result


@router.get("/{summary_doc_id}/versions")
def get_versions(summary_doc_id: str, request: Request, user_id: str):
    require_self(user_id, request)
    versions = list_versions(summary_doc_id, user_id)
    if versions is None:
        raise HTTPException(status_code=404, detail="Summary doc not found.")
    return {"versions": versions}


class UserIdBody(BaseModel):
    user_id: str


@router.post("/{summary_doc_id}/versions/{version_id}/restore")
def post_restore(summary_doc_id: str, version_id: str, body: UserIdBody, request: Request):
    require_self(body.user_id, request)
    doc = restore_version(summary_doc_id, body.user_id, version_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="Summary doc or version not found.")
    return doc


class AskBody(BaseModel):
    user_id: str
    instruction: str
    anchor_from: int | None = None
    anchor_to: int | None = None
    original_text: str | None = None
    allow_surrounding_edits: bool = False
    reference_text: str | None = None
    reference_image_base64: str | None = None


@router.post("/{summary_doc_id}/ask")
def post_ask(summary_doc_id: str, body: AskBody, request: Request):
    require_self(body.user_id, request)
    reference_image_bytes = (
        base64.b64decode(body.reference_image_base64)
        if body.reference_image_base64
        else None
    )
    suggestion = create_suggestion(
        summary_doc_id, body.user_id,
        anchor_from=body.anchor_from, anchor_to=body.anchor_to,
        instruction=body.instruction, original_text=body.original_text,
        allow_surrounding_edits=body.allow_surrounding_edits,
        reference_text=body.reference_text,
        reference_image_bytes=reference_image_bytes,
    )
    if suggestion is None:
        raise HTTPException(status_code=404, detail="Summary doc not found.")
    return suggestion


class KeepSuggestionBody(BaseModel):
    user_id: str
    content: dict


@router.post("/{summary_doc_id}/suggestions/{suggestion_id}/keep")
def post_keep(summary_doc_id: str, suggestion_id: str, body: KeepSuggestionBody, request: Request):
    require_self(body.user_id, request)
    doc = keep_suggestion(summary_doc_id, body.user_id, suggestion_id, body.content)
    if doc is None:
        raise HTTPException(status_code=404, detail="Suggestion not found or already resolved.")
    return doc


@router.post("/{summary_doc_id}/suggestions/{suggestion_id}/undo")
def post_undo(summary_doc_id: str, suggestion_id: str, body: UserIdBody, request: Request):
    require_self(body.user_id, request)
    ok = undo_suggestion(summary_doc_id, body.user_id, suggestion_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Suggestion not found or already resolved.")
    return {"undone": True}
