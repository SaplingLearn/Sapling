"""Minimal migration runner for Supabase Postgres (#197).

App runtime uses db/connection.py::table() (PostgREST), which cannot execute DDL.
Migrations are raw DDL, so this admin tool connects directly with psycopg over the
Supabase *direct* connection string (SUPABASE_DB_URL, NOT the pooler). This is the
one sanctioned exception to the table()-only convention.

Usage:
    SUPABASE_DB_URL=postgresql://... python -m db.migrate            # apply pending
    SUPABASE_DB_URL=postgresql://... python -m db.migrate --baseline # record as applied without running
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import psycopg

MIGRATIONS_DIR = Path(__file__).parent / "migrations"


def discover_migrations(migrations_dir: Path) -> list[Path]:
    """All *.sql migration files, sorted by filename (numeric prefix = order)."""
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


def _split_statements(sql: str) -> list[str]:
    """Split migration SQL into individual statements.

    Splits on semicolons and filters out empty/whitespace-only statements and
    full-line comments. Sufficient for simple DDL migrations in this repo.
    """
    statements = []
    for stmt in sql.split(";"):
        # Strip whitespace
        stmt = stmt.strip()
        # Skip empty statements
        if not stmt:
            continue
        # Skip full-line comment-only statements
        lines = [line.strip() for line in stmt.splitlines() if line.strip()]
        if all(line.startswith("--") for line in lines):
            continue
        statements.append(stmt)
    return statements


def apply_migration(conn: psycopg.Connection, path: Path) -> None:
    """Run one migration's SQL and record it, atomically.

    Statements containing CONCURRENTLY are executed outside a transaction block
    (in autocommit mode) as required by Postgres. All other statements run in
    a single transaction as before.
    """
    statements = _split_statements(path.read_text())

    # Execute each statement; CONCURRENTLY statements require autocommit
    for stmt in statements:
        if "CONCURRENTLY" in stmt.upper():
            # Must run outside any transaction block
            # Commit any open transaction first before switching to autocommit
            conn.commit()
            old_autocommit = conn.autocommit
            conn.autocommit = True
            try:
                with conn.cursor() as cur:
                    cur.execute(stmt)
            finally:
                conn.autocommit = old_autocommit
        else:
            # Normal statements run in the transaction
            with conn.cursor() as cur:
                cur.execute(stmt)

    # Record the migration as applied
    with conn.cursor() as cur:
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
            "ERROR: SUPABASE_DB_URL is not set "
            "(Supabase → Settings → Database → Connection string → Direct).",
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
