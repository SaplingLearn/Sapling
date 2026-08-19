"""Preflight guards for the prod promotion runner (#516).

Every function here is pure — it takes plain data, so these tests need no
database, no network and no credentials.
"""
from pathlib import Path

from promotion.preflight import (
    Finding,
    evaluate,
    ledger_diff,
    project_ref,
    scan_destructive,
    staging_gap,
)

POOLER = "postgresql://postgres.abcdefghijklmnop:pw@aws-0-us-west-2.pooler.supabase.com:5432/postgres"
DIRECT = "postgresql://postgres:pw@db.abcdefghijklmnop.supabase.co:5432/postgres"
API = "https://abcdefghijklmnop.supabase.co"


def test_project_ref_from_pooler_uri():
    assert project_ref(POOLER) == "abcdefghijklmnop"


def test_project_ref_from_direct_uri():
    assert project_ref(DIRECT) == "abcdefghijklmnop"


def test_project_ref_from_api_url():
    assert project_ref(API) == "abcdefghijklmnop"


def test_project_ref_unknown_shape_is_empty():
    assert project_ref("postgresql://postgres:pw@127.0.0.1:54322/postgres") == ""


def test_ledger_diff_reports_pending_in_file_order():
    files = ["0001_a.sql", "0002_b.sql", "0003_c.sql"]
    pending, orphans = ledger_diff(files, {"0001_a.sql"})
    assert pending == ["0002_b.sql", "0003_c.sql"]
    assert orphans == []


def test_ledger_diff_reports_orphans():
    pending, orphans = ledger_diff(["0001_a.sql"], {"0001_a.sql", "0099_ghost.sql"})
    assert pending == []
    assert orphans == ["0099_ghost.sql"]


def test_staging_gap_flags_migrations_staging_never_ran():
    assert staging_gap(["0002_b.sql", "0003_c.sql"], {"0002_b.sql"}) == ["0003_c.sql"]


def test_staging_gap_empty_when_staging_is_ahead():
    assert staging_gap(["0002_b.sql"], {"0002_b.sql", "0003_c.sql"}) == []


def test_scan_destructive_flags_drop_table(tmp_path):
    f = tmp_path / "0050_x.sql"
    f.write_text("CREATE TABLE a (id int);\nDROP TABLE legacy_grades;\n")
    findings = scan_destructive([f])
    assert [x.kind for x in findings] == ["DROP TABLE"]
    assert "0050_x.sql:2" in findings[0].detail


def test_scan_destructive_flags_drop_column_and_truncate(tmp_path):
    f = tmp_path / "0051_y.sql"
    f.write_text("ALTER TABLE t DROP COLUMN old;\nTRUNCATE TABLE cache;\n")
    assert {x.kind for x in scan_destructive([f])} == {"DROP COLUMN", "TRUNCATE"}


def test_scan_destructive_flags_type_change(tmp_path):
    f = tmp_path / "0052_z.sql"
    f.write_text("ALTER TABLE t ALTER COLUMN amount TYPE numeric;\n")
    assert [x.kind for x in scan_destructive([f])] == ["ALTER COLUMN ... TYPE"]


def test_scan_destructive_flags_set_data_type(tmp_path):
    """SET DATA TYPE is the spelled-out form of the same destructive change."""
    f = tmp_path / "0068_t.sql"
    f.write_text("ALTER TABLE t ALTER COLUMN amount SET DATA TYPE numeric;\n")
    assert [x.kind for x in scan_destructive([f])] == ["ALTER COLUMN ... TYPE"]


def test_scan_destructive_flags_type_change_on_quoted_column(tmp_path):
    f = tmp_path / "0069_t.sql"
    f.write_text('ALTER TABLE t ALTER COLUMN "type" TYPE text;\n')
    assert [x.kind for x in scan_destructive([f])] == ["ALTER COLUMN ... TYPE"]


def test_scan_destructive_ignores_set_not_null_on_column_named_type(tmp_path):
    """This repo has columns literally named `type` (0001/0009/0026); a benign
    ALTER on one is not a type change."""
    f = tmp_path / "0070_ok.sql"
    f.write_text("ALTER TABLE events ALTER COLUMN type SET NOT NULL;\n")
    assert scan_destructive([f]) == []


def test_scan_destructive_ignores_drop_default_on_column_named_type(tmp_path):
    f = tmp_path / "0071_ok.sql"
    f.write_text("ALTER TABLE cosmetics ALTER COLUMN type DROP DEFAULT;\n")
    assert scan_destructive([f]) == []


def test_repo_migrations_with_type_columns_scan_clean_of_type_changes():
    """The three real migrations that define columns named `type` must not
    produce an ALTER-COLUMN-TYPE finding — none of them changes a type."""
    migrations = Path(__file__).resolve().parents[1] / "db" / "migrations"
    paths = [
        migrations / "0001_baseline_schema.sql",
        migrations / "0009_cosmetics.sql",
        migrations / "0026_ops.sql",
    ]
    assert all(p.is_file() for p in paths)
    kinds = {x.kind for x in scan_destructive(paths)}
    assert "ALTER COLUMN ... TYPE" not in kinds


def test_scan_destructive_flags_table_rename(tmp_path):
    """Real shape from 0020_academics_split.sql — old prod code breaks on it
    in the migrate→merge window exactly like a DROP TABLE."""
    f = tmp_path / "0060_r.sql"
    f.write_text("ALTER TABLE courses RENAME TO course_offerings;\n")
    assert [x.kind for x in scan_destructive([f])] == ["ALTER TABLE ... RENAME"]


def test_scan_destructive_flags_column_rename(tmp_path):
    f = tmp_path / "0061_r.sql"
    f.write_text("ALTER TABLE enrollments RENAME COLUMN course_id TO offering_id;\n")
    assert [x.kind for x in scan_destructive([f])] == ["ALTER TABLE ... RENAME"]


def test_scan_destructive_flags_drop_view(tmp_path):
    f = tmp_path / "0062_v.sql"
    f.write_text("DROP VIEW IF EXISTS leaderboard;\n")
    assert [x.kind for x in scan_destructive([f])] == ["DROP VIEW"]


def test_scan_destructive_ignores_column_named_rename(tmp_path):
    """RENAME must be the operation after the table name, not any identifier."""
    f = tmp_path / "0063_ok.sql"
    f.write_text("ALTER TABLE t ADD COLUMN rename text;\n")
    assert scan_destructive([f]) == []


def test_scan_destructive_ignores_line_comments(tmp_path):
    """The repo's migrations explain themselves at length; a mention is not a DROP."""
    f = tmp_path / "0053_c.sql"
    f.write_text("-- this replaces the old DROP TABLE approach\nCREATE TABLE ok (id int);\n")
    assert scan_destructive([f]) == []


def test_scan_destructive_ignores_block_comments(tmp_path):
    f = tmp_path / "0054_c.sql"
    f.write_text("/*\n  We used to TRUNCATE here.\n*/\nCREATE TABLE ok (id int);\n")
    assert scan_destructive([f]) == []


def test_scan_destructive_sees_ddl_after_dashes_inside_literal(tmp_path):
    """`--` inside a string literal is data, not a comment — the DROP after the
    literal must not vanish with the rest of the line."""
    f = tmp_path / "0064_lit.sql"
    f.write_text("INSERT INTO t (note) VALUES ('a--b'); DROP TABLE users;\n")
    assert [x.kind for x in scan_destructive([f])] == ["DROP TABLE"]


def test_scan_destructive_sees_ddl_after_escaped_quote_in_literal(tmp_path):
    """'' is an escaped quote — the literal is still open across it."""
    f = tmp_path / "0065_esc.sql"
    f.write_text("INSERT INTO t (note) VALUES ('it''s -- data'); DROP TABLE users;\n")
    assert [x.kind for x in scan_destructive([f])] == ["DROP TABLE"]


def test_scan_destructive_block_comment_markers_inside_literals(tmp_path):
    """/* and */ inside literals are data; treating them as comment delimiters
    would blank the TRUNCATE sitting between the two statements."""
    f = tmp_path / "0066_blk.sql"
    f.write_text(
        "INSERT INTO t (note) VALUES ('open /* marker');\n"
        "TRUNCATE cache;\n"
        "INSERT INTO t (note) VALUES ('close */ marker');\n"
    )
    findings = scan_destructive([f])
    assert [x.kind for x in findings] == ["TRUNCATE"]
    assert "0066_blk.sql:2" in findings[0].detail


def test_scan_destructive_still_ignores_comment_after_literal(tmp_path):
    """A closed literal hands control back to the SQL lexer — a real comment
    after it is still a comment."""
    f = tmp_path / "0067_ok.sql"
    f.write_text("INSERT INTO t (note) VALUES ('a'); -- replaces the DROP TABLE step\n")
    assert scan_destructive([f]) == []


def test_scan_destructive_clean_migration_passes(tmp_path):
    f = tmp_path / "0055_ok.sql"
    f.write_text("CREATE TABLE IF NOT EXISTS t (id int);\nCREATE INDEX ON t (id);\n")
    assert scan_destructive([f]) == []


def test_scan_destructive_flags_wrapped_type_change(tmp_path):
    """House style wraps ALTER COLUMN ... TYPE across lines; must not evade the scan."""
    f = tmp_path / "0056_w.sql"
    f.write_text(
        "ALTER TABLE assignments\n"
        "  ALTER COLUMN points_possible\n"
        "  TYPE numeric\n"
        "  USING points_possible::numeric;\n"
    )
    assert [x.kind for x in scan_destructive([f])] == ["ALTER COLUMN ... TYPE"]


def test_scan_destructive_flags_wrapped_drop_column(tmp_path):
    """The keywords themselves straddle the break — this fails under a line-oriented scan."""
    f = tmp_path / "0057_wrapped.sql"
    f.write_text("ALTER TABLE t\n  DROP\n  COLUMN old;\n")
    assert [x.kind for x in scan_destructive([f])] == ["DROP COLUMN"]


def test_scan_destructive_ignores_wrapped_drop_not_null(tmp_path):
    """Real benign shape from 0012_gradebook.sql: DROP NOT NULL is not DROP COLUMN."""
    f = tmp_path / "0058_ok.sql"
    f.write_text("ALTER TABLE assignments\n  ALTER COLUMN due_date DROP NOT NULL;\n")
    assert scan_destructive([f]) == []


def test_scan_destructive_wrapped_statement_reports_start_line(tmp_path):
    f = tmp_path / "0059_w.sql"
    f.write_text(
        "CREATE TABLE ok (id int);\n"
        "\n"
        "ALTER TABLE t\n"
        "  DROP COLUMN old;\n"
    )
    findings = scan_destructive([f])
    assert [x.kind for x in findings] == ["DROP COLUMN"]
    assert findings[0].detail.startswith("0059_w.sql:3:")


def _evaluate(**over):
    kwargs = dict(
        db_url=POOLER,
        supabase_url=API,
        ledger_exists=True,
        migration_files=["0001_a.sql", "0002_b.sql"],
        recorded={"0001_a.sql"},
        staging_recorded={"0001_a.sql", "0002_b.sql"},
        destructive=[],
        commits_ahead=3,
        migrations_drift="",
        production_is_ancestor=True,
        allow_destructive=False,
        skip_staging_check=False,
    )
    kwargs.update(over)
    return evaluate(**kwargs)


def test_evaluate_clean_case_has_no_findings():
    assert _evaluate() == []


def test_evaluate_blocks_on_migrations_drift():
    """The preflight file listing and db.migrate both read the LOCAL working
    tree, but the thing being promoted is origin/main. A checkout that differs
    invalidates the whole audit in both directions: a stale main hides an
    origin/main migration from preflight entirely (neither pending nor an
    orphan — it never applies, and prod code 500s on the missing schema); a
    feature-branch checkout applies an unmerged migration to production. The
    finding must name the offending files and the remediation.
    """
    findings = _evaluate(
        migrations_drift="M\tbackend/db/migrations/0002_b.sql\n?? backend/db/migrations/0099_stray.sql"
    )
    assert [f.kind for f in findings] == ["migrations-drift"]
    detail = findings[0].detail
    assert "0002_b.sql" in detail and "0099_stray.sql" in detail  # the offending state
    assert "origin/main" in detail
    # the remediation: checkout main, pull, remove stray files
    assert "git checkout main" in detail
    assert "pull" in detail
    assert "stray" in detail


def test_evaluate_blocks_when_production_not_ancestor_of_main():
    """A production hotfix/revert never back-merged to main makes the merge
    fail deterministically AFTER migrations applied, with the retry loop then
    misdirecting the operator ("may still be landing"). Preflight must catch
    it before any DDL, and say how to reconcile.
    """
    findings = _evaluate(production_is_ancestor=False)
    assert [f.kind for f in findings] == ["production-diverged"]
    detail = findings[0].detail.lower()
    assert "back-merge" in detail
    assert "not on" in detail  # names the offending state: commits not on main


def test_evaluate_blocks_on_project_ref_mismatch():
    findings = _evaluate(supabase_url="https://zzzzzzzzzzzzzzzz.supabase.co")
    assert [f.kind for f in findings] == ["target-mismatch"]


def test_evaluate_blocks_when_db_ref_unparseable():
    """An unrecognised DB URI must fail CLOSED, not silently skip the guard.

    The failure this reproduces: .env.production carries a SUPABASE_DB_URL the
    parser can't read (or one copy-pasted from staging alongside a blank
    SUPABASE_URL) — the mismatch check must not vouch for a target it can't see.
    """
    findings = _evaluate(db_url="postgresql://postgres:pw@127.0.0.1:54322/postgres")
    assert [f.kind for f in findings] == ["target-unverified"]
    assert "SUPABASE_DB_URL" in findings[0].detail


def test_evaluate_blocks_when_api_ref_unparseable():
    findings = _evaluate(supabase_url="")
    assert [f.kind for f in findings] == ["target-unverified"]
    assert "SUPABASE_URL" in findings[0].detail


def test_evaluate_blocks_once_when_both_refs_unparseable():
    findings = _evaluate(db_url="", supabase_url="")
    assert [f.kind for f in findings] == ["target-unverified"]
    assert "SUPABASE_DB_URL" in findings[0].detail
    assert "SUPABASE_URL" in findings[0].detail


def test_evaluate_blocks_when_ledger_missing():
    assert "no-ledger" in [f.kind for f in _evaluate(ledger_exists=False)]


def test_evaluate_blocks_on_orphans():
    findings = _evaluate(recorded={"0001_a.sql", "0099_ghost.sql"})
    assert "orphan" in [f.kind for f in findings]


def test_evaluate_blocks_when_staging_has_not_run_it():
    findings = _evaluate(staging_recorded={"0001_a.sql"})
    assert "staging-gap" in [f.kind for f in findings]


def test_evaluate_staging_check_can_be_skipped():
    findings = _evaluate(staging_recorded={"0001_a.sql"}, skip_staging_check=True)
    assert "staging-gap" not in [f.kind for f in findings]


def test_evaluate_unknown_staging_ledger_with_pending_blocks_once():
    """Missing STAGING_SUPABASE_DB_URL must not be silently read as 'nothing ran'.

    None (unreadable) and set() (read, empty) are different claims. Conflating
    them turned the default no-env-var experience into a false per-migration
    accusation. This must be exactly one finding, not one per pending migration.
    """
    findings = _evaluate(staging_recorded=None)  # default fixture leaves 0002_b.sql pending
    kinds = [f.kind for f in findings]
    assert kinds == ["staging-unknown"]
    assert "STAGING_SUPABASE_DB_URL" in findings[0].detail
    assert "aws-1-us-west-2" in findings[0].detail


def test_evaluate_unknown_staging_ledger_with_nothing_pending_is_silent():
    """No pending migrations means the unreadable ledger never mattered."""
    findings = _evaluate(staging_recorded=None, recorded={"0001_a.sql", "0002_b.sql"})
    assert "staging-unknown" not in [f.kind for f in findings]


def test_evaluate_unknown_staging_ledger_can_be_skipped():
    findings = _evaluate(staging_recorded=None, skip_staging_check=True)
    assert "staging-unknown" not in [f.kind for f in findings]


def test_evaluate_blocks_on_destructive_ddl():
    findings = _evaluate(destructive=[Finding("DROP TABLE", "0002_b.sql:4: DROP TABLE x;")])
    assert "destructive" in [f.kind for f in findings]


def test_evaluate_destructive_can_be_allowed():
    findings = _evaluate(
        destructive=[Finding("DROP TABLE", "0002_b.sql:4: DROP TABLE x;")],
        allow_destructive=True,
    )
    assert "destructive" not in [f.kind for f in findings]


def test_evaluate_reports_nothing_to_promote():
    findings = _evaluate(commits_ahead=0, recorded={"0001_a.sql", "0002_b.sql"})
    assert [f.kind for f in findings] == ["nothing-to-promote"]


def test_evaluate_allows_a_migration_only_promotion():
    """Code is level but the schema is behind — that is still work to do."""
    findings = _evaluate(commits_ahead=0)  # default fixture leaves 0002_b.sql pending
    assert findings == []
