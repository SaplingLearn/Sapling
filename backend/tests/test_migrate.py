from types import SimpleNamespace
from unittest.mock import MagicMock

from db.migrate import discover_migrations, pending_migrations, print_notice, run


def test_discover_migrations_sorts_by_filename(tmp_path):
    for name in ["0002_b.sql", "0001_a.sql", "0010_c.sql"]:
        (tmp_path / name).write_text("SELECT 1;")
    result = [p.name for p in discover_migrations(tmp_path)]
    assert result == ["0001_a.sql", "0002_b.sql", "0010_c.sql"]


def test_pending_migrations_excludes_applied(tmp_path):
    files = [tmp_path / "0001_a.sql", tmp_path / "0002_b.sql"]
    for f in files:
        f.write_text("SELECT 1;")
    pending = pending_migrations(files, {"0001_a.sql"})
    assert [p.name for p in pending] == ["0002_b.sql"]


# ── Server notices reach the operator ────────────────────────────────────────
#
# psycopg drops server-side NOTICE/WARNING unless a handler is registered, so a
# migration whose only output is `RAISE WARNING` (0045: live achievements left
# with no triggers; 0046: what it repaired and what it could not) produced
# nothing an operator could act on. These pin the channel.


def _diag(severity, message):
    return SimpleNamespace(
        severity_nonlocalized=severity, severity=severity, message_primary=message,
    )


def test_run_registers_a_notice_handler(tmp_path):
    """Without this the RAISE output of 0045/0046 is discarded silently."""
    conn = MagicMock()
    run(conn, migrations_dir=tmp_path)
    conn.add_notice_handler.assert_called_once_with(print_notice)


def test_warnings_are_printed_to_stderr(capsys):
    print_notice(_diag("WARNING", "0046: these live achievement(s) have NO triggers"))
    captured = capsys.readouterr()
    assert "0046: these live achievement(s) have NO triggers" in captured.err
    assert "WARNING" in captured.err


def test_notices_are_printed_to_stdout(capsys):
    print_notice(_diag("NOTICE", "0046: restored 3 achievement trigger(s)"))
    captured = capsys.readouterr()
    assert "0046: restored 3 achievement trigger(s)" in captured.out


def test_an_empty_notice_prints_nothing(capsys):
    print_notice(_diag("NOTICE", ""))
    captured = capsys.readouterr()
    assert captured.out == "" and captured.err == ""
