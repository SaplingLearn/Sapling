"""Per-user, non-blocking guard for admin account operations.

Seed / wipe / copy each start with a wipe and then write a lot of rows over
PostgREST, which has no transactions. Two of them interleaving on the same
account would leave a mix of both results, so a second operation on an account
that already has one running is REJECTED (the route answers 409), never queued:
the admin who clicked twice wants to know, not to wait.

Two layers (#117):

1. An in-process slot (always): a second operation in THIS process is refused
   without any I/O.
2. A Postgres lease (`services/pg_lease.py`, key ``account_op:<user id>``)
   while the ``stateless_locks`` flag is on: a second operation on ANOTHER
   replica (or uvicorn worker) is refused too. The lease is renewed while the
   operation runs and expires ``ACCOUNT_OP_LEASE_TTL_S`` after a crashed
   process stopped renewing it. With the flag off, or the database unable to
   answer the claim (fail open, one warning per outage), the in-process slot
   is the whole guard — what it always was.

Every operation re-starts from a wipe, so a run that slips past this guard
(flag off on a multi-replica deploy, or a DB outage) still converges when
re-run; the guard's job is the common double-submit.
"""

from __future__ import annotations

import threading
from collections.abc import Iterator
from contextlib import contextmanager

from services import pg_lease

#: How long the lease outlives a process that stopped renewing it.
ACCOUNT_OP_LEASE_TTL_S = 120


class AccountBusy(RuntimeError):
    """Another account operation is already running for this user."""

    def __init__(self, user_id: str):
        super().__init__(f"an account operation is already running for {user_id}")
        self.user_id = user_id


_guard = threading.Lock()
_running: set[str] = set()


@contextmanager
def account_op(user_id: str) -> Iterator[None]:
    """Hold the account-operation slot for `user_id` for the `with` body.

    Raises `AccountBusy` immediately (never blocks) when the slot is taken,
    here or (flag on) on another replica. The slot is released however the
    body exits, exceptions included.
    """
    with _guard:
        if user_id in _running:
            raise AccountBusy(user_id)
        _running.add(user_id)
    try:
        with pg_lease.lease(f"account_op:{user_id}", ACCOUNT_OP_LEASE_TTL_S) as held:
            if not held:
                raise AccountBusy(user_id)
            yield
    finally:
        with _guard:
            _running.discard(user_id)


def is_busy(user_id: str) -> bool:
    """Whether an account operation for `user_id` is running in this process
    (the in-process layer only: no I/O)."""
    with _guard:
        return user_id in _running
