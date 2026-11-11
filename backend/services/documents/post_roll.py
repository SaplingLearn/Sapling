"""
backend/services/documents/post_roll.py

An upload's best-effort side effects after the document is saved (#118,
moved from routes/documents.py): study-guide cache invalidation, the
course-context refresh, the achievement check, and the SSE route's
fire-and-forget post-roll tasks with their shutdown drain.
"""
from __future__ import annotations

import asyncio
import logging

from db.connection import table
from services.achievement_service import check_achievements
from services.course_context_service import refresh_course_context

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
        logger.warning("documents_uploaded achievement check failed", exc_info=True)


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
