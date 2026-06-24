"""One-off ops script: copy the canonical `courses` catalog from prod to staging.

`courses` is the shared course catalog (no `user_id`, no encrypted columns), so it
can be copied row-for-row across projects safely — unlike `users`, whose encrypted
columns are keyed to a per-environment ENCRYPTION_KEY.

This spans two Supabase projects, so it deliberately bypasses
db/connection.py::table() (single-environment). It reads PROD via PostgREST (prod has
no direct DB URL) and writes STAGING via psycopg, mirroring db/migrate.py's direct
connection. Writes target STAGING only; prod is read-only.

Sync semantics: additive upsert keyed on `id` (INSERT … ON CONFLICT DO UPDATE).
Courses deleted in prod are NOT removed from staging — this seeds/refreshes, it does
not mirror. Safe to rerun.

Usage (from backend/):
    venv/bin/python -m db.copy_courses_to_staging            # preview (read-only)
    venv/bin/python -m db.copy_courses_to_staging --yes      # apply the upsert
"""

from __future__ import annotations

import argparse
import sys

import httpx
import psycopg

from db._staging_ops import confirm_write, dotenv_value

# Columns present on prod's `courses` table (a subset of staging's schema). Staging
# defaults fill the rest (credits, meeting_times, location, syllabus_url).
COLUMNS = [
    "id",
    "course_code",
    "course_name",
    "department",
    "description",
    "instructor_name",
    "school",
    "semester",
    "created_at",
]

PAGE = 1000  # rows requested per PostgREST Range page


def fetch_prod_courses(base_url: str, service_key: str) -> list[dict]:
    # Page via the PostgREST Range header with Prefer: count=exact, and loop until
    # we've fetched the total reported in Content-Range. Inferring completion from
    # batch length vs PAGE is unreliable: if prod's db-max-rows is below PAGE the
    # first response is short and the loop would stop early, under-fetching silently.
    headers = {
        "apikey": service_key,
        "Authorization": f"Bearer {service_key}",
        "Prefer": "count=exact",
    }
    select = ",".join(COLUMNS)
    rows: list[dict] = []
    offset = 0
    total: int | None = None
    with httpx.Client(timeout=30) as client:
        while True:
            range_headers = {**headers, "Range-Unit": "items", "Range": f"{offset}-{offset + PAGE - 1}"}
            r = client.get(
                f"{base_url}/rest/v1/courses",
                params={"select": select, "order": "id"},
                headers=range_headers,
            )
            r.raise_for_status()
            batch = r.json()
            rows.extend(batch)

            # Content-Range looks like "0-999/1234" (or "*/1234" when empty).
            content_range = r.headers.get("Content-Range", "")
            if total is None and "/" in content_range:
                tail = content_range.split("/", 1)[1].strip()
                if tail.isdigit():
                    total = int(tail)

            if not batch:
                break
            offset += len(batch)
            if total is not None and offset >= total:
                break
    return rows


def upsert_staging(db_url: str, rows: list[dict]) -> int:
    cols = ", ".join(COLUMNS)
    placeholders = ", ".join(["%s"] * len(COLUMNS))
    # Keep `created_at` in the INSERT (set on first seed) but exclude it from the
    # UPDATE: it is effectively immutable, so re-runs must not overwrite staging's
    # existing value with prod's.
    immutable = {"id", "created_at"}
    updates = ", ".join(f"{c} = EXCLUDED.{c}" for c in COLUMNS if c not in immutable)
    sql = (
        f"INSERT INTO courses ({cols}) VALUES ({placeholders}) "
        f"ON CONFLICT (id) DO UPDATE SET {updates}"
    )
    values = [tuple(row.get(c) for c in COLUMNS) for row in rows]
    with psycopg.connect(db_url, connect_timeout=15) as conn:
        with conn.cursor() as cur:
            cur.executemany(sql, values)
            cur.execute("SELECT count(*) FROM courses")
            total = cur.fetchone()[0]
        conn.commit()
    return total


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--prod-env", default=".env")
    ap.add_argument("--staging-env", default=".env.staging")
    ap.add_argument("--yes", action="store_true", help="apply the upsert (default: preview)")
    args = ap.parse_args()

    prod_url = dotenv_value(args.prod_env, "SUPABASE_URL")
    prod_key = dotenv_value(args.prod_env, "SUPABASE_SERVICE_KEY")
    staging_db = dotenv_value(args.staging_env, "SUPABASE_DB_URL")

    print(f"Reading courses from prod ({prod_url}) ...")
    rows = fetch_prod_courses(prod_url, prod_key)
    print(f"  fetched {len(rows)} course rows")

    if not confirm_write(staging_db, args.yes, f"upsert {len(rows)} courses"):
        return 0

    print("Upserting into staging ...")
    total = upsert_staging(staging_db, rows)
    print(f"  done. staging courses table now has {total} rows")
    return 0


if __name__ == "__main__":
    sys.exit(main())
