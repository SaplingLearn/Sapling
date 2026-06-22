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

MIGRATIONS_DIR = Path(__file__).parent / "migrations"


def discover_migrations(migrations_dir: Path) -> list[Path]:
    """All *.sql migration files, sorted by filename (numeric prefix = order)."""
    return sorted(Path(migrations_dir).glob("*.sql"))


def pending_migrations(all_files: list[Path], applied: set[str]) -> list[Path]:
    """Migration files whose basename has not yet been recorded as applied."""
    return [p for p in all_files if p.name not in applied]
