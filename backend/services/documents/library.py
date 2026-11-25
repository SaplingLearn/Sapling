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
from services.document_indexing import PENDING, schedule_document_index
from services.encryption import bind, decrypt_if_present, decrypt_json

logger = logging.getLogger(__name__)


#: Columns the Library reads, as they are once the redesign's migration has
#: run.
_LIBRARY_COLS = (
    "id,user_id,offering_id,folder_id,file_name,category,summary,"
    "concept_notes,page_count,created_at,processed_at"
)

#: What the Library read before it, for the window where the code is deployed
#: and the migration has not run. The two new columns are display-only — a
#: document with no `folder_id` is loose in its course and one with no
#: `page_count` shows an em dash — so losing them is a thinner page, while a
#: 400 would be no page at all.
_LIBRARY_COLS_LEGACY = (
    "id,user_id,offering_id,file_name,category,summary,"
    "concept_notes,created_at,processed_at"
)

#: The PostgREST wording for "that column does not exist" (the same markers
#: `services/documents/persistence.py` reads on the insert side).
_MISSING_COLUMN_MARKERS = ("PGRST204", "does not exist", "Could not find the")


def _is_missing_column(exc: Exception) -> bool:
    """Does this error say a column is absent, rather than the read failing?

    Reads the RESPONSE BODY, not `str(exc)`: `db/connection.py` raises through
    httpx's `raise_for_status()`, whose message never carries the payload that
    names the column. A guard written against the exception string would never
    fire — exactly how the insert side's first escape hatch shipped dead.
    """
    body = ""
    response = getattr(exc, "response", None)
    if response is not None:
        try:
            body = response.text or ""
        except Exception:
            body = ""
    return any(m in body or m in str(exc) for m in _MISSING_COLUMN_MARKERS)


async def _read_documents(filters: dict, order: str, extra: str = "") -> list[dict]:
    """Read the Library's columns, falling back to the pre-migration set.

    Only a missing column is caught; any other failure is the caller's to
    surface, so a real outage still reads as one.
    """
    try:
        return await table("documents").aselect(
            _LIBRARY_COLS + extra, filters=filters, order=order) or []
    except Exception as exc:
        if not _is_missing_column(exc):
            raise
        logger.warning(
            "documents is missing the Library's new columns; reading without them "
            "until the migration runs", exc_info=True,
        )
        return await table("documents").aselect(
            _LIBRARY_COLS_LEGACY + extra, filters=filters, order=order) or []


async def _hydrate(docs: list[dict]) -> list[dict]:
    """Decrypt the encrypted columns and resolve each row's abstract course.

    The row keys on the OFFERING (0025); the HTTP boundary keeps the abstract
    course_id (#435). Each unique offering_id resolves once, in one threadpool
    hop (offering_course_id is a cached sync read, #117).
    """
    offering_ids = list(dict.fromkeys(d.get("offering_id") for d in docs if d.get("offering_id")))
    offering_to_course = (
        await run_in_threadpool(_courses_for_offerings, offering_ids) if offering_ids else {}
    )
    for d in docs:
        d["summary"] = decrypt_if_present(d.get("summary"), bind=bind("documents", "summary", d))
        notes_raw = d.get("concept_notes")
        if isinstance(notes_raw, str):
            try:
                d["concept_notes"] = decrypt_json(
                    notes_raw, bind=bind("documents", "concept_notes", d))
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


async def list_user_documents(user_id: str) -> list[dict]:
    """The user's live documents, newest first, decrypted, each with the
    abstract ``course_id`` its offering belongs to."""
    docs = await _read_documents(
        {"user_id": f"eq.{user_id}", "deleted_at": "is.null"}, "created_at.desc")
    return await _hydrate(docs)


async def list_trashed_documents(user_id: str) -> list[dict]:
    """The user's soft-deleted documents, most recently deleted first.

    The Trash is a read of the same table: `soft_delete_document` has always
    stamped ``deleted_at`` rather than removing the row, so nothing new is
    stored to make Trash work — only this read, `restore_document` and
    `hard_delete_document` below.
    """
    docs = await _read_documents(
        {"user_id": f"eq.{user_id}", "deleted_at": "not.is.null"},
        "deleted_at.desc", extra=",deleted_at")
    return await _hydrate(docs)


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


async def update_document_row(document_id: str, user_id: str, updates: dict) -> dict:
    """Write validated field updates to an owned document; the updated row."""
    updated = await table("documents").aupdate(
        updates, filters={"id": f"eq.{document_id}", "user_id": f"eq.{user_id}"})
    return updated[0] if updated else {"id": document_id, **updates}


async def restore_document(document_id: str, user_id: str) -> None:
    """Undo a soft delete: clear ``deleted_at`` and re-index.

    The delete WITHDREW the document's chunks (#758) rather than hiding them,
    so clearing the stamp alone would leave a live document that retrieval
    cannot see. The row is therefore put back in the indexing queue — reset to
    ``pending`` with a fresh attempt budget, because its status is still
    whatever the original index left — and the usual entry point schedules the
    work (a job when `jobs_queue` is on, inline otherwise).

    Never raises on the indexing half: the restore itself has happened by
    then, and the lifespan sweeper drains any row left pending.
    """
    await table("documents").aupdate(
        {"deleted_at": None},
        filters={"id": f"eq.{document_id}", "user_id": f"eq.{user_id}"},
    )
    try:
        await table("documents").aupdate(
            {
                "index_status": PENDING,
                "index_attempts": 0,
                "index_leased_at": None,
                "index_error": None,
            },
            filters={"id": f"eq.{document_id}", "user_id": f"eq.{user_id}"},
            prefer_return_minimal=True,
        )
        await run_in_threadpool(schedule_document_index, document_id, user_id)
    except Exception:
        logger.exception(
            "re-indexing document %s after restore failed; the sweeper will retry",
            document_id,
        )


async def hard_delete_document(document_id: str, user_id: str) -> None:
    """Remove a soft-deleted document for good ("Delete Forever" / Empty
    Trash). Only ever called on a row that is already in the Trash — the route
    refuses otherwise, so a mis-click in the Library can never skip the
    30-day grace the Trash gives.

    ``enrollments.syllabus_doc_id`` is ``ON DELETE SET NULL`` and
    ``course_chunks`` cascade, so the row can go.
    """
    await table("documents").adelete(
        filters={
            "id": f"eq.{document_id}",
            "user_id": f"eq.{user_id}",
            "deleted_at": "not.is.null",
        }
    )
