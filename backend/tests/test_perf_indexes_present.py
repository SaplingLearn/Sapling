"""
Drift guard for the performance-index migration (#160, #161, #176, #177, #178).

There is no live Postgres in the unit suite, so we can't EXPLAIN the queries
here. What we *can* cheaply guarantee is that every index the audit called for
exists in BOTH the canonical schema (`supabase_schema.sql`, applied to fresh
environments) and the hand-applied migration (`migration_perf_indexes.sql`,
applied to existing prod). The two drifting apart is the exact failure mode
issue #197 is about, so this test pins them together.
"""
import os
import re

_DB = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "db")

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
    with open(os.path.join(_DB, name), encoding="utf-8") as fh:
        return fh.read()


def test_migration_declares_every_audited_index():
    sql = _read("migration_perf_indexes.sql")
    for index, table in EXPECTED_INDEXES.items():
        assert index in sql, f"{index} missing from migration_perf_indexes.sql"
        # Verify the index is actually declared ON the right table, not just
        # that the table name happens to appear somewhere (e.g. in a comment).
        # The CREATE may span lines, and may include CONCURRENTLY, so match
        # the index name followed by an ON <table>( clause across whitespace.
        pattern = re.escape(index) + r"\s+ON\s+" + re.escape(table) + r"\s*\("
        assert re.search(pattern, sql), (
            f"{index} is not declared ON {table}( in migration_perf_indexes.sql"
        )


def test_schema_mirrors_every_migration_index():
    sql = _read("supabase_schema.sql")
    for index in EXPECTED_INDEXES:
        assert index in sql, f"{index} not mirrored into supabase_schema.sql"


def test_indexes_are_idempotent_create_if_not_exists():
    # Both files must use IF NOT EXISTS so a re-run is a no-op (#197 hygiene).
    for fname in ("migration_perf_indexes.sql", "supabase_schema.sql"):
        sql = _read(fname)
        for index in EXPECTED_INDEXES:
            line = next((ln for ln in sql.splitlines() if index in ln), "")
            assert "IF NOT EXISTS" in line, f"{index} in {fname} is not guarded"
