"""
backend/services/documents/library.py

The document library's reads and writes behind GET /user/{id}, DELETE and
PATCH /doc/{id} (#118, moved from routes/documents.py). Async over the ``a*``
seam (#117); the route keeps the session / ownership guards.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from starlette.concurrency import run_in_threadpool

from db.connection import table
from services.academics import offering_course_id
from services.check_item_service import retire_items_for_documents
from services.encryption import decrypt_if_present, decrypt_json

logger = logging.getLogger(__name__)


async def list_user_documents(user_id: str) -> list[dict]:
    """The user's live documents, newest first, decrypted, each with the
    abstract ``course_id`` its offering belongs to."""
    docs = await table("documents").aselect(
        "id,user_id,offering_id,file_name,category,summary,concept_notes,created_at,processed_at",
        filters={"user_id": f"eq.{user_id}", "deleted_at": "is.null"},
        order="created_at.desc",
    ) or []
    # The row keys on the OFFERING (0025); the HTTP boundary keeps the
    # abstract course_id (#435). Each unique offering_id resolves once, in one
    # threadpool hop (offering_course_id is a cached sync read, #117).
    offering_ids = list(dict.fromkeys(d.get("offering_id") for d in docs if d.get("offering_id")))
    offering_to_course = (
        await run_in_threadpool(_courses_for_offerings, offering_ids) if offering_ids else {}
    )
    for d in docs:
        d["summary"] = decrypt_if_present(d.get("summary"))
        notes_raw = d.get("concept_notes")
        if isinstance(notes_raw, str):
            try:
                d["concept_notes"] = decrypt_json(notes_raw)
            except Exception:
                # decrypt_json re-raises when both decrypt AND plaintext
                # parse fail (a genuinely corrupted row) — degrade that one
                # row instead of 500ing the whole list (matches
                # _existing_doc_by_request_id and scan_document_concepts).
                logger.warning(
                    "concept_notes decrypt failed for document %s; degrading to []",
                    d.get("id"),
                )
                d["concept_notes"] = []
        d["course_id"] = offering_to_course.get(d.get("offering_id"))
    return docs


def _courses_for_offerings(offering_ids: list[str]) -> dict[str, str | None]:
    """offering id -> abstract course id, one resolve per offering."""
    return {off_id: offering_course_id(off_id) for off_id in offering_ids}


async def soft_delete_document(document_id: str, user_id: str) -> None:
    """Soft-delete an owned document and withdraw its chunks (#758)."""
    # Soft delete (0025): stamp deleted_at; reads filter it out. The
    # enrollments.syllabus_doc_id FK (ON DELETE SET NULL) stays intact.
    await table("documents").aupdate(
        {"deleted_at": datetime.now(timezone.utc).isoformat()},
        filters={"id": f"eq.{document_id}", "user_id": f"eq.{user_id}"},
    )
    # #758: the stamp alone left every chunk the document produced — private
    # ones included — in retrieval. Withdraw them now, after the stamp, so an
    # index finishing concurrently sees the deletion (document_indexing
    # re-checks). Never raises; retrieval refuses a chunk whose every source
    # document is deleted, which covers a withdrawal that fails part-way.
    from services.chunk_visibility import withdraw_document_chunks

    await run_in_threadpool(withdraw_document_chunks, document_id, user_id)
    # Learning loop PKG-04 (A23): check items drafted from this document's
    # text leave the class pool with it. Never gated on LEARNING_LOOP_ENABLED
    # (withdrawal holds under the kill switch too) and never fails the delete.
    try:
        await run_in_threadpool(retire_items_for_documents, [document_id])
    except Exception:
        logger.warning("Retiring check items for doc %s failed", document_id, exc_info=True)


async def update_document_row(document_id: str, user_id: str, updates: dict) -> dict:
    """Write validated field updates to an owned document; the updated row."""
    updated = await table("documents").aupdate(
        updates, filters={"id": f"eq.{document_id}", "user_id": f"eq.{user_id}"})
    return updated[0] if updated else {"id": document_id, **updates}
