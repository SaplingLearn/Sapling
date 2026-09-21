"""Drains the document indexing queue (#482).

`documents.index_status` is the work queue; this is what empties it. A queue
nothing drains is the failure #482 is about in a new form —
`scripts/backfill_document_chunks.py` existed for months and was invoked by
nothing — so the sweeper is ON by default in real model mode. Defaulting it
off would repeat what happened to DBOS, which ADR 0011 leaves off in every
deployed environment.

Each pass claims documents through `claim_documents_for_indexing` — an atomic
`UPDATE ... RETURNING` over `SKIP LOCKED`, so two instances never drive the
same document — and re-drives each through the shared entry point,
`services.document_indexing.index_document`. The claim spends the attempt, so
a document that keeps crashing the worker stops at INDEX_MAX_ATTEMPTS.

It claims ONE document at a time, up to BATCH_SIZE per pass. Claiming the
whole batch at once started every lease together and then indexed the
documents in turn, so a slow batch could outlive the lease on its last ones —
letting another instance, or an admin force, claim them mid-queue and spend a
second attempt on a healthy document.
"""
from __future__ import annotations

import asyncio
import contextlib
import logging
import os

from agents._providers import model_mode
from db.connection import rpc
from services.document_indexing import (
    INDEX_LEASE_SECONDS,
    INDEX_MAX_ATTEMPTS,
    index_document,
)

logger = logging.getLogger(__name__)

SWEEP_INTERVAL_SECONDS = int(os.getenv("INDEX_SWEEP_INTERVAL_SECONDS", "300"))
#: Most documents one pass re-drives. Each is claimed only when its turn comes.
BATCH_SIZE = int(os.getenv("INDEX_SWEEP_BATCH", "10"))

_OFF = frozenset({"false", "0", "off", "no"})

_task: asyncio.Task | None = None


def sweeper_enabled() -> bool:
    """On unless switched off, and only in real model mode.

    Outside real mode (#439, every E2E run) there is nothing to embed with, so
    a sweep could only mark rows `skipped`; the upload's own inline attempt
    already does that. INDEX_SWEEPER_ENABLED is the kill switch.
    """
    if os.getenv("INDEX_SWEEPER_ENABLED", "true").strip().lower() in _OFF:
        return False
    return model_mode() == "real"


def sweep_once() -> int:
    """Re-drive up to BATCH_SIZE unfinished documents. Returns how many.

    Synchronous — PostgREST calls are — so the loop runs it in a thread, the
    same reason the upload post-roll does. Never raises: a failed claim (the
    RPC does not exist until the migration runs) ends the pass with a warning,
    and one bad document never costs the rest.
    """
    if not sweeper_enabled():
        return 0
    driven = 0
    for _ in range(BATCH_SIZE):
        try:
            claimed = rpc(
                "claim_documents_for_indexing",
                {
                    "max_attempts": INDEX_MAX_ATTEMPTS,
                    "lease_seconds": INDEX_LEASE_SECONDS,
                    # One per claim: the lease must start when the work does.
                    "batch_size": 1,
                },
            )
        except Exception:
            logger.warning("[RAG] index sweep could not claim a document", exc_info=True)
            break
        if not claimed:
            break
        doc_id = claimed[0]["id"]
        try:
            index_document(doc_id, claimed=True)
            driven += 1
        except Exception:
            # The row stays 'indexing' until its lease expires, then a later
            # sweep takes it again with the attempt already spent.
            logger.exception("[RAG] index sweep could not re-drive doc %s", doc_id)
    if driven:
        logger.info("[RAG] index sweep re-drove %d document(s)", driven)
    return driven


async def _loop() -> None:
    # Sleep FIRST: a deploy restarts every instance at once, and the uploads in
    # flight at that moment are still making their own inline attempts.
    while True:
        await asyncio.sleep(SWEEP_INTERVAL_SECONDS)
        try:
            await asyncio.to_thread(sweep_once)
        except Exception:
            # sweep_once does not raise by contract; this is the backstop that
            # keeps one surprise from ending recovery for the process's life.
            logger.exception("[RAG] index sweep raised; the loop continues")


def start_sweeper() -> None:
    """Start the loop on the running event loop. Called from the app lifespan."""
    global _task
    if not sweeper_enabled():
        logger.info("[RAG] index sweeper not started (disabled, or not real model mode)")
        return
    if _task is None or _task.done():
        _task = asyncio.get_running_loop().create_task(_loop(), name="index-sweeper")
        logger.info(
            "[RAG] index sweeper started (every %ss, batch %d)",
            SWEEP_INTERVAL_SECONDS, BATCH_SIZE,
        )


async def stop_sweeper() -> None:
    """Cancel the loop. Safe when it never started."""
    global _task
    task, _task = _task, None
    if task is None:
        return
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task
