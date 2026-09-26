"""PKG-00 migration invariants. Live schema is proven by migration replay in
the E2E lane; this guards the properties later packages depend on."""

import pathlib
import re

MIG_DIR = pathlib.Path(__file__).resolve().parents[1] / "db" / "migrations"


def _migration() -> str:
    hits = sorted(MIG_DIR.glob("*_learning_loop_beta.sql"))
    assert len(hits) == 1, f"expected exactly one learning_loop_beta migration, got {hits}"
    return hits[0].read_text()


def test_column_defaults_to_opted_out():
    sql = _migration()
    assert re.search(r"learning_loop_beta\s+boolean\s+NOT NULL\s+DEFAULT\s+false", sql), (
        "learning_loop_beta must be boolean NOT NULL DEFAULT false"
    )


def test_migration_is_idempotent():
    assert "ADD COLUMN IF NOT EXISTS" in _migration()


def test_migration_prefix_is_a_utc_timestamp():
    name = sorted(MIG_DIR.glob("*_learning_loop_beta.sql"))[0].name
    assert re.fullmatch(r"\d{14}_learning_loop_beta\.sql", name), name
