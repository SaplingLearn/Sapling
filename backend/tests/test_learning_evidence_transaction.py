"""Optimistic concurrency and retry identity through the real Python writer.

The RPC emulator is not a database transaction proof; real rollback/locking and
multi-worker behavior are covered by test_learning_evidence_transaction_db.py.
"""

from copy import deepcopy
from datetime import datetime, timedelta, timezone
from unittest.mock import patch
from uuid import uuid4

import httpx
import pytest

from learning import bkt
from learning.evidence import Evidence, PlanningPersistenceUnavailable
from learning.evidence_transaction import (
    EvidenceObservationSuperseded,
    EvidenceTransactionConflict,
    EvidencePlan,
    fingerprint,
    operation_id,
    read_receipt,
)
from learning.learner_state import state_row
from test_learning_evidence_apply import NODES, NOW, _apply, _evidence_factory


def grade(**kwargs):
    return {
        "node_id": "n1",
        "channel": "free_response",
        "correct": True,
        "session_id": "s1",
        "question_hash": "q1",
        "check_item_id": "item1",
        **kwargs,
    }


def run_with(factory, payload):
    with patch(
        "test_learning_evidence_apply._evidence_factory", return_value=(factory, factory.mocks)
    ):
        return _apply(payload, edges=[])[0]


def setup():
    factory, mocks = _evidence_factory(NODES, [], [])
    factory.mocks = mocks
    return factory, factory.rpc


def test_same_operation_replay_returns_exact_receipt_without_more_state_or_journal():
    factory, transport = setup()
    operation = str(uuid4())
    payload = {"evidence": [grade(operation_id=operation)]}
    first = run_with(factory, payload)
    states, events = deepcopy(transport.committed_states), deepcopy(transport.committed_events)
    second = run_with(factory, payload)
    assert second == first
    assert transport.committed_states == states and transport.committed_events == events
    assert len(transport.plans) == 1
    receipt = transport.receipts[operation]
    assert receipt["posteriors"]["n1"] == first[0]["after"]


def test_old_receipt_replay_does_not_mark_a_new_utc_study_day():
    factory, transport = setup()
    operation = str(uuid4())
    payload = {"evidence": [grade(operation_id=operation)]}
    with patch(
        "test_learning_evidence_apply._evidence_factory", return_value=(factory, factory.mocks)
    ):
        first, _, first_streak = _apply(payload, edges=[], now=NOW)
        replay, _, replay_streak = _apply(payload, edges=[], now=NOW + timedelta(days=1))
        fresh, _, fresh_streak = _apply(
            {"evidence": [grade(operation_id=str(uuid4()), question_hash="fresh-question")]},
            edges=[],
            now=NOW + timedelta(days=1),
        )
    assert replay == first and fresh
    first_streak.assert_called_once_with("u1")
    replay_streak.assert_not_called()
    fresh_streak.assert_called_once_with("u1")
    assert len(transport.committed_events) == len(transport.receipts) == 2


@pytest.mark.parametrize(
    "change", [{"correct": False}, {"question_hash": "other"}, {"max_rung": 2}]
)
def test_changed_semantic_input_cannot_reuse_a_committed_operation(change):
    factory, transport = setup()
    operation = str(uuid4())
    run_with(factory, {"evidence": [grade(operation_id=operation)]})
    before = deepcopy(transport.committed_states)
    with pytest.raises(EvidenceTransactionConflict):
        run_with(factory, {"evidence": [grade(operation_id=operation, **change)]})
    assert transport.committed_states == before and len(transport.committed_events) == 1


def test_recheck_with_distinct_operation_is_not_mistaken_for_receipt_replay():
    factory, transport = setup()
    run_with(factory, {"evidence": [grade(operation_id=str(uuid4()))]})
    run_with(factory, {"evidence": [grade(operation_id=str(uuid4()))]})
    first, second = transport.committed_events
    assert first["weight"] == 1.0 and second["weight"] < first["weight"]
    assert second["p_before"] == pytest.approx(first["p_after"])
    assert len(transport.receipts) == 2
    assert first.get("planning_observation") is None and second.get("planning_observation") is None


@pytest.mark.parametrize("code", ["40P01", "40001", "55P03", "57014"])
def test_explicit_rolled_back_sql_conflict_rebuilds_boundedly(code):
    factory, transport = setup()
    calls = []

    def rpc(name, args):
        if name == "learning_evidence_commit":
            calls.append(deepcopy(args))
            if len(calls) == 1:
                request = httpx.Request("POST", "http://localhost/rpc/learning_evidence_commit")
                response = httpx.Response(409, json={"code": code}, request=request)
                raise httpx.HTTPStatusError(
                    "transaction rolled back", request=request, response=response
                )
        return transport(name, args)

    factory.rpc = rpc
    assert run_with(factory, {"evidence": [grade(operation_id=str(uuid4()))]})
    assert len(calls) == 2 and calls[0]["p_operation_id"] == calls[1]["p_operation_id"]
    assert calls[0]["p_plan"]["events"][0]["id"] == calls[1]["p_plan"]["events"][0]["id"]
    assert len(transport.committed_events) == 1


def test_stale_snapshot_recomputes_from_newer_scalar_not_old_prior():
    factory, transport = setup()
    p_after_other = bkt.update(0.35, "free_response", False)
    calls = []

    def rpc(name, args):
        if name == "learning_evidence_commit":
            calls.append(deepcopy(args))
            if len(calls) == 1:
                state = deepcopy(args["p_plan"]["state_rows"][0])
                state.update(
                    p_known=p_after_other,
                    opps=1,
                    streak_unassisted=0,
                    n_strong_unassisted=0,
                    max_streak_unassisted=0,
                    evidence_version=1,
                )
                transport.committed_states["n1"] = state
                return {"status": "stale"}
        return transport(name, args)

    factory.rpc = rpc
    result = run_with(factory, {"evidence": [grade()]})
    assert len(calls) == 2
    assert result[0]["before"] == pytest.approx(p_after_other)
    assert result[0]["after"] == pytest.approx(bkt.update(p_after_other, "free_response", True))
    assert transport.committed_states["n1"]["opps"] == 2


def test_ambiguous_commit_retries_identical_payload_and_never_rebuilds_without_receipt():
    factory, transport = setup()
    attempts = []

    def rpc(name, args):
        if name == "learning_evidence_commit":
            attempts.append(deepcopy(args))
            raise httpx.ReadTimeout("unknown commit")
        return transport(name, args)

    factory.rpc = rpc
    with pytest.raises(PlanningPersistenceUnavailable):
        run_with(factory, {"evidence": [grade()]})
    assert len(attempts) == 2 and attempts[0] == attempts[1]
    assert not transport.committed_events and not transport.committed_states
    assert sum(name == "learning_evidence_snapshot" for name, _ in transport.calls) == 1


def test_snapshot_keeps_original_missing_versions_and_metrics_are_never_overwritten():
    snapshot = {
        "nodes": [{"id": "n1", "evidence_version": 7}],
        "states": [],
        "edges": [],
        "checks": [],
    }
    plan = EvidencePlan(str(uuid4()), snapshot, NOW)
    from learning.learner_state import LearnerState

    state = LearnerState("u1", "n1", htc_k=0.9, unassisted_next=0.8, assist_gap=0.1, in_zone=True)
    plan.states["n1"] = state
    plan.state_rows["n1"] = state_row(state, NOW)
    payload = plan.payload([])
    assert payload["states_expected"] == [{"node_id": "n1", "version": None}]
    assert (
        not {"evidence_version", "htc_k", "unassisted_next", "assist_gap", "in_zone"}
        & payload["state_rows"][0].keys()
    )


def test_operation_and_fingerprint_bind_order_course_retention_and_explicit_identity():
    a, b = Evidence(**grade()), Evidence(**grade(question_hash="q2"))
    assert fingerprint("u1", "c1", [a, b], None) != fingerprint("u1", "c1", [b, a], None)
    assert fingerprint("u1", "c1", [a], None) != fingerprint("u1", "other", [a], None)
    assert fingerprint("u1", "c1", [a], None) != fingerprint("u1", "c1", [a], 0.8)
    with pytest.raises(EvidenceTransactionConflict):
        operation_id([a, Evidence(**grade(operation_id=str(uuid4())))])


def test_receipt_outage_is_not_missing_and_a_foreign_receipt_is_not_disclosed():
    with patch("learning.evidence_transaction.rpc", side_effect=RuntimeError("unavailable")):
        with pytest.raises(PlanningPersistenceUnavailable):
            read_receipt("u1", str(uuid4()))
    with patch("learning.evidence_transaction.rpc", return_value={"status": "conflict"}):
        with pytest.raises(EvidenceTransactionConflict):
            read_receipt("u1", str(uuid4()))


def test_tagged_topology_mix_is_rejected_before_any_table_or_rpc_write():
    from services.graph_service import apply_graph_update

    value = grade(
        planning_provenance={
            "check_item_id": "item1",
            "difficulty": 1,
            "synthetic_idk": False,
            "previously_seen": False,
        }
    )
    with (
        patch("services.graph_service.table") as table,
        patch("learning.evidence_transaction.rpc") as rpc,
    ):
        with pytest.raises(ValueError, match="topology"):
            apply_graph_update(
                "u1", {"new_nodes": [{"concept_name": "new"}], "evidence": [value]}, "c1"
            )
        table.assert_not_called()
        rpc.assert_not_called()


def test_frozen_observation_time_is_used_for_math_and_superseded_never_retried_as_new():
    factory, transport = setup()
    observed = datetime(2026, 10, 18, 22, 0, tzinfo=timezone.utc)
    calls = []

    def rpc(name, args):
        if name == "learning_evidence_commit":
            calls.append(deepcopy(args))
            return {"status": "superseded"}
        return transport(name, args)

    factory.rpc = rpc
    with pytest.raises(EvidenceObservationSuperseded):
        run_with(factory, {"evidence": [grade(operation_id=str(uuid4()), observed_at=observed)]})
    assert len(calls) == 1 and not transport.committed_events
    assert calls[0]["p_plan"]["observed_at"] == observed.isoformat()
    assert calls[0]["p_plan"]["events"][0]["created_at"] == observed.isoformat()


def test_completed_old_operation_receipt_replays_before_order_or_version_checks():
    factory, transport = setup()
    operation = str(uuid4())
    old = grade(
        operation_id=operation, observed_at=datetime(2026, 10, 18, 22, 0, tzinfo=timezone.utc)
    )
    initial = run_with(factory, {"evidence": [old]})
    run_with(
        factory,
        {"evidence": [grade(operation_id=str(uuid4()), question_hash="new", correct=False)]},
    )
    current = deepcopy(transport.committed_states)
    replay = run_with(factory, {"evidence": [old]})
    assert replay == initial and transport.committed_states == current
