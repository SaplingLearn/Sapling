"""
backend/services/documents/blank.py

"New Document": an empty library document for the student to write in.

Every other row in the Library is an uploaded file the pipeline read. This one
is the student's own page — no file, no extracted text, nothing to summarize —
which is why it is created here rather than through the upload path, and why
it is born with a terminal index status.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from db.connection import table
from services.document_indexing import SKIPPED
from services.documents import library_api

#: Longest name accepted, matching what `documents.file_name` holds.
MAX_NAME = 255

#: What an unnamed one saves as. The Library drops the new row straight into
#: rename-in-place, so a name is optional; the client dedupes a second one to
#: "New Document 2", the same rule as folders.
DEFAULT_NAME = "New Document"


async def create_blank_document(
    user_id: str,
    *,
    file_name: str | None = None,
    course_id: str | None = None,
    offering_id: str | None = None,
    folder_id: str | None = None,
) -> dict:
    """Insert the row and return it as the HTTP boundary speaks it.

    `index_status` is terminal (`skipped`) on purpose: there is no text to
    index, and a `pending` row with nothing in it would be claimed by the
    sweeper over and over until it exhausted its attempt budget.

    The caller resolves `offering_id` (documents key on the offering, 0025) and
    validates `folder_id`; this writes what it is given.
    """
    now = datetime.now(timezone.utc).isoformat()
    row: dict = {
        "id": str(uuid.uuid4()),
        "user_id": user_id,
        "offering_id": offering_id,
        "file_name": (file_name or "").strip()[:MAX_NAME] or DEFAULT_NAME,
        "category": "other",
        "summary": None,
        "concept_notes": None,
        "index_status": SKIPPED,
        "index_attempts": 0,
        "created_at": now,
        "processed_at": now,
    }
    if folder_id:
        row["folder_id"] = folder_id

    inserted = await table("documents").ainsert(row)
    created = dict(inserted[0] if inserted else row)
    # The HTTP boundary keeps the abstract course id (#435), not the offering.
    created["course_id"] = course_id
    created.pop("offering_id", None)
    return created


async def create_for_request(user_id: str, body: dict) -> dict:
    """Make a blank document for a POST /blank.

    It inherits the scope the student is standing in: the Library sends the
    open course and folder, which are resolved and checked the same way a move
    resolves them.
    """
    course_id = body.get("course_id") or None
    folder_id = body.get("folder_id") or None
    return await create_blank_document(
        user_id,
        file_name=body.get("file_name"),
        course_id=course_id,
        offering_id=(
            await library_api.offering_for_course(user_id, course_id) if course_id else None
        ),
        folder_id=(
            await library_api.validated_folder_id(folder_id, user_id) if folder_id else None
        ),
    )
