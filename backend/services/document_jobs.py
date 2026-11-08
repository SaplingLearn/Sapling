"""The upload pipeline's slow tail on the job queue (#116, plan phase 2).

With the `jobs_queue` flag on for the uploader, an upload no longer runs text
extraction (Docling/OCR), the document agents, persistence and indexing in the
request. The request stores the file in `document_uploads`
(20261108212226_document_uploads.sql), enqueues a ``document.process`` job and
watches that row; the worker (`python -m worker`) runs the pipeline and
records each stage on the row as it goes. The SSE stream turns those stages
into the SAME status/progress/result/error events the inline pipeline emits
(the sequence of the OCR_ASYNC path: extracting_text … graph_updated, result,
status:done), so the frontend needs no new case. `/upload/sync` waits
(bounded) for the row to finish and returns the same JSON as before.

Flag off (the default) nothing here runs: `should_queue` says no and the
routes take their unchanged inline path.

Falling back to inline, so turning the flag on never loses an upload:
  * the stage+enqueue fails (migration not applied, PostgREST down);
  * no worker takes the job within PICKUP_GRACE_SECONDS (none running, or a
    deep backlog): the request takes the upload back with a compare-and-swap
    on ``stage`` (queued -> inline) and runs it inline. The worker does the
    same swap (queued -> extracting) when it starts, so exactly one of the two
    runs it; the job, if it is claimed later, sees ``inline`` and completes
    as a no-op.
  * files over QUEUED_UPLOAD_MAX_BYTES never queue (the bytes travel through
    Postgres; see the migration header).

Delivery is at least once: a worker that dies mid-run (or outlives its lease)
has the job re-offered, and the re-run starts over. Persistence is keyed on
the request id (the unique (user_id, request_id) index on `documents`), so a
re-run adopts the row an earlier attempt saved instead of saving a second.

Pipeline helpers (`_persist_document`, the syllabus/graph post-steps, the
post-roll side effects, the error strings) still live in routes/documents.py
and are imported from there lazily: moving them is phase 4's job (#118), and
teammate PRs edit that file.
"""
from __future__ import annotations

import asyncio
import logging
import os
import time
from dataclasses import dataclass
from typing import Any, AsyncIterator

from db.connection import table
from db.scope import runs_as_service
from services import jobs
from services.agent_events import SaplingEvent
from services.encryption import decrypt_bytes, decrypt_json, encrypt_bytes, encrypt_json
from services.feature_flags import flag_on

logger = logging.getLogger(__name__)

DOCUMENT_PROCESS_JOB = "document.process"

#: Largest file that goes through the queue. The bytes are staged in Postgres
#: (base64 of the AES-GCM ciphertext, ~1.33x) for the worker to read back and
#: cleared once the upload finishes; a bigger file runs inline as before.
QUEUED_UPLOAD_MAX_BYTES = 20 * 1024 * 1024

#: How long a staged upload may sit `queued` before the request takes it back
#: and runs it inline. Long enough for a polling worker (5 s by default) to
#: pick it up; short enough that "flag on, no worker" costs one wait, not a
#: hung upload.
PICKUP_GRACE_SECONDS = float(os.getenv("UPLOAD_JOB_PICKUP_GRACE_SECONDS", "30"))
#: Longest an SSE stream / a sync request watches a claimed upload.
STREAM_MAX_WAIT_SECONDS = 900.0
SYNC_MAX_WAIT_SECONDS = 300.0
POLL_INTERVAL_SECONDS = 1.0
#: Polls between reads of the job row (to notice a dead-lettered job).
_JOB_CHECK_EVERY = 10

QUEUED = "queued"
EXTRACTING = "extracting"
CLASSIFYING = "classifying"
EXTRACTING_CONCEPTS = "extracting_concepts"
MERGING = "merging"
SAVING = "saving"
DONE = "done"
FAILED = "failed"
INLINE = "inline"

#: Stages in the order the worker passes them; the stream emits each one's
#: events once, in this order, however many it skipped between two polls.
_ORDER = (QUEUED, EXTRACTING, CLASSIFYING, EXTRACTING_CONCEPTS, MERGING, SAVING, DONE)
_RANK = {s: i for i, s in enumerate(_ORDER)}
_RUNNING = frozenset({EXTRACTING, CLASSIFYING, EXTRACTING_CONCEPTS, MERGING, SAVING})
TERMINAL = frozenset({DONE, FAILED, INLINE})

#: error_code values (fixed codes; never an exception message — plaintext).
ERR_UNREADABLE = "unreadable"
ERR_EXTRACT = "extract_failed"
ERR_AGENT = "agent_failed"
ERR_PERSIST = "persist_failed"
ERR_WORKER = "worker_failed"
ERR_NO_FILE = "file_missing"

_STATUS_COLUMNS = "id,stage,progress,error_code,document_id,job_id"


def _routes():
    from routes import documents  # lazy: see the module docstring

    return documents


# ── request side: decide, stage, enqueue ────────────────────────────────────


def should_queue(user_id: str, file_size: int) -> bool:
    """Whether this upload goes through the queue: `jobs_queue` on for the
    uploader and the file under the staging cap. Never raises (a flag-store
    error reads as off, the inline path)."""
    if file_size > QUEUED_UPLOAD_MAX_BYTES:
        return False
    try:
        return flag_on(jobs.JOBS_QUEUE_FLAG, user_id)
    except Exception:
        logger.warning("jobs_queue flag check failed; uploading inline", exc_info=True)
        return False


@dataclass
class Staged:
    id: str
    #: True when this call (re)queued the upload and must enqueue its job;
    #: False when it attached to one a retry of the same request already has.
    fresh: bool


def _select_by_request(user_id: str, request_id: str) -> dict | None:
    rows = table("document_uploads").select(
        "id,stage", filters={"user_id": f"eq.{user_id}", "request_id": f"eq.{request_id}"},
        limit=1,
    )
    return rows[0] if isinstance(rows, list) and rows else None


@runs_as_service  # #116: document_uploads is service-only (bucket E)
def stage_upload(
    *, user_id: str, offering_id: str, course_id: str, request_id: str,
    filename: str, content_type: str | None, file_bytes: bytes,
) -> Staged:
    """Store the file for the worker. Idempotent on (user_id, request_id):

    * no row yet -> insert one, ``fresh``;
    * a ``failed``/``inline`` row (an earlier attempt of this request ended)
      -> re-queue it with the re-sent file (compare-and-swap on the stage),
      ``fresh``: the client's retry re-runs the pipeline, as it does inline;
    * a waiting, running or done row -> attach to it (``fresh`` False).

    Raises on a database error; the caller falls back to inline.
    """
    staged_file = {
        "offering_id": offering_id,
        "course_id": course_id,
        "file_name": filename,
        "content_type": content_type or None,
        "file_size": len(file_bytes),
        "file_data": encrypt_bytes(file_bytes),
        "stage": QUEUED,
        "progress": {},
        "error_code": None,
        "document_id": None,
        "result": None,
    }
    existing = _select_by_request(user_id, request_id)
    if existing is None:
        try:
            rows = table("document_uploads").insert(
                {"user_id": user_id, "request_id": request_id, **staged_file}
            )
            return Staged(id=str(rows[0]["id"]), fresh=True)
        except Exception:
            # A concurrent retry of the same request won the unique key.
            existing = _select_by_request(user_id, request_id)
            if existing is None:
                raise
    if existing.get("stage") in (FAILED, INLINE):
        won = table("document_uploads").update(
            staged_file,
            filters={"id": f"eq.{existing['id']}", "stage": f"eq.{existing['stage']}"},
        )
        if won:
            return Staged(id=str(existing["id"]), fresh=True)
    return Staged(id=str(existing["id"]), fresh=False)


@runs_as_service
def enqueue_process(upload_id: str) -> str | None:
    """Enqueue the worker's job for a staged upload. Raises on failure."""
    out = jobs.enqueue(
        DOCUMENT_PROCESS_JOB, {"upload_id": upload_id},
        dedupe_key=f"{DOCUMENT_PROCESS_JOB}:{upload_id}",
    )
    job_id = out.get("id")
    if job_id:
        try:
            table("document_uploads").update(
                {"job_id": job_id}, filters={"id": f"eq.{upload_id}"},
                prefer_return_minimal=True,
            )
        except Exception:
            # Only the dead-letter check needs it; the upload itself is fine.
            logger.warning("could not record job %s on upload %s", job_id, upload_id,
                           exc_info=True)
    return job_id


@runs_as_service
def take_back(upload_id: str) -> bool:
    """queued -> inline, for the request to run the upload itself. False when
    a worker already started it (or it already ended)."""
    won = table("document_uploads").update(
        {"stage": INLINE, "file_data": None},
        filters={"id": f"eq.{upload_id}", "stage": f"eq.{QUEUED}"},
    )
    return bool(won)


@runs_as_service
def read_status(upload_id: str) -> dict | None:
    rows = table("document_uploads").select(
        _STATUS_COLUMNS, filters={"id": f"eq.{upload_id}"}, limit=1,
    )
    return rows[0] if isinstance(rows, list) and rows else None


@runs_as_service
def read_result(upload_id: str) -> dict:
    """The finished upload's stored outcome: ``{"result": …, "categories": […]}``."""
    rows = table("document_uploads").select(
        "result", filters={"id": f"eq.{upload_id}"}, limit=1,
    )
    raw = rows[0].get("result") if isinstance(rows, list) and rows else None
    if not raw:
        return {}
    out = decrypt_json(raw)
    return out if isinstance(out, dict) else {}


@runs_as_service
def job_status(job_id: str) -> str | None:
    rows = table("jobs").select("status", filters={"id": f"eq.{job_id}"}, limit=1)
    return rows[0].get("status") if isinstance(rows, list) and rows else None


@runs_as_service
def fail_if_running(upload_id: str, stage: str, code: str) -> bool:
    """Record a terminal failure the worker could not (its job dead-lettered
    mid-run). Conditional on the stage the caller saw."""
    won = table("document_uploads").update(
        {"stage": FAILED, "error_code": code, "file_data": None},
        filters={"id": f"eq.{upload_id}", "stage": f"eq.{stage}"},
    )
    return bool(won)


def stage_and_enqueue(**kwargs: Any) -> str | None:
    """Stage the upload and make sure a job will run it. Returns the upload
    id, or None when either step failed (the caller runs inline). Sync: call
    it off the event loop."""
    try:
        staged = stage_upload(**kwargs)
    except Exception:
        logger.warning("upload staging failed; running inline", exc_info=True)
        return None
    if not staged.fresh:
        return staged.id
    try:
        enqueue_process(staged.id)
    except Exception:
        logger.warning("document.process enqueue failed for upload %s; running inline",
                       staged.id, exc_info=True)
        # Ours to run now. If the swap loses, a worker already has it after all.
        return None if take_back(staged.id) else staged.id
    return staged.id


# ── request side: watch ─────────────────────────────────────────────────────


@dataclass
class Watch:
    """What a watch ended on. ``kind``: done | failed | inline | timeout."""

    kind: str = ""
    row: dict | None = None


async def _watch(
    upload_id: str, *, max_wait: float, grace: float | None = None,
    poll: float | None = None,
) -> AsyncIterator[dict]:
    """Yield the upload's status row each time its stage changes, until it is
    terminal, the request takes it back (``inline`` row), or `max_wait`."""
    grace = PICKUP_GRACE_SECONDS if grace is None else grace
    poll = POLL_INTERVAL_SECONDS if poll is None else poll
    started = time.monotonic()
    last_stage = None
    polls = 0
    while True:
        row = await asyncio.to_thread(read_status, upload_id)
        if row is None:
            yield {"id": upload_id, "stage": FAILED, "error_code": ERR_WORKER, "progress": {}}
            return
        stage = row.get("stage")
        elapsed = time.monotonic() - started
        if stage == QUEUED and elapsed >= grace:
            if await asyncio.to_thread(take_back, upload_id):
                logger.info("upload %s: no worker took it in %.0fs; running inline",
                            upload_id, grace)
                yield {**row, "stage": INLINE}
                return
            continue  # a worker took it in the meantime: re-read
        if stage != last_stage or stage in TERMINAL:
            last_stage = stage
            yield row
            if stage in TERMINAL:
                return
        if elapsed >= max_wait:
            yield {**row, "_timeout": True}
            return
        polls += 1
        if stage in _RUNNING and row.get("job_id") and polls % _JOB_CHECK_EVERY == 0:
            status = await asyncio.to_thread(job_status, row["job_id"])
            if status == "dead":
                await asyncio.to_thread(fail_if_running, upload_id, stage, ERR_WORKER)
                continue
        await asyncio.sleep(poll)


def _error_message(code: str | None) -> str:
    docs = _routes()
    return {
        ERR_UNREADABLE: docs.UNREADABLE_DOCUMENT_DETAIL,
        ERR_EXTRACT: "Could not read this document. Please try a different file.",
        ERR_PERSIST: "The document was processed but could not be saved. "
                     "Please try uploading it again.",
    }.get(code or "", "Document processing failed. Please try again.")


TIMEOUT_MESSAGE = (
    "This document is taking longer than usual to process. It will appear in "
    "your library when it finishes."
)


def _stage_events(stage: str, progress: dict) -> list[SaplingEvent]:
    """The progress events the inline pipeline emits on entering `stage`."""
    p = progress or {}
    if stage == EXTRACTING:
        return [SaplingEvent(type="progress", step="extracting_text",
                             message="Extracting text from document...")]
    if stage == CLASSIFYING:
        return [
            SaplingEvent(type="progress", step="extracted_text",
                         message=f"Extracted {int(p.get('char_count') or 0):,} chars."),
            SaplingEvent(type="progress", step="classify", message="Classifying document..."),
        ]
    if stage == EXTRACTING_CONCEPTS:
        is_syllabus = bool(p.get("is_syllabus"))
        return [
            SaplingEvent(type="progress", step="classified",
                         message=f"Classified as {p.get('category') or 'other'}.",
                         data={"category": p.get("category") or "other",
                               "is_syllabus": is_syllabus}),
            SaplingEvent(type="progress", step="extract",
                         message="Extracting summary, concepts"
                                 + (" and syllabus" if is_syllabus else "")
                                 + " in parallel..."),
        ]
    if stage == MERGING:
        return [
            SaplingEvent(type="progress", step="extracted",
                         message=f"Extracted {int(p.get('concept_count') or 0)} concept(s)."),
            SaplingEvent(type="progress", step="graph_update",
                         message="Merging concepts into the course graph..."),
        ]
    if stage == SAVING:
        return [SaplingEvent(type="progress", step="graph_updated",
                             message=f"Merged {int(p.get('merged_count') or 0)} concept(s).")]
    return []


def events_between(prev_rank: int, row: dict) -> tuple[list[SaplingEvent], int]:
    """Every stage's events from just after `prev_rank` up to the row's stage
    (inclusive), and the new rank. Terminal stages emit nothing here."""
    stage = row.get("stage")
    rank = _RANK.get(stage, prev_rank)
    out: list[SaplingEvent] = []
    for r in range(prev_rank + 1, min(rank, _RANK[SAVING]) + 1):
        out.extend(_stage_events(_ORDER[r], row.get("progress") or {}))
    return out, max(prev_rank, rank)


async def stream_events(
    upload_id: str, *, request_id: str | None, outcome: Watch,
    max_wait: float = STREAM_MAX_WAIT_SECONDS,
) -> AsyncIterator[SaplingEvent]:
    """The SSE events for a queued upload. Ends after a terminal pair
    (result + status:done, or error:failed + status:done), or with nothing
    more yielded and ``outcome.kind == "inline"``: the caller then runs the
    upload itself."""
    rank = 0
    err_data = {"request_id": request_id} if request_id else None
    async for row in _watch(upload_id, max_wait=max_wait):
        stage = row.get("stage")
        outcome.row = row
        if stage == INLINE:
            outcome.kind = INLINE
            return
        if row.get("_timeout"):
            outcome.kind = "timeout"
            yield SaplingEvent(type="error", step="failed", message=TIMEOUT_MESSAGE,
                               data=err_data)
            yield SaplingEvent(type="status", step="done", message="Failed.")
            return
        if stage == FAILED:
            outcome.kind = FAILED
            yield SaplingEvent(type="error", step="failed",
                               message=_error_message(row.get("error_code")), data=err_data)
            yield SaplingEvent(type="status", step="done", message="Failed.")
            return
        events, rank = events_between(rank, row)
        for ev in events:
            yield ev
        if stage == DONE:
            outcome.kind = DONE
            stored = await asyncio.to_thread(read_result, upload_id)
            yield SaplingEvent(type="result", step="finalize", message="Processing complete.",
                               data=stored.get("result") or {})
            yield SaplingEvent(type="status", step="done", message="Saved.",
                               data={"document_id": row.get("document_id")})
            return


async def wait_for_upload(upload_id: str, *, max_wait: float = SYNC_MAX_WAIT_SECONDS) -> Watch:
    """Watch a queued upload to its end, for `/upload/sync`."""
    outcome = Watch()
    async for row in _watch(upload_id, max_wait=max_wait):
        outcome.row = row
        if row.get("_timeout"):
            outcome.kind = "timeout"
            return outcome
        if row.get("stage") in TERMINAL:
            outcome.kind = row["stage"]
            return outcome
    return outcome


# ── worker side ─────────────────────────────────────────────────────────────


def _update(upload_id: str, data: dict, *, stage: str | None = None) -> bool:
    """Write the row; with `stage`, only while it is still in that stage."""
    filters = {"id": f"eq.{upload_id}"}
    if stage is not None:
        filters["stage"] = f"eq.{stage}"
    return bool(table("document_uploads").update(data, filters=filters))


def _finish_failed(upload_id: str, code: str) -> None:
    _update(upload_id, {"stage": FAILED, "error_code": code, "file_data": None})


@jobs.job_handler(DOCUMENT_PROCESS_JOB)
def _run_document_process_job(payload: dict) -> None:
    """Worker side: extraction -> agents -> persist -> post-roll, recording
    each stage on the upload row. A pipeline failure is RECORDED (the row goes
    `failed`, the job completes) exactly where the inline route would end the
    stream with error:failed — the client retries, it is not retried behind
    its back. Only infrastructure errors (the row unreadable) raise, so the
    queue retries those."""
    upload_id = (payload or {}).get("upload_id")
    if not isinstance(upload_id, str) or not upload_id:
        raise jobs.PermanentJobError("document.process: payload has no upload_id")
    rows = table("document_uploads").select("*", filters={"id": f"eq.{upload_id}"}, limit=1)
    row = rows[0] if isinstance(rows, list) and rows else None
    if row is None:
        logger.info("document.process: upload %s is gone (account deleted?)", upload_id)
        return
    stage = row.get("stage")
    if stage in TERMINAL:
        return  # the request ran it inline, or an earlier attempt finished it
    if stage == QUEUED:
        if not _update(upload_id, {"stage": EXTRACTING}, stage=QUEUED):
            return  # the request took it back between our read and the swap
    else:
        # A re-delivery: the attempt that moved it past `queued` died or
        # outlived its lease. Start over; persistence adopts its row if any.
        logger.warning("document.process: upload %s re-run from stage %s", upload_id, stage)
        _update(upload_id, {"stage": EXTRACTING})
    _process(row)


def _process(row: dict) -> None:
    docs = _routes()
    upload_id = row["id"]
    user_id = row["user_id"]
    request_id = row["request_id"]

    adopted = docs._existing_doc_by_request_id(user_id, request_id)
    if adopted and adopted.get("id"):
        _done(upload_id, adopted["id"], {"result": docs._replay_result_payload(adopted),
                                         "categories": []})
        return

    if not row.get("file_data"):
        _finish_failed(upload_id, ERR_NO_FILE)
        return
    filename = row.get("file_name") or ""
    try:
        file_bytes = decrypt_bytes(row["file_data"])
        text = docs.extract_text_from_file(file_bytes, filename, row.get("content_type") or "")
    except Exception:
        logger.exception("document.process: extraction failed for upload %s", upload_id)
        _finish_failed(upload_id, ERR_EXTRACT)
        return
    if not docs._has_usable_text(text):
        logger.warning("document.process: %d usable chars for upload %s - unreadable",
                       len((text or "").strip()), upload_id)
        _finish_failed(upload_id, ERR_UNREADABLE)
        return
    progress: dict[str, Any] = {"char_count": len(text)}
    _update(upload_id, {"stage": CLASSIFYING, "progress": progress})

    from agents._run import run_agent_sync

    try:
        result = run_agent_sync(_run_agents(row, text, progress))
    except Exception:
        logger.exception("document.process: agent pipeline failed for upload %s", upload_id)
        _finish_failed(upload_id, ERR_AGENT)
        return

    course_id = row["course_id"]
    offering_id = row["offering_id"]
    docs._save_orchestrator_syllabus(user_id=user_id, course_id=course_id,
                                     filename=filename, result=result)
    docs._graph_backstop(user_id=user_id, course_id=course_id,
                         filename=filename, result=result)
    try:
        try:
            doc_id, _ = docs._persist_document(
                user_id=user_id, offering_id=offering_id, filename=filename,
                result=result, request_id=request_id, course_id=course_id,
                char_count=len(text), extracted_text=text,
            )
            fresh = True
        except Exception:
            # #759: another attempt of this request saved it first.
            winner = docs._existing_doc_by_request_id(user_id, request_id)
            if not winner or not winner.get("id"):
                raise
            doc_id, fresh = winner["id"], False
    except Exception:
        logger.exception("document.process: persistence failed for upload %s", upload_id)
        _finish_failed(upload_id, ERR_PERSIST)
        return

    _done(upload_id, doc_id, {
        "result": result.model_dump(mode="json"),
        "categories": docs._grading_categories_from(result),
    })
    if fresh:
        _post_roll(docs, user_id=user_id, offering_id=offering_id, doc_id=doc_id)


def _done(upload_id: str, doc_id: str, stored: dict) -> None:
    _update(upload_id, {
        "stage": DONE, "document_id": doc_id, "result": encrypt_json(stored),
        "file_data": None, "error_code": None,
    })


async def _run_agents(row: dict, text: str, progress: dict):
    """The inline SSE route's phases 1-3, with the stage recorded between
    them. Same agents, limits and usage tasks (function mode serves the same
    handlers in the worker: it freezes the mode at boot like the API)."""
    from agents import WORKER_LIMITS
    from agents.classifier import classifier_agent
    from agents.concept_extraction import concept_extraction_agent
    from agents.deps import SaplingDeps
    from agents.document import DocumentProcessingResult
    from agents.summary import summary_agent
    from agents.syllabus_extraction import syllabus_extraction_agent
    from agents.tools.graph import apply_concepts_to_graph
    from agents.usage import record_agent_usage

    upload_id, user_id, course_id = row["id"], row["user_id"], row["course_id"]
    request_id = row.get("request_id")
    deps = SaplingDeps(user_id=user_id, course_id=course_id, supabase=None,
                       request_id=request_id)

    def usage(run, task):
        return record_agent_usage(run, feature="document", task=task,
                                  user_id=user_id, request_id=request_id)

    classification = usage(
        await classifier_agent.run(text, deps=deps, usage_limits=WORKER_LIMITS), "classifier",
    ).output
    progress.update(category=classification.category, is_syllabus=classification.is_syllabus)
    await asyncio.to_thread(_update, upload_id,
                            {"stage": EXTRACTING_CONCEPTS, "progress": dict(progress)})

    summary_task = summary_agent.run(text, deps=deps, usage_limits=WORKER_LIMITS)
    concepts_task = concept_extraction_agent.run(text, deps=deps, usage_limits=WORKER_LIMITS)
    syllabus = None
    if classification.is_syllabus:
        syllabus_task = syllabus_extraction_agent.run(text, deps=deps, usage_limits=WORKER_LIMITS)
        summary_r, concepts_r, syllabus_r = await asyncio.gather(
            summary_task, concepts_task, syllabus_task)
        syllabus = usage(syllabus_r, "syllabus").output
    else:
        summary_r, concepts_r = await asyncio.gather(summary_task, concepts_task)
    summary = usage(summary_r, "summary").output
    concepts = usage(concepts_r, "concepts").output
    progress["concept_count"] = len(concepts.concepts)
    await asyncio.to_thread(_update, upload_id, {"stage": MERGING, "progress": dict(progress)})

    merged = await apply_concepts_to_graph(user_id, course_id, [c.name for c in concepts.concepts])
    progress["merged_count"] = merged
    await asyncio.to_thread(_update, upload_id, {"stage": SAVING, "progress": dict(progress)})
    return DocumentProcessingResult(
        classification=classification, summary=summary, concepts=concepts,
        syllabus=syllabus, graph_updated=merged > 0,
    )


def _post_roll(docs, *, user_id: str, offering_id: str, doc_id: str) -> None:
    """The streaming route's post-roll, run in the worker after the row is
    saved. Each step best-effort, as there."""
    from services.document_indexing import schedule_document_index

    steps = (
        ("invalidate_study_guide_cache", docs._invalidate_study_guide_cache, (user_id, offering_id)),
        ("update_course_context", docs._refresh_course_context, (offering_id, user_id)),
        ("check_upload_achievements", docs._check_upload_achievements, (user_id,)),
        ("index_document", schedule_document_index, (doc_id, user_id)),
    )
    for label, fn, args in steps:
        try:
            fn(*args)
        except Exception:
            logger.exception("document.process: post-roll step %s failed for doc %s",
                             label, doc_id)


# ── route glue ──────────────────────────────────────────────────────────────


async def sync_via_queue(**stage_kwargs: Any) -> dict | None:
    """`/upload/sync` through the queue. Returns the response JSON (the saved
    row + `categories`, as the inline route returns), None when the caller
    must run the upload inline, or raises the HTTPException the inline route
    would have raised for the same failure."""
    from fastapi import HTTPException

    docs = _routes()
    upload_id = await asyncio.to_thread(stage_and_enqueue, **stage_kwargs)
    if upload_id is None:
        return None
    outcome = await wait_for_upload(upload_id)
    if outcome.kind == INLINE:
        return None
    if outcome.kind == DONE:
        doc_id = (outcome.row or {}).get("document_id")
        stored = await asyncio.to_thread(read_result, upload_id)
        user_id = stage_kwargs["user_id"]
        row = await asyncio.to_thread(_saved_row, doc_id, user_id) if doc_id else None
        if row is None:
            raise HTTPException(status_code=502, detail=docs.UPLOAD_FAILED_DETAIL)
        row["categories"] = stored.get("categories") or []
        return row
    if outcome.kind == "timeout":
        raise HTTPException(status_code=504, detail=TIMEOUT_MESSAGE)
    code = (outcome.row or {}).get("error_code")
    if code in (ERR_UNREADABLE, ERR_EXTRACT):
        raise HTTPException(status_code=422, detail=_error_message(code))
    raise HTTPException(status_code=502, detail=docs.UPLOAD_FAILED_DETAIL)


@runs_as_service  # `*` includes the index/text columns a student's grant does not cover
def _saved_row(doc_id: str, user_id: str) -> dict | None:
    """The documents row as the inline `/upload/sync` returns it (the insert's
    representation): every column but `extracted_text`, with summary and
    concept notes decrypted. Filtered on the uploader too."""
    from services.encryption import decrypt_if_present

    rows = table("documents").select(
        "*", filters={"id": f"eq.{doc_id}", "user_id": f"eq.{user_id}"}, limit=1,
    )
    if not isinstance(rows, list) or not rows:
        return None
    row = dict(rows[0])
    row.pop("extracted_text", None)
    row["summary"] = decrypt_if_present(row.get("summary"))
    notes = row.get("concept_notes")
    if isinstance(notes, str):
        try:
            row["concept_notes"] = decrypt_json(notes)
        except Exception:
            row["concept_notes"] = []
    return row
