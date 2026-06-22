"""
Tests for the migration runner + ordering manifest (#197) and the cosmetics
idempotency fix (#196). No live Postgres — these cover the pure ordering /
completeness logic and the textual idempotency invariants.
"""
import os

from db import migrate

_DB = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "db")


# ── #197: manifest + runner ────────────────────────────────────────────────

def test_manifest_covers_every_migration_file():
    # Every migration_*.sql on disk (except the ledger bootstrap) must be in the
    # manifest, and the manifest must not reference files that don't exist.
    assert set(migrate.MANIFEST) == migrate.discover_migrations()


def test_manifest_has_no_duplicates():
    assert len(migrate.MANIFEST) == len(set(migrate.MANIFEST))


def test_known_dependency_order_is_encoded():
    # The one hard ordering constraint in the codebase.
    assert migrate.MANIFEST.index("migration_drop_legacy_grade_tables.sql") < (
        migrate.MANIFEST.index("migration_gradebook.sql")
    )


def test_pending_excludes_applied_and_preserves_order():
    applied = {"migration_roles.sql", "migration_gradebook.sql"}
    result = migrate.pending(applied)
    assert "migration_roles.sql" not in result
    assert "migration_gradebook.sql" not in result
    # surviving entries keep manifest order
    assert result == [m for m in migrate.MANIFEST if m not in applied]


def test_pending_empty_when_all_applied():
    assert migrate.pending(set(migrate.MANIFEST)) == []


def test_ledger_migration_creates_table_if_not_exists():
    with open(os.path.join(_DB, "migration_schema_migrations.sql"), encoding="utf-8") as fh:
        sql = fh.read()
    assert "CREATE TABLE IF NOT EXISTS schema_migrations" in sql


# ── #196: cosmetics idempotency ────────────────────────────────────────────

def test_cosmetics_constraints_are_all_guarded():
    with open(os.path.join(_DB, "migration_cosmetics.sql"), encoding="utf-8") as fh:
        sql = fh.read()
    # Each FK must sit inside an IF NOT EXISTS pg_constraint guard so a second
    # run is a no-op rather than "constraint already exists".
    constraints = [
        "fk_user_settings_avatar_frame",
        "fk_user_settings_banner",
        "fk_user_settings_name_color",
        "fk_user_settings_title",
        "fk_user_settings_featured_role",
    ]
    assert sql.count("ADD CONSTRAINT fk_user_settings") == len(constraints)
    for name in constraints:
        assert f"conname = '{name}'" in sql, f"{name} is not guarded"
    # "ADD CONSTRAINT IF NOT EXISTS" is not valid Postgres; it may only appear in
    # the explanatory comment, never as actual DDL.
    assert "    ADD CONSTRAINT IF NOT EXISTS" not in sql
