"""
Drift guard for the dedup-unique migration (#181, #195).

Asserts both UNIQUE indexes exist in the back-fill migration and are mirrored
into the canonical baseline schema (so fresh DBs get them inline), and that the
node index uses NULLS NOT DISTINCT so course-less duplicates also collide.

After the db restructure on main, migrations are ordered files under
db/migrations/ applied by db/migrate.py (the old flat migration_dedup_unique.sql
and supabase_schema.sql were removed). This guard tracks the canonical files:
  - migrations/0021_graph_dedup_constraints.sql (the back-fill migration)
  - migrations/0001_baseline_schema.sql        (fresh-DB inline schema)
"""
import os

_MIGRATIONS = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "db", "migrations"
)

_DEDUP_MIGRATION = "0021_graph_dedup_constraints.sql"
_BASELINE_SCHEMA = "0001_baseline_schema.sql"


def _read(name: str) -> str:
    with open(os.path.join(_MIGRATIONS, name), encoding="utf-8") as fh:
        return fh.read()


def test_migration_creates_both_unique_indexes():
    sql = _read(_DEDUP_MIGRATION)
    assert "idx_graph_nodes_user_concept_course" in sql
    assert "idx_graph_edges_unique" in sql
    # Node index must mirror the app's _normalize_concept: collapse whitespace
    # (regexp_replace) AND lower-case, plus null-collapsing.
    assert "lower(regexp_replace(btrim(concept_name), '\\s+', ' ', 'g'))" in sql
    assert "NULLS NOT DISTINCT" in sql


def test_migration_is_transaction_wrapped():
    # migrate.py runs each file in its own transaction; the explicit BEGIN/COMMIT
    # keeps the dedup DELETEs atomic with the index build (no rows can sneak in
    # between dedup and CREATE UNIQUE INDEX, which would fail the build).
    sql = _read(_DEDUP_MIGRATION)
    assert "BEGIN;" in sql
    assert "COMMIT;" in sql


def test_baseline_schema_mirrors_both_unique_indexes():
    # Fresh DBs are created from the baseline schema, so the same two UNIQUE
    # indexes must be present inline there as well.
    sql = _read(_BASELINE_SCHEMA)
    assert "idx_graph_nodes_user_concept_course" in sql
    assert "idx_graph_edges_unique" in sql
    assert "NULLS NOT DISTINCT" in sql


def test_migration_dedups_before_building_node_index():
    sql = _read(_DEDUP_MIGRATION)
    # The node delete must precede the unique-index creation, else it can't build.
    assert sql.index("DELETE FROM graph_nodes") < sql.index(
        "idx_graph_nodes_user_concept_course"
    )
    assert sql.index("DELETE FROM graph_edges\n WHERE id IN") < sql.index(
        "idx_graph_edges_unique"
    )


def test_edge_index_columns_match_app_upsert_on_conflict():
    # The edge upsert in graph_service.apply_graph_update uses
    # on_conflict="user_id,source_node_id,target_node_id"; the index must cover
    # exactly those columns or the upsert has no arbiter and fails.
    sql = _read(_DEDUP_MIGRATION)
    assert "ON graph_edges(user_id, source_node_id, target_node_id)" in sql
