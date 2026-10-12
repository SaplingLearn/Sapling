"""HTTP routes for the editable library summary doc (/api/summary-docs).

Sync `def` handlers throughout, matching routes/documents.py — this
feature extends the upload pipeline that module owns, and
_persist_document (which creates the one summary doc an upload produces)
is itself sync. Phase 2 (ask/keep/undo) is in Task 13.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from services.auth_guard import require_self
from services.summary_docs_service import (
    add_source,
    get_summary_doc,
    list_versions,
    remove_source,
    restore_version,
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
