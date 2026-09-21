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


# ── review round 2: a retry waits ───────────────────────────────────────────


def _backoff_migration() -> str:
    hits = sorted(MIG_DIR.glob("*_document_index_retry_backoff.sql"))
    assert len(hits) == 1, f"expected exactly one retry-backoff migration, got {hits}"
    return hits[0].read_text()


def test_the_backoff_migration_sorts_after_the_one_it_amends():
    first = sorted(MIG_DIR.glob("*_document_index_status.sql"))[0].name
    second = sorted(MIG_DIR.glob("*_document_index_retry_backoff.sql"))[0].name
    assert second > first


def test_a_failed_or_partial_row_waits_after_its_last_attempt():
    """Review round 2: failed/partial rows were claimable at once, and the
    finished row's lease was cleared, so `NULLS FIRST` handed a just-failed
    document straight back — three attempts inside one sweep, a whole budget
    spent on a few seconds of Gemini 5xx."""
    sql = _backoff_migration()
    assert re.search(
        r"index_status IN \('partial', 'failed'\)\s*AND\s*\(c\.index_leased_at IS NULL"
        r"\s*OR c\.index_leased_at\s*<\s*now\(\) - make_interval\(secs => lease_seconds\)\)",
        sql,
    )


def test_the_signature_is_unchanged_so_no_second_overload_appears():
    """PostgREST resolves a function by its argument NAMES; a second overload is
    how #629 nearly left an unfiltered match_course_chunks callable."""
    sql = _backoff_migration()
    assert "CREATE OR REPLACE FUNCTION claim_documents_for_indexing(" in sql
    assert re.search(r"max_attempts\s+INT,\s*lease_seconds\s+INT,\s*batch_size\s+INT", sql)
    assert "DROP FUNCTION" not in sql
    assert "REVOKE ALL ON FUNCTION claim_documents_for_indexing" in sql
