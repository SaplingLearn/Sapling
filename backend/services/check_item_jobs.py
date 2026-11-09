"""Upload-time check-item drafting on the job queue (#116 x learning-loop PKG-04).

With the learning loop on, an upload's indexing and its check-item drafting
run as ONE ordered task (`routes/documents.py::_index_then_check_items`):
the items cite the chunks indexing writes, and the A23 source rule reads
their visibility. With the `jobs_queue` flag on for the uploader that task
moves to the worker, as `document.index` does for the loop-off upload
(`services/document_indexing.py::schedule_document_index`): one
``check_items.document`` job, whose handler runs the same chain
(`routes/documents.py::_index_then_draft`) — indexing, then the drafting on
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
pipeline failure — the nightly backfill (spec §11.7) drafts what a run left.

The per-user LLM budget (#119): the work is the uploader's (llm_usage rows are
attributed to them, `acting_for`), and it is post-response background work, so
the budget never refuses it (`llm_budget.background_work`) — as in-process,
where it rides the upload request's own budget decision.
"""
from __future__ import annotations

import logging

from db.connection import table
from services import jobs
from services.encryption import decrypt_json
from services.feature_flags import flag_on

logger = logging.getLogger(__name__)

CHECK_ITEMS_DOCUMENT_JOB = "check_items.document"


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
        notes = decrypt_json(raw) if isinstance(raw, str) else (raw or [])
    except Exception:
        logger.warning("check items: concept notes of doc %s unreadable; drafting none", doc_id)
        notes = []
    names = [n.get("name") for n in notes if isinstance(n, dict)] if isinstance(notes, list) else []
    return [n for n in names if isinstance(n, str) and n.strip()]


@jobs.job_handler(CHECK_ITEMS_DOCUMENT_JOB)
def _run_check_items_document_job(payload: dict) -> None:
    """Worker side of `enqueue_for_document`: the in-process chain, run for
    the uploader. Only an unreadable document row raises (the queue retries
    that); every step of the chain logs its own failure."""
    payload = payload or {}
    doc_id, user_id, course_id = (payload.get(k) for k in ("doc_id", "user_id", "course_id"))
    if not all(isinstance(v, str) and v for v in (doc_id, user_id, course_id)):
        raise jobs.PermanentJobError("check_items.document: payload needs doc_id, user_id, course_id")
    names = _concept_names(doc_id)
    if names is None:
        logger.info("check_items.document: doc %s is gone; nothing to index or draft", doc_id)
        return
    from routes import documents  # lazy: the route module imports this one
    from services import llm_budget
    from services.request_context import acting_for

    with acting_for(user_id), llm_budget.background_work():
        documents._index_then_draft(doc_id, user_id, course_id, names)
