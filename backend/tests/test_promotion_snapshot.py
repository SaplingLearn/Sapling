"""Snapshot diffing for the promotion runner (#516).

`diff` and `format_diff` are pure, so they need no database. `capture` is a thin
psycopg shell exercised through a fake connection.
"""
from promotion.snapshot import capture, diff, format_diff


class FakeCursor:
    def __init__(self, script):
        self._script = script
        self._rows = []

    def execute(self, sql, params=None):
        for fragment, rows in self._script:
            if fragment in " ".join(sql.split()):
                self._rows = rows
                return
        raise AssertionError(f"unexpected SQL: {sql}")

    def fetchone(self):
        return self._rows[0]

    def fetchall(self):
        return self._rows

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class FakeConn:
    def __init__(self, script):
        self._script = script
        self.info = type("info", (), {"host": "aws-0-us-west-2.pooler.supabase.com"})()

    def cursor(self):
        return FakeCursor(self._script)


def test_capture_collects_ledger_and_counts():
    conn = FakeConn(
        [
            ("to_regclass", [(True,)]),
            ("FROM schema_migrations", [("0001_a.sql",), ("0002_b.sql",)]),
            ("information_schema.tables", [("users",), ("notes",)]),
            # capture() quotes identifiers, so the fragment must too.
            ('SELECT count(*) FROM public."users"', [(8,)]),
            ('SELECT count(*) FROM public."notes"', [(0,)]),
        ]
    )
    snap = capture(conn)
    assert snap["ledger_exists"] is True
    assert snap["ledger"] == ["0001_a.sql", "0002_b.sql"]
    assert snap["tables"] == {"users": 8, "notes": 0}
    assert snap["host"] == "aws-0-us-west-2.pooler.supabase.com"


def test_capture_handles_missing_ledger():
    conn = FakeConn(
        [
            ("to_regclass", [(False,)]),
            ("information_schema.tables", [("users",)]),
            ('SELECT count(*) FROM public."users"', [(3,)]),
        ]
    )
    snap = capture(conn)
    assert snap["ledger_exists"] is False
    assert snap["ledger"] == []


BEFORE = {"tables": {"users": 8, "terms": 4}, "ledger": ["0001_a.sql"]}
AFTER = {"tables": {"users": 8, "terms": 3, "events": 0}, "ledger": ["0001_a.sql", "0002_b.sql"]}


def test_diff_reports_new_tables():
    assert diff(BEFORE, AFTER)["new_tables"] == ["events"]


def test_diff_reports_dropped_tables():
    assert diff(AFTER, BEFORE)["dropped_tables"] == ["events"]


def test_diff_reports_row_count_changes():
    assert diff(BEFORE, AFTER)["count_changes"] == {"terms": (4, 3)}


def test_diff_reports_new_migrations():
    assert diff(BEFORE, AFTER)["new_migrations"] == ["0002_b.sql"]


def test_diff_of_identical_snapshots_is_empty():
    d = diff(BEFORE, BEFORE)
    assert d["new_tables"] == [] and d["dropped_tables"] == []
    assert d["count_changes"] == {} and d["new_migrations"] == []


def test_format_diff_mentions_every_change():
    text = format_diff(diff(BEFORE, AFTER))
    assert "events" in text and "terms" in text and "0002_b.sql" in text


def test_format_diff_says_no_change_when_empty():
    assert "no schema or row-count changes" in format_diff(diff(BEFORE, BEFORE))
