"""Characterization tests for scripts/migration_drift_report.py (#317).

The script's CLI contract — sections, messages, exit codes (2 no env var,
1 drift, 0 clean) — can gate CI, so these pin its observable behavior while
the ledger-diff primitives underneath it move to their shared home in
promotion.preflight (#516). The script's own extra checks (number collision,
ALREADY EXISTS, data blockers) stay its own; only the shared primitives are
unified, and the identity test at the top is what keeps the two from ever
re-implementing the diff apart again.
"""
from types import SimpleNamespace

import scripts.migration_drift_report as drift
from promotion import preflight


def test_ledger_primitives_are_the_promotion_preflight_implementation():
    """THE finding: the pending/orphans computation, the ledger reads and the
    no-ledger guidance used to be re-implemented inline here, which is exactly
    how this script and the workflow preflight drifted apart before (#317's
    own docstring warns about it). The script must consume the promotion
    preflight's objects, not copies of them.
    """
    assert drift.ledger_diff is preflight.ledger_diff
    assert drift.ledger_exists is preflight.ledger_exists
    assert drift.recorded_filenames is preflight.recorded_filenames
    assert drift.NO_LEDGER_REMEDIATION is preflight.NO_LEDGER_REMEDIATION


class _FakeCursor:
    """Serves the two shared-primitive reads: ledger_exists (execute +
    fetchone) and recorded_filenames (execute + fetchall)."""

    def __init__(self, conn):
        self._conn = conn

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, sql, params=None):
        pass

    def fetchone(self):
        return (self._conn.has_ledger,)

    def fetchall(self):
        return [(name,) for name in sorted(self._conn.recorded)]


class _NothingExists:
    """Result of the script's own existence/blocker probes: nothing exists."""

    def fetchone(self):
        return (0,)

    def fetchall(self):
        return []


class FakeConn:
    """Just enough of psycopg's Connection for the script's reads: the shared
    primitives go through cursor(); the script's own ALREADY-EXISTS and
    DATA-BLOCKERS probes go through conn.execute()."""

    def __init__(self, recorded=frozenset(), has_ledger=True):
        self.recorded = set(recorded)
        self.has_ledger = has_ledger

    def cursor(self):
        return _FakeCursor(self)

    def execute(self, sql, params=None):
        return _NothingExists()

    def rollback(self):
        pass


def run_script(monkeypatch, capsys, tmp_path, files, recorded, has_ledger=True):
    """Run main() against a fabricated migrations dir and a fake ledger."""
    for name in files:
        (tmp_path / name).write_text("CREATE TABLE IF NOT EXISTS t (id int);\n")
    monkeypatch.setattr(drift, "MIGRATIONS", tmp_path)
    monkeypatch.setattr(
        drift, "psycopg", SimpleNamespace(connect=lambda url: FakeConn(recorded, has_ledger))
    )
    monkeypatch.setenv("SUPABASE_DB_URL", "postgresql://postgres:pw@example:5432/postgres")
    rc = drift.main()
    return rc, capsys.readouterr().out


def test_clean_ledger_exits_zero(monkeypatch, capsys, tmp_path):
    rc, out = run_script(
        monkeypatch, capsys, tmp_path,
        files=["0001_a.sql", "0002_b.sql"],
        recorded={"0001_a.sql", "0002_b.sql"},
    )
    assert rc == 0
    assert "on disk 2 | recorded 2 | pending 0" in out
    assert "DRIFT" not in out


def test_pending_alone_is_not_drift(monkeypatch, capsys, tmp_path):
    """The normal state of an environment that is merely behind: exit 0, so a
    CI gate on this script does not block ordinary catch-up applies."""
    rc, out = run_script(
        monkeypatch, capsys, tmp_path,
        files=["0001_a.sql", "0002_b.sql"],
        recorded={"0001_a.sql"},
    )
    assert rc == 0
    assert "  0002_b.sql" in out  # listed under PENDING
    assert "DRIFT" not in out


def test_orphan_is_drift_and_exits_one(monkeypatch, capsys, tmp_path):
    rc, out = run_script(
        monkeypatch, capsys, tmp_path,
        files=["0001_a.sql"],
        recorded={"0001_a.sql", "0009_ghost.sql"},
    )
    assert rc == 1
    assert "  0009_ghost.sql" in out
    assert "DRIFT — do not apply on top of this:" in out
    assert "1 orphan(s) recorded but absent from the repo" in out


def test_orphan_number_collision_note_is_preserved(monkeypatch, capsys, tmp_path):
    """The script's own extra checks stay the script's — unification of the
    diff primitives must not lose the number-collision annotation."""
    rc, out = run_script(
        monkeypatch, capsys, tmp_path,
        files=["0001_a.sql", "0002_b.sql"],
        recorded={"0001_a.sql", "0002_b.sql", "0002_zzz.sql"},
    )
    assert rc == 1
    assert "0002_zzz.sql  <-- NUMBER COLLIDES WITH 0002_b.sql" in out


def test_no_ledger_exits_one_with_the_exact_guidance(monkeypatch, capsys, tmp_path):
    """Byte-exact: this block is the script's most-quoted output, and its
    remediation text is now the shared NO_LEDGER_REMEDIATION constant — the
    move must not reformat it."""
    rc, out = run_script(
        monkeypatch, capsys, tmp_path, files=["0001_a.sql"], recorded=set(), has_ledger=False
    )
    assert rc == 1
    assert out == (
        "NO LEDGER — this database has never been migrated by db/migrate.py.\n"
        "Reconcile with `python -m db.migrate --baseline` against a schema you\n"
        "have verified is current, rather than applying.\n"
    )


def test_missing_db_url_exits_two(monkeypatch, capsys):
    monkeypatch.delenv("SUPABASE_DB_URL", raising=False)
    assert drift.main() == 2
    assert "SUPABASE_DB_URL is not set" in capsys.readouterr().err
