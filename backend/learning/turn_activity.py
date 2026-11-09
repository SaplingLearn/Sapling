"""Durable, prose-free timing and fencing for a materialised tutor turn.

This is session metadata, never learning evidence. A pending operation may have
been interrupted by a worker crash. Its elapsed time cannot earn a higher help
ceiling. A new request supersedes it, and an older request cannot later commit
feedback into the new request's state. Database CAS and ownership remain with
the route/store; these transformations are pure.
"""

from __future__ import annotations

import math

KEY = "turn_activity"


class StaleTurnActivity(RuntimeError):
    """Another turn superseded this operation or it already completed."""


def _time(value) -> float | None:
    if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
        return None
    return float(value)


def timing(doc: dict) -> tuple[float | None, bool]:
    """Latest durable activity and whether independent time is untrustworthy.

    Legacy absence preserves the served-at contract. Malformed or pending
    metadata fails closed until a subsequent valid turn completes.
    """
    if KEY not in doc:
        return None, False
    value = doc[KEY]
    if not isinstance(value, dict):
        return None, True
    at = _time(value.get("at"))
    valid = (
        isinstance(value.get("id"), str)
        and bool(value["id"])
        and value.get("state") in {"pending", "interrupted", "complete"}
        and at is not None
    )
    return at, not valid or value.get("state") == "pending"


def begin(doc: dict, operation_id: str, now: float) -> None:
    if not isinstance(operation_id, str) or not operation_id or _time(now) is None:
        raise ValueError("Invalid turn operation")
    doc[KEY] = {"id": operation_id, "state": "pending", "at": float(now)}


def complete(doc: dict, operation_id: str, now: float) -> None:
    value = doc.get(KEY)
    if (
        not isinstance(value, dict)
        or value.get("id") != operation_id
        or value.get("state") != "pending"
    ):
        raise StaleTurnActivity("Tutor turn changed; retry from current state")
    if _time(now) is None:
        raise ValueError("Invalid completion time")
    doc[KEY] = {"id": operation_id, "state": "complete", "at": float(now)}


def interrupt(doc: dict, operation_id: str, now: float) -> None:
    value = doc.get(KEY)
    if not isinstance(value, dict) or value.get("id") != operation_id:
        return  # An old cancellation must not change a newer turn's timing.
    if _time(now) is None:
        raise ValueError("Invalid interruption time")
    prior = _time(value.get("at"))
    doc[KEY] = {
        "id": operation_id,
        "state": "interrupted",
        "at": max(float(now), prior if prior is not None else 0.0),
    }
