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
import re
import subprocess
import sys
import time
from typing import Callable

import psycopg

from db import migrate as db_migrate
from promotion import preflight, smoke, snapshot
from promotion.runner import Options, Ports, run


def _run(cmd: list[str], timeout: float = 120) -> str:
    """Run a subprocess and surface its real stderr on failure.

    `check=True` alone collapses every git/gh failure into "returned non-zero
    exit status 1" and throws away the one line (merge conflict, bad ref,
    auth expired, ...) that would tell the operator what actually happened.

    Every caller of this is a network call (git fetch, gh pr create/view/
    merge). Without a timeout, a stalled network or a `gh` sitting on an
    interactive prompt hangs forever with no output — possibly AFTER the
    migration has already applied. httpx_fetch bounds its calls at 25s and
    the deploy poll bounds itself at wait_timeout; this is the same
    discipline applied to subprocess calls.
    """
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(f"`{' '.join(cmd[:2])}` timed out after {timeout}s") from exc
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

    def migrations_drift(self) -> str:
        """How the LOCAL migrations dir differs from origin/main; "" = clean.

        Preflight's file listing and db_migrate.run() both read the local
        working tree, but the thing being promoted is origin/main — so the
        runner blocks on any mismatch. Two complementary reads, because
        neither alone covers both failure directions: `git diff --name-status
        origin/main` catches tracked files differing in content or presence
        (either direction — including a stale checkout missing an origin/main
        file) but is blind to untracked strays; `git status --porcelain`
        catches the strays but reports nothing for a merely-old checkout.
        Absolute pathspec, so the check is correct regardless of the cwd the
        tool was launched from.
        """
        migrations = str(db_migrate.MIGRATIONS_DIR)
        tracked = _run(["git", "diff", "--name-status", "origin/main", "--", migrations])
        untracked = _run(["git", "status", "--porcelain", "--", migrations])
        return "\n".join(part for part in (tracked, untracked) if part)

    def is_ancestor(self, ancestor: str, descendant: str) -> bool:
        """`git merge-base --is-ancestor`: exit 0 = yes, 1 = no.

        Not routed through _run, which reads every non-zero exit as failure —
        here exit 1 is a valid answer. Any OTHER exit (bad ref, not a repo) is
        a real error and raises: the caller treats this guard as fail-closed,
        so an unreadable answer must block, never pass as either boolean.
        Same 120s no-hang discipline as _run.
        """
        cmd = ["git", "merge-base", "--is-ancestor", ancestor, descendant]
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError("`git merge-base` timed out after 120s") from exc
        if result.returncode == 0:
            return True
        if result.returncode == 1:
            return False
        detail = (result.stderr or result.stdout).strip()
        raise RuntimeError(f"`git merge-base` failed ({result.returncode}): {detail}")


# The created PR's number is the trailing path segment of the URL `gh pr
# create` prints; anchored on /pull/ so compare/commit URLs mixed into the
# same output never match.
_PR_URL_RE = re.compile(r"https://\S+/pull/(\d+)\b")


class Gh:
    def __init__(self, sleep: Callable[[float], None] = time.sleep) -> None:
        # Injected like runner.Ports.sleep so ensure_pr's fallback retry is
        # testable without wall-clock waits.
        self._sleep = sleep

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

        created = _run([
            "gh", "pr", "create", "--base", base, "--head", head,
            "--title", title, "--body", "Automated promotion (#516).",
        ])
        # `gh pr create`'s own stdout (the new PR's URL) is the one
        # immediately-consistent source of the number: the list endpoint can
        # lag creation by seconds, and a miss there fails the run AFTER the
        # migration has already applied. Last match wins — gh mixes progress
        # and warning lines into the same output.
        urls = _PR_URL_RE.findall(created)
        if urls:
            return int(urls[-1])

        # Fallback for an unparseable output shape: bounded list re-queries
        # (with a pause for list-endpoint lag), never a second create —
        # guessing again would just open PRs in a loop.
        for attempt in range(3):
            if attempt:
                self._sleep(2)
            existing = _run([
                "gh", "pr", "list", "--base", base, "--head", head, "--state", "open",
                "--limit", "1", "--json", "number", "--jq", ".[0].number // empty",
            ])
            if existing:
                return int(existing)
        raise RuntimeError(
            f"gh pr create for {head} -> {base} did not produce a discoverable "
            "open PR. Check `gh pr list` manually."
        )

    def state(self, number: int) -> str:
        return _run(["gh", "pr", "view", str(number), "--json", "state", "--jq", ".state"])

    def merge(self, number: int, match_head_commit: str) -> None:
        # Pinned to the SHA preflight audited. Unpinned, `gh pr merge --merge`
        # merges whatever origin/main's tip is AT MERGE TIME, so commits
        # landing while the operator sat at the confirm prompt would be
        # promoted with their migrations never scanned nor applied. Flag
        # verified against the gh CLI in PATH: `gh pr merge --help` documents
        # `--match-head-commit SHA` ("Commit SHA that the pull request head
        # must match to allow merge") — GitHub itself rejects a moved head.
        _run([
            "gh", "pr", "merge", str(number), "--merge",
            "--match-head-commit", match_head_commit,
        ])


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
        with psycopg.connect(url) as conn:
            return preflight.recorded_filenames(conn)
    except psycopg.Error as exc:
        # NOT re-raised: a stale URI, a paused staging project, or a
        # transient network fault here must not abort the whole run before
        # the operator ever sees a preflight report — that would deny them
        # the existence of --skip-staging-check at the exact moment they'd
        # want it. Print the reason (so the degradation isn't silent) and
        # return None, same as "the var is unset": preflight.evaluate turns
        # that into its documented `staging-unknown` finding, whose own text
        # says exactly this ("could not read staging's migration ledger").
        print(f"WARNING: could not read staging's migration ledger ({exc})", file=sys.stderr)
        return None


def _preflight_data(conn) -> dict:
    files = [p.name for p in db_migrate.discover_migrations(db_migrate.MIGRATIONS_DIR)]
    # The shared ledger primitives (preflight.ledger_exists/recorded_filenames/
    # ledger_diff) — the same ones scripts/migration_drift_report.py consumes,
    # so this preflight and that report can never diff the ledger differently.
    exists = preflight.ledger_exists(conn)
    recorded: set[str] = preflight.recorded_filenames(conn) if exists else set()

    pending, _ = preflight.ledger_diff(files, recorded)
    pending_paths = [db_migrate.MIGRATIONS_DIR / name for name in pending]
    return {
        # .strip() to match the value main() actually connects with — an
        # unstripped value with leading whitespace makes urlparse() (inside
        # preflight.project_ref) yield no ref, which silently no-ops the
        # target-mismatch guard instead of tripping it.
        "db_url": os.environ.get("SUPABASE_DB_URL", "").strip(),
        "supabase_url": os.environ.get("SUPABASE_URL", "").strip(),
        "ledger_exists": exists,
        "migration_files": files,
        "recorded": recorded,
        "staging_recorded": _staging_recorded(),
        "destructive": preflight.scan_destructive(pending_paths),
    }


def _confirm(prompt: str, auto_yes: bool) -> bool:
    """The interactive confirmation gate — a plain function, not a closure
    over `main()`'s locals, so it is directly testable.

    `input()` raises `EOFError` on non-interactive stdin (no controlling
    terminal, a closed pipe, CI invoking this without a tty). `str(EOFError())`
    is empty, so letting it propagate would make `main()`'s handler print a
    bare "ERROR: " — right after the migration has already applied, the exact
    moment a clear message matters most. Treat it exactly like a typed "n"
    instead: the runner's own "ABORTED before the merge" report already
    explains the migrations are applied and returns EXIT_ABORTED, which is a
    far clearer outcome. Ctrl-C at the prompt gets the same treatment:
    KeyboardInterrupt is a BaseException that `main()`'s `except Exception`
    never catches, so propagating it would skip that report for a raw
    traceback.
    """
    if auto_yes:
        return True
    try:
        return input(f"{prompt} [y/N] ").strip().lower() in {"y", "yes"}
    except EOFError:
        return False
    except KeyboardInterrupt:
        # The newline keeps the terminal's ^C echo off the report's first line.
        print()
        return False


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
        return _confirm(prompt, args.yes)

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
    except Exception as exc:  # noqa: BLE001 — no path may exit as a raw traceback:
        # this also covers psycopg errors from Git.commits_ahead_of's int()
        # parse, psycopg.connect(), and anything else not already wrapped in
        # a RuntimeError by _run()/_staging_recorded().
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
