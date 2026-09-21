"""Admin view of the document indexing queue (#482).

A failed index used to be a WARNING in a background thread behind a
healthy-looking `documents` row — nothing anyone would see. `GET /unindexed`
lists every live document that has not finished indexing, and
`POST /{document_id}/reindex` forces one back through the shared entry point.

Every endpoint calls `require_admin`. The list reads only the scalar index
columns plus what identifies a document: never `extracted_text`, `summary` or
`concept_notes`, which are encrypted and have no business on an ops list.
"""
from __future__ import annotations

import asyncio

from fastapi import APIRouter, HTTPException, Request

from db.connection import page_all, table
from services.auth_guard import require_admin
from services.document_indexing import (
    FAILED,
    INDEX_MAX_ATTEMPTS,
    INDEXING,
    PARTIAL,
    PENDING,
    index_document,
)

router = APIRouter()

_UNFINISHED = (PENDING, INDEXING, PARTIAL, FAILED)

_LIST_COLUMNS = ",".join((
    "id", "file_name", "category", "offering_id", "created_at",
    "index_status", "index_attempts", "index_error", "index_chunk_count",
    "index_leased_at",
))


@router.get("/unindexed")
def list_unindexed(request: Request) -> dict:
    """Live documents that are not `indexed` (or a designed `skipped`).

    `exhausted` marks a document at its attempt budget: the sweeper will never
    retry it again, so it stays out of retrieval until someone forces it.
    """
    require_admin(request)
    rows = list(page_all(
        table("documents"), _LIST_COLUMNS,
        filters={
            "index_status": f"in.({','.join(_UNFINISHED)})",
            "deleted_at": "is.null",
        },
        order="created_at.desc",
    ))
    for row in rows:
        row["exhausted"] = (row.get("index_attempts") or 0) >= INDEX_MAX_ATTEMPTS
    return {"documents": rows, "count": len(rows), "max_attempts": INDEX_MAX_ATTEMPTS}


@router.post("/{document_id}/reindex")
async def reindex(document_id: str, request: Request) -> dict:
    """Force one document through the indexer now, and report what happened.

    Synchronous on purpose: an operator forcing a single document wants to know
    whether it worked. `force` re-drives any status and resets the attempt
    budget, but never takes a row on a live lease — that answers 409.
    """
    require_admin(request)
    found = await asyncio.to_thread(
        table("documents").select,
        "id", filters={"id": f"eq.{document_id}", "deleted_at": "is.null"}, limit=1,
    )
    if not found:
        raise HTTPException(status_code=404, detail="Document not found")

    outcome = await asyncio.to_thread(index_document, document_id, force=True)
    if outcome.status == INDEXING:
        raise HTTPException(
            status_code=409,
            detail="This document is being indexed right now; try again shortly.",
        )
    return {
        "document_id": document_id,
        "status": outcome.status,
        "chunk_count": outcome.chunk_count,
        "error": outcome.error,
    }
