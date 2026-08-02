"""`python -m promotion` — the real ports wired to the real world (#516).

Run from backend/ with production's env loaded:

    venv/bin/dotenv -f .env.production run -- venv/bin/python -m promotion

Flags:
    --allow-destructive      proceed despite destructive DDL in pending migrations
    --skip-staging-check     proceed despite migrations staging has never run
    --yes                    answer the confirmation prompt automatically (CI)
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time

import psycopg

from db import migrate as db_migrate
from promotion import preflight, smoke, snapshot
from promotion.runner import Options, Ports, run


class Git:
    def fetch(self) -> None:
        subprocess.run(["git", "fetch", "origin", "--quiet"], check=True)

    def head_sha(self, ref: str) -> str:
        return subprocess.run(
            ["git", "rev-parse", ref], check=True, capture_output=True, text=True
        ).stdout.strip()

    def commits_ahead_of(self, base: str, head: str) -> int:
        result = subprocess.run(
            ["git", "rev-list", "--count", f"{base}..{head}"],
            check=True, capture_output=True, text=True,
        )
        return int(result.stdout.strip())


class Gh:
    def ensure_pr(self, base: str, head: str, title: str) -> int:
        existing = subprocess.run(
            ["gh", "pr", "list", "--base", base, "--head", head, "--state", "all",
             "--limit", "1", "--json", "number,state", "--jq", ".[0].number // empty"],
            check=True, capture_output=True, text=True,
        ).stdout.strip()
        if existing:
            return int(existing)
        subprocess.run(
            ["gh", "pr", "create", "--base", base, "--head", head,
             "--title", title, "--body", "Automated promotion (#516)."],
            check=True, capture_output=True, text=True,
        )
        return self.ensure_pr(base, head, title)

    def state(self, number: int) -> str:
        return subprocess.run(
            ["gh", "pr", "view", str(number), "--json", "state", "--jq", ".state"],
            check=True, capture_output=True, text=True,
        ).stdout.strip()

    def merge(self, number: int) -> None:
        subprocess.run(["gh", "pr", "merge", str(number), "--merge"],
                       check=True, capture_output=True, text=True)


def _staging_recorded() -> set[str]:
    """Staging's ledger, so preflight can refuse DDL staging never ran."""
    url = os.environ.get("STAGING_SUPABASE_DB_URL", "").strip()
    if not url:
        return set()
    with psycopg.connect(url) as conn, conn.cursor() as cur:
        cur.execute("SELECT filename FROM schema_migrations")
        return {row[0] for row in cur.fetchall()}


def _preflight_data(conn) -> dict:
    files = [p.name for p in db_migrate.discover_migrations(db_migrate.MIGRATIONS_DIR)]
    with conn.cursor() as cur:
        cur.execute("SELECT to_regclass('public.schema_migrations') IS NOT NULL")
        exists = bool(cur.fetchone()[0])
        recorded: set[str] = set()
        if exists:
            cur.execute("SELECT filename FROM schema_migrations")
            recorded = {row[0] for row in cur.fetchall()}

    pending, _ = preflight.ledger_diff(files, recorded)
    pending_paths = [db_migrate.MIGRATIONS_DIR / name for name in pending]
    return {
        "db_url": os.environ.get("SUPABASE_DB_URL", ""),
        "supabase_url": os.environ.get("SUPABASE_URL", ""),
        "ledger_exists": exists,
        "migration_files": files,
        "recorded": recorded,
        "staging_recorded": _staging_recorded(),
        "destructive": preflight.scan_destructive(pending_paths),
    }


def main() -> int:
    parser = argparse.ArgumentParser(prog="promotion")
    parser.add_argument("--allow-destructive", action="store_true")
    parser.add_argument("--skip-staging-check", action="store_true")
    parser.add_argument("--yes", action="store_true")
    args = parser.parse_args()

    db_url = os.environ.get("SUPABASE_DB_URL", "").strip()
    if not db_url:
        print(
            "ERROR: SUPABASE_DB_URL is not set. Run under production's env:\n"
            "  venv/bin/dotenv -f .env.production run -- venv/bin/python -m promotion\n"
            "It must be the SESSION-mode pooler URI (port 5432, user postgres.<ref>); "
            "production is on the aws-0-us-west-2 cluster. Build it with "
            "`python scripts/pooler_url.py .env.production aws-0-us-west-2 --raw`.",
            file=sys.stderr,
        )
        return 1

    def confirm(prompt: str) -> bool:
        if args.yes:
            return True
        return input(f"{prompt} [y/N] ").strip().lower() in {"y", "yes"}

    ports = Ports(
        connect=lambda: psycopg.connect(db_url),
        preflight_data=_preflight_data,
        capture=snapshot.capture,
        migrate=lambda conn: db_migrate.run(conn),
        git=Git(),
        gh=Gh(),
        fetch=smoke.httpx_fetch,
        confirm=confirm,
        out=print,
        sleep=time.sleep,
    )
    return run(ports, Options(
        allow_destructive=args.allow_destructive,
        skip_staging_check=args.skip_staging_check,
    ))


if __name__ == "__main__":
    raise SystemExit(main())
