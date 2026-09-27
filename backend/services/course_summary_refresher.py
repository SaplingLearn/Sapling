"""Writes the class summary prose off every request path (spec §13 A35).

With the learning loop on, every graded answer flushes evidence through
`apply_graph_update`, which refreshes the class aggregates of each of the
student's offerings of that course. Regenerating the offering's prose there
put a gemini-2.5-flash call on the answer path for every offering, on every
answer (the 2026-09-27 live sequence test: 84% of a run's cost). So in that
regime `update_course_context` writes numbers only, and this lifespan task
runs `course_context_service.refresh_stale_summaries` once per
`config.COURSE_SUMMARY_REFRESH_INTERVAL_S`: one call per offering whose summary
no longer says what its numbers say, at most `config.COURSE_SUMMARY_REFRESH_BATCH`
per pass per process.

Off when the loop is off: the pre-series regime writes its prose inline.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging

import config
from services.course_context_service import refresh_stale_summaries

logger = logging.getLogger(__name__)

_task: asyncio.Task | None = None


def refresher_enabled() -> bool:
    """On exactly when the loop regime is: `update_course_context` then writes
    no prose, so nothing else would."""
    return config.LEARNING_LOOP_ENABLED


async def _loop() -> None:
    # Sleep FIRST: a deploy restarts every instance at once, and nothing is
    # lost by waiting one interval (the prose is not on any request path).
    while True:
        await asyncio.sleep(config.COURSE_SUMMARY_REFRESH_INTERVAL_S)
        try:
            written = await asyncio.to_thread(refresh_stale_summaries)
            if written:
                logger.info("course summary refresher rewrote %d summary(ies)", written)
        except Exception:
            # refresh_stale_summaries logs per-offering failures itself; this
            # backstop keeps one failed read from ending the task.
            logger.warning("course summary refresh pass raised; the loop continues", exc_info=True)


def start_refresher() -> None:
    """Start the loop on the running event loop. Called from the app lifespan."""
    global _task
    if not refresher_enabled():
        logger.info("course summary refresher not started (learning loop off)")
        return
    if _task is None or _task.done():
        _task = asyncio.get_running_loop().create_task(_loop(), name="course-summary-refresher")
        logger.info(
            "course summary refresher started (every %ss, batch %d)",
            config.COURSE_SUMMARY_REFRESH_INTERVAL_S,
            config.COURSE_SUMMARY_REFRESH_BATCH,
        )


async def stop_refresher() -> None:
    """Cancel the loop. Safe when it never started."""
    global _task
    task, _task = _task, None
    if task is None:
        return
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task
