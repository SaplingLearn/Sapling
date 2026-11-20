"""PR #866 Z67: the migration runner bounds how long a migration waits for a
table lock.

An ALTER that waits for its lock behind a long reader queues every later read
and write of that table behind it. Several applied learning-loop migrations
validate a CHECK on populated tables (node_mastery_events, sessions,
flashcards) under ACCESS EXCLUSIVE with no lock_timeout of their own, and an
applied migration is never edited, so the runner sets one per session: a lock
that does not come in time fails that file (rolled back, nothing recorded;
run it again) instead of queueing traffic."""

from __future__ import annotations

import pytest

from db import migrate
from tests.test_migrate_work_mem import _FakeConn, _FakeCursor

_SET = "SELECT set_config('lock_timeout', %s, false)"


class _ParamCursor(_FakeCursor):
    """Also records each statement's parameters."""

    def execute(self, sql, params=None):
        self.log.append(sql if isinstance(sql, str) else str(sql))
        if params is not None:
            self.log.append(("params", tuple(params)))


class _Conn(_FakeConn):
    def cursor(self):
        return _ParamCursor(self.log)


def _bound(log) -> list:
    """The values each lock_timeout set_config was given, in order."""
    return [log[i + 1][1][0] for i, s in enumerate(log) if s == _SET]


def test_run_bounds_the_lock_wait_before_touching_the_ledger(tmp_path):
    conn = _Conn()

    migrate.run(conn, migrations_dir=tmp_path)

    assert _bound(conn.log) == ["5s"], conn.log
    first_ddl = next(i for i, s in enumerate(conn.log) if isinstance(s, str) and "schema_migrations" in s)
    assert conn.log.index(_SET) < first_ddl, "the bound must precede any migration work"


def test_the_bound_is_configurable_and_zero_disables_it(tmp_path, monkeypatch):
    for value in ("30s", "0", "1500ms", "2min"):
        monkeypatch.setattr(migrate, "LOCK_TIMEOUT", value)
        conn = _Conn()
        migrate.run(conn, migrations_dir=tmp_path)
        assert _bound(conn.log) == [value]


@pytest.mark.parametrize("value", ["5 s", "5s'; DROP TABLE users; --", "", "soon"])
def test_a_malformed_bound_fails_before_any_statement_runs_with_it(tmp_path, monkeypatch, value):
    monkeypatch.setattr(migrate, "LOCK_TIMEOUT", value)
    conn = _Conn()
    with pytest.raises(ValueError):
        migrate.run(conn, migrations_dir=tmp_path)
    assert _SET not in conn.log
    assert not any(isinstance(s, str) and "schema_migrations" in s for s in conn.log)
