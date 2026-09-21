"""The #482 migration's invariants.

The live schema is proven by migration replay from empty in the E2E lane; this
guards the properties the rest of #482 depends on, which a later edit to the
file could otherwise drop silently.
"""
import pathlib
import re

MIG_DIR = pathlib.Path(__file__).resolve().parents[1] / "db" / "migrations"


def _migration() -> str:
    hits = sorted(MIG_DIR.glob("*_document_index_status.sql"))
    assert len(hits) == 1, f"expected exactly one index-status migration, got {hits}"
    return hits[0].read_text()


def test_every_status_value_is_in_the_check_constraint():
    sql = _migration()
    for value in ("pending", "indexing", "indexed", "partial", "failed", "skipped"):
        assert f"'{value}'" in sql, f"{value} missing from the migration"


def test_new_columns_default_to_an_inert_state():
    # 'skipped' deliberately: between this migration landing and the derivation
    # backfill running, the sweeper must not claim a historical row.
    sql = _migration()
    assert re.search(
        r"index_status\s+text\s+NOT NULL\s+DEFAULT\s+'skipped'", sql, re.IGNORECASE
    )


def test_claim_function_is_not_exposed_to_the_anon_key():
    # PostgREST would otherwise expose it to the anon key the frontend ships.
    sql = _migration()
    assert "REVOKE ALL ON FUNCTION claim_documents_for_indexing" in sql
    assert "GRANT EXECUTE ON FUNCTION claim_documents_for_indexing" in sql
    assert "service_role" in sql


def test_claim_is_atomic_and_skips_locked_rows():
    sql = _migration()
    assert "FOR UPDATE SKIP LOCKED" in sql
    assert "RETURNING" in sql


def test_claim_increments_attempts_so_a_crash_still_counts():
    # A document that crashes the worker must be bounded to MAX attempts.
    sql = _migration()
    assert re.search(r"index_attempts\s*=\s*d\.index_attempts\s*\+\s*1", sql)


def test_confidence_is_range_checked():
    sql = _migration()
    assert "shareability_confidence" in sql
    assert re.search(r"shareability_confidence\s*>=\s*0", sql)
    assert re.search(r"shareability_confidence\s*<=\s*1", sql)
