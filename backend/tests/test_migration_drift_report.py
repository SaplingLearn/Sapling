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


class _Rows:
    def __init__(self, one=(0,), many=()):
        self._one, self._many = one, list(many)

    def fetchone(self):
        return self._one

    def fetchall(self):
        return self._many


class ProbingConn(FakeConn):
    """A ledger that exists, with the script's own probes answered per query:
    ``existing`` names tables/columns/indexes that already exist, ``dupes`` the
    duplicate rows the UNIQUE-index blocker query finds, and ``broken`` the
    tables whose blocker query raises (table not there yet)."""

    def __init__(self, recorded, existing=(), dupes=(), broken=()):
        super().__init__(recorded)
        self.existing, self.dupes, self.broken = set(existing), list(dupes), set(broken)
        self.rollbacks = 0

    def execute(self, sql, params=None):
        if sql.startswith("SELECT count(*)"):
            return _Rows(one=(1 if params[-1] in self.existing else 0,))
        if any(f"FROM {t}" in sql for t in self.broken):
            raise RuntimeError("relation does not exist")
        return _Rows(many=self.dupes)

    def rollback(self):
        self.rollbacks += 1


def run_probing(monkeypatch, capsys, tmp_path, sqls, recorded, **conn_kwargs):
    for name, sql in sqls.items():
        (tmp_path / name).write_text(sql)
    conn = ProbingConn(recorded, **conn_kwargs)
    monkeypatch.setattr(drift, "MIGRATIONS", tmp_path)
    monkeypatch.setattr(drift, "psycopg", SimpleNamespace(connect=lambda url: conn))
    monkeypatch.setenv("SUPABASE_DB_URL", "postgresql://postgres:pw@example:5432/postgres")
    rc = drift.main()
    return rc, capsys.readouterr().out, conn


def test_already_exists_with_if_not_exists_is_listed_but_safe(monkeypatch, capsys, tmp_path):
    rc, out, _ = run_probing(
        monkeypatch, capsys, tmp_path,
        sqls={
            "0001_a.sql": "CREATE TABLE IF NOT EXISTS t (id int);\n",
            "0002_b.sql": (
                "CREATE TABLE IF NOT EXISTS public.widgets (id int);\n"
                "ALTER TABLE widgets ADD COLUMN IF NOT EXISTS colour text;\n"
                "CREATE INDEX IF NOT EXISTS widgets_colour_idx ON widgets (colour);\n"
            ),
        },
        recorded={"0001_a.sql"},
        existing={"widgets", "colour", "widgets_colour_idx"},
    )
    assert rc == 0
    assert (
        "ALREADY EXISTS (pending migration, object already present)\n"
        "  0002_b.sql  (safe: uses IF NOT EXISTS)\n"
        "      column widgets.colour\n"
        "      index widgets_colour_idx\n"
        "      table widgets\n"
    ) in out
    assert "DRIFT" not in out


def test_already_exists_without_if_not_exists_is_drift(monkeypatch, capsys, tmp_path):
    rc, out, _ = run_probing(
        monkeypatch, capsys, tmp_path,
        sqls={"0001_a.sql": "CREATE TABLE widgets (id int);\n"},
        recorded=set(),
        existing={"widgets"},
    )
    assert rc == 1
    assert "  0001_a.sql  (!! NO IF NOT EXISTS — would fail)\n      table widgets\n" in out
    assert "an object already exists for a migration without IF NOT EXISTS" in out


def test_nothing_already_present_says_the_ledger_is_behind(monkeypatch, capsys, tmp_path):
    rc, out, _ = run_probing(
        monkeypatch, capsys, tmp_path,
        sqls={"0001_a.sql": "CREATE TABLE widgets (id int);\n"},
        recorded=set(),
    )
    assert rc == 0
    assert "  none — the ledger is behind, not lying" in out


def test_unique_index_over_duplicate_rows_is_a_data_blocker(monkeypatch, capsys, tmp_path):
    rc, out, _ = run_probing(
        monkeypatch, capsys, tmp_path,
        sqls={
            "0001_a.sql": (
                "CREATE UNIQUE INDEX IF NOT EXISTS w_uq ON public.widgets (a, b) "
                "WHERE deleted_at IS NULL;\n"
            ),
        },
        recorded=set(),
        dupes=[("x", "y", 2)],
    )
    assert rc == 1
    assert (
        "DATA BLOCKERS (pending UNIQUE index vs rows already present)\n"
        "  0001_a.sql: w_uq WOULD FAIL — duplicate rows exist:\n"
        "      ('x', 'y', 2)\n"
    ) in out
    assert "live rows already violate a pending UNIQUE index" in out


def test_unique_index_on_a_missing_table_is_reported_not_fatal(monkeypatch, capsys, tmp_path):
    rc, out, conn = run_probing(
        monkeypatch, capsys, tmp_path,
        sqls={"0001_a.sql": "CREATE UNIQUE INDEX w_uq ON widgets (a);\n"},
        recorded=set(),
        broken={"widgets"},
    )
    assert rc == 0
    assert "  0001_a.sql: w_uq — could not check (RuntimeError)\n" in out
    assert conn.rollbacks == 1
    assert out.endswith("DATA BLOCKERS (pending UNIQUE index vs rows already present)\n"
                        "  0001_a.sql: w_uq — could not check (RuntimeError)\n"
                        "  none\n")


def test_full_report_is_byte_stable(monkeypatch, capsys, tmp_path):
    """Every section at once, byte-exact: pins section order, the per-section
    'none' lines and the DRIFT summary order while main() is split into
    per-section helpers (#118 complexity ratchet)."""
    rc, out, _ = run_probing(
        monkeypatch, capsys, tmp_path,
        sqls={
            "0001_a.sql": "CREATE TABLE IF NOT EXISTS t (id int);\n",
            "0002_b.sql": "CREATE TABLE widgets (id int);\nCREATE UNIQUE INDEX w_uq ON widgets (a);\n",
            "0003_c.sql": "CREATE UNIQUE INDEX IF NOT EXISTS g_uq ON gadgets (a);\n",
        },
        recorded={"0001_a.sql", "0009_x.sql"},
        existing={"widgets"},
        dupes=[(1, 2)],
        broken={"gadgets"},
    )
    assert rc == 1
    assert out == (
        "on disk 3 | recorded 2 | pending 2\n\n"
        "PENDING\n  0002_b.sql\n  0003_c.sql\n\n"
        "ORPHANS (recorded here, absent from the repo)\n  0009_x.sql\n\n"
        "ALREADY EXISTS (pending migration, object already present)\n"
        "  0002_b.sql  (!! NO IF NOT EXISTS — would fail)\n"
        "      table widgets\n\n"
        "DATA BLOCKERS (pending UNIQUE index vs rows already present)\n"
        "  0002_b.sql: w_uq WOULD FAIL — duplicate rows exist:\n"
        "      (1, 2)\n"
        "  0003_c.sql: g_uq — could not check (RuntimeError)\n\n"
        "DRIFT — do not apply on top of this:\n"
        "  1 orphan(s) recorded but absent from the repo\n"
        "  an object already exists for a migration without IF NOT EXISTS\n"
        "  live rows already violate a pending UNIQUE index\n"
    )
