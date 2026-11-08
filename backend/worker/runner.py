"""The worker loop: claim one job, run its handler, record the outcome (#116).

Kept free of process concerns (signals, config, logging setup) so the loop is
testable against a fake queue; `worker/__main__.py` is the process around it.

One job per claim, up to `batch` per pass, the same shape as the index
sweeper (services/index_sweeper.py): claiming a whole batch at once starts
every lease together, so the last jobs of a slow batch could outlive their
lease and be re-run by another worker while still queued here. The stop
signal is checked before every claim, so a SIGTERM lets the job in hand
finish and claims nothing after it.

While a handler runs, a heartbeat thread pushes the job's lease forward
(services/jobs.py::heartbeat), so a job that legitimately takes longer than
one lease (a 50-page OCR) is not handed to a second worker mid-run.

The lease rule (services/jobs.py MIN_LEASE_SECONDS): claim_jobs re-offers a
running job once `locked_at + <the CLAIMER's lease>` has passed, so a beat
protects a job only from claimers whose lease is longer than the gap between
beats. Hence every worker (a) refuses a lease under MIN_LEASE_SECONDS and (b)
beats every HEARTBEAT_INTERVAL_SECONDS = MIN_LEASE_SECONDS / 3 whatever its own
lease is: no worker in the fleet can then see a live job as expired, even with
two beats lost.

Once a heartbeat reports the claim lost it stops. The fenced complete/fail is
still attempted (a reaped `dead` row accepts it; a re-claimed one refuses it),
and a refusal is warned about once, not twice. It also stops after
`max_heartbeat_seconds`, so a HUNG handler still loses its job to another
worker one lease later, as it did before heartbeats existed.

Upkeep: a worker that claims `jobs.prune` calls services/jobs.py::
schedule_prune every `prune_interval` seconds, which enqueues a prune only
when none is pending and none succeeded within the interval (and dedupes on an
hourly key), so N replicas give about one run per interval. A run deletes old
`succeeded` rows, and the terminal rows of the upload/sync staging tables, in
bounded batches.
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
        heartbeat_interval: float | None = None,
        prune_interval: float = jobs_module.PRUNE_INTERVAL_SECONDS,
        prune_after_days: int = jobs_module.PRUNE_AFTER_DAYS,
        max_heartbeat_seconds: float = jobs_module.MAX_HEARTBEAT_SECONDS,
    ) -> None:
        if not types:
            raise ValueError("a worker needs at least one job type to claim")
        # Fleet-wide lease rule (module docstring): refuse a lease other
        # workers' heartbeats cannot outpace.
        jobs_module.check_lease(lease_seconds)
        self.worker_id = worker_id
        self.types = list(types)
        self.batch = max(1, int(batch))
        self.lease_seconds = int(lease_seconds)
        self.poll_interval = float(poll_interval)
        self.queue = queue
        self.stop = stop or threading.Event()
        # A third of the FLEET minimum lease, not of this worker's own: any
        # worker may claim with MIN_LEASE_SECONDS, so two beats can be lost (a
        # PostgREST blip) before any claimer sees the job as expired. An
        # explicit interval is capped at that; <= 0 turns the heartbeat off.
        cap = jobs_module.HEARTBEAT_INTERVAL_SECONDS
        self.heartbeat_interval = (
            cap if heartbeat_interval is None else min(float(heartbeat_interval), cap)
        )
        self.max_heartbeat_seconds = float(max_heartbeat_seconds)
        self.prune_interval = float(prune_interval)
        # 0 (or less) = never schedule a prune from this worker.
        self.prune_after_days = int(prune_after_days)
        self._next_upkeep = 0.0

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
        # A refused heartbeat (`beat.lost`) does NOT skip the fenced
        # complete/fail below: "refused" is either a re-claim (the fenced write
        # is refused too, harmlessly) or the reap to `dead` on a last attempt,
        # where complete_job/fail_job still ACCEPT the same fence so the row
        # records how the attempt really ended (20261108095241). What `lost`
        # changes is the logging: the heartbeat already warned, so a refused
        # outcome is not warned about twice.
        beat = _Heartbeat(self.queue, job, self.heartbeat_interval, self.max_heartbeat_seconds)
        try:
            with beat:
                handler(job.payload)
        except PermanentJobError as exc:
            self._fail(job, _describe(exc), permanent=True, started=started,
                       lease_lost_logged=beat.lost)
            return
        except Exception as exc:
            logger.warning("job.handler_raised id=%s type=%s", job.id, job.type, exc_info=True)
            self._fail(job, _describe(exc), permanent=False, started=started,
                       lease_lost_logged=beat.lost)
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
            _log_lease_lost(job, ms, already_logged=beat.lost,
                            note="re-claimed after its lease ran out; that run decides it")

    def _fail(self, job: Job, error: str, *, permanent: bool, started: float,
              lease_lost_logged: bool = False) -> None:
        ms = int((time.monotonic() - started) * 1000)
        try:
            status = self.queue.fail(job, error, permanent=permanent)
        except Exception:
            logger.exception("job.fail_failed id=%s type=%s", job.id, job.type)
            return
        if status is None:
            _log_lease_lost(job, ms, already_logged=lease_lost_logged)
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
            self._upkeep()
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


    # ── upkeep ──────────────────────────────────────────────────────────────

    def _upkeep(self) -> None:
        """At most once per `prune_interval`: make sure a prune run is queued.
        Only on a worker that claims `jobs.prune` (it would otherwise queue
        work it never runs), and never raises."""
        if (self.prune_after_days <= 0 or jobs_module.PRUNE_JOB_TYPE not in self.types
                or time.monotonic() < self._next_upkeep):
            return
        self._next_upkeep = time.monotonic() + self.prune_interval
        schedule = getattr(self.queue, "schedule_prune", None)
        if schedule is None:
            return
        try:
            schedule(self.prune_after_days)
        except Exception:
            logger.warning("job.prune_schedule_failed worker=%s", self.worker_id, exc_info=True)


class _Heartbeat:
    """Context manager: beat `job`'s lease every `interval` seconds on a
    daemon thread until the block exits. A failed beat (exception) is logged
    and retried next interval; a refused one (the claim is gone) sets `lost`
    and ends it, and so does running past `max_seconds` (a hung handler must
    not hold its job forever). The worker reads `lost` after the handler so a
    refused outcome write is not warned about a second time."""

    def __init__(self, queue: Any, job: Job, interval: float,
                 max_seconds: float = float("inf")) -> None:
        self._beat = getattr(queue, "heartbeat", None)
        self._job = job
        self._interval = interval
        self._max_seconds = max_seconds
        self._done = threading.Event()
        self._thread: threading.Thread | None = None
        self.lost = False

    def __enter__(self) -> "_Heartbeat":
        if self._beat is not None and self._interval > 0:
            self._thread = threading.Thread(
                target=self._loop, name=f"job-heartbeat-{self._job.id}", daemon=True)
            self._thread.start()
        return self

    def __exit__(self, *_exc) -> None:
        self._done.set()
        if self._thread is not None:
            # A beat in flight finishes on its own (it is fenced, so a late one
            # is harmless); do not hold the worker for it.
            self._thread.join(timeout=5)

    def _loop(self) -> None:
        job = self._job
        started = time.monotonic()
        while not self._done.wait(self._interval):
            if time.monotonic() - started >= self._max_seconds:
                logger.error("job.heartbeat_gave_up id=%s type=%s attempt=%d after %.0fs: "
                             "the lease will lapse and the job be offered again",
                             job.id, job.type, job.attempt, self._max_seconds)
                return
            try:
                ok = self._beat(job)
            except Exception:
                logger.warning("job.heartbeat_failed id=%s type=%s", job.id, job.type,
                               exc_info=True)
                continue
            if ok is not True:
                self.lost = True
                logger.warning("job.lease_lost id=%s type=%s attempt=%d (heartbeat refused: "
                               "re-claimed or reaped; this run's outcome will not be recorded)",
                               job.id, job.type, job.attempt)
                return


def _log_lease_lost(job: Job, ms: int, *, already_logged: bool, note: str = "") -> None:
    """The fenced outcome write was refused. WARNING once per lost claim: when
    the heartbeat already warned (`already_logged`), this is only INFO."""
    log = logger.info if already_logged else logger.warning
    log("job.lease_lost id=%s type=%s attempt=%d duration_ms=%d%s",
        job.id, job.type, job.attempt, ms, f" ({note})" if note else "")


def _describe(exc: BaseException) -> str:
    text = f"{type(exc).__name__}: {exc}"
    return text[: jobs_module.MAX_ERROR_CHARS]
