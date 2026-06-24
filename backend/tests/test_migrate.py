from db.migrate import discover_migrations, pending_migrations


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
