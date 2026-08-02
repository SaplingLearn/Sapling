"""`python -m promotion` — the real ports wired to the real world (#516).

Run from backend/ with production's env loaded:

    venv/bin/dotenv -f .env.production run -- venv/bin/python -m promotion

Flags:
    --allow-destructive      proceed despite destructive DDL in pending migrations
    --skip-staging-check     proceed despite migrations staging has never run
    --verify-only            skip preflight/migrate/merge; just wait for the
                              deploy to report production's current tip and run
                              smoke. This is the real way to re-check a
                              promotion without re-merging (see runner.Options).
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


def _run(cmd: list[str]) -> str:
    """Run a subprocess and surface its real stderr on failure.

    `check=True` alone collapses every git/gh failure into "returned non-zero
    exit status 1" and throws away the one line (merge conflict, bad ref,
    auth expired, ...) that would tell the operator what actually happened.
    """
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()
        raise RuntimeError(f"`{' '.join(cmd[:2])}` failed ({result.returncode}): {detail}")
    return result.stdout.strip()


class Git:
    def fetch(self) -> None:
        _run(["git", "fetch", "origin", "--quiet"])

    def head_sha(self, ref: str) -> str:
        return _run(["git", "rev-parse", ref])

    def commits_ahead_of(self, base: str, head: str) -> int:
        return int(_run(["git", "rev-list", "--count", f"{base}..{head}"]))


class Gh:
    def ensure_pr(self, base: str, head: str, title: str) -> int:
        # --state open ONLY. `--state all` was the bug: it can return a PREVIOUS
        # promotion's already-MERGED PR (this repo's real history returns
        # {"number": 515, "state": "MERGED"} for base=production/head=main), and
        # the runner reads an already-merged PR as "resume here, skip the
        # confirm" — silently bypassing the one human gate this tool has.
        existing = _run([
            "gh", "pr", "list", "--base", base, "--head", head, "--state", "open",
            "--limit", "1", "--json", "number", "--jq", ".[0].number // empty",
        ])
        if existing:
            return int(existing)

        _run([
            "gh", "pr", "create", "--base", base, "--head", head,
            "--title", title, "--body", "Automated promotion (#516).",
        ])
        # Re-query once, not recursively: a second miss means `gh pr create`
        # did something other than what we expect, and guessing again would
        # just create PRs in a loop.
        existing = _run([
            "gh", "pr", "list", "--base", base, "--head", head, "--state", "open",
            "--limit", "1", "--json", "number", "--jq", ".[0].number // empty",
        ])
        if not existing:
            raise RuntimeError(
                f"gh pr create for {head} -> {base} did not produce a discoverable "
                "open PR. Check `gh pr list` manually."
            )
        return int(existing)

    def state(self, number: int) -> str:
        return _run(["gh", "pr", "view", str(number), "--json", "state", "--jq", ".state"])

    def merge(self, number: int) -> None:
        _run(["gh", "pr", "merge", str(number), "--merge"])


def _staging_recorded() -> set[str] | None:
    """Staging's ledger, so preflight can refuse DDL staging never ran.

    None means "couldn't read it" (most commonly: the var just isn't set —
    it ships in no .env* example in this repo), which preflight.evaluate
    treats as "unknown", NOT as "staging has run nothing".
    """
    url = os.environ.get("STAGING_SUPABASE_DB_URL", "").strip()
    if not url:
        return None
    try:
        with psycopg.connect(url) as conn, conn.cursor() as cur:
            cur.execute("SELECT filename FROM schema_migrations")
            return {row[0] for row in cur.fetchall()}
    except psycopg.Error as exc:
        # Same wart _run() fixes for subprocesses: an unwrapped driver error
        # would escape main()'s handler as a raw traceback instead of the one
        # clean line an operator needs mid-promotion.
        raise RuntimeError(f"could not read staging's migration ledger ({exc})") from exc


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
    parser.add_argument(
        "--verify-only", action="store_true",
        help="skip preflight/migrate/merge; just wait for the deploy and run smoke",
    )
    parser.add_argument("--yes", action="store_true")
    args = parser.parse_args()

    # --verify-only touches no database at all (see runner.Options.verify_only:
    # it skips preflight/snapshot/migrate entirely), so it must not be blocked
    # by a credential this mode never uses.
    db_url = os.environ.get("SUPABASE_DB_URL", "").strip()
    if not db_url and not args.verify_only:
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
    options = Options(
        allow_destructive=args.allow_destructive,
        skip_staging_check=args.skip_staging_check,
        verify_only=args.verify_only,
    )
    try:
        return run(ports, options)
    except RuntimeError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
