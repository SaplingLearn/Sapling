"""`python -m worker` (run from `backend/`): drain the Postgres job queue (#116).

Boots like the API's lifespan does, minus the HTTP parts, and refuses to start
if any of it fails:
  1. freeze_model_mode()      the model mode is fixed for the process (#771)
  2. validate_config()        required secrets present (#174)
  3. verify_encryption_key()  ENCRYPTION_KEY belongs to this database (#742)
Then it imports the modules that register job handlers, starts the events
drain thread (handlers record LLM usage and events), and runs the loop until
SIGTERM or SIGINT. A signal lets the job in hand finish, claims nothing more,
flushes the events queue and exits 0. A boot failure exits 2.

Delivery is at least once (a crash or an outlived lease re-offers a job), so
handlers must be safe to re-run. While a handler runs its lease is heartbeated,
up to --max-heartbeat-seconds; there is no per-job timeout beyond that: a hung
handler holds its worker, and once the heartbeat gives up the job is offered to
another one lease later.

Lease rule (services/jobs.py MIN_LEASE_SECONDS, 300 s): a job is re-offered
once `locked_at + <the CLAIMING worker's lease>` has passed, so every worker
beats every MIN_LEASE_SECONDS / 3 regardless of its own lease, and a
--lease-seconds / JOBS_LEASE_SECONDS under the minimum is refused at boot
(exit 2). Then no worker in the fleet can re-claim a job another one is still
running. A longer lease is allowed; it only slows how soon THIS worker's
claims pick up a job whose heartbeat stopped.

Railway: the `worker` service in .railway/railway.ts (docs/deploy/railway.md).
  image           backend/Dockerfile, SAPLING_IMAGE_TARGET=worker (or full)
  start command   python -m worker   (WORKDIR is /app)
  env             references to every API variable a worker code path reads
                  (railway.ts SHARED_VARIABLES, pinned by
                  tests/test_railway_worker_env.py); no PORT, no healthcheck
  scaling         any number of replicas: claims use FOR UPDATE SKIP LOCKED
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import signal
import socket
import sys
import threading
import uuid
from pathlib import Path

#: Modules whose import registers job handlers (`@job_handler`). A new job
#: type's module goes here, or the worker never claims that type.
HANDLER_MODULES: tuple[str, ...] = (
    "services.course_context_service",  # course_context.refresh
    "services.document_indexing",       # document.index
    "services.document_jobs",           # document.process
)

EXIT_BOOT_FAILED = 2

logger = logging.getLogger("sapling.worker")


class _JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        out = {
            "ts": self.formatTime(record),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        if record.exc_info:
            out["exc"] = self.formatException(record.exc_info)
        return json.dumps(out, default=str)


def _configure_logging(fmt: str) -> None:
    handler = logging.StreamHandler(sys.stdout)
    if fmt == "json":
        handler.setFormatter(_JsonFormatter())
    else:
        handler.setFormatter(logging.Formatter(
            "%(asctime)s [%(levelname)s] %(name)s: %(message)s"))
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(logging.INFO)


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name) or default)
    except ValueError:
        return default


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    from services.jobs import (
        DEFAULT_LEASE_SECONDS,
        MAX_HEARTBEAT_SECONDS,
        MIN_LEASE_SECONDS,
        PRUNE_AFTER_DAYS,
    )

    p = argparse.ArgumentParser(prog="python -m worker", description=__doc__.split("\n")[0])
    p.add_argument("--poll-interval", type=float,
                   default=_env_float("JOBS_POLL_INTERVAL_SECONDS", 5.0),
                   help="seconds to sleep when the queue is empty (default 5)")
    p.add_argument("--batch", type=int, default=int(_env_float("JOBS_BATCH", 10)),
                   help="most jobs per pass, each claimed when its turn comes (default 10)")
    p.add_argument("--lease-seconds", type=int,
                   default=int(_env_float("JOBS_LEASE_SECONDS", DEFAULT_LEASE_SECONDS)),
                   help="how long a claim holds its job before it is re-offered "
                        f"(default {DEFAULT_LEASE_SECONDS}; at least {MIN_LEASE_SECONDS}, "
                        "or the worker refuses to start)")
    p.add_argument("--max-heartbeat-seconds", type=float,
                   default=_env_float("JOBS_MAX_HEARTBEAT_SECONDS", MAX_HEARTBEAT_SECONDS),
                   help="stop extending a running job's lease after this long, so a "
                        "hung handler's job is re-offered (default 3600)")
    # An env var/CLI knob, not a feature flag, on purpose: pruning succeeded
    # job rows past their retention is queue upkeep, not a product feature.
    # The prune never touches queued/failed/running or dead rows (prune_jobs
    # deletes only `succeeded`), no student sees it, and 0 turns it off.
    p.add_argument("--prune-after-days", type=int,
                   default=int(_env_float("JOBS_PRUNE_AFTER_DAYS", PRUNE_AFTER_DAYS)),
                   help="delete succeeded jobs older than this many days, from an "
                        "hourly jobs.prune run (default 14; 0 = never schedule one)")
    p.add_argument("--types", default="",
                   help="comma-separated job types to claim (default: every registered type)")
    p.add_argument("--worker-id", default="",
                   help="name recorded in jobs.locked_by (default host:pid:random)")
    p.add_argument("--once", action="store_true",
                   help="run a single pass and exit (cron / manual drain)")
    p.add_argument("--log-format", choices=("text", "json"),
                   default=os.getenv("JOBS_LOG_FORMAT", "text"))
    return p.parse_args(argv)


def boot() -> None:
    """The API lifespan's pre-serve checks. Raises on any failure."""
    from agents._providers import freeze_model_mode
    from config import validate_config
    from services.encryption_canary import verify_encryption_key

    mode = freeze_model_mode()
    validate_config()
    verify_encryption_key()
    logger.info("worker.boot model_mode=%s", mode)


def load_handlers() -> list[str]:
    import importlib

    from services.jobs import registered_types

    for name in HANDLER_MODULES:
        importlib.import_module(name)
    return registered_types()


def install_signal_handlers(stop: threading.Event) -> None:
    """SIGTERM (Railway's stop) and SIGINT set `stop`: the job in hand
    finishes, nothing more is claimed, and the loop returns."""
    def _on_signal(signum, _frame):
        logger.info("worker.signal %s: finishing the job in hand, then stopping",
                    signal.Signals(signum).name)
        stop.set()

    signal.signal(signal.SIGTERM, _on_signal)
    signal.signal(signal.SIGINT, _on_signal)


def main(argv: list[str] | None = None) -> int:
    from dotenv import load_dotenv

    # Same file the API reads (main.py), before config is imported.
    load_dotenv(Path(__file__).resolve().parents[1] / ".env")
    args = parse_args(argv)
    _configure_logging(args.log_format)

    from services.jobs import check_lease

    try:
        check_lease(args.lease_seconds)
    except ValueError as exc:
        logger.critical("worker.boot_failed: --lease-seconds/JOBS_LEASE_SECONDS: %s", exc)
        return EXIT_BOOT_FAILED

    try:
        boot()
        available = load_handlers()
    except Exception:
        logger.critical("worker.boot_failed: refusing to start", exc_info=True)
        return EXIT_BOOT_FAILED

    wanted = [t.strip() for t in args.types.split(",") if t.strip()] or available
    unknown = sorted(set(wanted) - set(available))
    if unknown or not wanted:
        logger.critical("worker.boot_failed: no handler for job types %s (registered: %s)",
                        unknown or wanted, available)
        return EXIT_BOOT_FAILED

    from services import events_service
    from worker.runner import Worker

    stop = threading.Event()
    install_signal_handlers(stop)

    worker = Worker(
        worker_id=args.worker_id or f"{socket.gethostname()}:{os.getpid()}:{uuid.uuid4().hex[:6]}",
        types=wanted,
        batch=args.batch,
        lease_seconds=args.lease_seconds,
        poll_interval=args.poll_interval,
        stop=stop,
        prune_after_days=args.prune_after_days,
        max_heartbeat_seconds=args.max_heartbeat_seconds,
    )
    events_service.start_worker()
    try:
        if args.once:
            worker.run_once()
        else:
            worker.run_forever()
    finally:
        events_service.shutdown()
    return 0


if __name__ == "__main__":
    sys.exit(main())
