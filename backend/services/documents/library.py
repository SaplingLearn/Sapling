"""
backend/services/documents/library.py

The document library's reads and writes behind GET /user/{id}, DELETE and
PATCH /doc/{id} (#118, moved from routes/documents.py). Async over the ``a*``
seam (#117); the route keeps the session / ownership guards.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

import httpx
from starlette.concurrency import run_in_threadpool

from db.connection import table
from services.academics import offering_course_id
from services.check_item_service import (
    forget_drafting,
    report_withdrawal_failure,
    retire_items_for_documents,
)
from services.document_indexing import PENDING, schedule_document_index
from services.encryption import bind, decrypt_if_present, decrypt_json

logger = logging.getLogger(__name__)


#: Columns the Library reads, as they are once the redesign's migration has
#: run.
_LIBRARY_COLS = (
    "id,user_id,offering_id,folder_id,file_name,category,summary,"
    "concept_notes,page_count,created_at,processed_at,check_items_status"
)

#: What the Library read before it, for the window where the code is deployed
#: and the migration has not run. The two new columns are display-only — a
#: document with no `folder_id` is loose in its course and one with no
#: `page_count` shows an em dash — so losing them is a thinner page, while a
#: 400 would be no page at all.
_LIBRARY_COLS_LEGACY = (
    "id,user_id,offering_id,file_name,category,summary,"
    "concept_notes,created_at,processed_at,check_items_status"
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
        except httpx.StreamError:
            # A streamed body that was never read (or was closed unread) has
            # no text to give; the exception string is still checked below.
            body = ""
    return any(m in body or m in str(exc) for m in _MISSING_COLUMN_MARKERS)


async def _read_documents(
    filters: dict, order: str, extra: str = "",
) -> list[dict[str, Any]]:
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


async def _hydrate(docs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Decrypt the encrypted columns and resolve each row's abstract course.

    The row keys on the OFFERING (0025); the HTTP boundary keeps the abstract
    course_id (#435). Each unique offering_id resolves once, in one threadpool
    hop (offering_course_id is a cached sync read, #117).
    """
    offering_ids: list[str] = list(dict.fromkeys(
        oid for d in docs if isinstance(oid := d.get("offering_id"), str) and oid
    ))
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
        offering_id = d.get("offering_id")
        d["course_id"] = (
            offering_to_course.get(offering_id) if isinstance(offering_id, str) else None
        )
    return docs


async def list_user_documents(user_id: str) -> list[dict]:
    """The user's live documents, newest first, decrypted, each with the
    abstract ``course_id`` its offering belongs to."""
    docs = await _read_documents(
        {"user_id": f"eq.{user_id}", "deleted_at": "is.null"}, "created_at.desc")
    docs = await _hydrate(docs)
    # W8.1c: stamp concept_notes with graph node ids when names match, so
    # the Library can pass conceptIds into libraryNext. One graph_nodes read
    # for the whole list; not persisted on the documents row.
    await _attach_concept_node_ids(user_id, docs)
    return docs


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


def _notes_need_node_ids(docs: list[dict]) -> bool:
    """True when any decrypted note has a name but no node_id yet."""
    for d in docs:
        if not d.get("course_id"):
            continue
        notes = d.get("concept_notes")
        if not isinstance(notes, list):
            continue
        for note in notes:
            if (
                isinstance(note, dict)
                and (note.get("name") or "").strip()
                and not (note.get("node_id") or "").strip()
            ):
                return True
    return False


async def _attach_concept_node_ids(user_id: str, docs: list[dict]) -> None:
    """Mutate each note with ``node_id`` when (course_id, name) hits the graph.

    Dedup matches ``graph_service._normalize_concept`` (case / whitespace).
    Skips the read when nothing needs an id.
    """
    if not _notes_need_node_ids(docs):
        return
    # Imported here so list tests that never need ids stay free of a
    # graph_service import cycle through the module top.
    from services.graph_service import _normalize_concept

    rows = await table("graph_nodes").aselect(
        "id,concept_name,course_id",
        filters={"user_id": f"eq.{user_id}"},
    ) or []
    by_key: dict[tuple[str, str], str] = {}
    for row in rows:
        course_id = row.get("course_id")
        name = row.get("concept_name")
        node_id = row.get("id")
        if course_id and name and node_id:
            by_key[(course_id, _normalize_concept(name))] = node_id
    if not by_key:
        return
    for d in docs:
        course_id = d.get("course_id")
        notes = d.get("concept_notes")
        if not course_id or not isinstance(notes, list):
            continue
        for note in notes:
            if not isinstance(note, dict):
                continue
            name = note.get("name")
            if not name or note.get("node_id"):
                continue
            node_id = by_key.get((course_id, _normalize_concept(name)))
            if node_id:
                note["node_id"] = node_id


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
    # text leave the class pool with it. Never gated on the loop (withdrawal
    # holds under the kill switch, and for a student whose learning_loop flag
    # is off) and never fails the delete — but a failure is reported (Z34),
    # never only logged: an operator re-runs the idempotent withdrawal.
    try:
        await run_in_threadpool(retire_items_for_documents, [document_id])
    except Exception:
        logger.warning("Retiring check items for doc %s failed", document_id, exc_info=True)
        await run_in_threadpool(report_withdrawal_failure, user_id, document_id)


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
    # The delete RETIRED the check items drafted from this document (A23,
    # `retire_items_for_documents` deletes them), so a `done` mark would now
    # claim items that no longer exist. Back to never-drafted: the loop's
    # draft on enable (`claim_undrafted_documents`) drafts it again the next
    # time the student opens a loop session in the course. Never raises.
    await run_in_threadpool(forget_drafting, document_id)
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
