"""PKG-11: FSRS state on flashcards + the quiz/flashcard gate seams.

Route tests mock `table` (tests/test_graph_service.py::_mock_table style) and
patch the gate at the route module (`routes.flashcards.learning_loop_active`).
FSRS maths is PKG-02's (tests/test_learning_fsrs.py); here `next_state`,
`interval` and `order_due` are patched at the route module so these tests
prove WIRING — what the route reads, what it writes, in what order — not
the curve. Flag-off tests snapshot the exact legacy query strings and
payload key sets: the pre-series behaviour must be byte-identical.
"""

from __future__ import annotations

import pathlib
import re

import pytest
from fastapi.testclient import TestClient

from main import app

client = TestClient(app)

MIG_DIR = pathlib.Path(__file__).resolve().parents[1] / "db" / "migrations"
USER_ID = "user_test"

LEGACY_LIST_COLS = (
    "id,user_id,topic,offering_id,front,back,times_reviewed,last_rating,last_reviewed_at,created_at"
)
LEGACY_RATE_COLS = "id,times_reviewed"
LEGACY_RATE_KEYS = {"times_reviewed", "last_rating", "last_reviewed_at"}
FSRS_COLS = ",fsrs_d,fsrs_s,due_at,reps,lapses"
FSRS_KEYS = {"fsrs_d", "fsrs_s", "due_at", "reps", "lapses"}


# ── Migration ────────────────────────────────────────────────────────────────


def _migration() -> str:
    hits = sorted(MIG_DIR.glob("*_learning_flashcards_fsrs.sql"))
    assert len(hits) == 1, f"expected exactly one learning_flashcards_fsrs migration, got {hits}"
    return hits[0].read_text()


class TestMigration:
    def test_prefix_is_a_utc_timestamp(self):
        hits = sorted(MIG_DIR.glob("*_learning_flashcards_fsrs.sql"))
        assert hits, "no learning_flashcards_fsrs migration"
        assert re.fullmatch(r"\d{14}_learning_flashcards_fsrs\.sql", hits[0].name), hits[0].name

    @pytest.mark.parametrize(
        "col,decl",
        [
            ("fsrs_d", r"double precision"),
            ("fsrs_s", r"double precision"),
            ("due_at", r"timestamptz"),
            ("reps", r"int\s+NOT NULL\s+DEFAULT\s+0"),
            ("lapses", r"int\s+NOT NULL\s+DEFAULT\s+0"),
        ],
    )
    def test_columns_are_declared_per_spec(self, col, decl):
        assert re.search(rf"ADD COLUMN IF NOT EXISTS\s+{col}\s+{decl}", _migration()), col

    def test_due_index_is_user_scoped(self):
        assert re.search(
            r"CREATE INDEX IF NOT EXISTS flashcards_due_idx ON flashcards \(user_id, due_at\)",
            _migration(),
        )

    def test_only_touches_flashcards(self):
        sql = _migration()
        assert "ALTER TABLE flashcards" in sql
        assert not re.search(r"ALTER TABLE (?!flashcards)", sql)
        assert "DROP" not in sql.upper()
