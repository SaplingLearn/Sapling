"""Before/after snapshots of the production database (#516).

The point is evidence, not monitoring: capture once before migrating and once
after, then diff, so the operator confirming the merge sees exactly what the
migration did — and so a failed promotion has an artifact to reason about
instead of terminal scrollback.

SELECTs only. Nothing here writes.
"""
from __future__ import annotations

LEDGER_EXISTS_SQL = "SELECT to_regclass('public.schema_migrations') IS NOT NULL"
LEDGER_SQL = "SELECT filename FROM schema_migrations ORDER BY filename"
TABLES_SQL = """
    SELECT table_name
    FROM information_schema.tables
    WHERE table_schema = 'public' AND table_type = 'BASE TABLE'
    ORDER BY table_name
"""


def capture(conn) -> dict:
    """Ledger contents and per-table row counts for the connected database."""
    snapshot: dict = {"host": getattr(conn.info, "host", "unknown")}

    with conn.cursor() as cur:
        cur.execute(LEDGER_EXISTS_SQL)
        exists = bool(cur.fetchone()[0])
        snapshot["ledger_exists"] = exists

        ledger: list[str] = []
        if exists:
            cur.execute(LEDGER_SQL)
            ledger = [row[0] for row in cur.fetchall()]
        snapshot["ledger"] = ledger

        cur.execute(TABLES_SQL)
        names = [row[0] for row in cur.fetchall()]

        counts: dict[str, int] = {}
        for name in names:
            # Identifier comes from information_schema, never from user input,
            # and count(*) takes no bindable parameter for a table name.
            cur.execute(f'SELECT count(*) FROM public."{name}"')
            counts[name] = cur.fetchone()[0]
        snapshot["tables"] = counts

    return snapshot


def diff(before: dict, after: dict) -> dict:
    """What changed between two snapshots."""
    b, a = before.get("tables", {}), after.get("tables", {})
    return {
        "new_tables": sorted(set(a) - set(b)),
        "dropped_tables": sorted(set(b) - set(a)),
        "count_changes": {k: (b[k], a[k]) for k in sorted(set(b) & set(a)) if b[k] != a[k]},
        "new_migrations": [m for m in after.get("ledger", []) if m not in set(before.get("ledger", []))],
    }


def format_diff(d: dict) -> str:
    """Human-readable diff for the confirmation prompt and the final report."""
    lines: list[str] = []
    if d["new_migrations"]:
        lines.append(f"  migrations applied ({len(d['new_migrations'])}):")
        lines += [f"    + {m}" for m in d["new_migrations"]]
    if d["new_tables"]:
        lines.append(f"  new tables: {', '.join(d['new_tables'])}")
    if d["dropped_tables"]:
        lines.append(f"  DROPPED tables: {', '.join(d['dropped_tables'])}")
    if d["count_changes"]:
        lines.append("  row-count changes:")
        lines += [f"    {t}: {old} -> {new}" for t, (old, new) in d["count_changes"].items()]
    return "\n".join(lines) if lines else "  no schema or row-count changes"
