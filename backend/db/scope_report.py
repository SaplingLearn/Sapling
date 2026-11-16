"""The ``db_user_scope`` rollout report: one log line + an in-process tally per
would-be denial (#115, RLS step 2; docs/security/db-user-scope-rollout.md).

``db/scope.py`` decides who a PostgREST call runs as; this module only keeps
score. Three things feed it, all from ``db/scope.py``:

* :func:`record` - a would-be denial: a ``shadow`` read whose user-scoped
  re-run disagreed with the service-role read, a ``shadow`` write that names
  another user (a heuristic: ``db/scope.py::_other_user``), an unscoped query
  (no session subject), or an ``enforce`` refusal. It writes ONE structured WARNING line (the
  :data:`LOG_TOKEN` prefix, ``key=value`` fields: a stdlib log line, so it
  lands in the Railway service logs (stdout) — grep there; it is not shipped
  to Logfire) and bumps a per-key counter. An unscoped query under shadow is
  logged once per (route, table) per process but counted every time.
* :func:`note_write` - a ``shadow`` write or rpc that was NOT checked. Writes
  are never executed twice, so their RLS outcome is unknowable until
  ``enforce``; this is the inventory of (route, table, op) the policies and
  the cross-user matrix must cover before that. Counted only, never logged.
* :func:`note_shadow` - coverage of the read comparison (sampled, compared,
  skipped because the pool was busy, ...), so "no divergences" can be told
  apart from "nothing was compared".

What is recorded: event, kind, mode, HTTP method, route TEMPLATE (never the
raw path), table/rpc name, operation, HTTP status, PostgREST error code,
row COUNTS, the request id and the opaque user id. Never row contents, never
a raw path, never an error message.

The tally is per process (each uvicorn worker has its own) and resets on
deploy; ``GET /api/admin/analytics/db-scope`` returns it next to the
cross-worker view built from the ``events`` table. Nothing here does I/O, and
nothing here is reached while the flag is ``off`` (pinned by
tests/test_db_scope_report.py).
"""
from __future__ import annotations

import logging
import os
import threading
import time
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger("sapling.db_scope")

#: Every line this module logs starts with this token: grep for it.
LOG_TOKEN = "db_user_scope.divergence"

#: The fields that group a divergence in the tally (and in the admin report).
KEY_FIELDS = ("event", "kind", "mode", "method", "route", "target", "op", "status", "code")
WRITE_KEY_FIELDS = ("method", "route", "target", "op")

#: Distinct keys kept per tally. Route templates x tables x ops is naturally
#: bounded; the cap only stops a pathological source from growing memory.
MAX_KEYS = 2_000

_lock = threading.Lock()
_started = time.time()
#: key tuple -> [count, first_seen, last_seen, last_request_id]
_divergences: dict[tuple, list] = {}
_writes: dict[tuple, list] = {}
_coverage: dict[str, int] = {}
_dropped = 0


def _clean(value) -> str:
    """One log/report token: no spaces, never empty, bounded."""
    if value is None or value == "":
        return "-"
    text = str(value)
    return "".join(c if c.isprintable() and not c.isspace() else "_" for c in text)[:200]


def _bump(store: dict, key: tuple, request_id: Optional[str]) -> None:
    global _dropped
    now = time.time()
    with _lock:
        hit = store.get(key)
        if hit is None:
            if len(store) >= MAX_KEYS:
                _dropped += 1
                return
            store[key] = [1, now, now, request_id]
            return
        hit[0] += 1
        hit[2] = now
        if request_id:
            hit[3] = request_id


def key_of(fields: dict) -> tuple:
    """The grouping key (:data:`KEY_FIELDS`) for one divergence. The ONE
    normalisation both views use — this process's tally and the admin
    report's grouping of ``events`` rows — so the same divergence has the
    same key in both: values pass through :func:`_clean`, and a missing
    value (None or "") is None."""
    return tuple(None if fields.get(k) in (None, "") else _clean(fields.get(k))
                 for k in KEY_FIELDS)


def format_line(fields: dict) -> str:
    """The one WARNING line for a divergence (also what tests and the runbook
    grep for). Field order is fixed so a line reads the same every time."""
    order = KEY_FIELDS + ("service_rows", "scoped_rows", "request_id", "user")
    return LOG_TOKEN + " " + " ".join(f"{k}={_clean(fields.get(k))}" for k in order)


def record(*, event: str, kind: str, mode: str, method: Optional[str], route: Optional[str],
           target: Optional[str], op: Optional[str], status: Optional[int] = None,
           code: Optional[str] = None, service_rows: Optional[int] = None,
           scoped_rows: Optional[int] = None, request_id: Optional[str] = None,
           user: Optional[str] = None, level: int = logging.WARNING,
           log: bool = True) -> None:
    """Log one structured line (unless ``log`` is False) and count it — every
    call is counted. Never raises."""
    fields = {
        "event": event, "kind": kind, "mode": mode, "method": method or "?",
        "route": route or "?", "target": target or "?", "op": op or "?",
        "status": status, "code": code, "service_rows": service_rows,
        "scoped_rows": scoped_rows, "request_id": request_id, "user": user,
    }
    try:
        if log:
            logger.log(level, "%s", format_line(fields))
        _bump(_divergences, key_of(fields), request_id)
    except Exception:  # pragma: no cover - observability never breaks a request
        logger.debug("db scope divergence not recorded", exc_info=True)


def note_write(*, method: Optional[str], route: Optional[str], target: str, op: str,
               request_id: Optional[str] = None) -> None:
    """Count a ``shadow`` write/rpc whose RLS outcome was not checked."""
    try:
        key = (_clean(method or "?"), _clean(route or "?"), _clean(target), _clean(op))
        _bump(_writes, key, request_id)
    except Exception:  # pragma: no cover
        logger.debug("db scope write not noted", exc_info=True)


def note_shadow(outcome: str, n: int = 1) -> None:
    """Coverage counter for the read comparison: ``sampled``, ``compared``,
    ``agreed``, ``diverged``, ``skipped_busy``, ``transport_error``."""
    with _lock:
        _coverage[outcome] = _coverage.get(outcome, 0) + n


def _iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, timezone.utc).isoformat()


def snapshot(limit: int = 100) -> dict:
    """This process's tally, highest counts first."""
    with _lock:
        div = sorted(_divergences.items(), key=lambda kv: -kv[1][0])[:limit]
        wr = sorted(_writes.items(), key=lambda kv: -kv[1][0])[:limit]
        coverage = dict(_coverage)
        dropped = _dropped
        div_keys, wr_keys = len(_divergences), len(_writes)
    return {
        "pid": os.getpid(),
        "since": _iso(_started),
        "shadow_reads": coverage,
        "divergences": [
            {**dict(zip(KEY_FIELDS, key)), "count": v[0], "first_seen": _iso(v[1]),
             "last_seen": _iso(v[2]), "last_request_id": v[3]}
            for key, v in div
        ],
        "divergence_keys": div_keys,
        "unverified_writes": [
            {**dict(zip(WRITE_KEY_FIELDS, key)), "count": v[0], "last_seen": _iso(v[2])}
            for key, v in wr
        ],
        "unverified_write_keys": wr_keys,
        "dropped_keys": dropped,
    }


def reset() -> None:
    """Forget the tally (tests)."""
    global _dropped, _started
    with _lock:
        _divergences.clear()
        _writes.clear()
        _coverage.clear()
        _dropped = 0
        _started = time.time()
