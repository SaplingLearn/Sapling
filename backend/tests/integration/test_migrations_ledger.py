"""Migration ledger consistency against the real local stack (#398).

The offline apply-order pins live in tests/test_migrations.py. This is the
DB-backed half: on the running stack, every migration file on disk must be
recorded in the schema_migrations ledger — a file present but unrecorded means
the DB is behind, or a file was added without `python -m db.migrate`.
"""
from pathlib import Path

import pytest

from db.migrate import discover_migrations

pytestmark = pytest.mark.integration


def test_schema_migrations_ledger_records_every_file(db_conn):
    on_disk = {p.name for p in discover_migrations(Path("db/migrations"))}
    rows = db_conn.execute("SELECT filename FROM schema_migrations").fetchall()
    recorded = {r["filename"] for r in rows}
    missing = on_disk - recorded
    assert not missing, (
        f"migrations on disk but not applied to the local stack: {sorted(missing)} "
        "(run `python -m db.migrate`)"
    )
