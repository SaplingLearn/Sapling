"""Atomic evidence transport; Python remains the learning-math authority.

Only graph_service's single writer submits a plan. Snapshot/CAS retries handle
concurrent legacy writers; an ambiguous acknowledgment retries the IDENTICAL
plan first. Receipts identify whole committed operations, never partial rows.
No learner answer, rubric or prompt is stored in this protocol.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from datetime import datetime, timezone
import hashlib
import json
import math
from typing import Callable
import uuid

from db.connection import rpc
from learning.evidence import Evidence, PlanningPersistenceUnavailable
from learning.learner_state import LearnerState, _from_row
from learning.params import EVIDENCE_TRANSACTION_RETRIES

_DATETIME_TYPE = datetime


class EvidenceTransactionConflict(PlanningPersistenceUnavailable):
    """An operation identity was reused with different semantic input/plan."""


class EvidenceObservationSuperseded(PlanningPersistenceUnavailable):
    """An uncommitted older grade cannot overwrite newer learner evidence."""


def fingerprint(user_id: str, course_id: str | None, evidences: list[Evidence], retention) -> str:
    value = {
        "user_id": user_id,
        "course_id": course_id,
        "retention": retention,
        "evidence": [ev.model_dump(mode="json", exclude={"operation_id"}) for ev in evidences],
    }
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(encoded.encode()).hexdigest()


def operation_id(evidences: list[Evidence]) -> str:
    supplied = {ev.operation_id for ev in evidences if ev.operation_id is not None}
    if len(supplied) > 1 or (supplied and any(ev.operation_id is None for ev in evidences)):
        raise EvidenceTransactionConflict("Evidence batch operation identity disagrees")
    # Compatibility only: stable during THIS invocation, not across HTTP retries.
    return next(iter(supplied)) if supplied else str(uuid.uuid4())


def _result(value) -> dict:
    if not isinstance(value, dict) or not isinstance(value.get("status"), str):
        raise PlanningPersistenceUnavailable("Invalid evidence transaction response")
    return value


def _receipt(value: dict, user_id: str, op_id: str, expected_fingerprint=None) -> dict:
    receipt = value.get("receipt")
    if (
        not isinstance(receipt, dict)
        or receipt.get("user_id") != user_id
        or receipt.get("operation_id") != op_id
        or not isinstance(receipt.get("input_fingerprint"), str)
        or not isinstance(receipt.get("changes"), list)
        or not isinstance(receipt.get("posteriors"), dict)
    ):
        raise PlanningPersistenceUnavailable("Invalid evidence transaction receipt")
    if expected_fingerprint is not None and receipt["input_fingerprint"] != expected_fingerprint:
        raise EvidenceTransactionConflict("Evidence operation input changed")
    for change in receipt["changes"]:
        if not isinstance(change, dict) or not isinstance(change.get("concept"), str):
            raise PlanningPersistenceUnavailable("Invalid evidence transaction changes")
        for key in ("before", "after"):
            number = change.get(key)
            if (
                type(number) not in (int, float)
                or not math.isfinite(number)
                or not 0 <= number <= 1
            ):
                raise PlanningPersistenceUnavailable("Invalid evidence transaction posterior")
    for node_id, value in receipt["posteriors"].items():
        if (
            not isinstance(node_id, str)
            or not node_id
            or type(value) not in (int, float)
            or not math.isfinite(value)
            or not 0 <= value <= 1
        ):
            raise PlanningPersistenceUnavailable("Invalid evidence receipt posterior")
    return receipt


def read_receipt(user_id: str, op_id: str, *, input_fingerprint: str | None = None) -> dict | None:
    """Owner-scoped committed receipt for checkpoint recovery, or no receipt.

    Missing is not permission to grade again or invent an outcome. An earlier
    network request might still be queued; the operation's identity remains
    mandatory on any later submission. Read failures never become 'missing'.
    """
    try:
        op_id = str(uuid.UUID(op_id))
        out = _result(
            rpc("learning_evidence_receipt", {"p_user_id": user_id, "p_operation_id": op_id})
        )
        if out["status"] == "missing":
            return None
        if out["status"] != "committed":
            raise EvidenceTransactionConflict("Evidence operation ownership changed")
        return _receipt(out, user_id, op_id, input_fingerprint)
    except PlanningPersistenceUnavailable:
        raise
    except Exception as exc:
        raise PlanningPersistenceUnavailable("Evidence transaction receipt unavailable") from exc


@dataclass
class EvidencePlan:
    op_id: str
    snapshot: dict
    now: datetime
    observed_at: datetime | None = None
    nodes: dict[str, dict] = field(init=False)
    states: dict[str, LearnerState] = field(init=False)
    state_rows: dict[str, dict] = field(default_factory=dict)
    mirrors: dict[str, dict] = field(default_factory=dict)
    events: list[dict] = field(default_factory=list)

    def __post_init__(self):
        self.snapshot = deepcopy(self.snapshot)
        self.nodes = {row["id"]: deepcopy(row) for row in self.snapshot["nodes"]}
        self.states = {row["node_id"]: _from_row(row, self.now) for row in self.snapshot["states"]}

    def event_id(self, index: int) -> str:
        return str(uuid.uuid5(uuid.UUID(self.op_id), str(index)))

    def prior_check(self, ev: Evidence) -> bool:
        return any(
            row["session_id"] == ev.session_id
            and row["question_hash"] == ev.question_hash
            and row["count"] > 0
            for row in self.snapshot["checks"]
        )

    def payload(self, changes: list[dict]) -> dict:
        versions = {row["node_id"]: row["evidence_version"] for row in self.snapshot["states"]}
        return {
            "observed_at": self.observed_at.isoformat() if self.observed_at is not None else None,
            "nodes": [
                {"id": row["id"], "version": row["evidence_version"]}
                for row in self.snapshot["nodes"]
            ],
            "states_expected": [
                {"node_id": node_id, "version": versions.get(node_id)}
                for node_id in sorted(self.nodes)
            ],
            "edges": self.snapshot["edges"],
            "checks": self.snapshot["checks"],
            "state_rows": list(self.state_rows.values()),
            "mirrors": list(self.mirrors.values()),
            "events": self.events,
            "changes": changes,
        }


def _retryable_sql(exc: Exception) -> bool:
    try:
        return exc.response.json().get("code") in {"40P01", "40001", "55P03", "57014"}
    except Exception:
        return False


def commit_evidence_transaction(
    user_id: str,
    course_id: str | None,
    evidences: list[Evidence],
    retention,
    compute: Callable[[EvidencePlan], list[dict]],
) -> tuple[list[dict], dict, bool]:
    """Return original changes/receipt and whether this call newly committed.

    The transient flag is deliberately outside the durable receipt: recovering
    an old operation must not count as new study activity on the recovery day.
    A lost acknowledgment recovered as replay can omit best-effort activity
    effects; it cannot invent activity for a later day.
    """
    op_id = operation_id(evidences)
    semantic = fingerprint(user_id, course_id, evidences, retention)
    times = {getattr(ev, "observed_at", None) for ev in evidences}
    if len(times) > 1:
        raise EvidenceTransactionConflict("Evidence batch observation times disagree")
    observed_at = next(iter(times)) if times else None
    if observed_at is not None:
        if not isinstance(observed_at, _DATETIME_TYPE) or observed_at.tzinfo is None:
            raise EvidenceTransactionConflict("Evidence observation time is not trusted UTC")
        observed_at = observed_at.astimezone(timezone.utc)
    try:
        existing = read_receipt(user_id, op_id, input_fingerprint=semantic)
        if existing is not None:
            return existing["changes"], existing, False
        node_ids = sorted({ev.node_id for ev in evidences})
        checks = sorted(
            {
                (ev.session_id, ev.question_hash)
                for ev in evidences
                if ev.session_id and ev.question_hash
            }
        )
        for _attempt in range(EVIDENCE_TRANSACTION_RETRIES):
            snapshot = _result(
                rpc(
                    "learning_evidence_snapshot",
                    {
                        "p_user_id": user_id,
                        "p_course_id": course_id,
                        "p_node_ids": node_ids,
                        "p_checks": [
                            {"session_id": sid, "question_hash": qh} for sid, qh in checks
                        ],
                    },
                )
            )
            if snapshot["status"] != "snapshot":
                raise EvidenceTransactionConflict("Evidence target ownership/course unavailable")
            plan = EvidencePlan(
                op_id, snapshot, observed_at or datetime.now(timezone.utc), observed_at
            )
            changes = compute(plan)
            payload = plan.payload(changes)
            args = {
                "p_user_id": user_id,
                "p_course_id": course_id,
                "p_operation_id": op_id,
                "p_input_fingerprint": semantic,
                "p_plan": payload,
            }
            # An ambiguous response is retried identically, never recalculated.
            try:
                out = _result(rpc("learning_evidence_commit", args))
            except Exception as first:
                if _retryable_sql(first):
                    continue  # The server explicitly rolled back the transaction.
                try:
                    out = _result(rpc("learning_evidence_commit", args))
                except Exception as second:
                    known = read_receipt(user_id, op_id, input_fingerprint=semantic)
                    if known is not None:
                        return known["changes"], known, False
                    raise PlanningPersistenceUnavailable(
                        "Evidence commit acknowledgment unavailable"
                    ) from second
            if out["status"] == "stale":
                continue
            if out["status"] == "superseded":
                raise EvidenceObservationSuperseded(
                    "Newer learner evidence supersedes this uncommitted grade"
                )
            if out["status"] not in {"committed", "replay"}:
                raise EvidenceTransactionConflict(
                    "Evidence transaction identity/ownership conflict"
                )
            receipt = _receipt(out, user_id, op_id, semantic)
            return receipt["changes"], receipt, out["status"] == "committed"
        raise PlanningPersistenceUnavailable("Evidence transaction remained busy")
    except PlanningPersistenceUnavailable:
        raise
    except Exception as exc:
        raise PlanningPersistenceUnavailable("Evidence transaction unavailable") from exc
