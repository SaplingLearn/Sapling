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
has the job re-offered. Every write a run makes to the row is a
compare-and-swap on the stage it last wrote AND on its owner token
(`progress.owner` = worker id + job attempt, recorded when it moves the row
off `queued`), so a stale attempt can never move the stage backwards or
overwrite `done`/`failed`: its next write finds the row moved on and it stops.
A re-delivered job takes the row over only when the row has not moved for a
lease (otherwise it fails with `UploadBusy` and the queue retries it later),
and its re-run adopts the `documents` row an earlier attempt saved instead of
saving a second (persistence is keyed on the request id).

The stack relies on the worker's lease heartbeat (worker/runner.py, the PR
above this one) so that a LIVE long run keeps its lease and is never
re-delivered. Without a heartbeat (this change alone) a run longer than the
lease can be re-delivered while it is still going; the fence above still
holds: the newer attempt owns the row from its takeover, and the older one's
next write is refused.

Two requests watching one row (a client retry of the same X-Request-ID): only
the one that wins the queued -> inline swap runs the upload inline; it records
its own outcome on the row (`done` + document id, or `failed` + code) through
`record_inline_outcome` / `records_inline_outcome`. The loser keeps watching
and answers from that outcome (or the `documents` row) instead of running the
pipeline a second time.

Retention: `file_data` is cleared at every terminal stage and `result` once
the outcome has been handed to the client (the SSE result / the sync JSON);
an outcome nobody comes back for is removed by `prune_document_uploads`.

The agents run through the ONE upload pipeline the streaming route runs
(agents.document.run_document_agents; its steps become this row's stages, and
the events a watcher replays come from services/document_pipeline.py, #835).
The persistence helpers (`_persist_document`, the syllabus/graph post-steps,
the post-roll side effects, the error strings) live in services/documents/
(#118) and are reached through routes/documents.py's re-exports, imported
lazily, so a patch on the route module still reaches this path.
"""
from __future__ import annotations

import asyncio
import functools
import json
import logging
import os
import threading
import time
import uuid
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Any, AsyncIterator

from db.connection import table
from db.scope import runs_as_service
from services import jobs, llm_budget, staged_jobs
from services.agent_events import SaplingEvent
from services.documents_read import saved_document
from services.encryption import decrypt_bytes, decrypt_json, encrypt_bytes, encrypt_json
from services.feature_flags import flag_on
from services.llm_budget import budget_error_in

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
#: Consecutive polls a watch may fail (PostgREST blips) before it gives up
#: with the timeout answer. Any successful poll resets the count.
_MAX_DB_ERRORS = 10
#: An `inline` row this old belongs to a request that died without recording
#: an outcome (a crash, a deploy): a retry of the request may take it over.
INLINE_STALE_SECONDS = STREAM_MAX_WAIT_SECONDS
#: The worker's lease (worker/__main__.py reads the same variable). A row a
#: running attempt has not moved for this long is a dead attempt's.
_LEASE_SECONDS = float(os.getenv("JOBS_LEASE_SECONDS", str(jobs.DEFAULT_LEASE_SECONDS)))
#: A re-delivered job whose row went quiet less than a lease ago waits out the
#: rest of the lease in the handler when that is at most this long (a dead
#: owner's last write lands up to one heartbeat, lease/3, after its last beat),
#: instead of spending a queue attempt on `UploadBusy`.
_TAKEOVER_WAIT_MAX_SECONDS = _LEASE_SECONDS / 3
_sleep = time.sleep  # patched in tests

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
#: Stages the WORKER never runs from. For a watcher `inline` is not an end:
#: it means "a request runs it", and that request records done/failed.
TERMINAL = frozenset({DONE, FAILED, INLINE})

#: error_code values (fixed codes; never an exception message — plaintext).
ERR_UNREADABLE = "unreadable"
ERR_EXTRACT = "extract_failed"
ERR_AGENT = "agent_failed"
ERR_PERSIST = "persist_failed"
ERR_WORKER = "worker_failed"
ERR_NO_FILE = "file_missing"
ERR_ABANDONED = "abandoned"
#: #119: the per-user LLM budget refused the upload's model work (agents or
#: vision OCR). The stream says when it resets; /upload/sync answers 429.
ERR_BUDGET = "llm_budget"

_STATUS_COLUMNS = "id,user_id,request_id,stage,progress,error_code,document_id,job_id,updated_at"
#: The staged-job machinery (services/staged_jobs.py): the owner tokens live
#: in the plaintext `progress` (opaque ids, never content) — the worker
#: attempt that runs the row (`owner`), and the request that took it back to
#: run inline (`inline_owner`).
SPEC = staged_jobs.Spec(table="document_uploads", job_type=DOCUMENT_PROCESS_JOB,
                        owner_column="progress", label="upload")


def _routes():
    from routes import documents  # lazy: see the module docstring

    return documents


def _age_seconds(row: dict) -> float | None:
    """Seconds since the row's `updated_at`, or None when it is unreadable."""
    return staged_jobs.age_seconds(row.get("updated_at"))


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


#: `fresh`: this call (re)queued the upload and must enqueue its job; False
#: when it attached to one a retry of the same request already has.
Staged = staged_jobs.Staged


def _select_by_request(user_id: str, request_id: str) -> dict | None:
    rows = table("document_uploads").select(
        "id,user_id,stage,updated_at,job_id,document_id",
        filters={"user_id": f"eq.{user_id}", "request_id": f"eq.{request_id}"},
        limit=1,
    )
    return rows[0] if isinstance(rows, list) and rows else None


def _document_alive(doc_id: str | None, user_id: str) -> bool:
    if not doc_id:
        return False
    rows = table("documents").select(
        "id", filters={"id": f"eq.{doc_id}", "user_id": f"eq.{user_id}", "deleted_at": "is.null"},
        limit=1,
    )
    return isinstance(rows, list) and bool(rows)


def _restageable(row: dict, user_id: str) -> bool:
    """Whether a retry of the request should re-run this earlier attempt
    rather than attach to it:

    * ``failed``: the attempt ended; the retry re-runs it, as inline does;
    * ``inline`` older than INLINE_STALE_SECONDS: the request running it died
      without recording an outcome;
    * ``done`` whose document is gone (soft-deleted, or deleted: the FK set
      document_id NULL): `_existing_doc_by_request_id` no longer sees it, so
      the inline path would run the upload again too;
    * ``queued`` past the pickup grace with no live job: the request that
      staged it died before enqueueing (or its job is gone), so nothing will
      ever run it.

    A lookup error reads as "attach" (the watcher's own take-back still ends
    a stuck `queued` row)."""
    stage = row.get("stage")
    if stage == FAILED:
        return True
    age = _age_seconds(row)
    if stage == INLINE:
        return age is not None and age > INLINE_STALE_SECONDS
    try:
        if stage == DONE:
            return not _document_alive(row.get("document_id"), user_id)
        if stage == QUEUED and age is not None and age > PICKUP_GRACE_SECONDS:
            return job_status(str(row["id"]), row.get("job_id")) not in staged_jobs.LIVE_JOB
    except Exception:
        logger.warning("upload %s: liveness check failed; attaching", row.get("id"),
                       exc_info=True)
    return False


@runs_as_service  # #116: document_uploads is service-only (bucket E)
def stage_upload(
    *, user_id: str, offering_id: str, course_id: str, request_id: str,
    filename: str, content_type: str | None, file_bytes: bytes,
) -> Staged:
    """Store the file for the worker. Idempotent on (user_id, request_id):

    * no row yet -> insert one, ``fresh``;
    * an earlier attempt of this request that ended or was abandoned
      (`_restageable`) -> re-queue it with the re-sent file
      (compare-and-swap on the stage, and on `updated_at` for a `queued`
      row, whose stage does not change), ``fresh``;
    * a waiting, running, inline-running or done row -> attach to it
      (``fresh`` False).

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
        "job_id": None,
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
    stage = existing.get("stage")
    if _restageable(existing, user_id):
        filters = {"id": f"eq.{existing['id']}", "stage": f"eq.{stage}"}
        if stage == QUEUED:
            filters["updated_at"] = f"eq.{existing['updated_at']}"
        if table("document_uploads").update(staged_file, filters=filters):
            logger.info("upload %s: re-staged an earlier %s attempt of the request",
                        existing["id"], stage)
            return Staged(id=str(existing["id"]), fresh=True)
    return Staged(id=str(existing["id"]), fresh=False)


@runs_as_service
def enqueue_process(upload_id: str) -> str | None:
    """Enqueue the worker's job for a staged upload. Raises on failure."""
    return staged_jobs.enqueue(SPEC, table, upload_id, {"upload_id": upload_id})


@runs_as_service
def take_back(upload_id: str, token: str) -> bool:
    """queued -> inline, for the request holding `token` to run the upload
    itself (recorded as `progress.inline_owner`). False when a worker already
    started it, another request took it, or it ended."""
    return staged_jobs.take_back(SPEC, table, upload_id, token, clear={"file_data": None})


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
def clear_result(upload_id: str) -> None:
    """Drop the encrypted outcome (and any bytes) once the client has it.
    Best-effort: a row nobody clears is removed by prune_document_uploads."""
    try:
        table("document_uploads").update(
            {"result": None, "file_data": None},
            filters={"id": f"eq.{upload_id}", "stage": f"in.({DONE},{FAILED})"},
            prefer_return_minimal=True,
        )
    except Exception:
        logger.warning("could not clear the stored outcome of upload %s", upload_id,
                       exc_info=True)


@runs_as_service
def job_status(upload_id: str, job_id: str | None = None) -> str | None:
    """The status of the upload's `document.process` job: by the id recorded
    on the row, or — when that best-effort write never landed — by the job's
    dedupe key (the newest job enqueued for this upload)."""
    job = staged_jobs.job_row(SPEC, table, upload_id, job_id)
    return job.get("status") if job else None


@runs_as_service
def fail_if_running(upload_id: str, stage: str, code: str) -> bool:
    """Record a terminal failure the worker could not (its job dead-lettered
    mid-run). Conditional on the stage the caller saw."""
    return staged_jobs.cas_update(
        SPEC, table, upload_id,
        {"stage": FAILED, "error_code": code, "file_data": None, "result": None}, stage=stage,
    )


def stage_and_enqueue(**kwargs: Any) -> str | None:
    """Stage the upload and make sure a job will run it. Returns the upload
    id, or None when the caller must run it inline (staging failed, or the
    enqueue failed and this request took the row back). Sync: call it off the
    event loop."""
    try:
        staged = stage_upload(**kwargs)
    except Exception:
        logger.warning("upload staging failed; running inline", exc_info=True)
        return None
    if not staged.fresh:
        return staged.id
    token = uuid.uuid4().hex
    if staged_jobs.enqueue_or_take_back(SPEC, staged.id, enqueue_fn=enqueue_process,
                                        take_back_fn=take_back, token=token):
        _claim_inline(staged.id, token)  # ours to run now
        return None
    return staged.id


# ── request side: an inline run records its outcome ─────────────────────────


@dataclass
class InlineClaim:
    """The upload row this request took back to run inline, if any."""

    upload_id: str | None = None
    token: str | None = None
    recorded: bool = field(default=False, compare=False)


#: Set per upload request by `record_inline_outcome` / `records_inline_outcome`;
#: filled by whichever step wins the queued -> inline swap for the request.
_INLINE_CLAIM: ContextVar[InlineClaim | None] = ContextVar("sapling_inline_claim",
                                                           default=None)


def _claim_inline(upload_id: str, token: str) -> None:
    holder = _INLINE_CLAIM.get()
    if holder is not None:
        holder.upload_id, holder.token = upload_id, token


@runs_as_service
def finish_inline(claim: InlineClaim, *, document_id: str | None = None,
                  error_code: str | None = None) -> bool:
    """Record an inline run's outcome on the row it took back: ``done`` with
    the document id, else ``failed`` with `error_code`. Only while the row is
    still this request's (`inline` + its token). Never raises."""
    if not claim.upload_id or not claim.token or claim.recorded:
        return False
    claim.recorded = True
    if document_id:
        data = {"stage": DONE, "document_id": document_id, "error_code": None,
                "progress": {"inline_owner": claim.token, "adopted": True}}
    else:
        data = {"stage": FAILED, "error_code": error_code or ERR_WORKER}
    data.update(file_data=None, result=None)
    return staged_jobs.finish_inline(SPEC, table, claim.upload_id, claim.token, data)


def _finish_inline_detached(claim: InlineClaim, **kwargs: Any) -> None:
    """`finish_inline` on a daemon thread, for a close that cannot await (a
    no-op if the awaited call already recorded it)."""
    threading.Thread(target=finish_inline, args=(claim,), kwargs=kwargs,
                     name="inline-outcome", daemon=True).start()


def _code_for_message(message: str | None) -> str:
    for code in (ERR_UNREADABLE, ERR_EXTRACT, ERR_PERSIST):
        if message == _error_message(code):
            return code
    return ERR_AGENT


def _sse_outcome(item: Any) -> tuple[str, str | None] | None:
    """(stage, document id or error code) for a terminal SSE frame."""
    if not isinstance(item, dict):
        return None
    try:
        ev = json.loads(item.get("data") or "{}")
    except (TypeError, ValueError):
        return None
    if ev.get("type") == "error" and ev.get("step") == "failed":
        return FAILED, _code_for_message(ev.get("message"))
    data = ev.get("data") or {}
    if ev.get("type") == "status" and ev.get("step") == "done" and data.get("document_id"):
        return DONE, data["document_id"]
    return None


async def record_inline_outcome(frames: AsyncIterator[dict]) -> AsyncIterator[dict]:
    """Wrap the upload SSE generator: when the request ran a queued upload
    inline (it won the take-back), record that run's outcome on the row from
    the stream's own terminal frames — or ``abandoned`` when the stream closed
    without one (the client went away)."""
    holder = InlineClaim()
    token = _INLINE_CLAIM.set(holder)
    outcome: tuple[str, str | None] | None = None
    try:
        async for frame in frames:
            if holder.upload_id and outcome is None:
                outcome = _sse_outcome(frame)
            yield frame
    finally:
        try:
            _INLINE_CLAIM.reset(token)
        except ValueError:  # closed from another context
            pass
        if holder.upload_id and not holder.recorded:
            stage, value = outcome or (FAILED, ERR_ABANDONED)
            kwargs = {"document_id": value} if stage == DONE else {"error_code": value}
            try:
                await asyncio.to_thread(finish_inline, holder, **kwargs)
            except BaseException:
                # Closed by a cancellation (the client went away): an await
                # here is cancelled again, so record it off the loop instead.
                _finish_inline_detached(holder, **kwargs)


def records_inline_outcome(endpoint):
    """Decorator for `/upload/sync`: when the request ran a queued upload
    inline, record the outcome (the returned row's id, or the error the route
    raised) on the row it took back."""
    @functools.wraps(endpoint)
    async def wrapper(*args: Any, **kwargs: Any):
        from fastapi import HTTPException

        holder = InlineClaim()
        token = _INLINE_CLAIM.set(holder)
        try:
            try:
                response = await endpoint(*args, **kwargs)
            except HTTPException as exc:
                if holder.upload_id:
                    unreadable = exc.detail == _routes().UNREADABLE_DOCUMENT_DETAIL
                    code = ((ERR_UNREADABLE if unreadable else ERR_EXTRACT)
                            if exc.status_code == 422 else ERR_AGENT)
                    await asyncio.to_thread(finish_inline, holder, error_code=code)
                raise
            except Exception:
                if holder.upload_id:
                    await asyncio.to_thread(finish_inline, holder, error_code=ERR_WORKER)
                raise
            except BaseException:
                if holder.upload_id:
                    _finish_inline_detached(holder, error_code=ERR_ABANDONED)
                raise
            if holder.upload_id:
                doc_id = response.get("id") if isinstance(response, dict) else None
                await asyncio.to_thread(finish_inline, holder, document_id=doc_id,
                                        error_code=None if doc_id else ERR_WORKER)
            return response
        finally:
            _INLINE_CLAIM.reset(token)
    return wrapper


# ── request side: watch ─────────────────────────────────────────────────────


@dataclass
class Watch:
    """What a watch ended on. ``kind``: done | failed | inline | timeout."""

    kind: str = ""
    row: dict | None = None


def _adopted_document(row: dict) -> dict | None:
    """The documents row another request's inline run saved for this upload."""
    user_id, request_id = row.get("user_id"), row.get("request_id")
    if not user_id or not request_id:
        return None
    return _routes()._existing_doc_by_request_id(user_id, request_id)


async def _watch(
    upload_id: str, *, max_wait: float, grace: float | None = None,
    poll: float | None = None,
) -> AsyncIterator[dict]:
    """Yield the upload's status row each time its stage changes, until it is
    terminal, THIS request takes it back (an ``inline`` row: run it), or
    `max_wait` (services/staged_jobs.py runs the loop).

    An ``inline`` row another request took back is not an end: that request
    records its outcome on the row (done/failed), and its saved `documents`
    row is adopted as soon as it exists (yielded as ``done``, progress
    ``adopted``). A transient database error on any read or swap is retried on
    the next poll; only `_MAX_DB_ERRORS` in a row end the watch, with the
    timeout answer."""
    token = uuid.uuid4().hex
    plan = staged_jobs.WatchPlan(
        spec=SPEC, row_id=upload_id, token=token, ends=frozenset({DONE, FAILED}),
        running=_RUNNING, grace=PICKUP_GRACE_SECONDS if grace is None else grace,
        max_wait=max_wait, poll=POLL_INTERVAL_SECONDS if poll is None else poll,
        job_check_every=_JOB_CHECK_EVERY, max_errors=_MAX_DB_ERRORS,
    )

    def _adopt(row: dict) -> dict | None:
        doc = _adopted_document(row)
        if doc and doc.get("id"):
            return {**row, "stage": DONE, "document_id": doc["id"], "progress": {"adopted": True}}
        return None

    io = staged_jobs.WatchIO(
        read=lambda: read_status(upload_id),
        take_back=lambda: take_back(upload_id, token),
        job_dead=lambda row: job_status(upload_id, row.get("job_id")) == "dead",
        fail_dead=lambda row: fail_if_running(upload_id, row.get("stage"), ERR_WORKER),
        adopt=_adopt,
    )
    async for end in staged_jobs.awatch(plan, io):
        if end.kind == staged_jobs.TOOK_BACK:
            _claim_inline(upload_id, token)
            yield end.row
        elif end.kind == staged_jobs.GONE:
            yield {"id": upload_id, "stage": FAILED, "error_code": ERR_WORKER, "progress": {}}
        elif end.kind in (staged_jobs.PENDING, staged_jobs.TIMEOUT):
            base = end.row or {"id": upload_id, "stage": QUEUED, "progress": {}}
            yield {**base, "_timeout": True}
        else:  # PROGRESS, END, ADOPTED
            yield end.row


async def _retrying(fn, *args: Any, default: Any = None, tries: int = 3) -> Any:
    """`fn(*args)` off the loop, retried over a short blip; `default` if it
    keeps failing."""
    for attempt in range(tries):
        try:
            return await asyncio.to_thread(fn, *args)
        except Exception:
            logger.warning("%s failed (try %d/%d)", getattr(fn, "__name__", fn),
                           attempt + 1, tries, exc_info=True)
            if attempt + 1 < tries:
                await asyncio.sleep(POLL_INTERVAL_SECONDS)
    return default


def _error_message(code: str | None) -> str:
    docs = _routes()
    if code == ERR_BUDGET:
        return llm_budget.user_message(llm_budget.next_reset())
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
    """The progress events the inline pipeline emits on entering `stage`:
    the worker records each pipeline step as a stage, and the events come
    from the same vocabulary the streaming route uses (document_pipeline)."""
    from services import document_pipeline as dp

    p = progress or {}
    if stage == EXTRACTING:
        return [dp.extracting_text_event()]
    if stage == CLASSIFYING:
        return [dp.extracted_text_event(int(p.get("char_count") or 0)),
                *dp.step_events(dp.PipelineStep(dp.CLASSIFY))]
    if stage == EXTRACTING_CONCEPTS:
        return dp.step_events(dp.PipelineStep(
            dp.CLASSIFIED, category=p.get("category") or "other",
            is_syllabus=bool(p.get("is_syllabus"))))
    if stage == MERGING:
        return dp.step_events(dp.PipelineStep(
            dp.EXTRACTED, concept_count=int(p.get("concept_count") or 0)))
    if stage == SAVING:
        return dp.step_events(dp.PipelineStep(dp.MERGED, merged=int(p.get("merged_count") or 0)))
    return []


def events_between(prev_rank: int, row: dict) -> tuple[list[SaplingEvent], int]:
    """Every stage's events from just after `prev_rank` up to the row's stage
    (inclusive), and the new rank. Terminal stages emit nothing here, and
    neither does an ADOPTED outcome (a document an earlier attempt or another
    request saved): nothing ran for this watcher to report, so it gets the
    replay's result + done only — as the inline idempotent replay does —
    never "Extracted 0 chars"."""
    stage = row.get("stage")
    rank = _RANK.get(stage, prev_rank)
    progress = row.get("progress") or {}
    if progress.get("adopted"):
        return [], max(prev_rank, rank)
    out: list[SaplingEvent] = []
    for r in range(prev_rank + 1, min(rank, _RANK[SAVING]) + 1):
        out.extend(_stage_events(_ORDER[r], progress))
    return out, max(prev_rank, rank)


async def _result_payload(upload_id: str, row: dict) -> dict:
    """The `result` event's data for a done upload: the stored outcome, or —
    once that was delivered and cleared, or for an adopted/inline outcome
    that never stored one — the idempotent replay of the saved row."""
    stored = await _retrying(read_result, upload_id, default={})
    if stored.get("result"):
        return stored["result"]
    doc_id, user_id = row.get("document_id"), row.get("user_id")
    doc = await _retrying(saved_document, doc_id, user_id) if doc_id and user_id else None
    return _routes()._replay_result_payload(doc) if doc else {}


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
        if row.get("_timeout"):
            outcome.kind = "timeout"
            yield SaplingEvent(type="error", step="failed", message=TIMEOUT_MESSAGE,
                               data=err_data)
            yield SaplingEvent(type="status", step="done", message="Failed.")
            return
        if stage == INLINE:
            outcome.kind = INLINE
            return
        if stage == FAILED:
            outcome.kind = FAILED
            code = row.get("error_code")
            data = err_data
            if code == ERR_BUDGET:  # #119: the inline route's budget event shape
                data = {**(err_data or {}), "code": llm_budget.ERROR_CODE,
                        "reset_at": llm_budget.next_reset().isoformat()}
            yield SaplingEvent(type="error", step="failed",
                               message=_error_message(code), data=data)
            yield SaplingEvent(type="status", step="done", message="Failed.")
            return
        events, rank = events_between(rank, row)
        for ev in events:
            yield ev
        if stage == DONE:
            outcome.kind = DONE
            data = await _result_payload(upload_id, row)
            yield SaplingEvent(type="result", step="finalize", message="Processing complete.",
                               data=data)
            await asyncio.to_thread(clear_result, upload_id)
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


class UploadBusy(Exception):
    """A re-delivered job found its upload still moving under another
    attempt. Retryable: the queue offers it again after the backoff, by which
    time that attempt has finished (a no-op re-run) or gone quiet (taken
    over)."""


class _Superseded(Exception):
    """This attempt no longer owns the row (a newer attempt took it over, or
    the request failed it): stop without writing anything more."""


@dataclass
class _Run:
    """One attempt's ownership of an upload row. Every write is a
    compare-and-swap on the stage this attempt last wrote and its owner
    token, so it can never move the stage backwards or overwrite an outcome
    someone else recorded; a refused write raises `_Superseded`."""

    upload_id: str
    owner: str
    stage: str
    progress: dict = field(default_factory=dict)

    def advance(self, stage: str, data: dict | None = None, **progress: Any) -> None:
        new_progress = {**self.progress, **progress, "owner": self.owner}
        won = staged_jobs.cas_update(
            SPEC, table, self.upload_id,
            {**(data or {}), "stage": stage, "progress": new_progress},
            stage=self.stage, owner=self.owner,
        )
        if not won:
            raise _Superseded(f"upload {self.upload_id}: {self.stage} -> {stage} refused")
        self.stage, self.progress = stage, new_progress


def _attempt_is_current(job: jobs.Job) -> bool:
    """Whether the jobs row still carries this claim (the runner's fence for
    complete/fail, checked up front so a stale attempt never touches the
    upload)."""
    rows = table("jobs").select("status,attempts,locked_by",
                                filters={"id": f"eq.{job.id}"}, limit=1)
    row = rows[0] if isinstance(rows, list) and rows else {}
    return (row.get("status") == "running" and row.get("attempts") == job.attempt
            and row.get("locked_by") == job.locked_by)


def _finish_failed(run: _Run, code: str) -> None:
    try:
        run.advance(FAILED, {"error_code": code, "file_data": None, "result": None})
    except _Superseded:
        logger.info("document.process: upload %s moved on; not recording %s",
                    run.upload_id, code)


@jobs.job_handler(DOCUMENT_PROCESS_JOB)
def _run_document_process_job(payload: dict) -> None:
    """Worker side: extraction -> agents -> persist -> post-roll, recording
    each stage on the upload row. A pipeline failure is RECORDED (the row goes
    `failed`, the job completes) exactly where the inline route would end the
    stream with error:failed — the client retries, it is not retried behind
    its back. Only infrastructure errors (the row unreadable) and `UploadBusy`
    raise, so the queue retries those."""
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
    job = jobs.current_job()
    if job is not None and not _attempt_is_current(job):
        logger.warning("document.process: attempt %d of job %s is no longer current; "
                       "leaving upload %s alone", job.attempt, job.id, upload_id)
        return
    owner = staged_jobs.owner_token(job)
    if stage != QUEUED:
        # A re-delivery: an earlier attempt moved it past `queued`. Take it
        # over only if that attempt has gone quiet for a lease; a live one
        # keeps it (with the heartbeat, a live run is never re-delivered).
        age = _age_seconds(row)
        if age is not None and age < _LEASE_SECONDS:
            remaining = _LEASE_SECONDS - age
            if remaining > _TAKEOVER_WAIT_MAX_SECONDS:
                raise UploadBusy(f"upload {upload_id} moved {age:.0f}s ago ({stage}); "
                                 "another attempt still runs it")
            _sleep(remaining)  # still quiet after it? the swap below finds out
    # queued -> extracting, or a takeover from the previous attempt's token.
    if not staged_jobs.claim(SPEC, table, row, to_stage=EXTRACTING, owner=owner):
        if stage == QUEUED:
            return  # the request took it back between our read and the swap
        raise UploadBusy(f"upload {upload_id} moved while being taken over")
    if stage != QUEUED:
        logger.warning("document.process: upload %s taken over from stage %s (owner %s)",
                       upload_id, stage, (row.get("progress") or {}).get("owner"))
    run = _Run(upload_id=upload_id, owner=owner, stage=EXTRACTING)
    # #119: the work is the uploader's — llm_usage rows are attributed to them
    # and the per-user LLM budget applies, as on the inline path. Reset on
    # exit, so the worker's next job never inherits this user.
    from services.request_context import acting_for

    try:
        with acting_for(row.get("user_id")):
            _process(row, run)
    except _Superseded as exc:
        logger.info("document.process: stopping, this attempt lost the upload (%s)", exc)


def _stored_outcome(row: dict) -> dict:
    """The outcome an earlier attempt stored on the row before saving, if any."""
    raw = row.get("result")
    if not raw:
        return {}
    try:
        out = decrypt_json(raw)
    except Exception:
        return {}
    return out if isinstance(out, dict) else {}


def _process(row: dict, run: _Run) -> None:
    docs = _routes()
    upload_id = row["id"]
    user_id = row["user_id"]
    request_id = row["request_id"]

    adopted = docs._existing_doc_by_request_id(user_id, request_id)
    if adopted and adopted.get("id"):
        # An earlier attempt saved it and died before recording `done`. It
        # stored the full outcome (syllabus categories included) at `saving`,
        # before the insert; without it, replay what the row persists.
        stored = _stored_outcome(row)
        notes = adopted.get("concept_notes")
        _done(run, adopted["id"], {
            "result": stored.get("result") or docs._replay_result_payload(adopted),
            "categories": stored.get("categories") or [],
        }, adopted=True, category=adopted.get("category") or "other",
            concept_count=len(notes) if isinstance(notes, list) else 0)
        return

    if not row.get("file_data"):
        _finish_failed(run, ERR_NO_FILE)
        return
    filename = row.get("file_name") or ""
    try:
        file_bytes = decrypt_bytes(row["file_data"])
        text = docs.extract_text_from_file(file_bytes, filename, row.get("content_type") or "")
    except Exception as exc:
        if budget_error_in(exc) is not None:
            logger.warning("document.process: LLM budget refused OCR for upload %s", upload_id)
            _finish_failed(run, ERR_BUDGET)
            return
        logger.exception("document.process: extraction failed for upload %s", upload_id)
        _finish_failed(run, ERR_EXTRACT)
        return
    if not docs._has_usable_text(text):
        logger.warning("document.process: %d usable chars for upload %s - unreadable",
                       len((text or "").strip()), upload_id)
        _finish_failed(run, ERR_UNREADABLE)
        return
    run.advance(CLASSIFYING, char_count=len(text))

    from agents._run import run_agent_sync

    try:
        result, merged = run_agent_sync(_run_agents(row, text, run))
    except _Superseded:
        raise
    except Exception as exc:
        if budget_error_in(exc) is not None:
            logger.warning("document.process: LLM budget refused upload %s", upload_id)
            _finish_failed(run, ERR_BUDGET)
            return
        logger.exception("document.process: agent pipeline failed for upload %s", upload_id)
        _finish_failed(run, ERR_AGENT)
        return

    stored = {"result": result.model_dump(mode="json"),
              "categories": docs._grading_categories_from(result)}
    # Stored before the insert, so a re-run that adopts the saved row can
    # still answer with the full result and the syllabus categories.
    run.advance(SAVING, {"result": encrypt_json(stored)}, merged_count=merged)

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
        _finish_failed(run, ERR_PERSIST)
        return

    try:
        _done(run, doc_id, stored)
    except _Superseded:
        # The document is saved (a retry replays it); only the row's receipt
        # belongs to someone else now.
        logger.warning("document.process: upload %s saved as %s but the row moved on",
                       upload_id, doc_id)
    if fresh:
        _post_roll(docs, user_id=user_id, offering_id=offering_id, doc_id=doc_id)


def _done(run: _Run, doc_id: str, stored: dict, **progress: Any) -> None:
    run.advance(DONE, {
        "document_id": doc_id, "result": encrypt_json(stored),
        "file_data": None, "error_code": None,
    }, **progress)


async def _run_agents(row: dict, text: str, run: _Run):
    """The one upload pipeline (agents.document.run_document_agents, as the
    streaming route runs it), with each step recorded as the row's stage.
    Function mode serves the same handlers in the worker: it freezes the mode
    at boot like the API. Returns (result, merged concept count)."""
    from contextlib import aclosing

    from agents.deps import SaplingDeps
    from services import document_pipeline as dp

    deps = SaplingDeps(user_id=row["user_id"], course_id=row["course_id"], supabase=None,
                       request_id=row.get("request_id"))
    result, merged = None, 0
    async with aclosing(dp.run_document_agents(text, deps)) as steps:
        async for step in steps:
            if step.name == dp.CLASSIFIED:
                await asyncio.to_thread(run.advance, EXTRACTING_CONCEPTS, None,
                                        category=step.category, is_syllabus=step.is_syllabus)
            elif step.name == dp.EXTRACTED:
                await asyncio.to_thread(run.advance, MERGING, None,
                                        concept_count=step.concept_count)
            elif step.name == dp.DONE:
                result, merged = step.result, step.merged
    return result, merged


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
    must run the upload inline (this request took it back), or raises the
    HTTPException the inline route would have raised for the same failure.
    A duplicate of a request already running answers from that run's outcome
    — it never runs the pipeline (or its insert) a second time."""
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
        user_id = stage_kwargs["user_id"]
        stored = await _retrying(read_result, upload_id, default={})
        row = await _retrying(saved_document, doc_id, user_id) if doc_id else None
        if row is None:
            raise HTTPException(status_code=502, detail=docs.UPLOAD_FAILED_DETAIL)
        row["categories"] = stored.get("categories") or []
        await asyncio.to_thread(clear_result, upload_id)
        return row
    if outcome.kind == "timeout":
        raise HTTPException(status_code=504, detail=TIMEOUT_MESSAGE)
    code = (outcome.row or {}).get("error_code")
    if code == ERR_BUDGET:  # #119: the same 429 the inline route raises
        raise llm_budget.LLMBudgetExceeded(
            limit=None, used=None, reset_at=llm_budget.next_reset(), source="job",
        )
    if code in (ERR_UNREADABLE, ERR_EXTRACT):
        raise HTTPException(status_code=422, detail=_error_message(code))
    raise HTTPException(status_code=502, detail=docs.UPLOAD_FAILED_DETAIL)
