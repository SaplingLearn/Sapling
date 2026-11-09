"""Drains the document indexing queue (#482).

`documents.index_status` is the work queue; this is what empties it. A queue
nothing drains is the failure #482 is about in a new form —
`scripts/backfill_document_chunks.py` existed for months and was invoked by
nothing — so the sweeper is ON by default in production in real model mode.
Defaulting it off there would repeat what happened to DBOS, which ADR 0011
leaves off in every deployed environment. Non-production environments default
it off so they can sleep (see `sweeper_enabled`).

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
import threading

from agents._providers import model_mode
from db.connection import rpc
from services.document_indexing import (
    EMBEDDINGS_UNAVAILABLE,
    INDEX_LEASE_SECONDS,
    INDEX_MAX_ATTEMPTS,
    index_document,
)
from services.rag_service import embedding_blocked

logger = logging.getLogger(__name__)

SWEEP_INTERVAL_SECONDS = int(os.getenv("INDEX_SWEEP_INTERVAL_SECONDS", "300"))
#: Most documents one pass re-drives. Each is claimed only when its turn comes.
BATCH_SIZE = int(os.getenv("INDEX_SWEEP_BATCH", "10"))

_OFF = frozenset({"false", "0", "off", "no"})

_task: asyncio.Task | None = None

#: The running loop's stop signal, set by `stop_sweeper` and read between
#: claims (#758). Cancelling the loop task cancels only the `await`: the
#: `to_thread` batch keeps running, and before this it went on claiming through
#: shutdown — each claim spending an attempt and starting a 600 s lease the
#: dying process would never finish, so a run of deploys could exhaust
#: perfectly healthy documents. A thread cannot be cancelled, so it is told
#: instead; the document already in hand finishes. One Event per started loop,
#: so a stop can never leak into a later start.
_stop: threading.Event | None = None


def sweeper_enabled() -> bool:
    """On in production by default, and only ever in real model mode.

    Outside real mode (#439, every E2E run) there is nothing to embed with, so
    a sweep could only mark rows `skipped`; the upload's own inline attempt
    already does that. INDEX_SWEEPER_ENABLED is the kill switch.

    Unset, it follows APP_ENV: on in production (APP_ENV's own default), off
    everywhere else. Staging and the per-PR preview environments run on
    Railway Serverless, which only sleeps a service after ~5 minutes with no
    outbound traffic; a pass every 300 s reset that clock forever, so those
    environments billed as always-on. Set INDEX_SWEEPER_ENABLED=true to run
    it outside production.
    """
    raw = os.getenv("INDEX_SWEEPER_ENABLED")
    if raw is not None and raw.strip():
        if raw.strip().lower() in _OFF:
            return False
    elif os.getenv("APP_ENV", "production").strip().lower() != "production":
        return False
    return model_mode() == "real"


def sweep_once(stop: threading.Event | None = None) -> int:
    """Re-drive up to BATCH_SIZE unfinished documents. Returns how many.

    `stop`, once set, ends the pass before its next claim (shutdown).

    Synchronous — PostgREST calls are — so the loop runs it in a thread, the
    same reason the upload post-roll does. Never raises: a failed claim (the
    RPC does not exist until the migration runs) ends the pass with a warning,
    and one bad document never costs the rest.

    Spec §13 A128: while the embeddings breaker is open the pass backs off —
    it claims nothing (a claim would spend an attempt on a document the
    outage, not its content, keeps out of the index), and a document that
    comes back deferred ends the pass too: `index_document` put it back
    unclaimed, so the next claim could hand it straight back.
    """
    if not sweeper_enabled():
        return 0
    driven = 0
    for _ in range(BATCH_SIZE):
        if stop is not None and stop.is_set():
            logger.info("[RAG] index sweep stopping: shutdown requested")
            break
        if embedding_blocked():
            logger.info(
                "[RAG] index sweep backing off: the embeddings breaker is open "
                "(next pass in %ss)", SWEEP_INTERVAL_SECONDS,
            )
            break
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
            outcome = index_document(doc_id, claimed=True)
        except Exception:
            # The row stays 'indexing' until its lease expires, then a later
            # sweep takes it again with the attempt already spent.
            logger.exception("[RAG] index sweep could not re-drive doc %s", doc_id)
            continue
        if getattr(outcome, "error", None) == EMBEDDINGS_UNAVAILABLE:
            logger.info(
                "[RAG] index sweep backing off: the embeddings breaker opened "
                "(doc %s put back)", doc_id,
            )
            break
        driven += 1
    if driven:
        logger.info("[RAG] index sweep re-drove %d document(s)", driven)
    return driven


async def _loop(stop: threading.Event) -> None:
    # Sleep FIRST: a deploy restarts every instance at once, and the uploads in
    # flight at that moment are still making their own inline attempts.
    while True:
        await asyncio.sleep(SWEEP_INTERVAL_SECONDS)
        try:
            await asyncio.to_thread(sweep_once, stop)
        except Exception:
            # sweep_once does not raise by contract; this is the backstop that
            # keeps one surprise from ending recovery for the process's life.
            logger.exception("[RAG] index sweep raised; the loop continues")


def start_sweeper() -> None:
    """Start the loop on the running event loop. Called from the app lifespan."""
    global _task, _stop
    if not sweeper_enabled():
        logger.info("[RAG] index sweeper not started (disabled, or not real model mode)")
        return
    if _task is None or _task.done():
        _stop = threading.Event()
        _task = asyncio.get_running_loop().create_task(_loop(_stop), name="index-sweeper")
        logger.info(
            "[RAG] index sweeper started (every %ss, batch %d)",
            SWEEP_INTERVAL_SECONDS, BATCH_SIZE,
        )


async def stop_sweeper() -> None:
    """Stop claiming, then cancel the loop. Safe when it never started."""
    global _task, _stop
    # First: a batch already handed to a worker thread outlives the task's
    # cancellation and must see this before its next claim.
    if _stop is not None:
        _stop.set()
    _stop = None
    task, _task = _task, None
    if task is None:
        return
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task
