"""Shared idempotency + summary helpers for the local/staging seed scripts.

Extracted from ``seed_staging.py`` so ``seed_local_rich.py`` reuses the exact
same upsert-on-UNIQUE / insert-if-absent / summary machinery. All DB access
goes through ``db.connection.table()``.
"""
from __future__ import annotations

from collections import defaultdict

from db.connection import table  # module-level so tests can monkeypatch it

counts: dict[str, dict[str, int]] = defaultdict(lambda: {"created": 0, "skipped": 0})


def reset_counts() -> None:
    counts.clear()


def record(table_name: str, created: bool) -> None:
    counts[table_name]["created" if created else "skipped"] += 1


def exists_by(table_name: str, eq_filters: dict) -> bool:
    filters = {col: f"eq.{val}" for col, val in eq_filters.items()}
    select_col = next(iter(eq_filters))
    rows = table(table_name).select(select_col, filters=filters, limit=1) or []
    return len(rows) > 0


def upsert(table_name: str, row: dict, on_conflict: str) -> None:
    exists = exists_by(table_name, {k: row[k] for k in on_conflict.split(",")})
    table(table_name).upsert(row, on_conflict=on_conflict)
    record(table_name, created=not exists)


def insert_if_absent(table_name: str, row_id: str, row: dict) -> None:
    if exists_by(table_name, {"id": row_id}):
        record(table_name, created=False)
        return
    table(table_name).insert({"id": row_id, **row})
    record(table_name, created=True)


def print_summary(order: list[str], header: str) -> int:
    print(f"\n{header}")
    total_created = 0
    for name in order:
        c = counts.get(name, {"created": 0, "skipped": 0})
        total_created += c["created"]
        print(f"  {name:24s} created={c['created']:<3d} skipped(exists)={c['skipped']}")
    print(f"  {'TOTAL created':24s} {total_created}")
    if total_created == 0:
        print("  (all rows already present — re-run was a no-op)")
    return total_created
