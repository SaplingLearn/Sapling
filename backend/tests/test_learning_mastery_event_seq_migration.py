"""The PKG-03 reopen for the live sequence-test finding (spec §4, §13 A36):
node_mastery_events.evidence_seq.

Read from the SQL file only: this guards the DDL graph_service depends on and
does NOT prove the live schema. The E2E lane's fresh-DB replay (`make e2e-up`
with E2E_FRESH_DB=1) is what applies it."""

import pathlib
import re

MIG_DIR = pathlib.Path(__file__).resolve().parents[1] / "db" / "migrations"


def _migration() -> tuple[str, str]:
    hits = sorted(MIG_DIR.glob("*_learning_mastery_event_seq.sql"))
    assert len(hits) == 1, f"expected exactly one evidence_seq migration, got {hits}"
    return hits[0].name, hits[0].read_text()


def _ddl(sql: str) -> str:
    return "\n".join(line for line in sql.splitlines() if not line.lstrip().startswith("--"))


def test_evidence_seq_is_a_nullable_non_negative_integer():
    _, sql = _migration()
    ddl = _ddl(sql)
    assert "ALTER TABLE node_mastery_events ADD COLUMN IF NOT EXISTS evidence_seq integer" in ddl
    assert "NOT NULL" not in ddl, "legacy journal writers never set it"
    assert "CHECK (evidence_seq IS NULL OR evidence_seq >= 0)" in ddl
    assert ddl.count(";") == 1, "one statement: the column"


def test_migration_prefix_is_a_utc_timestamp_after_the_other_journal_columns():
    name, _ = _migration()
    assert re.fullmatch(r"\d{14}_learning_mastery_event_seq\.sql", name), name
    for prior in ("learner_state", "grader_backend"):
        (earlier,) = sorted(MIG_DIR.glob(f"*_learning_{prior}.sql"))
        assert name > earlier.name, f"must sort after {earlier.name}"


def test_spec_section_4_records_the_column():
    spec = (
        pathlib.Path(__file__).resolve().parents[2]
        / "docs/superpowers/specs/2026-09-26-learning-loop-design.md"
    ).read_text()
    section_4 = spec.split("## 4. Schemas", 1)[1].split("## 5. Evidence model", 1)[0]
    assert "_learning_mastery_event_seq.sql" in section_4
    assert (
        "ALTER TABLE node_mastery_events ADD COLUMN IF NOT EXISTS evidence_seq integer" in section_4
    )
