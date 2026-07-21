"""Pull the real course CATALOG from a remote Supabase (default: staging) into LOCAL.

Copies the *unencrypted* catalog tables — `courses` and `course_offerings` — over
the source's REST API (read-only on the source) and upserts them into the local
Supabase. User-scoped / encrypted data is intentionally NOT copied: those columns
are encrypted with the remote project's ENCRYPTION_KEY and would be undecryptable
locally (see docs/local-supabase.md). Idempotent — upserts on `id`.

Local already ships the 4 canonical `terms` (migration 0019) and a demo `schools`
row, which the pulled offerings/courses reference, so only the two bulk tables are
pulled. Run from backend/ with the local .env active:

    python -m db.seed_local_catalog                 # source = .env.staging
    SOURCE_ENV=.env.production python -m db.seed_local_catalog

Source is read-only. Destination MUST be local (guarded).
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import httpx
from dotenv import dotenv_values

BACKEND_DIR = Path(__file__).resolve().parent.parent
LOCAL_ENV = BACKEND_DIR / ".env"
SOURCE_ENV = BACKEND_DIR / os.getenv("SOURCE_ENV", ".env.staging")

# FK order: courses before course_offerings. terms/schools already exist locally.
TABLES = ["courses", "course_offerings"]
PAGE = 1000   # source read page size
BATCH = 500   # local upsert batch size


def _load(path: Path) -> tuple[str, str]:
    vals = dotenv_values(path)
    url = (vals.get("SUPABASE_URL") or "").strip().rstrip("/")
    key = (vals.get("SUPABASE_SERVICE_KEY") or "").strip()
    if not url or not key:
        sys.exit(f"ERROR: {path} is missing SUPABASE_URL / SUPABASE_SERVICE_KEY")
    return url, key


def _headers(key: str) -> dict:
    return {"apikey": key, "Authorization": f"Bearer {key}"}


def fetch_all(client: httpx.Client, base: str, key: str, table: str) -> list[dict]:
    rows: list[dict] = []
    offset = 0
    while True:
        r = client.get(
            f"{base}/rest/v1/{table}",
            params={"select": "*", "limit": PAGE, "offset": offset, "order": "id"},
            headers=_headers(key),
        )
        r.raise_for_status()
        page = r.json()
        rows.extend(page)
        if len(page) < PAGE:
            break
        offset += PAGE
    return rows


def upsert(client: httpx.Client, base: str, key: str, table: str, rows: list[dict]) -> int:
    if not rows:
        return 0
    headers = {
        **_headers(key),
        "Content-Type": "application/json",
        "Prefer": "resolution=merge-duplicates,return=minimal",
    }
    done = 0
    for i in range(0, len(rows), BATCH):
        chunk = rows[i : i + BATCH]
        r = client.post(
            f"{base}/rest/v1/{table}",
            params={"on_conflict": "id"},
            headers=headers,
            json=chunk,
        )
        if r.status_code >= 300:
            sys.exit(f"ERROR upserting {table} batch @{i}: HTTP {r.status_code} {r.text[:300]}")
        done += len(chunk)
        print(f"    {table}: {done}/{len(rows)}", end="\r", flush=True)
    print()
    return done


def main() -> int:
    src_url, src_key = _load(SOURCE_ENV)
    dst_url, dst_key = _load(LOCAL_ENV)
    if "127.0.0.1" not in dst_url and "localhost" not in dst_url:
        sys.exit(f"REFUSING: destination {dst_url!r} is not local — this script only writes to local.")

    print(f"source (read-only): {src_url}  [{SOURCE_ENV.name}]")
    print(f"dest   (local):     {dst_url}")
    with httpx.Client(timeout=90.0) as client:
        for table in TABLES:
            print(f"  pulling {table}…")
            rows = fetch_all(client, src_url, src_key, table)
            upsert(client, dst_url, dst_key, table, rows)
            print(f"  ✓ {table}: {len(rows)} rows")
    print("done.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
