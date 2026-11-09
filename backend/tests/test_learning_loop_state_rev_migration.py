"""Owner decision A38 06(q): sessions.loop_state_rev, the compare-and-set
revision learning/loop_state_store.py filters every loop_state save on.

Read from the SQL file only: this guards the DDL the store depends on and does
NOT prove the live schema. The E2E lane's fresh-DB replay (`make e2e-up` with
E2E_FRESH_DB=1) is what applies it."""

import pathlib
import re

MIG_DIR = pathlib.Path(__file__).resolve().parents[1] / "db" / "migrations"


def _migration() -> tuple[str, str]:
    hits = sorted(MIG_DIR.glob("*_learning_loop_state_rev.sql"))
    assert len(hits) == 1, f"expected exactly one loop_state_rev migration, got {hits}"
    return hits[0].name, hits[0].read_text()


def _ddl(sql: str) -> str:
    return "\n".join(line for line in sql.splitlines() if not line.lstrip().startswith("--"))


def test_loop_state_rev_is_a_non_null_bigint_defaulting_to_zero():
    _, sql = _migration()
    ddl = _ddl(sql)
    assert (
        "ALTER TABLE sessions ADD COLUMN IF NOT EXISTS loop_state_rev bigint NOT NULL DEFAULT 0"
        in ddl
    )
    assert ddl.count(";") == 1, "one statement: the column"


def test_migration_prefix_is_a_utc_timestamp_after_the_loop_state_column():
    name, _ = _migration()
    assert re.fullmatch(r"\d{14}_learning_loop_state_rev\.sql", name), name
    (earlier,) = sorted(MIG_DIR.glob("*_learning_session_loop_state.sql"))
    assert name > earlier.name, f"must sort after {earlier.name}"
