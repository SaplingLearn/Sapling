"""Fire-and-forget write path for observability events (issue #116).

Two public helpers — ``log_event`` (analytics / audit / error) and
``log_llm_usage`` (per-call LLM token + cost) — enqueue a row onto a bounded
in-process queue and return immediately. A single daemon worker thread drains
the queue in small batches and inserts through the sanctioned
``db/connection.py::table()`` seam.

Design guarantees:

* **Never adds latency.** The calling thread only builds a dict and does a
  non-blocking ``put``. No DB call happens on the request thread.
* **Never raises into request handling.** Every failure — a full queue, a
  serialization slip, a PostgREST error inside the worker — is caught and
  logged via the stdlib logger. Logging observability data must not break the
  thing being observed.
* **No raw content.** ``log_event(content=...)`` is hashed to a 16-hex
  fingerprint (``content_fp``); the raw string is never enqueued or persisted.
* **Kill switch.** ``EVENTS_LOGGING_ENABLED=false`` turns both helpers into
  no-ops.

Cost computation and token-field normalization live in
``services/llm_pricing.py``; this module just persists what it's given.
"""

from __future__ import annotations

import logging
import os
import queue
import threading
from typing import Any, Optional

from db.connection import table
from services import llm_pricing
from services.fingerprint import fingerprint_text
from services.request_context import current_request_id

logger = logging.getLogger("sapling.events")

# Tunables (env-driven). Read at queue-construction time so tests can shrink
# the queue via reset_for_tests(maxsize=...).
_DEFAULT_QUEUE_MAX = int(os.getenv("EVENTS_QUEUE_MAX", "10000"))

# Batch flush parameters: drain up to _BATCH_MAX rows or wait _FLUSH_INTERVAL
# seconds, whichever comes first.
_BATCH_MAX = 50
_FLUSH_INTERVAL = 1.0

# ── Module state ────────────────────────────────────────────────────────────

_queue: "queue.Queue[dict]" = queue.Queue(maxsize=_DEFAULT_QUEUE_MAX)
_dropped = 0
_dropped_lock = threading.Lock()

_worker: Optional[threading.Thread] = None
_worker_lock = threading.Lock()
_stop = threading.Event()


def _logging_enabled() -> bool:
    """Read the kill switch each call so it can be toggled at runtime / in tests."""
    return os.getenv("EVENTS_LOGGING_ENABLED", "true").strip().lower() not in {
        "false", "0", "no", "off",
    }


# ── Public API ──────────────────────────────────────────────────────────────


def log_event(
    event_type: str,
    *,
    category: str,
    user_id: str | None = None,
    request_id: str | None = None,
    payload: dict | None = None,
    content: str | None = None,
) -> None:
    """Enqueue a row for the ``events`` table. Never raises, never blocks.

    ``content`` is fingerprinted to ``content_fp`` (16 hex chars); the raw
    string is hashed here and immediately dropped — it never enters the queue.
    """
    if not _logging_enabled():
        return
    try:
        row = {
            "event_type": event_type,
            "category": category,
            "user_id": user_id,
            "request_id": request_id if request_id is not None else current_request_id(),
            "payload": payload or {},
            "content_fp": fingerprint_text(content, length=16) if content else None,
        }
        _enqueue("events", row)
    except Exception:  # pragma: no cover - defensive; enqueue is already guarded
        logger.exception("log_event failed; event dropped")


def log_llm_usage(
    *,
    feature: str,
    task: str | None,
    model: str,
    usage: Any,
    provider: str = "gemini",
    user_id: str | None = None,
    request_id: str | None = None,
) -> None:
    """Enqueue a row for the ``llm_usage`` table. Never raises, never blocks.

    ``usage`` is any Pydantic AI / Gemini usage object (or dict); it is
    normalized here and the cost computed from ``llm_pricing.MODEL_PRICING``
    (``cost_usd = NULL`` for unpriced models).
    """
    if not _logging_enabled():
        return
    try:
        tokens = llm_pricing.normalize_usage(usage)
        row = {
            "user_id": user_id,
            "request_id": request_id if request_id is not None else current_request_id(),
            "feature": feature,
            "task": task,
            "model": model,
            "provider": provider,
            "prompt_tokens": tokens["prompt_tokens"],
            "completion_tokens": tokens["completion_tokens"],
            "total_tokens": tokens["total_tokens"],
            "cost_usd": llm_pricing.cost_usd(
                model, tokens["prompt_tokens"], tokens["completion_tokens"],
            ),
        }
        _enqueue("llm_usage", row)
    except Exception:  # pragma: no cover - defensive
        logger.exception("log_llm_usage failed; row dropped")


# ── Enqueue + drop accounting ───────────────────────────────────────────────


def _enqueue(table_name: str, row: dict) -> None:
    global _dropped
    try:
        _queue.put_nowait({"table": table_name, "row": row})
    except queue.Full:
        with _dropped_lock:
            _dropped += 1
            n = _dropped
        # Throttle: warn on the first drop and every 1000th thereafter so a
        # sustained overflow doesn't flood the logs.
        if n == 1 or n % 1000 == 0:
            logger.warning(
                "events queue full (max=%d); dropped %d event(s) so far",
                _queue.maxsize, n,
            )


def dropped_count() -> int:
    """Number of events dropped due to queue overflow (test/metrics hook)."""
    return _dropped


# ── Flush ───────────────────────────────────────────────────────────────────


def _flush_batch(items: list[dict]) -> None:
    """Insert a batch grouped by table. Errors are swallowed + logged.

    A failed bulk insert falls back to inserting that table's rows one at a
    time, so a single poison row can't take its whole batch down with it.
    """
    if not items:
        return
    grouped: dict[str, list[dict]] = {}
    for item in items:
        grouped.setdefault(item["table"], []).append(item["row"])
    for table_name, rows in grouped.items():
        try:
            table(table_name).insert(rows)
        except Exception:
            logger.info(
                "events bulk insert failed for table %r (%d row(s)); "
                "retrying rows individually",
                table_name, len(rows), exc_info=True,
            )
            _flush_rows_individually(table_name, rows)


def _flush_rows_individually(table_name: str, rows: list[dict]) -> None:
    """Per-row salvage after a failed bulk insert: only the rows that
    individually fail are dropped (logged per-row at debug, plus one warning
    with the drop count). Never raises — same contract as _flush_batch."""
    dropped = 0
    for row in rows:
        try:
            table(table_name).insert([row])
        except Exception:
            dropped += 1
            logger.debug(
                "events row insert failed for table %r; row dropped",
                table_name, exc_info=True,
            )
    if dropped:
        logger.warning(
            "events flush dropped %d of %d row(s) for table %r after per-row retry",
            dropped, len(rows), table_name,
        )


def flush_now() -> None:
    """Synchronously drain the queue on the calling thread.

    Test-only determinism hook (and used by ``shutdown()``): pulls everything
    currently queued and inserts it, so tests never race the worker thread.
    """
    items: list[dict] = []
    while True:
        try:
            items.append(_queue.get_nowait())
        except queue.Empty:
            break
    _flush_batch(items)


# ── Background worker lifecycle ─────────────────────────────────────────────


def _worker_loop() -> None:
    """Drain-and-insert loop: batch up to _BATCH_MAX rows or _FLUSH_INTERVAL."""
    while not _stop.is_set():
        batch: list[dict] = []
        try:
            batch.append(_queue.get(timeout=_FLUSH_INTERVAL))
        except queue.Empty:
            continue
        while len(batch) < _BATCH_MAX:
            try:
                batch.append(_queue.get_nowait())
            except queue.Empty:
                break
        _flush_batch(batch)


def start_worker() -> None:
    """Start the daemon drain thread (idempotent).

    Called from the FastAPI lifespan in production. Unit tests deliberately do
    not call this — they use ``flush_now()`` for deterministic draining.
    """
    global _worker
    with _worker_lock:
        if _worker is not None and _worker.is_alive():
            return
        _stop.clear()
        _worker = threading.Thread(
            target=_worker_loop, name="sapling-events-worker", daemon=True,
        )
        _worker.start()


def shutdown() -> None:
    """Stop the worker and flush anything still queued (called on app shutdown)."""
    global _worker
    _stop.set()
    worker = _worker
    if worker is not None:
        worker.join(timeout=2.0)
        _worker = None
    flush_now()


# ── Test hook ────────────────────────────────────────────────────────────────


def reset_for_tests(maxsize: int | None = None) -> None:
    """Reset queue, counters, and one-time-warning state between tests.

    Wired into an autouse fixture in ``tests/conftest.py`` so no test leaks
    queued rows or a tripped drop-counter into the next.
    """
    global _queue, _dropped, _worker
    _stop.set()
    if _worker is not None:
        _worker.join(timeout=1.0)
        _worker = None
    _stop.clear()
    _queue = queue.Queue(maxsize=maxsize if maxsize is not None else _DEFAULT_QUEUE_MAX)
    with _dropped_lock:
        _dropped = 0
    llm_pricing._warned_models.clear()
