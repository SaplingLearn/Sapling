"""Durable tagged append precedes BKT writes; legacy journal stays best effort."""

from contextlib import contextmanager
from copy import deepcopy
from unittest.mock import patch

import pytest

from learning.evidence import PlanningPersistenceUnavailable
from test_learning_evidence_apply import NODES, _apply, _evidence_factory


def grade(key="q1", **extra):
    return {
        "node_id": "n1",
        "channel": "free_response",
        "correct": False,
        "session_id": "s1",
        "check_item_id": "ci1",
        "question_hash": key,
        "planning_provenance": {
            "check_item_id": "ci1",
            "difficulty": 3,
            "synthetic_idk": False,
            "previously_seen": False,
        },
        **extra,
    }


@contextmanager
def writer():
    factory, mocks = _evidence_factory(NODES, [], [])
    journal = factory("node_mastery_events")
    journal.insert_ignore_duplicates.side_effect = lambda row, **kw: [row]
    with patch("test_learning_evidence_apply._evidence_factory", return_value=(factory, mocks)):
        yield journal, mocks, lambda rows: _apply({"evidence": rows}, edges=[])


def test_tagged_append_is_durable_before_any_scalar_write():
    with writer() as (journal, mocks, apply):

        def append(row, **_kw):
            assert not mocks["learner_state"].upsert.called
            assert not mocks["graph_nodes"].update.called
            assert row["planning_observation"]["correct"] is False
            return [row]

        journal.insert_ignore_duplicates.side_effect = append
        result, _, _ = apply([grade(max_rung=2)])
        assert result
        assert mocks["learner_state"].upsert.call_count == 1
        journal.insert.assert_not_called()


def test_strict_append_failure_or_missing_migration_never_changes_scalar_state():
    with writer() as (journal, mocks, apply):
        journal.insert_ignore_duplicates.side_effect = RuntimeError(
            "planning_observation unavailable"
        )
        with pytest.raises(PlanningPersistenceUnavailable):
            apply([grade()])
        assert journal.insert_ignore_duplicates.call_count == 2
        ids = [call.args[0]["id"] for call in journal.insert_ignore_duplicates.call_args_list]
        assert ids[0] == ids[1]
        mocks["learner_state"].upsert.assert_not_called()
        mocks["graph_nodes"].update.assert_not_called()
        journal.insert.assert_not_called()  # never retry without the provenance column


def test_committed_then_timeout_is_verified_by_identical_readback_before_one_state_write():
    with writer() as (journal, mocks, apply):
        committed = []

        def append(row, **_kw):
            if not committed:
                committed.append(deepcopy(row))
                raise RuntimeError("response timed out after commit")
            return []

        journal.insert_ignore_duplicates.side_effect = append
        journal.select.side_effect = lambda *a, **kw: deepcopy(committed)
        apply([grade()])
        assert journal.insert_ignore_duplicates.call_count == 2
        assert mocks["learner_state"].upsert.call_count == 1
        assert mocks["graph_nodes"].update.call_count == 1
        assert journal.select.call_args.kwargs["filters"] == {"id": f"eq.{committed[0]['id']}"}


@pytest.mark.parametrize("readback", ["missing", "mismatch", "outage"])
def test_ambiguous_duplicate_without_identical_readback_fails_before_scalar_writes(readback):
    with writer() as (journal, mocks, apply):
        attempted = []

        def append(row, **_kw):
            attempted.append(deepcopy(row))
            return []

        def select(*_a, **_kw):
            if readback == "outage":
                raise RuntimeError("readback unavailable")
            return [] if readback == "missing" else [{**attempted[0], "correct": True}]

        journal.insert_ignore_duplicates.side_effect = append
        journal.select.side_effect = select
        with pytest.raises(PlanningPersistenceUnavailable):
            apply([grade()])
        mocks["learner_state"].upsert.assert_not_called()
        mocks["graph_nodes"].update.assert_not_called()


def test_writer_forced_duplicate_recheck_is_the_canonical_persisted_provenance():
    with writer() as (journal, _mocks, apply):
        apply([grade(correct=True), grade(correct=True)])
        rows = [call.args[0] for call in journal.insert_ignore_duplicates.call_args_list]
        assert rows[0]["planning_observation"]["independent"] is True
        assert rows[1]["planning_observation"]["same_session_recheck"] is True
        assert rows[1]["planning_observation"]["independent"] is False
        assert [row["evidence_seq"] for row in rows] == [0, 1]


def test_readback_accepts_equivalent_db_numeric_json_without_coercing_boolean_flags():
    from services.graph_service import _same_planning_event

    with writer() as (journal, mocks, apply):
        committed = []

        def append(row, **_kw):
            if not committed:
                committed.append(deepcopy(row))
                raise RuntimeError("response lost after commit")
            return []

        def select(*_a, **_kw):
            return [{**committed[0], "weight": 0, "delta": 0}]

        journal.insert_ignore_duplicates.side_effect = append
        journal.select.side_effect = select
        apply([grade(correct=True, max_rung=6)])
        assert mocks["learner_state"].upsert.call_count == 1
        assert not _same_planning_event({**committed[0], "weight": False}, committed[0])


def test_untagged_legacy_journal_failure_preserves_its_existing_best_effort_contract():
    with writer() as (journal, mocks, apply):
        row = grade()
        row.pop("planning_provenance")
        journal.insert.side_effect = RuntimeError("legacy journal unavailable")
        result, _, _ = apply([row])
        assert result
        assert mocks["learner_state"].upsert.call_count == 1
        assert journal.insert.call_count == 2
        journal.insert_ignore_duplicates.assert_not_called()
