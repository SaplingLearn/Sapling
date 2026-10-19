"""Every evidence batch commits provenance, learner state and graph atomically.

The transport is hermetically emulated here; real SQL rollback has a separate
integration gate. Legacy evidence retains NULL provenance, not weaker durability.
"""
from contextlib import contextmanager
from copy import deepcopy
from unittest.mock import patch
from uuid import uuid4

import pytest

from learning.evidence import PlanningPersistenceUnavailable
from test_learning_evidence_apply import NODES, _apply, _evidence_factory


def grade(key="q1", **extra):
    return {
        "node_id": "n1", "channel": "free_response", "correct": False,
        "session_id": "s1", "check_item_id": "ci1", "question_hash": key,
        "planning_provenance": {
            "check_item_id": "ci1", "difficulty": 3,
            "synthetic_idk": False, "previously_seen": False,
        },
        **extra,
    }


@contextmanager
def writer():
    factory, mocks = _evidence_factory(NODES, [], [])
    journal = factory("node_mastery_events")
    transport = factory.rpc
    with patch("test_learning_evidence_apply._evidence_factory", return_value=(factory, mocks)):
        yield journal, mocks, transport, lambda rows: _apply({"evidence": rows}, edges=[]), factory


def test_tagged_batch_commits_final_provenance_and_both_scalar_mirrors():
    with writer() as (journal, mocks, transport, apply, _factory):
        result, _, _ = apply([grade(max_rung=2)])
        assert result
        [event] = transport.committed_events
        assert event["planning_observation"]["correct"] is False
        assert event["planning_observation"]["max_rung"] == 2
        assert event["planning_observation"]["independent"] is False
        mocks["learner_state"].upsert.assert_called_once()
        mocks["graph_nodes"].update.assert_called_once()
        assert len(transport.receipts) == 1
        journal.insert_ignore_duplicates.assert_not_called()


def test_missing_provenance_migration_rejects_whole_transaction_without_column_fallback():
    with writer() as (journal, mocks, transport, apply, _factory):
        journal.insert.side_effect = RuntimeError("planning_observation unavailable")
        with pytest.raises(PlanningPersistenceUnavailable):
            apply([grade()])
        assert journal.insert.call_count == 2
        attempts = [call.args[0] for call in journal.insert.call_args_list]
        assert attempts[0] == attempts[1] and "planning_observation" in attempts[0]
        mocks["learner_state"].upsert.assert_not_called()
        mocks["graph_nodes"].update.assert_not_called()
        assert transport.committed_events == [] and transport.receipts == {}
        journal.insert_ignore_duplicates.assert_not_called()


def test_committed_then_timeout_replays_identical_operation_without_double_apply():
    with writer() as (journal, mocks, transport, apply, factory):
        calls = []
        def rpc(name, params):
            output = transport(name, params)
            if name == "learning_evidence_commit":
                calls.append(deepcopy(params))
                if len(calls) == 1:
                    raise RuntimeError("response lost after atomic commit")
            return output
        factory.rpc = rpc
        apply([grade()])
        assert len(calls) == 2 and calls[0] == calls[1]
        mocks["learner_state"].upsert.assert_called_once()
        mocks["graph_nodes"].update.assert_called_once()
        journal.insert.assert_called_once()
        assert len(transport.committed_events) == len(transport.receipts) == 1


@pytest.mark.parametrize("readback", ["missing", "mismatch", "outage"])
def test_unknown_commit_without_matching_receipt_never_reports_scalar_success(readback):
    with writer() as (journal, mocks, transport, apply, factory):
        attempts = []
        def rpc(name, params):
            if name == "learning_evidence_commit":
                attempts.append(deepcopy(params))
                raise RuntimeError("commit unavailable before acknowledgment")
            if name == "learning_evidence_receipt" and attempts:
                if readback == "outage":
                    raise RuntimeError("receipt unavailable")
                if readback == "mismatch":
                    return {"status": "committed", "receipt": {
                        "operation_id": params["p_operation_id"], "user_id": "u1", "course_id": "c1",
                        "input_fingerprint": "different", "changes": [], "posteriors": {},
                    }}
            return transport(name, params)
        factory.rpc = rpc
        with pytest.raises(PlanningPersistenceUnavailable):
            apply([grade()])
        assert len(attempts) == 2 and attempts[0] == attempts[1]
        mocks["learner_state"].upsert.assert_not_called()
        mocks["graph_nodes"].update.assert_not_called()
        journal.insert.assert_not_called()
        assert transport.receipts == {} and transport.committed_events == []


def test_writer_forced_duplicate_recheck_is_canonical_in_same_atomic_plan():
    with writer() as (_journal, mocks, transport, apply, _factory):
        apply([grade(correct=True), grade(correct=True)])
        rows = transport.committed_events
        assert rows[0]["planning_observation"]["independent"] is True
        assert rows[1]["planning_observation"]["same_session_recheck"] is True
        assert rows[1]["planning_observation"]["independent"] is False
        assert [row["evidence_seq"] for row in rows] == [0, 1]
        assert len(transport.plans[-1]["state_rows"]) == len(transport.plans[-1]["mirrors"]) == 1
        mocks["learner_state"].upsert.assert_called_once()
        assert mocks["learner_state"].upsert.call_args.args[0]["opps"] == 2


def test_receipt_accepts_finite_json_numbers_without_coercing_boolean_posteriors():
    from learning.evidence_transaction import _receipt
    operation = str(uuid4())
    expected = {"operation_id": operation, "user_id": "u1", "course_id": "c1",
                "input_fingerprint": "semantic", "changes": [{"concept": "A", "before": 0, "after": 1.0}],
                "posteriors": {"n1": 1.0}}
    assert _receipt({"receipt": expected}, "u1", operation, "semantic") == expected
    for key in ("before", "after"):
        invalid = deepcopy(expected)
        invalid["changes"][0][key] = False
        with pytest.raises(PlanningPersistenceUnavailable):
            _receipt({"receipt": invalid}, "u1", operation, "semantic")


def test_untagged_legacy_journal_failure_also_rejects_the_atomic_batch():
    with writer() as (journal, mocks, transport, apply, _factory):
        row = grade()
        row.pop("planning_provenance")
        journal.insert.side_effect = RuntimeError("legacy journal unavailable")
        with pytest.raises(PlanningPersistenceUnavailable):
            apply([row])
        assert journal.insert.call_count == 2
        assert all("planning_observation" not in call.args[0] for call in journal.insert.call_args_list)
        mocks["learner_state"].upsert.assert_not_called()
        mocks["graph_nodes"].update.assert_not_called()
        assert transport.receipts == {} and transport.committed_events == []


def test_canonical_operation_replay_preserves_one_observation_and_one_state_update():
    with writer() as (journal, mocks, transport, apply, _factory):
        row = grade(operation_id=str(uuid4()))
        first, _, _ = apply([row])
        second, _, _ = apply([row])
        assert first == second
        assert len(transport.committed_events) == len(transport.receipts) == 1
        mocks["learner_state"].upsert.assert_called_once()
        mocks["graph_nodes"].update.assert_called_once()
        journal.insert.assert_called_once()


def test_receipt_keeps_operation_posterior_after_a_later_learning_update():
    from learning.evidence_transaction import read_receipt
    with writer() as (journal, mocks, transport, apply, factory):
        first_id, later_id = str(uuid4()), str(uuid4())
        first, _, _ = apply([grade(operation_id=first_id)])
        later, _, _ = apply([grade("q2", correct=True, operation_id=later_id)])
        assert first[0]["after"] != later[0]["after"]
        with patch("learning.evidence_transaction.rpc", side_effect=factory.rpc):
            recovered = read_receipt("u1", first_id)
        assert recovered["posteriors"]["n1"] == first[0]["after"]
        replay, _, _ = apply([grade(operation_id=first_id)])
        assert replay == first
        assert transport.committed_states["n1"]["p_known"] == later[0]["after"]
        assert len(transport.committed_events) == len(transport.receipts) == 2
        assert mocks["learner_state"].upsert.call_count == mocks["graph_nodes"].update.call_count == 2
        assert journal.insert.call_count == 2
