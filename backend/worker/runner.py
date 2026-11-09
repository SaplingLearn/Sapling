"""The worker loop: claim one job, run its handler, record the outcome (#116).

Kept free of process concerns (signals, config, logging setup) so the loop is
testable against a fake queue; `worker/__main__.py` is the process around it.

One job per claim, up to `batch` per pass, the same shape as the index
sweeper (services/index_sweeper.py): claiming a whole batch at once starts
every lease together, so the last jobs of a slow batch could outlive their
lease and be re-run by another worker while still queued here. The stop
signal is checked before every claim, so a SIGTERM lets the job in hand
finish and claims nothing after it.
"""
from __future__ import annotations

import logging
import threading
import time
from types import ModuleType
from typing import Any

from services import jobs as jobs_module
from services.jobs import Job, PermanentJobError

logger = logging.getLogger("sapling.worker")


class Worker:
    def __init__(
        self,
        *,
        worker_id: str,
        types: list[str],
        batch: int = 10,
        lease_seconds: int = jobs_module.DEFAULT_LEASE_SECONDS,
        poll_interval: float = 5.0,
        queue: ModuleType | Any = jobs_module,
        stop: threading.Event | None = None,
    ) -> None:
        if not types:
            raise ValueError("a worker needs at least one job type to claim")
        self.worker_id = worker_id
        self.types = list(types)
        self.batch = max(1, int(batch))
        self.lease_seconds = int(lease_seconds)
        self.poll_interval = float(poll_interval)
        self.queue = queue
        self.stop = stop or threading.Event()

    # ── one pass ────────────────────────────────────────────────────────────

    def run_once(self) -> int:
        """Claim and run up to `batch` jobs, one at a time. Returns how many
        were claimed. Never raises: a failed claim ends the pass."""
        handled = 0
        for _ in range(self.batch):
            if self.stop.is_set():
                break
            try:
                claimed = self.queue.claim(
                    self.worker_id, types=self.types, limit=1,
                    lease_seconds=self.lease_seconds,
                )
            except Exception:
                logger.warning("job.claim_failed worker=%s", self.worker_id, exc_info=True)
                break
            if not claimed:
                break
            for job in claimed:
                self._run(job)
                handled += 1
        return handled

    def _run(self, job: Job) -> None:
        # jobs.current_job(): lets a handler fence its writes on this claim.
        token = jobs_module._CURRENT_JOB.set(job)
        try:
            self._run_job(job)
        finally:
            jobs_module._CURRENT_JOB.reset(token)

    def _run_job(self, job: Job) -> None:
        fields = (job.id, job.type, job.attempt, job.max_attempts)
        logger.info("job.claimed id=%s type=%s attempt=%d/%d", *fields)
        handler = self.queue.get_handler(job.type)
        started = time.monotonic()
        if handler is None:
            # Retried with backoff rather than dead-lettered at once: during a
            # rolling deploy a worker that knows the type may be seconds away.
            self._fail(job, f"no handler registered for job type {job.type!r}",
                       permanent=False, started=started)
            return
        try:
            handler(job.payload)
        except PermanentJobError as exc:
            self._fail(job, _describe(exc), permanent=True, started=started)
            return
        except Exception as exc:
            logger.warning("job.handler_raised id=%s type=%s", job.id, job.type, exc_info=True)
            self._fail(job, _describe(exc), permanent=False, started=started)
            return
        ms = int((time.monotonic() - started) * 1000)
        try:
            ok = self.queue.complete(job)
        except Exception:
            # The row stays `running` until its lease runs out, then is offered
            # again: at-least-once, which is why handlers must be re-runnable.
            logger.exception("job.complete_failed id=%s type=%s", job.id, job.type)
            return
        if ok:
            logger.info("job.succeeded id=%s type=%s attempt=%d duration_ms=%d",
                        job.id, job.type, job.attempt, ms)
        else:
            logger.warning("job.lease_lost id=%s type=%s attempt=%d duration_ms=%d "
                           "(re-claimed after its lease ran out; that run decides it)",
                           job.id, job.type, job.attempt, ms)

    def _fail(self, job: Job, error: str, *, permanent: bool, started: float) -> None:
        ms = int((time.monotonic() - started) * 1000)
        try:
            status = self.queue.fail(job, error, permanent=permanent)
        except Exception:
            logger.exception("job.fail_failed id=%s type=%s", job.id, job.type)
            return
        if status is None:
            logger.warning("job.lease_lost id=%s type=%s attempt=%d duration_ms=%d",
                           job.id, job.type, job.attempt, ms)
            return
        log = logger.error if status == "dead" else logger.warning
        log("job.%s id=%s type=%s attempt=%d/%d duration_ms=%d error=%s",
            status, job.id, job.type, job.attempt, job.max_attempts, ms, error)

    # ── the loop ────────────────────────────────────────────────────────────

    def run_forever(self) -> None:
        """Pass after pass until `stop` is set. A full pass goes straight into
        the next (there is likely more waiting); a short one sleeps
        `poll_interval`, waking at once on stop."""
        logger.info(
            "worker.started id=%s types=%s batch=%d lease_s=%d poll_s=%.1f",
            self.worker_id, ",".join(self.types), self.batch,
            self.lease_seconds, self.poll_interval,
        )
        while not self.stop.is_set():
            try:
                handled = self.run_once()
            except Exception:
                # run_once does not raise by contract; this keeps one surprise
                # from ending the worker.
                logger.exception("worker.pass_raised id=%s", self.worker_id)
                handled = 0
            if handled < self.batch:
                self.stop.wait(self.poll_interval)
        logger.info("worker.stopped id=%s", self.worker_id)


def _describe(exc: BaseException) -> str:
    text = f"{type(exc).__name__}: {exc}"
    return text[: jobs_module.MAX_ERROR_CHARS]
