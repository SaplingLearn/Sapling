"""PKG-05's reopen of PKG-03 (spec §4, §13 A22): node_mastery_events.grader_backend.

Read from the SQL file only: this guards the DDL graph_service depends on and
does NOT prove the live schema. The E2E lane's fresh-DB replay (`make e2e-up`
with E2E_FRESH_DB=1) is what applies it."""

import pathlib
import re

MIG_DIR = pathlib.Path(__file__).resolve().parents[1] / "db" / "migrations"
GRADER_BACKENDS = ("deterministic", "gemini", "gemini_second", "jev")


def _migration() -> tuple[str, str]:
    hits = sorted(MIG_DIR.glob("*_learning_grader_backend.sql"))
    assert len(hits) == 1, f"expected exactly one grader_backend migration, got {hits}"
    return hits[0].name, hits[0].read_text()


def test_grader_backend_column_is_nullable_and_checked():
    _, sql = _migration()
    assert "ALTER TABLE node_mastery_events ADD COLUMN IF NOT EXISTS grader_backend text" in sql
    assert "NOT NULL" not in sql, "legacy journal writers never set it"
    m = re.search(r"CHECK \(grader_backend IS NULL OR grader_backend IN \(([^)]*)\)\)", sql)
    assert m, sql
    assert tuple(v.strip().strip("'") for v in m.group(1).split(",")) == GRADER_BACKENDS


def test_migration_prefix_is_a_utc_timestamp_after_pkg03():
    name, _ = _migration()
    assert re.fullmatch(r"\d{14}_learning_grader_backend\.sql", name), name
    prior = sorted(MIG_DIR.glob("*_learning_learner_state.sql"))[0].name
    assert name > prior, "must sort after PKG-03's migration"


def test_evidence_literal_matches_the_check_list():
    """The model and the CHECK constraint name the same four backends, in order."""
    from typing import get_args

    from learning.evidence import GraderBackend

    assert get_args(GraderBackend) == GRADER_BACKENDS
