"""db/migration_units.py: a consolidated migration reads back as the units it
was made of, in the order the runner applies them."""

from __future__ import annotations

from pathlib import Path

import pytest

from db.migration_units import MIGRATION_UNITS, MIGRATIONS_DIR, UNIT_MARKER, split_units, unit_sql, units


def _consolidated() -> list[Path]:
    return [p for p in sorted(MIGRATIONS_DIR.glob("*.sql")) if UNIT_MARKER.search(p.read_text())]


def test_the_learning_system_is_one_consolidated_file_of_units():
    [path] = _consolidated()
    names = [name for name, _ in split_units(path)]
    assert names
    # filename order, each once: the order the original files applied in
    assert names == sorted(set(names))
    # every unit is a migration filename no plain file also has
    assert all(n.endswith(".sql") and not (MIGRATIONS_DIR / n).exists() for n in names)


def test_units_are_the_files_with_the_consolidated_one_expanded_in_place():
    plain = [p.name for p in sorted(MIGRATIONS_DIR.glob("*.sql")) if p not in _consolidated()]
    names = [name for name, _ in units()]
    assert [n for n in names if n in plain] == plain
    [consolidated] = _consolidated()
    assert len(names) == len(plain) + len(split_units(consolidated))


def test_a_unit_reads_back_its_own_sql_only():
    sql = unit_sql("20261118195124_learning_session_node_erase.sql")
    assert "-- @@ unit" not in sql
    assert sql.lstrip().startswith("--")
    assert (MIGRATION_UNITS / "20261118195124_learning_session_node_erase.sql").read_text() == sql


def test_the_unit_view_globs_like_a_directory():
    [hit] = MIGRATION_UNITS.glob("*_learning_session_node_erase.sql")
    assert hit.name == "20261118195124_learning_session_node_erase.sql" and hit.exists()
    assert not (MIGRATION_UNITS / "no_such.sql").exists()
    with pytest.raises(FileNotFoundError):
        unit_sql("no_such.sql")


def test_split_units_of_a_plain_file_is_the_file(tmp_path):
    f = tmp_path / "20990101000000_x.sql"
    f.write_text("SELECT 1;\n")
    assert split_units(f) == [(f.name, "SELECT 1;\n")]
