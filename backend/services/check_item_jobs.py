"""Upload-time check-item drafting on the job queue (#116 x learning-loop PKG-04).

With the learning loop on, an upload's indexing and its check-item drafting
run as ONE ordered task (`services/documents/post_roll.py::_index_then_check_items`):
the items cite the chunks indexing writes, and the A23 source rule reads
their visibility. With the `jobs_queue` flag on for the uploader that task
moves to the worker, as `document.index` does for the loop-off upload
(`services/document_indexing.py::schedule_document_index`): one
``check_items.document`` job, whose handler runs the same chain
(`services/documents/post_roll.py::_index_then_draft`) — indexing, then the drafting on
the job's own thread.

Flag off (the default) nothing here runs: `enqueue_for_document` says no and
the upload's post-roll runs the chain in-process, unchanged. An enqueue that
fails runs it in-process too, so turning the flag on never skips an upload's
drafting.

The payload is ids only (the queue's rule: `jobs.payload` is plaintext). The
concept names the drafting needs are read back from the document's own
encrypted `concept_notes`, which the upload stored in the same order the
in-process path passes them.

Delivery is at least once. A re-run is safe: `index_document` claims the row
(a finished or held row does nothing), and drafting skips every concept that
already has its items. A drafting failure is logged and recorded on the
document (`documents.check_items_status`) exactly where the in-process path
records it; the job completes, as `document.process` completes on a
pipeline failure. Nothing schedules a re-run of a `failed` or `unavailable`
document: `scripts/backfill_check_items.py` (spec §11.7) drafts what a run
left, run by hand (no job or workflow runs it).

The per-user LLM budget (#119): the work is the uploader's (llm_usage rows are
attributed to them, `acting_for`), and it is post-response background work, so
the token budget never refuses a request mid-run (`llm_budget.background_work`)
— as in-process, where it rides the upload request's own budget decision. The
uploader's GENERATION budget (`ai_budget.check(..., "generation")`, a fresh
read) is asked once per document before its drafting starts, on every path
(`within_generation_budget`, Z20): a hard-capped student, or an unreadable
ledger, drafts nothing — the document is indexed, its `pending` mark is taken
back, and draft on enable claims it once the budget has room.

The loop gate is the uploader's AT RUN TIME too: the job re-reads it
(`learning_loop_for_uploader`) before drafting, so the env kill switch or the
uploader's flag turned off after the enqueue drafts nothing — the document is
indexed (indexing is the upload's, whatever the loop says) and its `pending`
mark is taken back.

Draft on enable (owner decision, PR #866 C3): an upload made while the loop
was off for its uploader drafted nothing, so a student who gets the loop
later had no check items to be checked on. `draft_missing_for_course` runs
when they start or reopen a loop session for a course: it claims their
undrafted uploads in it (`check_item_service.claim_undrafted_documents`, the
`pending` mark the loop's "preparing" state reads) and schedules each on this
same job path — deduped per document, at most ENABLE_MAX_DOCS a scan, a scan
at most once per ENABLE_RESCAN_S per student and course in a process, never
past the student's generation budget (`ai_budget.check(..., "generation")`),
and the drafting itself always off the request thread.
"""
from __future__ import annotations

import functools
import logging
import threading
import time
from concurrent.futures import Future

import httpx

from db.connection import table
from learning.gate import learning_loop_for_uploader
from services import ai_budget, jobs
from services.encryption import bind, decrypt_json
from services.feature_flags import flag_on

logger = logging.getLogger(__name__)

CHECK_ITEMS_DOCUMENT_JOB = "check_items.document"

#: Draft on enable: how long one process waits before it scans one student's
#: course again. The claim is the cross-process guard (a claimed document is
#: never claimed twice); this keeps a session start or list from reading
#: documents on every request.
ENABLE_RESCAN_S = 15 * 60
#: Draft on enable: documents claimed per scan. Each is minutes of Flex
#: drafting; the next scan of the course (ENABLE_RESCAN_S later) claims more.
ENABLE_MAX_DOCS = 5
#: What a failed scan can raise: PostgREST/network errors (httpx, the
#: db_user_scope refusals), and a malformed answer. Anything else is a bug.
_STORE_FAILURES = (httpx.HTTPError, RuntimeError, ValueError)
#: A memory bound on the rescan clock, not a policy.
_SCANS_MAX = 4096
_scans: dict[tuple[str, str], float] = {}
_scans_lock = threading.Lock()


def _dedupe_key(doc_id: str) -> str:
    return f"{CHECK_ITEMS_DOCUMENT_JOB}:{doc_id}"


def enqueue_for_document(doc_id: str, *, user_id: str, course_id: str) -> bool:
    """Hand the upload's index-then-draft chain to the worker. True when it was
    enqueued; False when `jobs_queue` is off for the uploader or the enqueue
    failed — the caller then runs the chain itself."""
    if not flag_on(jobs.JOBS_QUEUE_FLAG, user_id):
        return False
    try:
        jobs.enqueue(
            CHECK_ITEMS_DOCUMENT_JOB,
            {"doc_id": doc_id, "user_id": user_id, "course_id": course_id},
            dedupe_key=_dedupe_key(doc_id),
        )
        return True
    except Exception:
        logger.warning(
            "check items: enqueue failed for doc %s; indexing and drafting in-process",
            doc_id, exc_info=True,
        )
        return False


def _concept_names(doc_id: str) -> list[str] | None:
    """The upload's concept names, from the document's stored concept_notes;
    None when the document is gone (deleted, or its account)."""
    rows = table("documents").select(
        "id,concept_notes", filters={"id": f"eq.{doc_id}", "deleted_at": "is.null"}, limit=1,
    )
    if not rows:
        return None
    raw = rows[0].get("concept_notes")
    try:
        notes = (decrypt_json(raw, bind=bind("documents", "concept_notes", rows[0]))
                 if isinstance(raw, str) else (raw or []))
    except Exception:
        logger.warning("check items: concept notes of doc %s unreadable; drafting none", doc_id)
        notes = []
    names = [n.get("name") for n in notes if isinstance(n, dict)] if isinstance(notes, list) else []
    return [n for n in names if isinstance(n, str) and n.strip()]


def _draft_document(doc_id: str, user_id: str, course_id: str) -> None:
    """One document's index-then-draft chain for its uploader — the job's
    body, and the in-process fallback's: the loop gate re-read NOW (off: index
    only, and the `pending` mark taken back), then the concept names, then
    the chain under the uploader's attribution, never refused by the budget.
    Only an unreadable document row, or (loop off) a failed indexing, raises;
    every step of the chain logs its own failure."""
    from services import documents  # lazy: its post-roll imports this module
    from services import llm_budget
    from services.check_item_service import clear_drafting
    from services.request_context import acting_for

    if not learning_loop_for_uploader(user_id):
        logger.info("check_items.document: the loop is off for the uploader of doc %s; "
                    "indexing only, nothing drafted", doc_id)
        from services.document_indexing import index_document

        clear_drafting(doc_id)
        # A failure raises: the queue retries the job (index_document claims
        # the row, so a retry is safe), and the sweeper re-drives the row anyway.
        with acting_for(user_id), llm_budget.background_work():
            index_document(doc_id)
        return
    names = _concept_names(doc_id)
    if names is None:
        logger.info("check_items.document: doc %s is gone; nothing to index or draft", doc_id)
        return
    with acting_for(user_id), llm_budget.background_work():
        documents._index_then_draft(doc_id, user_id, course_id, names)


@jobs.job_handler(CHECK_ITEMS_DOCUMENT_JOB)
def _run_check_items_document_job(payload: dict) -> None:
    """Worker side of `enqueue_for_document`: the in-process chain, run for
    the uploader (`_draft_document`). Only an unreadable document row, or
    with the loop off a failed indexing, raises (the queue retries those)."""
    payload = payload or {}
    doc_id, user_id, course_id = (payload.get(k) for k in ("doc_id", "user_id", "course_id"))
    if not all(isinstance(v, str) and v for v in (doc_id, user_id, course_id)):
        raise jobs.PermanentJobError("check_items.document: payload needs doc_id, user_id, course_id")
    _draft_document(doc_id, user_id, course_id)


# ── draft on enable (C3) ─────────────────────────────────────────────────────


def reset_enable_scans() -> None:
    """Forget every rescan clock (tests)."""
    with _scans_lock:
        _scans.clear()


def _scan_due(user_id: str, course_id: str) -> bool:
    """True, and the clock restarted, when this process has not scanned the
    student's course within ENABLE_RESCAN_S."""
    now = time.monotonic()
    key = (user_id, course_id)
    with _scans_lock:
        last = _scans.get(key)
        if last is not None and now - last < ENABLE_RESCAN_S:
            return False
        if len(_scans) >= _SCANS_MAX:
            for stale in [k for k, at in _scans.items() if now - at >= ENABLE_RESCAN_S]:
                del _scans[stale]
            while len(_scans) >= _SCANS_MAX:
                del _scans[next(iter(_scans))]
        _scans.pop(key, None)
        _scans[key] = now
        return True


def within_generation_budget(user_id: str) -> bool:
    """The student's generation budget has room (the hard level, or a usage
    read that failed, schedules nothing: no evidence of room, no spend)."""
    try:
        return ai_budget.check(user_id, "generation").level != "hard"
    except (ai_budget.AIBudgetUnavailable, ai_budget.AIBudgetExceeded) as exc:
        logger.info("check items: no draft on enable for %s (%s)", user_id, type(exc).__name__)
        return False


def _log_failure(doc_id: str, future: Future) -> None:
    exc = None if future.cancelled() else future.exception()
    if exc is not None:
        logger.error("check items: draft on enable failed for doc %s", doc_id, exc_info=exc)


def _draft_in_process(doc_id: str, user_id: str, course_id: str) -> Future | None:
    """The fallback when the queue does not take a document: the same chain,
    on check_item_service's bounded drafting pool (never the request's thread
    or the event loop); a failure is logged off the pool. A drafting the app's
    shutdown dropped has its mark taken back (`shutdown_draft_pool`), and the
    next scan claims the document again."""
    from services.check_item_service import clear_drafting, submit_drafting

    future = submit_drafting(user_id, doc_id, _draft_document, doc_id, user_id, course_id)
    if future is None:
        # Z21: the uploader already holds their places on the pool; the next
        # scan claims this document again
        clear_drafting(doc_id)
        return None
    future.add_done_callback(functools.partial(_log_failure, doc_id))
    return future


def draft_missing_for_course(
    user_id: str, course_id: str, *, offerings: list[str] | None = None,
) -> int:
    """Draft on enable (module docstring): schedule the drafting of the
    student's uploads in `course_id` that no run has covered, on the
    `check_items.document` path. Call it where a loop session for the course
    starts or reopens, with the loop on for the student. Returns how many
    documents it scheduled. `offerings`: the course's offering ids, when the
    caller already read them. A store failure is logged and schedules
    nothing: drafting is the course's background work, and a session must
    open whatever it meets."""
    if not user_id or not course_id or not _scan_due(user_id, course_id):
        return 0
    from services.check_item_service import claim_undrafted_documents

    try:
        claimed = claim_undrafted_documents(
            user_id, course_id, limit=ENABLE_MAX_DOCS, offerings=offerings,
            may_draft=lambda: within_generation_budget(user_id),
        )
    except _STORE_FAILURES as exc:
        logger.warning("check items: draft on enable could not scan course %s for %s (%s)",
                       course_id, user_id, type(exc).__name__)
        return 0
    for doc_id in claimed:
        # enqueue_for_document never raises (a failed enqueue answers False)
        if enqueue_for_document(doc_id, user_id=user_id, course_id=course_id):
            continue
        try:
            _draft_in_process(doc_id, user_id, course_id)
        except RuntimeError as exc:  # the pool is shutting down with the app
            logger.warning("check items: draft on enable could not queue doc %s (%s); its "
                           "mark expires and a later scan claims it", doc_id, type(exc).__name__)
    if claimed:
        logger.info("check items: draft on enable scheduled %d document(s) of course %s",
                    len(claimed), course_id)
    return len(claimed)
