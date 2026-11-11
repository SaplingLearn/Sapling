"""
backend/services/documents/post_roll.py

An upload's best-effort side effects after the document is saved (#118,
moved from routes/documents.py): study-guide cache invalidation, the
course-context refresh, the achievement check, the indexing — with the
learning loop on, the ordered index-then-draft check-item chain (PKG-04,
`_index_then_check_items`; the `check_items.document` job's body is
`_index_then_draft`) — and the SSE route's fire-and-forget post-roll tasks
with their shutdown drain.
"""
from __future__ import annotations

import asyncio
import logging

import config
from agents._providers import model_mode
from db.connection import table
from services import check_item_jobs, jobs
from services.achievement_service import check_achievements
from services.check_item_service import (
    DRAFTING_FAILED,
    DRAFTING_PENDING,
    drafting_flags,
    generate_for_document,
    mark_drafting,
    queue_generation_for_document,
)
from services.course_context_service import refresh_course_context
from services.document_indexing import index_document, schedule_document_index

logger = logging.getLogger(__name__)


def _invalidate_study_guide_cache(user_id: str, offering_id: str) -> None:
    """Background task: delete cached study guides so they regenerate fresh.

    Study guides key on the offering (0025), matching the documents that
    feed them.
    """
    try:
        table("study_guides").delete(
            filters={"user_id": f"eq.{user_id}", "offering_id": f"eq.{offering_id}"}
        )
    except Exception:
        logger.exception(
            "Failed to invalidate study guides cache for user=%s offering=%s",
            user_id, offering_id,
        )


def _refresh_course_context(offering_id: str, user_id: str) -> None:
    """Post-upload class-aggregate refresh: inline, or a queued job when the
    `jobs_queue` flag is on for the uploader (#116)."""
    refresh_course_context(offering_id, user_id=user_id)


def _check_upload_achievements(user_id: str) -> None:
    """Background task: best-effort achievement check."""
    try:
        check_achievements(user_id, "documents_uploaded", {})
    except Exception:
        pass


async def _stream_index_steps(
    doc_id: str, user_id: str, course_id: str, concept_names: list[str]
) -> list[tuple]:
    """The streaming upload's indexing post-roll step(s). #482: the id only —
    the indexer reads everything else off the stored row, which is what lets
    the sweeper re-drive this same work if the attempt dies with the process.

    Learning loop PKG-04: with the loop on, index then draft check items from
    the chunks it wrote — one ordered task (see upload_document_sync). In
    function mode (the E2E lane) post-response handlers stay unregistered, so
    the chain runs inline here with the check_items handler, and no step is
    left to spawn."""
    if not config.LEARNING_LOOP_ENABLED:
        return [("index_document", schedule_document_index, doc_id, user_id)]
    if model_mode() == "function":
        await asyncio.to_thread(
            _index_then_check_items, doc_id, user_id, course_id, concept_names
        )
        return []
    return [(
        "index_then_check_items", _index_then_check_items,
        doc_id, user_id, course_id, concept_names,
    )]


def _index_then_check_items(
    doc_id: str, user_id: str, course_id: str, concept_names: list[str]
) -> None:
    """PKG-04: check items cite the chunks indexing writes (and the A23 source
    rule reads their visibility), so the two run in ORDER inside one post-roll
    task. Only scheduled when LEARNING_LOOP_ENABLED; the flag-off path still
    schedules the indexing alone (`schedule_document_index`, byte-identical).

    #116: with `jobs_queue` on for the uploader the whole chain moves to the
    worker as ONE `check_items.document` job (services/check_item_jobs.py),
    which runs `_index_then_draft` there: the same two steps in the same
    order. Off — or when the enqueue fails — it runs here, as before #116.

    A128: the document's drafting status is `pending` from the first line —
    indexing included, since the student waits on both — until the drafting
    run records how it ended (`generate_for_document`); a queue that refuses
    the run records `failed`."""
    mark_drafting(doc_id, DRAFTING_PENDING)
    if check_item_jobs.enqueue_for_document(doc_id, user_id=user_id, course_id=course_id):
        return
    _index_then_draft(doc_id, user_id, course_id, concept_names)


def _index_then_draft(
    doc_id: str, user_id: str, course_id: str, concept_names: list[str]
) -> None:
    """The chain `_index_then_check_items` hands off (inline, or as the
    `check_items.document` job's body on the worker).

    Indexing runs here. The drafting — minutes of Flex calls — is QUEUED on
    check_item_service's own bounded pool in real mode, so it never holds the
    shared worker thread this runs on (the loop's default executor for the
    SSE route, Starlette's request threadpool for /upload/sync). In function
    mode the route runs this inline and the drafting runs here too, so the
    upload returns with its items (the E2E lane). Inside a job handler (#116)
    the drafting runs here as well: the worker IS the background, the job's
    lease and heartbeat cover the run, and the worker has no shutdown hook to
    drop a pool's queue.

    Each step is logged, never raised: an indexing failure leaves the document
    unindexed (the sweeper re-drives it) and drafting then falls back to its
    extracted text (A128: its items are stored `unsourced`); a drafting
    failure must not fail the upload that runs this inline in function mode,
    nor the job that runs it on the worker."""
    try:
        index_document(doc_id)
    except Exception:
        logger.exception("Indexing doc %s before check items failed", doc_id)
    here = model_mode() == "function" or jobs.current_job() is not None
    try:
        # spec §13 A140/A141: the uploader's drafting flags, resolved ONCE for
        # this run; with both off the call is exactly the one it always was
        flags = drafting_flags(user_id)
        extra = {"flags": flags} if any(flags) else {}
        if here:
            generate_for_document(
                doc_id, user_id=user_id, course_id=course_id,
                concept_names=concept_names, flex=True, **extra,
            )
        else:
            queue_generation_for_document(
                doc_id, user_id=user_id, course_id=course_id, concept_names=concept_names,
                **extra,
            )
    except Exception:
        logger.exception("Check items for doc %s failed", doc_id)
        if not here:
            # the run never started (generate_for_document marks its own end)
            mark_drafting(doc_id, DRAFTING_FAILED)


#: In-flight post-roll tasks (#759). The event loop holds only a WEAK
#: reference to a task, so an unreferenced create_task result can be
#: garbage-collected mid-flight; this set is the strong reference. Each task
#: removes itself when done, and drain_post_roll waits on what remains.
_POST_ROLL_TASKS: set[asyncio.Task] = set()

#: Shutdown budget for drain_post_roll. The work is best-effort and
#: re-drivable (the index sweeper picks up an unindexed row), so this bounds
#: how long a deploy waits rather than guaranteeing completion.
POST_ROLL_DRAIN_TIMEOUT_S = 15.0


def _spawn_post_roll(*tasks: tuple) -> None:
    """Fire-and-forget post-roll work for SSE / non-FastAPI-BackgroundTasks
    contexts. Each tuple is (label, callable, *args). Exceptions in the
    spawned task are logged via a done-callback so they don't disappear
    silently the way bare asyncio.create_task(...) lets them; each task is
    held in _POST_ROLL_TASKS until it finishes.
    """
    for label, fn, *args in tasks:
        task = asyncio.create_task(asyncio.to_thread(fn, *args), name=f"post_roll:{label}")
        _POST_ROLL_TASKS.add(task)
        task.add_done_callback(_POST_ROLL_TASKS.discard)
        task.add_done_callback(lambda t, _label=label: _log_post_roll_exc(t, _label))


async def drain_post_roll(timeout: float = POST_ROLL_DRAIN_TIMEOUT_S) -> None:
    """Wait (bounded) for in-flight post-roll tasks — called from the app
    lifespan at shutdown so an upload's indexing / course-context refresh is
    not cut off by a deploy. Only this loop's tasks are awaited. Never raises.
    """
    try:
        loop = asyncio.get_running_loop()
        pending = [t for t in _POST_ROLL_TASKS if not t.done() and t.get_loop() is loop]
        if not pending:
            return
        _, still = await asyncio.wait(pending, timeout=timeout)
        if still:
            logger.warning(
                "%d upload post-roll task(s) still running after %.0fs at shutdown",
                len(still), timeout,
            )
    except Exception:
        logger.debug("post-roll drain failed", exc_info=True)


def _log_post_roll_exc(task: "asyncio.Task", label: str) -> None:
    if task.cancelled():
        return
    exc = task.exception()
    if exc is not None:
        logger.error("Post-roll task '%s' failed: %s", label, exc, exc_info=exc)
