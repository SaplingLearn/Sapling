"""
Drift guard for the dedup-unique migration (#181, #195).

Asserts both UNIQUE indexes exist in the migration and are mirrored into the
canonical schema, and that the node index uses NULLS NOT DISTINCT so course-less
duplicates also collide.
"""
import os

_DB = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "db")


def _read(name: str) -> str:
    with open(os.path.join(_DB, name), encoding="utf-8") as fh:
        return fh.read()


def test_migration_creates_both_unique_indexes():
    sql = _read("migration_dedup_unique.sql")
    assert "idx_graph_nodes_user_concept_course" in sql
    assert "idx_graph_edges_unique" in sql
    # Node index must mirror the app's _normalize_concept: collapse whitespace
    # (regexp_replace) AND lower-case, plus null-collapsing.
    assert "lower(regexp_replace(btrim(concept_name), '\\s+', ' ', 'g'))" in sql
    assert "NULLS NOT DISTINCT" in sql


def test_schema_mirrors_both_unique_indexes():
    sql = _read("supabase_schema.sql")
    assert "idx_graph_nodes_user_concept_course" in sql
    assert "idx_graph_edges_unique" in sql


def test_migration_dedups_before_building_node_index():
    sql = _read("migration_dedup_unique.sql")
    # The node delete must precede the unique-index creation, else it can't build.
    assert sql.index("DELETE FROM graph_nodes") < sql.index(
        "idx_graph_nodes_user_concept_course"
    )
    assert sql.index("DELETE FROM graph_edges\n WHERE id IN") < sql.index(
        "idx_graph_edges_unique"
    )
