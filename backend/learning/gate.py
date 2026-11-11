"""The learning-loop gate (spec §7, §13 A14): is the loop on for this student?

Two switches, both must say yes:

- the env kill switch, `config.LEARNING_LOOP_ENABLED` (false/0/off/no turns the
  loop off for everyone; unset means the switch is not thrown). Read first: when
  it is thrown the answer is False with no read of any kind, so the kill switch
  costs nothing and reaches no database;
- the student's `learning_loop` feature flag (services/feature_flags.py
  REGISTRY; default off, client-visible). The owner turns it on from the admin
  Flags page: their own account, then a class, then everyone.

Off either way is the pre-loop app for that student, byte for byte: the loop
routes 404, the legacy tutor runs, nothing of the loop is read or written and
no loop model runs. No student (an anonymous request, the backfill's system
actor) is off.

Per request, once (owner decision 00): a route resolves the gate at entry and
carries the answer (`request.state.learning_loop`, `SaplingDeps.learning_loop`).
The flag resolver reads the flag store on a cold snapshot, so an `async def`
route reaches the gate through a worker thread (`run_in_threadpool`), never on
the event loop; a sync route (FastAPI's threadpool) calls it directly.

Work with no student request (the upload's check-item drafting, on the request
or the job queue) is the UPLOADER's: `learning_loop_for_uploader`, resolved once
per upload. The per-user settings column of the build phase stays retired
(PKG-14b, ADR 0030): this module reads no table itself.
"""

from __future__ import annotations

import config
from services.feature_flags import flag_on

#: The per-student flag (services/feature_flags.py REGISTRY).
LEARNING_LOOP_FLAG = "learning_loop"


def learning_loop_active(user_id: str | None) -> bool:
    """The env kill switch (read at call time, so a test or a reload sees the
    current value), then this student's `learning_loop` flag. Never raises:
    the flag resolver fails closed (off) on an unreadable store."""
    if not config.LEARNING_LOOP_ENABLED:
        return False
    return bool(user_id) and flag_on(LEARNING_LOOP_FLAG, user_id)


def learning_loop_for_request(user_id: str | None) -> bool:
    """The route-entry gate (owner decision 00): call ONCE per request.

    A route evaluates this at entry and carries the result on
    `SaplingDeps.learning_loop`; agents, tools and services read that field
    and never call the gate themselves (`tests/test_learning_gate_route_entry.py`
    pins that only `routes/` and the named route-entry helpers reference the
    gate). It may read the flag store: from an `async def`, hop to a worker
    thread first.
    """
    return learning_loop_active(user_id)


def learning_loop_for_uploader(user_id: str | None) -> bool:
    """Upload-time work with no student request behind it (check-item drafting,
    inline or on the job queue): the gate for the student who UPLOADED, read
    once per upload, before anything is scheduled. Off — the kill switch, or
    the uploader's flag — schedules the indexing alone, exactly the pre-loop
    upload, and drafts nothing, so a flag-off student's upload spends no loop
    model call. Items are course assets: a flag-on classmate's upload drafts
    the course's items, and the backfill drafts what flag-off uploads left."""
    return learning_loop_active(user_id)
