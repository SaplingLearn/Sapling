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


def test_scan_destructive_ignores_line_comments(tmp_path):
    """The repo's migrations explain themselves at length; a mention is not a DROP."""
    f = tmp_path / "0053_c.sql"
    f.write_text("-- this replaces the old DROP TABLE approach\nCREATE TABLE ok (id int);\n")
    assert scan_destructive([f]) == []


def test_scan_destructive_ignores_block_comments(tmp_path):
    f = tmp_path / "0054_c.sql"
    f.write_text("/*\n  We used to TRUNCATE here.\n*/\nCREATE TABLE ok (id int);\n")
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
        allow_destructive=False,
        skip_staging_check=False,
    )
    kwargs.update(over)
    return evaluate(**kwargs)


def test_evaluate_clean_case_has_no_findings():
    assert _evaluate() == []


def test_evaluate_blocks_on_project_ref_mismatch():
    findings = _evaluate(supabase_url="https://zzzzzzzzzzzzzzzz.supabase.co")
    assert [f.kind for f in findings] == ["target-mismatch"]


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
