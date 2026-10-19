"""PKG-03 migration invariants, read from the SQL file only: they guard the
properties graph_service depends on and do NOT prove the live schema. That
needs `python -m db.migrate` / a replay on PG15 (the E2E lane's
`make e2e-up`), whose status is recorded in HANDOFF-03 Known gaps."""

import pathlib
import re

MIG_DIR = pathlib.Path(__file__).resolve().parents[1] / "db" / "migrations"

NEW_EVENT_COLUMNS = (
    "channel",
    "correct",
    "weight",
    "assisted",
    "max_rung",
    "p_before",
    "p_after",
    "session_id",
    "check_item_id",
    "question_hash",
    "confidence",
)


def _migration() -> str:
    hits = sorted(MIG_DIR.glob("*_learning_learner_state.sql"))
    assert len(hits) == 1, f"expected exactly one learner_state migration, got {hits}"
    return hits[0].read_text()


def test_learner_state_table_is_keyed_per_user_and_node_and_cascades():
    sql = _migration()
    assert "CREATE TABLE IF NOT EXISTS learner_state" in sql
    assert re.search(r"PRIMARY KEY\s*\(\s*user_id\s*,\s*node_id\s*\)", sql)
    assert re.search(
        r"node_id\s+text\s+NOT NULL\s+REFERENCES\s+graph_nodes\(id\)\s+ON DELETE CASCADE", sql
    )


def test_p_known_is_required_and_counters_default_to_zero():
    sql = _migration()
    assert re.search(r"p_known\s+double precision\s+NOT NULL", sql)
    # max_streak_unassisted: spec §13 A3 (wheelspin reads "ever reached 3").
    for col in ("n_strong_unassisted", "streak_unassisted", "max_streak_unassisted", "opps"):
        assert re.search(rf"\b{col}\s+int\s+NOT NULL\s+DEFAULT\s+0", sql), col


def test_due_index_exists_for_the_scheduler():
    assert re.search(
        r"CREATE INDEX IF NOT EXISTS learner_state_due_idx ON learner_state\s*\(\s*user_id\s*,\s*fsrs_due_at\s*\)",
        _migration(),
    )


def test_every_evidence_column_is_added_idempotently_and_nullable():
    sql = _migration()
    for col in NEW_EVENT_COLUMNS:
        m = re.search(rf"ADD COLUMN IF NOT EXISTS\s+{col}\s+[^,;]+", sql)
        assert m, col
        assert "NOT NULL" not in m.group(0), f"{col} must stay nullable for legacy writers"


def test_migration_prefix_is_a_utc_timestamp_after_pkg00():
    name = sorted(MIG_DIR.glob("*_learning_learner_state.sql"))[0].name
    assert re.fullmatch(r"\d{14}_learning_learner_state\.sql", name), name
    beta = sorted(MIG_DIR.glob("*_learning_loop_beta.sql"))[0].name
    assert name > beta, "must sort after PKG-00's migration"
