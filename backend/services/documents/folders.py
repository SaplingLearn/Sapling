"""
backend/services/documents/folders.py

Library folders: a named box inside a course that holds documents
(20261125062932_library_folders.sql). Reads and writes
behind ``/api/documents/folders``; the route keeps the session / ownership
guards, as everywhere else under ``services/documents``.

``name`` is a PLAINTEXT label the student typed, like ``flashcard_sets.name``
— it is not study content, so nothing here encrypts. ``course_id`` is the
ABSTRACT course (the id the HTTP boundary speaks), or ``None`` for a folder the
student made with no course open.
"""
from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime, timezone

from fastapi import HTTPException

from db.connection import table
from services.academics import require_course_enrollment

logger = logging.getLogger(__name__)

#: One student cannot have more folders than this. Far past any real use; it
#: only stops a scripted client from filling the table.
MAX_FOLDERS = 300

#: Longest folder name accepted. The Library's rename input is narrower than
#: this, so it only bites a non-browser caller.
MAX_NAME = 120

_COLS = "id,user_id,course_id,name,created_at,updated_at"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def clean_name(name: str | None) -> str:
    """A folder name trimmed to what the column accepts, or ``""`` if blank.

    The caller decides what a blank name means — the Library substitutes
    "New Folder" (deduped) rather than refusing, which is what the design does.
    """
    return (name or "").strip()[:MAX_NAME]


async def list_folders(user_id: str) -> list[dict]:
    """Every folder the user has, oldest first (creation order is the order
    the Library shows them in, under each course)."""
    return await table("document_folders").aselect(
        _COLS,
        filters={"user_id": f"eq.{user_id}"},
        order="created_at.asc",
    ) or []


async def count_folders(user_id: str) -> int:
    rows = await table("document_folders").aselect(
        "id", filters={"user_id": f"eq.{user_id}"}
    ) or []
    return len(rows)


async def create_folder(user_id: str, name: str, course_id: str | None) -> dict:
    """Insert a folder and return the row. ``name`` must already be cleaned
    and non-empty (the column has a CHECK)."""
    now = _now_iso()
    row = {
        "id": str(uuid.uuid4()),
        "user_id": user_id,
        "course_id": course_id or None,
        "name": name,
        "created_at": now,
        "updated_at": now,
    }
    inserted = await table("document_folders").ainsert(row)
    return inserted[0] if inserted else row


async def get_folder(folder_id: str, user_id: str) -> dict | None:
    rows = await table("document_folders").aselect(
        _COLS,
        filters={"id": f"eq.{folder_id}", "user_id": f"eq.{user_id}"},
        limit=1,
    ) or []
    return rows[0] if rows else None


async def rename_folder(folder_id: str, user_id: str, name: str) -> dict:
    updated = await table("document_folders").aupdate(
        {"name": name},
        filters={"id": f"eq.{folder_id}", "user_id": f"eq.{user_id}"},
    )
    return updated[0] if updated else {"id": folder_id, "name": name}


async def delete_folder(folder_id: str, user_id: str) -> None:
    """Delete a folder. Its documents are NOT deleted: ``documents.folder_id``
    is ``ON DELETE SET NULL``, so they fall back to loose-in-the-course, which
    is what the Library's toast tells the student."""
    await table("document_folders").adelete(
        filters={"id": f"eq.{folder_id}", "user_id": f"eq.{user_id}"}
    )


# ── the route's handler bodies (#118: a route is the HTTP surface only) ──────


async def create_for_request(
    user_id: str, name: str | None, course_id: str | None,
) -> dict:
    """Make a folder for a POST /folders.

    A blank name is not an error — the Library creates the folder and renames
    it in place, so "no name yet" is its normal first state. The student must
    be enrolled in the course a folder is made in, for the same reason a
    document cannot be filed into a class they do not take (#115).
    """
    if course_id:
        await asyncio.to_thread(require_course_enrollment, user_id, course_id)
    if await count_folders(user_id) >= MAX_FOLDERS:
        raise HTTPException(
            status_code=400, detail=f"Folder limit reached ({MAX_FOLDERS}).")
    return await create_folder(user_id, clean_name(name) or "New Folder", course_id)


async def _require_own_folder(folder_id: str, user_id: str) -> dict:
    folder = await get_folder(folder_id, user_id)
    if not folder:
        raise HTTPException(status_code=404, detail="Folder not found.")
    return folder


async def rename_for_request(folder_id: str, user_id: str, name: str | None) -> dict:
    """Rename a folder for a PATCH /folders/{id}. Unlike creating one, this
    refuses a blank name: the student is renaming something that already has
    one, and emptying it would be a mistake, not a default."""
    await _require_own_folder(folder_id, user_id)
    cleaned = clean_name(name)
    if not cleaned:
        raise HTTPException(status_code=400, detail="A folder needs a name.")
    return await rename_folder(folder_id, user_id, cleaned)


async def delete_for_request(folder_id: str, user_id: str) -> None:
    """Delete a folder for a DELETE /folders/{id}."""
    await _require_own_folder(folder_id, user_id)
    await delete_folder(folder_id, user_id)
