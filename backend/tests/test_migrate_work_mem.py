"""run() must raise maintenance_work_mem before applying anything (#510 fallout).

0039_rag_vector_store builds an ivfflat index over VECTOR(768) and needs ~35 MB.
Supabase defaults maintenance_work_mem to 32 MB, so the migration dies with
"memory required is 35 MB, maintenance_work_mem is 32 MB" — and because
apply_migration wraps each file plus its ledger INSERT in one transaction with
no per-file recovery, everything queued behind it dies too. Staging hit this
with 5 migrations still pending.

The SET has to happen on the connection that runs the DDL: `ALTER DATABASE`
only reaches backends started after it, and a pooled connection is often
already established.
"""
from pathlib import Path

import pytest

from db import migrate


class _FakeCursor:
    def __init__(self, log: list[str]):
        self.log = log

    def execute(self, sql, params=None):
        self.log.append(sql if isinstance(sql, str) else str(sql))

    def fetchall(self):
        return []

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class _FakeConn:
    """Records executed SQL; no pending migrations so run() short-circuits."""

    def __init__(self):
        self.log: list[str] = []
        self.commits = 0
        self.notice_handlers: list = []

    def cursor(self):
        return _FakeCursor(self.log)

    def commit(self):
        self.commits += 1

    def add_notice_handler(self, handler):
        """run() also routes server NOTICEs to the operator's terminal.

        The real argument is a psycopg.Connection, so the double has to carry
        this too — without it run() raises AttributeError before it ever
        reaches the ledger, and these tests fail for a reason that has nothing
        to do with maintenance_work_mem.
        """
        self.notice_handlers.append(handler)


@pytest.fixture
def empty_dir(tmp_path) -> Path:
    return tmp_path


def test_run_sets_maintenance_work_mem_before_touching_the_ledger(empty_dir):
    """Order matters: an index build inside the very first migration must
    already see the raised value."""
    conn = _FakeConn()

    migrate.run(conn, migrations_dir=empty_dir)

    set_stmts = [s for s in conn.log if s.startswith("SET maintenance_work_mem")]
    assert set_stmts, f"run() never raised maintenance_work_mem; executed: {conn.log}"

    first_set = conn.log.index(set_stmts[0])
    first_ddl = next(
        (i for i, s in enumerate(conn.log) if "schema_migrations" in s), len(conn.log)
    )
    assert first_set < first_ddl, "the SET must precede any migration work"


def test_the_value_is_configurable_for_a_memory_tight_instance(empty_dir, monkeypatch):
    """A small instance must be able to dial this down without editing code."""
    monkeypatch.setattr(migrate, "MAINTENANCE_WORK_MEM", "64MB")
    conn = _FakeConn()

    migrate.run(conn, migrations_dir=empty_dir)

    assert any("'64MB'" in s for s in conn.log), conn.log


def test_the_default_clears_the_known_requirement(empty_dir):
    """0039 needs ~35 MB. The default must exceed that with headroom, or this
    fix does not actually fix the migration that motivated it."""
    value = migrate.MAINTENANCE_WORK_MEM
    assert value.upper().endswith("MB"), f"expected an MB value, got {value!r}"
    assert int(value[:-2]) >= 64, f"{value} leaves no headroom over 0039's ~35 MB"
