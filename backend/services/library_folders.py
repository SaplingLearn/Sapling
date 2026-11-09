"""Per-student Library folders (migration 20261108225556_library_folders).

A folder belongs to one student and, optionally, one abstract course. A
document sits in at most one folder via ``documents.folder_id``; documents rows
are already per-student, so membership lives on the row. The cross-row rules
Postgres can't express as an FK live here: the folder and the document must
have the same owner and the same course.
"""
from __future__ import annotations

import os
from datetime import datetime, timezone

from fastapi import HTTPException

from db.connection import table
from services.academics import offering_course_id, user_offering_ids_for_course

MAX_NAME = 120
MAX_FILE_NAME = 255
MAX_MOVE = 200


def _clean_name(raw: str | None, *, limit: int = MAX_NAME) -> str:
    name = (raw or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="Name can't be empty.")
    if len(name) > limit:
        raise HTTPException(status_code=400, detail=f"Name is longer than {limit} characters.")
    return name


def _in(ids: list[str]) -> str:
    quoted = ",".join('"' + i.replace('"', "") + '"' for i in ids)
    return f"in.({quoted})"


def _owned_folder(user_id: str, folder_id: str) -> dict:
    rows = table("library_folders").select(
        "id,user_id,course_id,name,created_at",
        filters={"id": f"eq.{folder_id}", "user_id": f"eq.{user_id}"},
        limit=1,
    )
    if not rows:
        raise HTTPException(status_code=404, detail="Folder not found.")
    return rows[0]


def list_library(user_id: str) -> dict:
    """The student's folders, plus which of their documents sit in one."""
    folders = table("library_folders").select(
        "id,course_id,name,created_at",
        filters={"user_id": f"eq.{user_id}"},
        order="created_at.asc",
    ) or []
    placed = table("documents").select(
        "id,folder_id",
        filters={
            "user_id": f"eq.{user_id}",
            "deleted_at": "is.null",
            "folder_id": "not.is.null",
        },
    ) or []
    return {
        "folders": folders,
        "placements": {r["id"]: r["folder_id"] for r in placed if r.get("folder_id")},
    }


def create_folder(user_id: str, name: str | None, course_id: str | None) -> dict:
    clean = _clean_name(name)
    if course_id:
        # Only under a course the student is enrolled in: the explorer nests
        # folders under the student's own courses.
        if not user_offering_ids_for_course(user_id, course_id):
            raise HTTPException(status_code=404, detail="Course not found.")
    row = {
        "user_id": user_id,
        "course_id": course_id or None,
        "name": clean,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    inserted = table("library_folders").insert(row)
    out = inserted[0] if inserted else row
    return {k: out.get(k) for k in ("id", "course_id", "name", "created_at")}


def rename_folder(user_id: str, folder_id: str, name: str | None) -> dict:
    clean = _clean_name(name)
    folder = _owned_folder(user_id, folder_id)
    table("library_folders").update(
        {"name": clean},
        filters={"id": f"eq.{folder_id}", "user_id": f"eq.{user_id}"},
    )
    return {"id": folder_id, "course_id": folder.get("course_id"), "name": clean,
            "created_at": folder.get("created_at")}


def delete_folder(user_id: str, folder_id: str) -> dict:
    """Delete the folder; its documents stay in their course (FK SET NULL)."""
    _owned_folder(user_id, folder_id)
    table("library_folders").delete(
        filters={"id": f"eq.{folder_id}", "user_id": f"eq.{user_id}"},
    )
    return {"deleted": True}


def move_documents(user_id: str, document_ids: list[str], folder_id: str | None) -> dict:
    """Put documents in a folder (or take them out with ``folder_id=None``).

    Every document must be the caller's, live, and in the folder's course.
    All-or-nothing: one bad id refuses the whole move.
    """
    ids = list(dict.fromkeys(i for i in document_ids if i))
    if not ids:
        raise HTTPException(status_code=400, detail="No documents to move.")
    if len(ids) > MAX_MOVE:
        raise HTTPException(status_code=400, detail=f"Move at most {MAX_MOVE} documents at once.")
    docs = table("documents").select(
        "id,offering_id",
        filters={"id": _in(ids), "user_id": f"eq.{user_id}", "deleted_at": "is.null"},
    ) or []
    if len({d["id"] for d in docs}) != len(ids):
        raise HTTPException(status_code=404, detail="Document not found.")
    if folder_id:
        folder = _owned_folder(user_id, folder_id)
        want = folder.get("course_id")
        cache: dict[str, str | None] = {}
        for d in docs:
            off = d.get("offering_id")
            if off and off not in cache:
                cache[off] = offering_course_id(off)
            if (cache.get(off) if off else None) != want:
                raise HTTPException(
                    status_code=409,
                    detail="A document can only go in a folder in its own course.",
                )
    table("documents").update(
        {"folder_id": folder_id or None},
        filters={"id": _in(ids), "user_id": f"eq.{user_id}"},
    )
    return {"moved": len(ids), "folder_id": folder_id or None}


def rename_document(user_id: str, document_id: str, file_name: str | None) -> dict:
    """Rename a document. The original extension is kept, since it is how the
    Library knows the file type (PDF / DOCX / PPTX)."""
    clean = _clean_name(file_name, limit=MAX_FILE_NAME)
    rows = table("documents").select(
        "id,file_name",
        filters={"id": f"eq.{document_id}", "user_id": f"eq.{user_id}", "deleted_at": "is.null"},
        limit=1,
    )
    if not rows:
        raise HTTPException(status_code=404, detail="Document not found.")
    ext = os.path.splitext(rows[0].get("file_name") or "")[1]
    if ext and not clean.lower().endswith(ext.lower()):
        clean = f"{clean}{ext}"
    table("documents").update(
        {"file_name": clean},
        filters={"id": f"eq.{document_id}", "user_id": f"eq.{user_id}"},
    )
    return {"id": document_id, "file_name": clean}
