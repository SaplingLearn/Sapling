"""Per-user, non-blocking, in-process guard for admin account operations.

Seed / wipe / copy each start with a wipe and then write a lot of rows over
PostgREST, which has no transactions. Two of them interleaving on the same
account would leave a mix of both results, so a second operation on an account
that already has one running is REJECTED (the route answers 409), never queued:
the admin who clicked twice wants to know, not to wait.

PER-PROCESS ONLY — a known limitation, not a distributed mutex. Two requests
for the same account that land in different processes both get the slot. The
deploy today is one process per service: the backend image runs a single
uvicorn worker (`backend/Dockerfile` CMD, no `--workers`; uvicorn would honour
`WEB_CONCURRENCY` if an environment set it). The replica count lives in the
Railway dashboard, not in this repo; a multi-replica (or multi-worker) deploy
needs a DB-backed claim here (a row claimed with a unique key and a lease)
before these operations are safe against a concurrent double-submit. Every
operation re-starts from a wipe, so a run that slips past this guard still
converges when re-run; the guard's job is the common double-submit.
"""

from __future__ import annotations

import threading
from collections.abc import Iterator
from contextlib import contextmanager


class AccountBusy(RuntimeError):
    """Another account operation is already running for this user here."""

    def __init__(self, user_id: str):
        super().__init__(f"an account operation is already running for {user_id}")
        self.user_id = user_id


_guard = threading.Lock()
_running: set[str] = set()


@contextmanager
def account_op(user_id: str) -> Iterator[None]:
    """Hold the account-operation slot for `user_id` for the `with` body.

    Raises `AccountBusy` immediately (never blocks) when the slot is taken.
    The slot is released however the body exits, exceptions included.
    """
    with _guard:
        if user_id in _running:
            raise AccountBusy(user_id)
        _running.add(user_id)
    try:
        yield
    finally:
        with _guard:
            _running.discard(user_id)


def is_busy(user_id: str) -> bool:
    """Whether an account operation for `user_id` is running in this process."""
    with _guard:
        return user_id in _running
