"""
backend/services/documents/library_api.py

The handler bodies behind the Library's own routes: the guards a Trash action
needs, how a move resolves the course and the folder it is given, and what a
PATCH actually writes.

The route is the HTTP surface only (#118); the reads and writes themselves
live in ``library.py`` and ``folders.py``, and this is the layer between — the
part that decides what a request means.
"""
from __future__ import annotations

import asyncio
import logging

from fastapi import HTTPException

from db.connection import table
from services.academics import require_course_enrollment
from services.documents import folders as folders_service
from services.documents.library import (
    hard_delete_document, restore_document, soft_delete_document,
)

logger = logging.getLogger(__name__)

#: Longest document name accepted, matching what `documents.file_name` holds.
MAX_NAME = 255

#: The categories `documents.category` may hold.
VALID_CATEGORIES = {
    "syllabus", "lecture_notes", "slides", "reading",
    "assignment", "study_guide", "other",
}


async def require_trashed_document(document_id: str, user_id: str) -> None:
    """404 unless the document is this user's AND currently in the Trash.

    The mirror of the route's `_require_owned_document`: Restore and Delete
    Forever are Trash-only, so a live document can never be purged by id and a
    mis-click in the Library cannot skip the 30-day grace.
    """
    docs = await table("documents").aselect(
        "id",
        filters={
            "id": f"eq.{document_id}",
            "user_id": f"eq.{user_id}",
            "deleted_at": "not.is.null",
        },
        limit=1,
    )
    if not docs:
        raise HTTPException(status_code=404, detail="Document not found in Trash.")


async def offering_for_course(user_id: str, course_id: str) -> str:
    """The offering a document moved into ``course_id`` should key on.

    Documents key on the OFFERING (0025) while the HTTP boundary speaks the
    abstract course id (#435), so a move has to resolve one. The student must
    be enrolled — moving a document into a course they do not take would put
    it in a graph they cannot see (#115).

    `require_course_enrollment` is both the gate AND the resolver: it answers
    with the enrolled offering, and a gated write uses THAT rather than
    `resolve_offering(create=True)`, so a move can never mint a catalog
    offering in a term the student is not taking the course in.
    """
    return await asyncio.to_thread(require_course_enrollment, user_id, course_id)


async def validated_folder_id(folder_id: str, user_id: str) -> str:
    """``folder_id``, once it is known to be this user's."""
    if not await folders_service.get_folder(folder_id, user_id):
        raise HTTPException(status_code=404, detail="Folder not found.")
    return folder_id


def validate_fields(body: dict) -> dict:
    """The fields a PATCH can be checked on without knowing who is asking.

    Pure, and called BEFORE the session is resolved: a bad category or a blank
    name is a malformed request whoever sent it, and has always answered 400
    rather than 403. The filing fields need the acting user, so they are
    resolved separately, after the ownership read.
    """
    updates: dict = {}

    category = body.get("category")
    if category is not None:
        if category not in VALID_CATEGORIES:
            raise HTTPException(status_code=400, detail=f"Invalid category '{category}'.")
        updates["category"] = category

    if "file_name" in body:
        name = (body.get("file_name") or "").strip()[:MAX_NAME]
        if not name:
            raise HTTPException(status_code=400, detail="A document needs a name.")
        updates["file_name"] = name

    if not updates and not ("course_id" in body or "folder_id" in body):
        raise HTTPException(status_code=400, detail="No valid fields to update.")
    return updates


async def resolve_filing(user_id: str, body: dict) -> dict:
    """Where a PATCH is moving the document, resolved against the student.

    ``course_id`` and ``folder_id`` accept an explicit ``null`` to mean "No
    Course" / "no folder" — which is why they are read with ``in body`` rather
    than by truthiness. Only the ones present are written, so dragging into a
    folder never disturbs the name.
    """
    updates: dict = {}

    if "course_id" in body:
        course_id = body.get("course_id")
        updates["offering_id"] = (
            await offering_for_course(user_id, course_id) if course_id else None
        )
        # A folder lives inside one course, so moving the document out of that
        # course unfiles it — unless this same call names a folder too.
        if "folder_id" not in body:
            updates["folder_id"] = None

    if "folder_id" in body:
        folder_id = body.get("folder_id")
        updates["folder_id"] = (
            await validated_folder_id(folder_id, user_id) if folder_id else None
        )

    return updates


async def delete(document_id: str, user_id: str, *, hard: bool, owned_check) -> dict:
    """Move a document to the Trash, or — with ``hard`` — delete it forever.

    ``hard`` only ever applies to a document already in the Trash, so the
    Library's own delete can never skip the 30-day grace period. The live
    ownership check is the route's (it is shared with every other handler),
    so it is passed in.
    """
    if hard:
        await require_trashed_document(document_id, user_id)
        await hard_delete_document(document_id, user_id)
        return {"deleted": True, "purged": True}
    await owned_check(document_id, user_id)
    await soft_delete_document(document_id, user_id)
    return {"deleted": True}


async def restore(document_id: str, user_id: str) -> dict:
    """Take a document back out of the Trash and re-index it."""
    await require_trashed_document(document_id, user_id)
    await restore_document(document_id, user_id)
    return {"restored": True}
