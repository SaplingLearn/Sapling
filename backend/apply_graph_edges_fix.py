"""Apply the graph_edges reconciliation to prod, transactionally, with verify.

Run (from backend/):
    ./venv/bin/dotenv -f .env.production run -- ./venv/bin/python apply_graph_edges_fix.py \
        /path/to/graph_edges_fix.sql
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import psycopg

WATCH = ["users", "graph_nodes", "node_mastery_events"]  # FK targets / must stay unchanged


def counts(cur, tables):
    out = {}
    for t in tables:
        cur.execute(f'SELECT count(*) FROM "{t}"')
        out[t] = cur.fetchone()[0]
    return out


def main() -> int:
    sql_path = Path(sys.argv[1])
    url = os.environ["SUPABASE_DB_URL"].strip()
    print(f"Target host: {url.split('@')[-1].split('/')[0]}")
    sql = sql_path.read_text()

    with psycopg.connect(url) as conn:
        with conn.cursor() as cur:
            # Pre-checks
            cur.execute("SELECT to_regclass('public.graph_edges')")
            if cur.fetchone()[0] is not None:
                print("graph_edges already exists — nothing to do (idempotent no-op).")
                return 0
            for t in ("users", "graph_nodes"):
                cur.execute("SELECT to_regclass(%s)", (f"public.{t}",))
                if cur.fetchone()[0] is None:
                    print(f"ABORT: FK target {t} missing; refusing to apply.")
                    return 1
            before = counts(cur, WATCH)
            print(f"before counts: {before}")

            # Apply (commits at end of `with conn` block; rolls back on exception)
            cur.execute(sql)

    # Reconnect for a clean post-commit verification
    with psycopg.connect(url) as conn, conn.cursor() as cur:
        cur.execute("SELECT to_regclass('public.graph_edges')")
        exists = cur.fetchone()[0] is not None
        cur.execute("SELECT count(*) FROM graph_edges")
        ge_rows = cur.fetchone()[0]
        cur.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_schema='public' AND table_name='graph_edges' ORDER BY ordinal_position"
        )
        cols = [r[0] for r in cur.fetchall()]
        cur.execute(
            "SELECT indexname FROM pg_indexes WHERE schemaname='public' AND tablename='graph_edges' ORDER BY 1"
        )
        idx = [r[0] for r in cur.fetchall()]
        cur.execute(
            "SELECT conname FROM pg_constraint WHERE conrelid='public.graph_edges'::regclass AND contype='u'"
        )
        uniq = [r[0] for r in cur.fetchall()]
        after = counts(cur, WATCH)

    print("\n== VERIFY ==")
    print(f"  graph_edges exists: {exists}  rows: {ge_rows}")
    print(f"  columns: {cols}")
    print(f"  indexes: {idx}")
    print(f"  unique constraints: {uniq}")
    print(f"  watched counts after: {after}")
    ok = exists and ge_rows == 0 and after == before and len(idx) >= 4 and uniq
    print(f"\n{'OK — graph_edges created, FK-target data unchanged.' if ok else 'CHECK FAILED — review above.'}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
