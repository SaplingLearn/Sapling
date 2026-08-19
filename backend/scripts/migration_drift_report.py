"""Read-only drift report between backend/db/migrations/ and a live database.

Answers the question you must answer before applying a backlog of migrations to
an environment that has been touched outside the repo (#317): **is the ledger
merely behind, or is it lying?**

    SUPABASE_DB_URL=... python scripts/migration_drift_report.py

Writes nothing. Runs no DDL. Safe against production.

Four sections:

  PENDING   — on disk, not in schema_migrations.
  ORPHANS   — in schema_migrations, not on disk. Means the environment ran SQL
              that never existed in this repo (dashboard editor, ad-hoc script).
              A filename collision here is the dangerous shape: staging having
              recorded `0032_retire_summer_2026.sql` while the repo's own
              `0032_rooms_missing_columns.sql` is pending means two different
              migrations share a number.
  ALREADY   — objects a PENDING migration would create that ALREADY EXIST.
              Every row here is the ledger lying: the schema moved without
              being recorded, so "pending" overstates what will actually run.
              Migrations written with IF NOT EXISTS will no-op safely; ones
              without it will fail the whole run.
  BLOCKERS  — live rows that already violate a UNIQUE index a PENDING migration
              would create. IF NOT EXISTS cannot save this one: it is a DATA
              conflict, invisible to a schema-only diff, and it is what turns a
              clean-looking backlog into a half-applied run.

The object list is parsed from the migration SQL itself (CREATE TABLE / ADD
COLUMN / CREATE INDEX), so it stays correct as migrations are added — nothing
to keep in sync by hand.

Exit codes: 2 no SUPABASE_DB_URL, 1 drift found (no ledger, orphans, a
non-idempotent collision, or a data blocker), 0 clean. Nonzero means "do not
apply on top of this" — so the report can gate CI directly rather than being
re-implemented inline, which is how the workflow preflight and this script
drifted apart in the first place.

The ledger primitives (pending/orphans, ledger reads, the no-ledger guidance)
are imported from promotion.preflight — the same implementation the promotion
runner's preflight consumes (#516) — so the two cannot drift apart again. The
extra checks (number collision, ALREADY EXISTS, data blockers) remain this
script's own.
"""
from __future__ import annotations

import os
import pathlib
import re
import sys

import psycopg

# Run as a script (`python scripts/migration_drift_report.py` from backend/),
# sys.path[0] is scripts/ — put backend/ there so the shared promotion
# primitives resolve; same pattern as the other scripts in this directory.
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from promotion.preflight import (  # noqa: E402
    NO_LEDGER_REMEDIATION,
    ledger_diff,
    ledger_exists,
    recorded_filenames,
)

MIGRATIONS = pathlib.Path(__file__).resolve().parent.parent / "db" / "migrations"

RE_TABLE = re.compile(r"create\s+table\s+(?:if\s+not\s+exists\s+)?([a-z0-9_.]+)", re.I)
RE_COLUMN = re.compile(
    r"alter\s+table\s+([a-z0-9_.]+)\s+add\s+column\s+(?:if\s+not\s+exists\s+)?([a-z0-9_]+)",
    re.I,
)
RE_INDEX = re.compile(r"create\s+(?:unique\s+)?index\s+(?:if\s+not\s+exists\s+)?([a-z0-9_]+)", re.I)

# A UNIQUE index is the one thing in a pending migration that IF NOT EXISTS
# cannot make safe: it still fails if the live data already violates it. That
# is a DATA problem, invisible to a schema-only diff, and it is what turns a
# clean-looking backlog into a half-applied run. Parsed so the check follows
# whatever migrations are actually pending.
RE_UNIQUE_INDEX = re.compile(
    r"create\s+unique\s+index\s+(?:if\s+not\s+exists\s+)?([a-z0-9_]+)\s+"
    r"on\s+([a-z0-9_.]+)\s*\(([^)]*)\)(?:\s*where\s+([^;]+))?",
    re.I | re.S,
)


def bare(name: str) -> str:
    return name.split(".")[-1]


def main() -> int:
    url = os.getenv("SUPABASE_DB_URL")
    if not url:
        print("SUPABASE_DB_URL is not set", file=sys.stderr)
        return 2

    files = sorted(p.name for p in MIGRATIONS.glob("*.sql"))
    conn = psycopg.connect(url)

    if not ledger_exists(conn):
        print("NO LEDGER — this database has never been migrated by db/migrate.py.")
        print(NO_LEDGER_REMEDIATION)
        return 1

    recorded = recorded_filenames(conn)
    pending, orphans = ledger_diff(files, recorded)

    print(f"on disk {len(files)} | recorded {len(recorded)} | pending {len(pending)}\n")

    print("PENDING")
    for p in pending:
        print(f"  {p}")
    if not pending:
        print("  none")

    print("\nORPHANS (recorded here, absent from the repo)")
    for o in orphans:
        clash = [f for f in files if f.split("_")[0] == o.split("_")[0]]
        note = f"  <-- NUMBER COLLIDES WITH {clash[0]}" if clash else ""
        print(f"  {o}{note}")
    if not orphans:
        print("  none")

    # Which objects the pending migrations would create, that already exist.
    print("\nALREADY EXISTS (pending migration, object already present)")
    found_any = False
    unsafe_already = False
    for name in pending:
        sql = (MIGRATIONS / name).read_text()
        hits: list[str] = []

        for tbl in {bare(t) for t in RE_TABLE.findall(sql)}:
            n = conn.execute(
                "SELECT count(*) FROM information_schema.tables WHERE table_name = %s",
                (tbl,),
            ).fetchone()[0]
            if n:
                hits.append(f"table {tbl}")

        for tbl, col in {(bare(t), c) for t, c in RE_COLUMN.findall(sql)}:
            n = conn.execute(
                "SELECT count(*) FROM information_schema.columns "
                "WHERE table_name = %s AND column_name = %s",
                (tbl, col),
            ).fetchone()[0]
            if n:
                hits.append(f"column {tbl}.{col}")

        for idx in set(RE_INDEX.findall(sql)):
            n = conn.execute(
                "SELECT count(*) FROM pg_indexes WHERE indexname = %s", (idx,)
            ).fetchone()[0]
            if n:
                hits.append(f"index {idx}")

        if hits:
            found_any = True
            idempotent = "if not exists" in sql.lower()
            if not idempotent:
                unsafe_already = True
            flag = "safe: uses IF NOT EXISTS" if idempotent else "!! NO IF NOT EXISTS — would fail"
            print(f"  {name}  ({flag})")
            for h in sorted(hits):
                print(f"      {h}")
    if not found_any:
        print("  none — the ledger is behind, not lying")

    # Data blockers: a pending UNIQUE index that live rows already violate.
    print("\nDATA BLOCKERS (pending UNIQUE index vs rows already present)")
    blocked = False
    for name in pending:
        sql = (MIGRATIONS / name).read_text()
        for idx, table, cols, pred in RE_UNIQUE_INDEX.findall(sql):
            cols_sql = ", ".join(c.strip() for c in cols.split(","))
            where = f" WHERE {pred.strip()}" if pred else ""
            try:
                dupes = conn.execute(
                    f"SELECT {cols_sql}, count(*) FROM {bare(table)}{where} "
                    f"GROUP BY {cols_sql} HAVING count(*) > 1 LIMIT 5"
                ).fetchall()
            except Exception as exc:  # table may not exist yet — that's fine
                conn.rollback()
                print(f"  {name}: {idx} — could not check ({type(exc).__name__})")
                continue
            if dupes:
                blocked = True
                print(f"  {name}: {idx} WOULD FAIL — duplicate rows exist:")
                for d in dupes:
                    print(f"      {d}")
    if not blocked:
        print("  none")

    # Exit nonzero on anything that makes "apply the backlog" unsafe, so this
    # can gate CI as-is. PENDING alone is not drift — that is the normal state
    # of an environment that is merely behind.
    problems = []
    if orphans:
        problems.append(f"{len(orphans)} orphan(s) recorded but absent from the repo")
    if unsafe_already:
        problems.append("an object already exists for a migration without IF NOT EXISTS")
    if blocked:
        problems.append("live rows already violate a pending UNIQUE index")
    if problems:
        print("\nDRIFT — do not apply on top of this:")
        for p in problems:
            print(f"  {p}")
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
