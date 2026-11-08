"""HTTP routes for Library folders and document organisation.

Mounted at ``/api/library``. Every route acts on the session user's own rows
(the identity comes from the session, never from the request body).
"""
from __future__ import annotations

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from services.auth_guard import get_session_user_id
from services import library_folders as svc

router = APIRouter()


class CreateFolderBody(BaseModel):
    name: str = ""
    course_id: str | None = None


class RenameFolderBody(BaseModel):
    name: str = ""


class MoveDocumentsBody(BaseModel):
    document_ids: list[str] = Field(default_factory=list)
    folder_id: str | None = None


class RenameDocumentBody(BaseModel):
    file_name: str = ""


@router.get("/folders")
def list_folders(request: Request):
    return svc.list_library(get_session_user_id(request))


@router.post("/folders")
def create_folder(body: CreateFolderBody, request: Request):
    return svc.create_folder(get_session_user_id(request), body.name, body.course_id)


@router.patch("/folders/{folder_id}")
def rename_folder(folder_id: str, body: RenameFolderBody, request: Request):
    return svc.rename_folder(get_session_user_id(request), folder_id, body.name)


@router.delete("/folders/{folder_id}")
def delete_folder(folder_id: str, request: Request):
    return svc.delete_folder(get_session_user_id(request), folder_id)


@router.put("/documents/folder")
def move_documents(body: MoveDocumentsBody, request: Request):
    return svc.move_documents(get_session_user_id(request), body.document_ids, body.folder_id)


@router.patch("/documents/{document_id}")
def rename_document(document_id: str, body: RenameDocumentBody, request: Request):
    return svc.rename_document(get_session_user_id(request), document_id, body.file_name)
