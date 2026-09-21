"""The one entry point that indexes a document into course_chunks (#482).

Indexing used to be a fire-and-forget post-roll on the streaming upload route
only: a closure over request state, wrapped in a catch-all. A failure left a
healthy-looking `documents` row whose content was absent from retrieval
forever, `/upload/sync` never indexed at all, and nothing could re-drive a
document because there was nothing to re-drive it FROM.

`index_document(doc_id)` reads everything it needs off the stored row, so four
callers share it — the streaming post-roll, `/upload/sync`, the sweeper
(`services/index_sweeper.py`) and the admin re-index endpoint — and a re-drive
three days later does the identical work. It owns every `index_status`
transition; no caller writes that column.

Durability comes from the status column, not DBOS. ADR 0011 keeps
DBOS_ENABLED off in every deployed environment, so a DBOS workflow would buy
nothing in production. See docs/superpowers/specs/2026-09-21-durable-document-
indexing-design.md for the state machine.
"""
from __future__ import annotations

import logging
import os
import time
from datetime import datetime, timedelta, timezone
from typing import NamedTuple

import httpx

from db.connection import table
from services.academics import offering_course_id
from services.chunk_visibility import decide_visibility
from services.chunker import chunk_for_category
from services.encryption import decrypt, decrypt_if_present
from services.events_service import log_event
from services.rag_service import course_relevance, index_document_chunks_detailed

logger = logging.getLogger(__name__)

PENDING = "pending"
INDEXING = "indexing"
INDEXED = "indexed"
PARTIAL = "partial"
FAILED = "failed"
SKIPPED = "skipped"

#: Statuses a claim may take a row from. `indexing` is deliberately absent: it
#: is only reclaimable once its lease has expired, which the SQL claim and the
#: forced claim each check against the lease itself.
_RECLAIMABLE = (PENDING, PARTIAL, FAILED)

INDEX_MAX_ATTEMPTS = int(os.getenv("INDEX_MAX_ATTEMPTS", "3"))
INDEX_LEASE_SECONDS = int(os.getenv("INDEX_LEASE_SECONDS", "600"))

#: Passes over rag_service within ONE attempt, with a sleep before each retry.
#: Kept short: this runs in a background thread and the sweeper re-drives
#: whatever is still short after it, bounded by INDEX_MAX_ATTEMPTS.
_INLINE_TRIES = 3
_BACKOFF_SECONDS = (1, 4)

#: Failures no retry can fix. Recorded with the attempt budget spent, so they
#: stay visible on the admin list and the sweeper never claims them again.
_TERMINAL_ERRORS = frozenset({"no_extracted_text", "no_chunks", "no_course"})


class IndexOutcome(NamedTuple):
    status: str
    chunk_count: int = 0
    #: An error CLASS (e.g. 'TypeError') or a fixed code ('no_extracted_text').
    #: Never an exception message: this is stored in plaintext and shown on an
    #: admin list, and a message can quote the document.
    error: str | None = None


def index_document(
    doc_id: str, *, force: bool = False, claimed: bool = False
) -> IndexOutcome:
    """Index one stored document, recording the outcome on its row.

    `claimed=True` means the caller already claimed the row through
    `claim_documents_for_indexing` (the sweeper), which set it `indexing` and
    spent an attempt. Every other caller leaves it False and this function
    claims the row itself — so every attempt is exactly one claim and one
    increment whoever drove it, which is what bounds a document that crashes
    the worker to INDEX_MAX_ATTEMPTS instead of retrying it forever.

    `force=True` (the admin endpoint) re-drives a row whatever its status,
    including `indexed`, and resets its budget — but never takes a row whose
    lease is still live, since that row is being indexed right now.
    """
    row = _load(doc_id)
    if row is None:
        return IndexOutcome(FAILED, error="no_such_document")

    # Code can ship ahead of its migration. Without the status columns this
    # indexes exactly as it did before #482, rather than silently not indexing
    # — which is what #629's code-ahead-of-migration window did to retrieval.
    tracking = "index_status" in row
    # The row as it stood before this call touched it (a sweeper-claimed row
    # is already past its claim). Needed to undo a re-drive that did nothing.
    prior = {
        col: row.get(col)
        for col in ("index_status", "index_attempts", "index_error",
                    "index_chunk_count", "index_leased_at")
    }
    first_attempt = (
        not claimed and not force
        and prior["index_status"] == PENDING and not prior["index_attempts"]
    )

    if tracking and not claimed:
        status = row.get("index_status")
        if not force:
            if status in (INDEXED, SKIPPED):
                return IndexOutcome(status, row.get("index_chunk_count") or 0)
            if (row.get("index_attempts") or 0) >= INDEX_MAX_ATTEMPTS:
                return IndexOutcome(status, error=row.get("index_error"))
        if not _claim_one(row, force=force):
            return IndexOutcome(INDEXING)

    was_recovery = claimed or row.get("index_status") in (PARTIAL, FAILED)
    try:
        outcome = _run(row)
    except Exception as exc:
        # The claim has already spent this attempt and set a lease. Anything
        # that escaped here would skip _finish and _report, leaving the row in
        # 'indexing' with no error class — and, once the budget was spent,
        # there for good. So every failure is recorded, whatever raised it.
        logger.exception("[RAG] indexing doc %s failed", doc_id)
        outcome = IndexOutcome(FAILED, error=type(exc).__name__)

    if tracking:
        if outcome.status == SKIPPED and not first_attempt:
            # `skipped` describes this PROCESS (embedding is off here), not the
            # document. Recorded on a re-drive it would be terminal: the row
            # would leave the sweeper's queue, the admin list and the backfill's
            # default targets — so a backfill run from a shell still holding the
            # E2E function-mode export would move every unfinished document out
            # of every recovery path. Only a never-attempted upload records it.
            _restore(doc_id, prior, claimed=claimed)
        else:
            _finish(doc_id, outcome)
    _report(row, outcome, was_recovery=was_recovery, tracking=tracking,
            claimed=claimed, force=force)
    return outcome


# ── reading the row ─────────────────────────────────────────────────────────


def _load(doc_id: str) -> dict | None:
    # `*`, not a column list: a named column that the migration has not added
    # yet would 400 the read, and the whole point of `tracking` above is that
    # an environment without those columns keeps indexing.
    rows = table("documents").select(
        "*", filters={"id": f"eq.{doc_id}", "deleted_at": "is.null"}, limit=1,
    )
    return rows[0] if rows else None


def _course_code(offering_id: str | None) -> str | None:
    """The BU course code chunks are partitioned by, via the offering."""
    course_id = offering_course_id(offering_id) if offering_id else None
    if not course_id:
        return None
    rows = table("courses").select(
        "course_code", filters={"id": f"eq.{course_id}"}, limit=1,
    )
    return (rows[0].get("course_code") or course_id) if rows else course_id


# ── the claim ───────────────────────────────────────────────────────────────


def _utc(dt: datetime) -> str:
    # 'Z', not '+00:00': this value also travels inside a PostgREST `or=(...)`
    # filter, where an unencoded '+' would read as a space.
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _claim_one(row: dict, *, force: bool) -> bool:
    """Take the row for this attempt. False means another caller has it.

    A compare-and-swap on `index_attempts`: two claimers that both read N
    cannot both win, because the loser's `index_attempts=eq.N` no longer
    matches once the winner has written N+1.
    """
    now = datetime.now(timezone.utc)
    attempts = row.get("index_attempts") or 0
    filters = {"id": f"eq.{row['id']}", "index_attempts": f"eq.{attempts}"}
    if force:
        cutoff = _utc(now - timedelta(seconds=INDEX_LEASE_SECONDS))
        filters["or"] = f"(index_status.neq.{INDEXING},index_leased_at.lt.{cutoff})"
        next_attempts = 1
    else:
        filters["index_status"] = f"in.({','.join(_RECLAIMABLE)})"
        next_attempts = attempts + 1
    won = table("documents").update(
        {
            "index_status": INDEXING,
            "index_leased_at": _utc(now),
            "index_attempts": next_attempts,
            "index_error": None,
        },
        filters=filters,
    )
    return bool(won)


# ── the work ────────────────────────────────────────────────────────────────


def _is_transient(exc: Exception) -> bool:
    """Worth retrying: a transport failure, or PostgREST saying 429 / 5xx.

    Embed failures never reach here — rag_service swallows them per batch and
    reports a short count instead, which `_run` retries on. What does reach
    here is the upsert and the ledger write. Anything else — a TypeError like
    #628, a 400 from a constraint — is a bug, and retrying a bug only burns
    rate limit and delays the error.
    """
    if isinstance(exc, httpx.TransportError):
        return True
    if isinstance(exc, httpx.HTTPStatusError):
        code = exc.response.status_code
        return code == 429 or code >= 500
    return False


def _run(row: dict) -> IndexOutcome:
    doc_id = row["id"]
    stored = row.get("extracted_text")
    if not stored:
        return IndexOutcome(FAILED, error="no_extracted_text")
    try:
        # STRICT, not decrypt_if_present: that falls back to the raw value, so
        # a process holding the wrong ENCRYPTION_KEY would chunk the base64
        # ciphertext and index it as course material. extracted_text has been
        # encrypted since the column was added (0030); there is no legacy
        # plaintext to tolerate.
        text = decrypt(stored)
    except Exception:
        logger.warning(
            "[RAG] extracted_text for doc %s does not decrypt under this "
            "process's ENCRYPTION_KEY — not indexing it", doc_id,
        )
        return IndexOutcome(FAILED, error="decrypt_failed")
    if not text.strip():
        return IndexOutcome(FAILED, error="no_extracted_text")

    category = row.get("category") or "other"
    chunks = chunk_for_category(text, category)
    if not chunks:
        return IndexOutcome(FAILED, error="no_chunks")

    course_code = _course_code(row.get("offering_id"))
    if course_code is None:
        return IndexOutcome(FAILED, error="no_course")

    user_id = row["user_id"]
    # Reproduced from what was stored, never re-decided: re-running the
    # classifier would let a non-deterministic model change a settled privacy
    # decision. A row from before #482 has no stored confidence and passes
    # None, which resolves PRIVATE — CLAUDE.md's rule for every unknown
    # answer. It is never invented as 1.0: `shareability` holds the
    # classifier's raw label, not a gated one, so assuming confidence would
    # publish a document the live upload path kept private.
    visibility = decide_visibility(
        user_id,
        shareability=row.get("shareability"),
        confidence=row.get("shareability_confidence"),
    )

    result = None
    for attempt in range(_INLINE_TRIES):
        if attempt:
            time.sleep(_BACKOFF_SECONDS[min(attempt - 1, len(_BACKOFF_SECONDS) - 1)])
        try:
            result = index_document_chunks_detailed(
                course_code, doc_id, user_id, chunks,
                visibility=visibility, category=category,
            )
        except Exception as exc:
            if _is_transient(exc) and attempt < _INLINE_TRIES - 1:
                logger.warning(
                    "[RAG] transient failure indexing doc %s (try %d/%d): %s",
                    doc_id, attempt + 1, _INLINE_TRIES, type(exc).__name__,
                )
                continue
            logger.exception("[RAG] indexing doc %s failed", doc_id)
            return IndexOutcome(FAILED, error=type(exc).__name__)

        if result.embedding_disabled:
            # #439: the seam turned embedding off (every function-mode run).
            # rag_service owns that rule; this only records it as the designed
            # no-op it is, so no log line has to be allowlisted to keep the
            # E2E logscan oracle quiet.
            return IndexOutcome(SKIPPED)
        if result.upserted >= result.total:
            break
        logger.warning(
            "[RAG] doc %s indexed %d/%d chunks (try %d/%d)",
            doc_id, result.upserted, result.total, attempt + 1, _INLINE_TRIES,
        )

    if result.upserted:
        _observe_course_relevance(
            doc_id, course_code, user_id, category,
            decrypt_if_present(row.get("summary")) or "", chunks[0],
        )
    if result.upserted >= result.total:
        return IndexOutcome(INDEXED, result.upserted)
    return IndexOutcome(
        PARTIAL if result.upserted else FAILED,
        result.upserted,
        result.embed_error or "embed_failed",
    )


def _observe_course_relevance(
    doc_id: str, course_code: str, user_id: str, category: str,
    doc_summary: str, first_chunk: str,
) -> None:
    """Record how on-topic an indexed upload is for its course. OBSERVE-ONLY (#628).

    This was a gate: below 0.35 the document was dropped from indexing. But it
    never produced a score — it multiplied floats by PostgREST's string form
    of the catalog vector and raised on every catalog course — so 0.35 was
    never calibrated against anything, and it was a raw dot product besides.
    Measured since: cosine against one paragraph of catalog blurb barely
    separates a receipt (0.49) from an on-topic lecture (0.60). So it only
    measures, and it runs AFTER indexing: no outcome here, including a failed
    embed, can keep a document out of retrieval. Whether anything becomes a
    gate again is #641's call, from the `rag.relevance_scored` data.
    """
    sample = "summary" if doc_summary else "first_chunk"
    try:
        score = course_relevance(course_code, doc_summary or first_chunk)
    except Exception:
        logger.warning("[RAG] relevance score failed for doc %s", doc_id, exc_info=True)
        return
    if score is None:
        return
    logger.info("[RAG] doc %s relevance to %s is %.3f (%s)", doc_id, course_code, score, sample)
    log_event(
        "rag.relevance_scored",
        category="usage",
        user_id=user_id,
        payload={
            "doc_id": doc_id,
            "course_id": course_code,
            "category": category,
            # An LLM abstract and a raw first chunk score on different
            # distributions; a threshold needs to know which it is looking at.
            "sample": sample,
            "score": round(score, 4),
        },
    )


# ── recording the outcome ───────────────────────────────────────────────────


def _finish(doc_id: str, outcome: IndexOutcome) -> None:
    # `index_leased_at` is deliberately left as the claim set it. On a
    # finished row it records when the last attempt BEGAN, and the claim
    # function's retry backoff reads it: a failed or partial row waits
    # lease_seconds from then. Clearing it here let `NULLS FIRST` hand a
    # just-failed document straight back to the sweeper in the same pass —
    # three attempts in a few seconds, a whole budget spent on a brief outage.
    data = {
        "index_status": outcome.status,
        "index_chunk_count": outcome.chunk_count,
        "index_error": outcome.error,
    }
    if outcome.error in _TERMINAL_ERRORS:
        data["index_attempts"] = INDEX_MAX_ATTEMPTS
    try:
        table("documents").update(
            data, filters={"id": f"eq.{doc_id}"}, prefer_return_minimal=True,
        )
    except Exception:
        # The chunks are already written; only the bookkeeping failed. The row
        # stays 'indexing' until its lease expires, and the sweeper then
        # re-drives it — idempotently, since chunk ids are content-addressed.
        logger.warning(
            "[RAG] could not record index outcome %s for doc %s",
            outcome.status, doc_id, exc_info=True,
        )


def _restore(doc_id: str, prior: dict, *, claimed: bool) -> None:
    """Put the row back as this call found it."""
    if claimed:
        # The SQL claim already overwrote the status and spent an attempt, and
        # neither was real work: back to the queue, attempt refunded.
        data = {
            "index_status": PENDING,
            "index_attempts": max((prior["index_attempts"] or 1) - 1, 0),
            "index_leased_at": None,
        }
    else:
        # Everything as it was, the last real attempt's time included — or the
        # retry backoff would restart from a call that did no work.
        data = {**prior, "index_attempts": prior["index_attempts"] or 0}
    try:
        table("documents").update(
            data, filters={"id": f"eq.{doc_id}"}, prefer_return_minimal=True,
        )
    except Exception:
        logger.warning("[RAG] could not restore index state for doc %s", doc_id,
                       exc_info=True)


def _report(
    row: dict, outcome: IndexOutcome, *, was_recovery: bool, tracking: bool,
    claimed: bool, force: bool,
) -> None:
    doc_id = row["id"]
    # The attempt this outcome belongs to: the sweeper's claim already counted
    # it in the row it handed over; an own claim counted it just now.
    before = row.get("index_attempts") or 0
    attempts = before if claimed else (1 if force else before + 1)
    if outcome.status in (FAILED, PARTIAL):
        log_event(
            "rag.index_failed",
            category="error",
            user_id=row.get("user_id"),
            payload={
                "doc_id": doc_id,
                "status": outcome.status,
                "error_type": outcome.error,
                "attempts": attempts,
            },
        )
    elif outcome.status == INDEXED and tracking and was_recovery:
        log_event(
            "rag.index_recovered",
            category="usage",
            user_id=row.get("user_id"),
            payload={
                "doc_id": doc_id,
                "attempts": attempts,
                "chunk_count": outcome.chunk_count,
            },
        )
    logger.info(
        "[RAG] doc %s index outcome: %s (%d chunks%s)",
        doc_id, outcome.status, outcome.chunk_count,
        f", {outcome.error}" if outcome.error else "",
    )
