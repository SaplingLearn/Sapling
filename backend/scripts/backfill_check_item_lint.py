#!/usr/bin/env python3
"""Backfill check_items.lint_flags (learning loop, spec §13 A113).

New check items are linted when they are stored (services/check_item_service.py
runs learning/item_lint.py over the stored shape). This lints the rows stored
before the linter existed (`lint_flags` NULL) and, with --relint, every row (run
it after a change to learning/item_lint.py). It reads the same stored shape the
write path lints — the decrypted prompt and the lettered options with the
correct letter (`lint_check_item`) — so a backfilled row and a freshly written
one agree. Flags are codes, never text; no item is dropped or rewritten, and no
model is called. The delayed post-test prefers unflagged items and the admin
review queue (/admin/check-items) lists the flagged ones.

Dry-run by default: prints what it would write — item ids and flag codes only,
never item text. Run from backend/:
    python scripts/backfill_check_item_lint.py [--course <id>] [--relint]          # preview
    python scripts/backfill_check_item_lint.py [--course <id>] [--relint] --apply

Reads .env; for staging/prod run under `dotenv -f .env.<env> run -- ...` and
check the `Project:` line it prints first. Needs the ENCRYPTION_KEY the rows
were written under: the item text is decrypted in memory to lint it. Needs
migration 20261108041639_learning_item_quality.sql applied. Idempotent: a row
whose stored flags already match is not written. Every row to write is read
first and written after the read finishes, so an update never moves a row out
from under the paged read (the default mode reads `lint_flags IS NULL`).
Exit 1 when any write failed.
"""

import argparse
import sys
from collections import Counter
from pathlib import Path
from urllib.parse import urlparse

from dotenv import load_dotenv

BASE = Path(__file__).parent.parent
load_dotenv(BASE / ".env")
sys.path.insert(0, str(BASE))

from db.connection import SUPABASE_URL  # noqa: E402
from services.check_item_service import (  # noqa: E402
    items_to_lint,
    lint_update,
    store_lint_flags,
)

_LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1", "0.0.0.0", "host.docker.internal"}
_SUPABASE_SUFFIX = ".supabase.co"


def _project_ref() -> str:
    """The project SUPABASE_URL points at (scripts/backfill_check_items.py's rule)."""
    host = (urlparse(SUPABASE_URL).hostname or "").lower()
    if not host or host in _LOCAL_HOSTS:
        return "local"
    if host.endswith(_SUPABASE_SUFFIX):
        return host[: -len(_SUPABASE_SUFFIX)].split(".")[0]
    return host


def plan(course: str | None, *, relint: bool) -> tuple[int, dict[tuple[str, ...], list[str]]]:
    """(rows read, {flags: [item ids whose stored flags differ]}) — reads only."""
    scanned = 0
    writes: dict[tuple[str, ...], list[str]] = {}
    for item in items_to_lint(course, relint=relint):
        scanned += 1
        flags = lint_update(item)
        if flags is not None:
            writes.setdefault(tuple(flags), []).append(item.id)
    return scanned, writes


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Lint stored check items and store their flags (spec §13 A113)."
    )
    parser.add_argument("--course", help="Only this (abstract) course id; default every course.")
    parser.add_argument(
        "--relint",
        action="store_true",
        help="Re-lint every row, not only the never-linted ones (after a linter change).",
    )
    parser.add_argument("--apply", action="store_true", help="Write the flags (default: dry run).")
    args = parser.parse_args(argv)

    print(f"Project: {_project_ref()}")
    scanned, writes = plan(args.course, relint=args.relint)
    rows = sum(len(ids) for ids in writes.values())
    by_flag: Counter[str] = Counter()
    for flags, ids in writes.items():
        for flag in flags:
            by_flag[flag] += len(ids)
    clean = len(writes.get((), []))
    print(
        f"  {scanned} row(s) read; {rows} to write ({clean} clean, {rows - clean} flagged)"
        + (" — dry run" if not args.apply else "")
    )
    for flag, n in sorted(by_flag.items()):
        print(f"    {flag}: {n}")

    failed = 0
    if args.apply:
        for flags, ids in sorted(writes.items()):
            try:
                store_lint_flags(flags, ids)
            except Exception as exc:  # noqa: BLE001 — one failed batch is reported, the rest still run
                failed += len(ids)
                print(f"  write failed for {len(ids)} row(s) flagged {list(flags)}: {type(exc).__name__}")
        print(f"Done: {rows - failed} row(s) written, {failed} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
