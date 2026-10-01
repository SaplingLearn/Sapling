"""Kill switch (spec §7, §13 A14): the loop is the default for every student;
LEARNING_LOOP_ENABLED=false/0/off/no turns it off for everyone. No per-user read.

PKG-14b retired the build-phase staff/QA toggle (the per-user settings column
— the column stays, dead; ADR 0030): this module imports no database helper, so a
gate call can never reach the DB in either state.
"""

from __future__ import annotations

import config


def learning_loop_active(user_id: str) -> bool:
    """`config.LEARNING_LOOP_ENABLED`, read at call time (so a test or a reload sees
    the current value). `user_id` is kept for the signature every caller uses; the
    answer is the same for every user. Never raises."""
    return bool(config.LEARNING_LOOP_ENABLED)


def learning_loop_for_request(user_id: str) -> bool:
    """The route-entry gate (owner decision 00): call ONCE per request.

    A route evaluates this at entry and carries the result on
    `SaplingDeps.learning_loop`; agents, tools and services read that field
    and never call the gate themselves (`tests/test_learning_gate_route_entry.py`
    pins that only `routes/` references the gate). Post-launch it is the env
    kill switch alone — no read of any kind.
    """
    return learning_loop_active(user_id)
