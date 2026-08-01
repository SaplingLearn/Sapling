"""Minimal migration runner for Supabase Postgres (#197).

App runtime uses db/connection.py::table() (PostgREST), which cannot execute DDL.
Migrations are raw DDL, so this admin tool connects with psycopg over
SUPABASE_DB_URL. This is the one sanctioned exception to the table()-only
convention.

WHICH CONNECTION STRING: the SESSION-mode pooler, port 5432.

This file used to say "the direct connection string, NOT the pooler". That
warning was about TRANSACTION mode (port 6543), which drops the session-level
behaviour psycopg and DDL depend on — and it is still correct about 6543. But
it predates Supabase moving the direct host to an IPv6-only endpoint:
db.<ref>.supabase.co now publishes only an AAAA record, so it is unreachable
from GitHub-hosted runners and from any network without a global IPv6 address.
Session mode behaves like a direct connection and its host publishes an A
record, so it is the reachable substitute — not a compromise.

Two details that are easy to miss: the pooler changes the username to
`postgres.<ref>`, and projects sit on NUMBERED clusters (`aws-0-`, `aws-1-`,
...) whose number is not derivable from the region. Take the host from the
dashboard's Connect panel, or let scripts/pooler_url.py assemble the URI from
an env file.

Usage:
    SUPABASE_DB_URL=postgresql://... python -m db.migrate            # apply pending
    SUPABASE_DB_URL=postgresql://... python -m db.migrate --baseline # record as applied without running
"""
from __future__ import annotations

import os
import re
import sys
from pathlib import Path

import psycopg

MIGRATIONS_DIR = Path(__file__).parent / "migrations"


# Two accepted filename shapes, both sortable and both fixed-width:
#   NNNN_          legacy sequential prefix (frozen — see below)
#   YYYYMMDDHHMMSS_  UTC timestamp, the convention for every NEW migration
#
# New migrations use a timestamp because a sequential counter is claimed when a
# branch is written but only validated when it merges, so concurrent branches
# routinely claim the same number.
#
# The legacy files are never renamed. `schema_migrations.filename` is the
# ledger's primary key and `pending_migrations` treats an unknown basename as
# unapplied, so renaming an applied migration re-runs it — and 0021_gradebook
# DROPs and re-CREATEs a table.
#
# Ordering is unaffected, but for a narrower reason than "timestamps are
# longer": sorting is character-by-character, so length decides nothing. Every
# legacy file starts with "0" and every timestamp this millennium starts with
# "2", and "0" < "2". A sequential migration numbered 3000+ would break that —
# one more reason the legacy set is frozen.
_MIGRATION_NAME_RE = re.compile(r"^(\d{4}|\d{14})_.+\.sql$")


def is_valid_migration_name(name: str) -> bool:
    """True when a filename carries a sortable, fixed-width numeric prefix.

    Anything else sorts unpredictably against its siblings, which silently
    changes apply order.
    """
    return bool(_MIGRATION_NAME_RE.match(name))


def discover_migrations(migrations_dir: Path) -> list[Path]:
    """All *.sql migration files, sorted by filename.

    Filename order IS apply order (see `is_valid_migration_name` for the two
    accepted prefix shapes and why both sort correctly together).
    """
    return sorted(Path(migrations_dir).glob("*.sql"))


def pending_migrations(all_files: list[Path], applied: set[str]) -> list[Path]:
    """Migration files whose basename has not yet been recorded as applied."""
    return [p for p in all_files if p.name not in applied]


def ensure_tracking_table(conn: psycopg.Connection) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS schema_migrations (
                filename   TEXT PRIMARY KEY,
                applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
            )
            """
        )
    conn.commit()


def applied_filenames(conn: psycopg.Connection) -> set[str]:
    with conn.cursor() as cur:
        cur.execute("SELECT filename FROM schema_migrations")
        return {row[0] for row in cur.fetchall()}


def apply_migration(conn: psycopg.Connection, path: Path) -> None:
    """Run one migration's SQL and record it, atomically."""
    with conn.cursor() as cur:
        cur.execute(path.read_text())
        cur.execute("INSERT INTO schema_migrations (filename) VALUES (%s)", (path.name,))
    conn.commit()


def run(
    conn: psycopg.Connection,
    migrations_dir: Path = MIGRATIONS_DIR,
    baseline: bool = False,
) -> list[str]:
    """Apply (or baseline-record) all pending migrations. Returns filenames handled."""
    ensure_tracking_table(conn)
    applied = applied_filenames(conn)
    pending = pending_migrations(discover_migrations(migrations_dir), applied)
    handled: list[str] = []
    for path in pending:
        if baseline:
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO schema_migrations (filename) VALUES (%s) ON CONFLICT DO NOTHING",
                    (path.name,),
                )
            conn.commit()
        else:
            apply_migration(conn, path)
        handled.append(path.name)
    return handled


def main() -> int:
    db_url = os.environ.get("SUPABASE_DB_URL", "").strip()
    if not db_url:
        print(
            "ERROR: SUPABASE_DB_URL is not set (Supabase → Connect → "
            "Session pooler, port 5432, user postgres.<ref>). The direct "
            "db.<ref>.supabase.co host is IPv6-only and unreachable from most "
            "networks; port 6543 is transaction mode and breaks DDL.",
            file=sys.stderr,
        )
        return 1
    baseline = "--baseline" in sys.argv[1:]
    with psycopg.connect(db_url) as conn:
        handled = run(conn, baseline=baseline)
    verb = "Baselined" if baseline else "Applied"
    print(f"{verb} {len(handled)} migration(s):" if handled else "No pending migrations.")
    for name in handled:
        print(f"  - {name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
