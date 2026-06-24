"""
Drift guard for the FK-integrity migration (#179, #180).

No live Postgres in the unit suite, so we assert the textual invariants that
matter: the numbered migration adds each constraint behind the pg_constraint
guard (re-runnable) and cleans orphans first, and the canonical baseline schema
declares the same REFERENCES inline so a fresh database is born with the FKs.

After main restructured db/ into ordered migrations applied by migrate.py, the
FK DDL lives in migrations/0020_fk_integrity.sql (for already-migrated DBs) and
the inline REFERENCES live in migrations/0001_baseline_schema.sql (for fresh
DBs). The old flat db/supabase_schema.sql / migration_*.sql files were deleted.
"""
import os

_MIGRATIONS = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "db", "migrations"
)

FK_MIGRATION = "0020_fk_integrity.sql"
BASELINE = "0001_baseline_schema.sql"

CONSTRAINTS = (
    "graph_edges_user_id_fkey",
    "notes_user_id_fkey",
    "notes_course_id_fkey",
)


def _read(name: str) -> str:
    with open(os.path.join(_MIGRATIONS, name), encoding="utf-8") as fh:
        return fh.read()


def test_migration_adds_each_constraint_behind_a_guard():
    sql = _read(FK_MIGRATION)
    for name in CONSTRAINTS:
        assert name in sql, f"{name} missing from migration"
        # Every ADD CONSTRAINT must be inside an IF NOT EXISTS pg_constraint guard.
    assert sql.count("IF NOT EXISTS") >= len(CONSTRAINTS)
    assert "pg_constraint" in sql


def test_migration_cleans_orphans_before_altering():
    sql = _read(FK_MIGRATION)
    # Orphan deletes must precede the ALTER TABLE that validates the FK.
    assert "DELETE FROM graph_edges" in sql
    assert "DELETE FROM notes" in sql
    assert sql.index("DELETE FROM graph_edges") < sql.index("graph_edges_user_id_fkey")
    assert sql.index("DELETE FROM notes") < sql.index("notes_user_id_fkey")


def test_migration_indexes_the_referencing_column():
    # graph_edges.user_id needs an index on the FK referencing side (#179).
    sql = _read(FK_MIGRATION)
    assert "CREATE INDEX IF NOT EXISTS idx_graph_edges_user_id" in sql


def test_baseline_declares_inline_references():
    # Fresh databases must be born with the FKs, declared inline in the baseline.
    sql = _read(BASELINE)
    assert "user_id           TEXT NOT NULL REFERENCES users(id)" in sql  # graph_edges
    assert "user_id TEXT NOT NULL REFERENCES users(id)" in sql            # notes
    assert "course_id TEXT NOT NULL REFERENCES courses(id)" in sql        # notes
