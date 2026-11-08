"""The eval harness is hermetic about the AI budget (tests/evals/_replay.py::hermetic_budget).

The eval runner has no database. Before this, every grader case's budget check
read `llm_usage` through PostgREST with an empty SUPABASE_URL, failed with
"Request URL is missing an 'http://' or 'https://' protocol." and logged one
WARNING (31 per `grader` replay in the `evals` CI job); with a developer's
backend/.env loaded it read that database instead. The harness now answers the
budget's reads from an empty in-memory store, and the production warning stays.
"""

from __future__ import annotations

import logging
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

import db.connection as dbconn
from services import ai_budget
from tests.evals import _replay as replay


@pytest.fixture
def no_database(monkeypatch):
    """A database client that fails the test on any request."""
    client = MagicMock(name="no_database")
    for verb in ("get", "post", "patch", "delete"):
        getattr(client, verb).side_effect = AssertionError("the eval budget reached the database")
    monkeypatch.setattr(dbconn, "_client", client)
    return client


@pytest.fixture
def budget_warnings(caplog):
    caplog.set_level(logging.WARNING, logger="sapling.ai_budget")
    return lambda: [r for r in caplog.records if r.name == "sapling.ai_budget"]


def _requests(client) -> int:
    return sum(getattr(client, verb).call_count for verb in ("get", "post", "patch", "delete"))


def test_the_budget_check_reads_the_store_and_never_the_database(no_database, budget_warnings):
    with replay.hermetic_budget() as store:
        assert ai_budget.check("eval-user", "grader").level == "normal"
        assert ai_budget.check("eval-user", "decision").level == "normal"
        assert ai_budget.check("eval-user", "close").level == "normal"
        assert ai_budget.check("eval-user", "tutor", "develop").level == "normal"
    assert _requests(no_database) == 0
    assert budget_warnings() == []
    # four llm_usage reads (no request key, so no request cache) and the tutor-call read
    assert [name for name, _ in store.reads].count("llm_usage") == 4
    assert all(f["user_id"] == "eq.eval-user" for name, f in store.reads if name == "llm_usage")
    assert [name for name, _ in store.reads].count(ai_budget._TUTOR_CALLS_TABLE) == 1


def test_no_recorded_usage_is_the_decision_the_failed_read_used_to_give(monkeypatch):
    """Replay results cannot move: the old path failed the read and failed open
    (summary None); the store's empty ledger gives the same decision for every kind."""
    failing = MagicMock(side_effect=RuntimeError("Request URL is missing a protocol"))
    for kind, band in (("grader", None), ("decision", None), ("close", None), ("tutor", "novice")):
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(ai_budget, "_load_rows", failing)
            ai_budget.reset_for_tests()
            failed_open = ai_budget.check("eval-user", kind, band)
        with replay.hermetic_budget():
            empty = ai_budget.check("eval-user", kind, band)
        assert empty == failed_open, kind


def test_tutor_calls_count_in_memory():
    with replay.hermetic_budget() as store:
        assert ai_budget.count_tutor_call("eval-user") == 1
        assert ai_budget.count_tutor_call("eval-user") == 2
        assert sum(store.tutor_calls.values()) == 2
    with replay.hermetic_budget() as fresh:
        assert ai_budget.count_tutor_call("eval-user") == 1  # a new store, a new count
        assert sum(fresh.tutor_calls.values()) == 1


def test_an_unknown_store_read_fails_loudly():
    store = replay.BudgetStore()
    with pytest.raises(LookupError):
        store.table("events")
    with pytest.raises(LookupError):
        store.rpc("learning_evidence_commit", {})


def test_the_module_seams_are_restored_even_when_the_block_raises():
    with pytest.raises(RuntimeError):
        with replay.hermetic_budget():
            assert ai_budget.table is not dbconn.table
            raise RuntimeError("boom")
    assert ai_budget.table is dbconn.table
    assert ai_budget.rpc is dbconn.rpc


def test_every_dataset_is_evaluated_inside_the_hermetic_budget(
    monkeypatch, no_database, budget_warnings
):
    """evaluate_dataset is the one path run_all.py, every cli_main and the
    VARIANTS modules evaluate through."""
    monkeypatch.delenv(replay.RUNS_LOG_ENV, raising=False)
    seen = []

    async def run(_case_input):
        seen.append(ai_budget.table)
        return ai_budget.check("eval-user", "grader")

    class Dataset:
        name = "hermetic_budget_probe"

        async def evaluate(self, run_fn):
            await run_fn(None)
            return SimpleNamespace(cases=[], failures=[], print=lambda **_k: None)

    replay.evaluate_dataset(Dataset, run, update=False, print_report=False)
    assert len(seen) == 1 and isinstance(getattr(seen[0], "__self__", None), replay.BudgetStore)
    assert _requests(no_database) == 0
    assert budget_warnings() == []
    assert ai_budget.table is dbconn.table


def test_grader_agreement_grades_inside_the_hermetic_budget(monkeypatch, tmp_path):
    from tests.evals import grader_agreement as ga

    seen = []

    async def grade_all(records):
        seen.append(ai_budget.table)
        return records

    monkeypatch.setattr(ga, "load", lambda _path, need_item: [])
    monkeypatch.setattr(ga, "grade_all", grade_all)
    monkeypatch.setattr(ga, "report", lambda records: {})
    path = tmp_path / "answers.jsonl"
    path.write_text("")
    assert ga.main([str(path)]) == 0
    assert len(seen) == 1 and isinstance(getattr(seen[0], "__self__", None), replay.BudgetStore)
    assert ai_budget.table is dbconn.table
