#!/usr/bin/env python3
"""Re-check stored check items with the alignment check (learning loop, spec §13 A119).

New check items are checked before they are stored (services/check_item_service.py:
the check_items_verify agent answers, per item, whether its question asks for
each rubric criterion and which course concept it tests, and
learning/item_alignment.py applies the answers). This re-checks the rows stored
before that existed (`aligned_at` NULL) and, with --reverify, every row, through
the same check and the same rules:

- every criterion asked, same concept → `aligned_at` stamped, nothing else;
- an unasked criterion → dropped from the stored rubric (an mc_reason item's
  reason criterion stays), `rubric_unasked_dropped` recorded in lint_flags;
- another listed concept → the item is re-keyed under it (a new id) and the old
  row deleted, `concept_retagged` recorded;
- no criterion asked, "none", or a concept outside the course → the item is
  retired (deleted through the A23 retire path);
- no verdict (the check unavailable, or an item left unanswered) → the item is
  left untouched and the run exits 1.

Evidence already recorded is never rewritten: node_mastery_events keys no
foreign key on an item, so its rows keep their check_item_id, node and
question_hash; reports and reviews key on (course_id, question_hash), which a
re-key keeps. An item may be re-tagged into its course's concepts: the concept
names of every student's graph_nodes (scripts/backfill_check_items.py's rule)
and the concepts the items checked are filed under.

Dry-run by default: runs the check (billed to llm_usage like any run, against
the system actor) and prints what it would write — item ids, concept keys and
codes only, never item text; writes nothing to check_items. Run from backend/:
    python scripts/backfill_check_item_alignment.py [--course <id>] [--reverify]       # preview
    python scripts/backfill_check_item_alignment.py [--course <id>] [--reverify] --apply --project <ref>

Reads .env; for staging/prod run under `dotenv -f .env.<env> run -- ...` and
check the `Project:` line it prints first: --apply requires --project naming that
project (exit 2 otherwise, before any read). Refuses (exit 2) when
SAPLING_MODEL_MODE is not 'real' unless --function-mode. Needs the
ENCRYPTION_KEY the rows were written under (the item text is decrypted in memory
to check it) and migration 20261108051912_learning_item_alignment.sql applied.
Every row is read and checked before anything is written (a write moves a row
out of the `aligned_at IS NULL` paging). Exit 1 when any write failed or any
item was left unchecked.
"""

import argparse
import sys
from collections import Counter, defaultdict
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlparse

from dotenv import load_dotenv

BASE = Path(__file__).parent.parent
load_dotenv(BASE / ".env")
sys.path.insert(0, str(BASE))

from agents._providers import model_mode  # noqa: E402
from db.connection import SUPABASE_URL  # noqa: E402
from learning.item_alignment import (  # noqa: E402
    ALIGNMENT_FLAGS,
    CONCEPT_RETAGGED,
    REASON_CODES,
    RUBRIC_UNASKED_DROPPED,
)
from services.check_item_service import (  # noqa: E402
    apply_item_alignment,
    check_stored_alignment,
    course_concept_names,
    items_to_align,
    mark_aligned,
    retire_items_by_id,
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


def plan(course: str | None, *, reverify: bool) -> tuple[int, list[tuple]]:
    """(rows read, [(row, item, Alignment | None)]) — reads and checks only,
    one course at a time; None = the check was unavailable for that course."""
    rows = items_to_align(course, reverify=reverify)
    by_course: dict[str, list] = defaultdict(list)
    for row, item in rows:
        by_course[item.course_id].append((row, item))
    planned: list[tuple] = []
    for course_id, entries in sorted(by_course.items()):
        scope = course_concept_names(course_id)
        for _, item in entries:
            scope.setdefault(item.concept_key, item.concept_key)
        results = check_stored_alignment(course_id, [item for _, item in entries], scope)
        for n, (row, item) in enumerate(entries):
            planned.append((row, item, None if results is None else results[n]))
    return len(rows), planned


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Re-check stored check items with the alignment check (spec §13 A119)."
    )
    parser.add_argument("--course", help="Only this (abstract) course id; default every course.")
    parser.add_argument(
        "--reverify",
        action="store_true",
        help="Re-check every row, not only the never-checked ones (after a check change).",
    )
    parser.add_argument("--apply", action="store_true", help="Write the changes (default: dry run).")
    parser.add_argument("--project", help="With --apply: the Supabase project ref this run writes to.")
    parser.add_argument(
        "--function-mode",
        action="store_true",
        help="Allow SAPLING_MODEL_MODE other than 'real' (deterministic local runs).",
    )
    args = parser.parse_args(argv)

    connected = _project_ref()
    print(f"Project: {connected}")
    if args.apply and args.project != connected:
        print(
            f"Refusing: --apply needs --project {connected} (the connected project); got "
            f"{args.project!r}. Check the env file this run loaded."
        )
        return 2
    mode = model_mode()
    if mode != "real" and not args.function_mode:
        print(
            f"Refusing: SAPLING_MODEL_MODE is {mode!r}, not 'real'. Unset it or pass "
            "--function-mode deliberately."
        )
        return 2

    read, planned = plan(args.course, reverify=args.reverify)
    unchanged: list[str] = []
    rewrites: list[tuple] = []
    retires: list[str] = []
    unchecked = 0
    rejected: Counter[str] = Counter()
    flagged: Counter[str] = Counter()
    for row, item, result in planned:
        if result is None or result.unverified:
            unchecked += 1
        elif result.reject:
            retires.append(item.id)
            rejected[REASON_CODES.get(result.reject, "rejected")] += 1
        elif result.flags:
            rewrites.append((row, item, result))
            flagged.update(result.flags)
        else:
            unchanged.append(item.id)
    print(
        f"  {read} row(s) read; {len(unchanged)} aligned as stored, "
        f"{flagged[RUBRIC_UNASKED_DROPPED]} trimmed, {flagged[CONCEPT_RETAGGED]} re-tagged, "
        f"{len(retires)} to retire, {unchecked} unchecked" + (" — dry run" if not args.apply else "")
    )
    for flag in ALIGNMENT_FLAGS:
        if flagged[flag]:
            print(f"    {flag}: {flagged[flag]}")
    for code, n in sorted(rejected.items()):
        print(f"    retire ({code}): {n}")
    for _, item, result in rewrites:
        if result.concept_key != item.concept_key:
            print(f"    re-tag {item.id}: {item.concept_key} -> {result.concept_key}")
    for item_id in retires:
        print(f"    retire {item_id}")

    failed = written = 0
    if args.apply:
        at = datetime.now(UTC).isoformat()
        if unchanged:
            try:
                written += mark_aligned(unchanged, at=at)
            except Exception as exc:  # noqa: BLE001 — one failed batch is reported, the rest still run
                failed += len(unchanged)
                print(f"  stamp failed for {len(unchanged)} row(s): {type(exc).__name__}")
        for row, item, result in rewrites:
            try:
                apply_item_alignment(row, item, result, at=at)
                written += 1
            except Exception as exc:  # noqa: BLE001
                failed += 1
                print(f"  write failed for {item.id}: {type(exc).__name__}")
        if retires:
            try:
                retire_items_by_id(retires)
                written += len(retires)
            except Exception as exc:  # noqa: BLE001
                failed += len(retires)
                print(f"  retire failed for {len(retires)} row(s): {type(exc).__name__}")
        print(f"Done: {written} row(s) written, {failed} failed, {unchecked} unchecked")
    return 1 if failed or unchecked else 0


if __name__ == "__main__":
    sys.exit(main())
