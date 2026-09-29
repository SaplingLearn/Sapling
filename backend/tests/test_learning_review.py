"""PKG-12 review surfaces: queue merge/order/budget, one grader path,
FSRS on flashcards, retention targets, successive relearning, events.
Hermetic: every table() is a mock, the grader helper is patched."""

from __future__ import annotations

import pathlib
import re
from datetime import datetime, timezone
from unittest.mock import MagicMock

from learning import params

NOW = datetime(2026, 9, 26, 12, 0, tzinfo=timezone.utc)
USER = "user_andres"
COURSE = "course-1"
MIG_DIR = pathlib.Path(__file__).resolve().parents[1] / "db" / "migrations"


def _tables(data: dict):
    """One MagicMock per table name so a test can assert on a specific table's
    update/insert calls (mirrors tests/test_graph_service.py::_cached_mock_table)."""
    handles: dict = {}

    def factory(name):
        if name not in handles:
            m = MagicMock(name=name)
            m.select.return_value = list(data.get(name, []))
            m.insert.return_value = []
            m.update.return_value = []
            m.upsert.return_value = []
            handles[name] = m
        return handles[name]

    return factory, handles


# ── Task 2: taxonomy, constants, migration ────────────────────────────────────


def test_review_events_are_in_the_taxonomy():
    from services import events_service

    assert {"review.served", "review.graded"} <= events_service.EVENT_TAXONOMY


def test_review_constants_exist_and_are_consistent():
    assert params.REVIEW_SECONDS_PER_FLASHCARD < params.REVIEW_SECONDS_PER_CHECK
    assert set(params.REVIEW_DIFFICULTY_BY_BAND) == {"novice", "develop", "profic"}
    assert set(params.REVIEW_DIFFICULTY_BY_BAND.values()) <= set(params.CHECK_ITEM_DIFFICULTIES)
    assert set(params.REVIEW_FORMAT_BY_BAND) == {"novice", "develop", "profic"}
    # rule 1 falls back to the other one
    assert set(params.REVIEW_FORMAT_BY_BAND.values()) == {"free", "mc_reason"}


def test_review_session_mode_migration():
    hits = sorted(MIG_DIR.glob("*_learning_sessions_mode_review.sql"))
    assert len(hits) == 1, hits
    sql = hits[0].read_text()
    assert re.fullmatch(r"\d{14}_learning_sessions_mode_review\.sql", hits[0].name)
    # sorts after every earlier series migration (the ledger applies in name order)
    assert hits[0].name > "20260929073325_learning_check_item_draft_failures_solo.sql"
    assert "DROP CONSTRAINT IF EXISTS sessions_mode_check" in sql
    assert re.search(r"CHECK \(mode IN \('socratic','expository','teachback','review'\)\)", sql)
