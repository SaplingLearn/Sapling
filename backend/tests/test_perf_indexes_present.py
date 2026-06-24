"""
Drift guard for the performance-index work (#160, #161, #176, #177, #178).

There is no live Postgres in the unit suite, so we can't EXPLAIN the queries
here. What we *can* cheaply guarantee is that every index the audit called for
is declared in BOTH places that must stay in sync:

  * db/migrations/0001_baseline_schema.sql — the canonical schema applied to
    fresh environments at baseline time.
  * db/migrations/0019_perf_indexes.sql — the standalone migration that
    backfills existing databases baselined before the indexes existed.

The two drifting apart is the exact failure mode the perf rollout guards
against, so this test pins them together.
"""
import os
import re

_MIGRATIONS = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "db", "migrations"
)

BASELINE = "0001_baseline_schema.sql"
PERF_MIGRATION = "0019_perf_indexes.sql"

# index name -> table it must be declared on
EXPECTED_INDEXES = {
    "idx_messages_session_created": "messages",
    "idx_graph_edges_user": "graph_edges",
    "idx_graph_edges_source": "graph_edges",
    "idx_graph_edges_target": "graph_edges",
    "idx_sessions_user_started": "sessions",
    "idx_documents_user_created": "documents",
    "idx_documents_user_course": "documents",
    "idx_study_guides_user": "study_guides",
    "idx_study_guides_lookup": "study_guides",
    "idx_quiz_attempts_user": "quiz_attempts",
}


def _read(name: str) -> str:
    with open(os.path.join(_MIGRATIONS, name), encoding="utf-8") as fh:
        return fh.read()


def _assert_declares_every_index(fname: str) -> None:
    sql = _read(fname)
    for index, table in EXPECTED_INDEXES.items():
        assert index in sql, f"{index} missing from {fname}"
        # Verify the index is actually declared ON the right table, not just
        # that the table name happens to appear somewhere (e.g. in a comment).
        # The CREATE may span lines, so match the index name followed by an
        # ON <table>( clause across whitespace.
        pattern = re.escape(index) + r"\s+ON\s+" + re.escape(table) + r"\s*\("
        assert re.search(pattern, sql), (
            f"{index} is not declared ON {table}( in {fname}"
        )


def test_baseline_schema_declares_every_audited_index():
    _assert_declares_every_index(BASELINE)


def test_perf_migration_declares_every_audited_index():
    _assert_declares_every_index(PERF_MIGRATION)


def test_indexes_are_idempotent_create_if_not_exists():
    # Both files must use IF NOT EXISTS so a re-run is a no-op.
    for fname in (BASELINE, PERF_MIGRATION):
        sql = _read(fname)
        for index in EXPECTED_INDEXES:
            line = next((ln for ln in sql.splitlines() if index in ln), "")
            assert "IF NOT EXISTS" in line, f"{index} in {fname} is not guarded"
