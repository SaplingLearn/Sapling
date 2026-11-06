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


# ── #758: the terminal state is stored ─────────────────────────────────────


def _terminal_migration() -> str:
    hits = sorted(MIG_DIR.glob("*_document_index_terminal_state.sql"))
    assert len(hits) == 1, f"expected exactly one terminal-state migration, got {hits}"
    return hits[0].read_text()


def _latest_claim() -> str:
    for path in sorted(MIG_DIR.glob("*.sql"), reverse=True):
        sql = path.read_text()
        if "FUNCTION claim_documents_for_indexing(" in sql:
            return sql
    raise AssertionError("no claim_documents_for_indexing definition")


def _reap(sql: str) -> str:
    return sql.split("UPDATE documents r", 1)[1].split(";", 1)[0]


def test_the_live_claim_reaps_an_over_budget_pending_row():
    """#758 review: `_restore` refunds a claim back to 'pending' with
    attempts > 0. Lower INDEX_MAX_ATTEMPTS under that count and the row is
    neither claimable (`attempts < max`) nor — before this — reaped: pending
    forever, out of retrieval, never reported as exhausted."""
    reap = _reap(_latest_claim())
    assert re.search(r"r\.index_status = 'pending'", reap)
    assert re.search(r"WHEN 'pending'\s+THEN 'attempts_exhausted'", reap)
    # Still bounded by the budget, so a fresh upload is never reaped.
    assert re.search(r"r\.index_attempts >= max_attempts", reap)


def test_the_reap_pending_fix_is_a_new_migration_not_an_edit():
    """The terminal-state file may already sit in a ledger; an edit would
    never re-run there."""
    assert "'pending'" not in _reap(_terminal_migration()).split("WHERE", 1)[1]
    hits = sorted(MIG_DIR.glob("*_document_index_reap_pending.sql"))
    assert len(hits) == 1 and hits[0].read_text() == _latest_claim()


def test_exhausted_is_admitted_by_the_check_constraint():
    sql = _terminal_migration()
    assert re.search(r"CHECK \(index_status IN\s*\([^)]*'exhausted'\)", sql)
    # …alongside every value the first migration admitted.
    for value in ("pending", "indexing", "indexed", "partial", "failed", "skipped"):
        assert f"'{value}'" in sql


def test_an_omitted_status_lands_in_the_queue_not_a_terminal_state():
    """'skipped' as the default meant any insert path that forgot the column
    landed, silently, where nothing would ever index it."""
    assert re.search(
        r"ALTER COLUMN index_status SET DEFAULT 'pending'", _terminal_migration()
    )


def test_a_last_attempt_that_died_holding_its_lease_is_reaped():
    """attempts = max and 'indexing': the claim's `attempts < max` meant
    nothing could ever retake it. The reaper makes it terminal and visible."""
    sql = _latest_claim()
    assert re.search(r"SET index_status = 'exhausted'", sql)
    assert re.search(r"r\.index_attempts >= max_attempts", sql)
    assert re.search(
        r"r\.index_status = 'indexing'\s*AND r\.index_leased_at < now\(\) - "
        r"make_interval\(secs => lease_seconds\)", sql)
    assert "'lease_expired'" in sql
    # The reap runs BEFORE the claim, in the same function.
    assert sql.index("SET index_status = 'exhausted'") < sql.index(
        "SET index_status    = 'indexing'")


def test_the_reaper_leaves_the_lease_so_a_slow_attempt_still_records():
    assert "index_leased_at =" not in _reap(_latest_claim())


def test_the_claim_clears_the_previous_error_and_keeps_its_contract():
    sql = _latest_claim()
    assert re.search(r"index_error\s*=\s*NULL", sql)
    assert "CREATE OR REPLACE FUNCTION claim_documents_for_indexing(" in sql
    assert re.search(r"max_attempts\s+INT,\s*lease_seconds\s+INT,\s*batch_size\s+INT", sql)
    assert "DROP FUNCTION" not in sql
    assert "FOR UPDATE SKIP LOCKED" in sql
    assert re.search(r"index_attempts\s*=\s*d\.index_attempts\s*\+\s*1", sql)
    assert "REVOKE ALL ON FUNCTION claim_documents_for_indexing" in sql
    assert "GRANT EXECUTE ON FUNCTION claim_documents_for_indexing" in sql
