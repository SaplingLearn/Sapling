"""
Ordered, idempotent migration runner (#197).

Replaces the prose ordering scattered across migration headers ("Run once in
the Supabase SQL editor", "needs documents to exist first") with a single
explicit MANIFEST and a schema_migrations ledger. Each migration is applied at
most once, in manifest order, and recorded — so a fresh environment reproduces
the schema deterministically and re-runs are no-ops.

The canonical full snapshot (supabase_schema.sql) is the baseline; this runner
governs the incremental migration_*.sql files. The PostgREST client in
db/connection.py cannot run DDL, so applying requires a direct Postgres
connection: set DATABASE_URL (Supabase → Project Settings → Database →
Connection string) and install psycopg. Inspection (`--status`) needs neither.

Usage (from backend/):
    python -m db.migrate --status     # show applied / pending (no DB writes)
    python -m db.migrate --apply      # apply pending migrations in order
"""
from __future__ import annotations

import argparse
import glob
import os

_DB_DIR = os.path.dirname(os.path.abspath(__file__))

# The ledger itself is bootstrapped by the runner, not applied as a migration.
_LEDGER_FILE = "migration_schema_migrations.sql"

# Explicit, ordered list of incremental migrations. Order is encoded here
# instead of in prose. The one hard dependency in the codebase — dropping the
# legacy grade tables before the gradebook rebuild — is encoded by position;
# the remaining files are independent and individually idempotent
# (CREATE ... IF NOT EXISTS / pg_constraint-guarded ALTERs). Append new
# migrations to the END of this tuple as they are added.
MANIFEST: tuple[str, ...] = (
    "migration_google_auth.sql",
    "migration_add_is_approved.sql",
    "migration_onboarding_fields.sql",
    "migration_roles.sql",
    "migration_admin_portal.sql",
    "migration_profile_settings.sql",
    "migration_avatars_bucket.sql",
    "migration_achievements.sql",
    "migration_cosmetics.sql",
    "migration_newsletter.sql",
    "migration_concept_notes.sql",
    "migration_documents_request_id.sql",
    "migration_encryption_text_columns.sql",
    "migration_flashcard_course_id.sql",
    "migration_notes.sql",
    "migration_drop_legacy_grade_tables.sql",  # must precede gradebook
    "migration_gradebook.sql",
)


def discover_migrations() -> set[str]:
    """Every incremental migration file on disk (excludes the ledger + snapshot)."""
    found = {os.path.basename(p) for p in glob.glob(os.path.join(_DB_DIR, "migration_*.sql"))}
    found.discard(_LEDGER_FILE)
    return found


def read_sql(name: str) -> str:
    with open(os.path.join(_DB_DIR, name), encoding="utf-8") as fh:
        return fh.read()


def pending(applied: set[str]) -> list[str]:
    """Manifest entries not yet recorded in the ledger, in manifest order."""
    return [m for m in MANIFEST if m not in applied]


def _applied_versions(cur) -> set[str]:
    cur.execute("SELECT version FROM schema_migrations")
    return {row[0] for row in cur.fetchall()}


def apply(database_url: str) -> list[str]:
    """Apply all pending migrations in order; return the list applied this run."""
    try:
        import psycopg  # lazy — not a runtime dependency of the app
    except ModuleNotFoundError as exc:  # pragma: no cover - env-dependent
        raise SystemExit(
            "psycopg is required to apply migrations: pip install 'psycopg[binary]'"
        ) from exc

    applied_now: list[str] = []
    with psycopg.connect(database_url) as conn:
        with conn.cursor() as cur:
            cur.execute(read_sql(_LEDGER_FILE))  # ensure ledger exists
            already = _applied_versions(cur)
            for name in pending(already):
                cur.execute(read_sql(name))
                cur.execute(
                    "INSERT INTO schema_migrations(version) VALUES (%s) "
                    "ON CONFLICT (version) DO NOTHING",
                    (name,),
                )
                applied_now.append(name)
        conn.commit()
    return applied_now


def _ledger_exists(cur) -> bool:
    cur.execute(
        "SELECT EXISTS (SELECT 1 FROM information_schema.tables "
        "WHERE table_name = 'schema_migrations')"
    )
    return bool(cur.fetchone()[0])


def _status(database_url: str | None) -> None:
    if not database_url:
        print("No DATABASE_URL set — showing manifest order only:\n")
        for i, name in enumerate(MANIFEST, 1):
            print(f"  {i:2}. {name}")
        return
    import psycopg

    # Read-only: never create the ledger here (contract is "no DB writes").
    # A missing ledger simply means nothing has been applied yet.
    with psycopg.connect(database_url) as conn, conn.cursor() as cur:
        already = _applied_versions(cur) if _ledger_exists(cur) else set()
    for name in MANIFEST:
        print(f"  [{'x' if name in already else ' '}] {name}")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Sapling migration runner (#197)")
    parser.add_argument("--apply", action="store_true", help="apply pending migrations")
    parser.add_argument("--status", action="store_true", help="show applied/pending")
    args = parser.parse_args(argv)

    database_url = os.getenv("DATABASE_URL")
    if args.apply:
        if not database_url:
            raise SystemExit("DATABASE_URL is required for --apply")
        done = apply(database_url)
        print(f"Applied {len(done)} migration(s): {', '.join(done) or '(none — up to date)'}")
    else:
        _status(database_url)


if __name__ == "__main__":
    main()
