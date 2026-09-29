"""Flag + per-user opt-in for the learning loop (spec §7). Fails closed."""

from __future__ import annotations

import logging

import config
from db.connection import table

logger = logging.getLogger("sapling.learning.gate")


def learning_loop_active(user_id: str) -> bool:
    """True only when LEARNING_LOOP_ENABLED is set AND the user opted in.

    Never raises. With the env var off it performs no database read, so the
    flag-off path is byte-identical to the pre-series product.
    """
    if not config.LEARNING_LOOP_ENABLED:
        return False
    try:
        rows = table("user_settings").select(
            "learning_loop_beta", filters={"user_id": f"eq.{user_id}"}
        )
    except Exception as exc:  # fail closed
        logger.warning("learning_loop_active: read failed for %s: %s", user_id, exc)
        return False
    if not rows:
        return False
    return bool(rows[0].get("learning_loop_beta", False))


def learning_loop_for_request(user_id: str) -> bool:
    """The route-entry gate (owner decision 00): call ONCE per request.

    A route evaluates this at entry and carries the result on
    `SaplingDeps.learning_loop`; agents, tools and services read that field
    and never call the gate themselves, so a request costs at most one
    `user_settings` read (`tests/test_learning_gate_route_entry.py` pins that
    only `routes/` references the gate). Same fail-closed contract as
    `learning_loop_active`: env kill switch off -> False with no read; any
    read error -> False.
    """
    return learning_loop_active(user_id)
