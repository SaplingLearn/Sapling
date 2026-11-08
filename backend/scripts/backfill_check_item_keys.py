#!/usr/bin/env python3
"""Solve-verify stored check items' answer keys (learning loop, spec §13 A124).

New check items are key-checked before they are stored
(services/check_item_service.py: a model of another family than the drafter
solves each item blind — from its question, its options under their stored
letters and its source passages, never its key, rubric or reference — and
learning/item_keys.py compares the answer with the key in code). This checks
the rows stored before that existed (`key_checked_at` NULL) and, with
--reverify, every row, through the same agents and the same rules:

- the solve agrees → `canonical_verified` set, an earlier model hold code
  cleared, `key_checked_at` stamped;
- a different answer → `key_disputed`; the passages do not settle one answer →
  `key_unsolved` (lint_flags); the item is HELD — withdrawn from every student
  read until an admin approves it (which confirms the key) or retires it in
  the review queue (/admin/check-items) — unless its key was already confirmed
  (an earlier agreement, an approval, an audit verdict "correct"): a model never
  un-confirms a key, so then the code is only recorded for staff;
- no usable answer, no source passage to solve from, or the check unavailable
  → the item is left untouched and the run exits 1.

Never deletes anything: a disputed item is flagged and held, and staff decide.
An item a human audit found wrong or ambiguous is skipped (a model never
overrules a human). Evidence is never touched.

The passages are the item's own sources: every document it cites
(`source_document_ids`), read through the A23 source rule (shared course
material only, its shared chunks) and ranked for its concept as a drafting call
ranks them. Items are solved a few concepts per call (CHECK_ITEM_CONCEPTS_PER_CALL
concepts, at most CHECK_ITEM_SOLVE_MAX_ITEMS items), like drafting calls.

Dry-run by default: runs the check (billed to llm_usage like any run, against
the system actor) and prints what it would write — item ids and codes only,
never item text; writes nothing to check_items. Run from backend/:
    python scripts/backfill_check_item_keys.py [--course <id>] [--reverify]       # preview
    python scripts/backfill_check_item_keys.py [--course <id>] [--reverify] --apply --project <ref>

Reads .env; for staging/prod run under `dotenv -f .env.<env> run -- ...` and
check the `Project:` line it prints first: --apply requires --project naming that
project (exit 2 otherwise, before any read). Refuses (exit 2) when
SAPLING_MODEL_MODE is not 'real' unless --function-mode. Needs the
ENCRYPTION_KEY the rows were written under (item and passage text is decrypted
in memory to solve it) and migration 20261108073631_learning_item_keys.sql
applied. Every row is read and checked before anything is written (a write
moves a row out of the `key_checked_at IS NULL` paging). Exit 1 when any write
failed or any item was left unchecked.
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
from learning.checks import KEY_DISPUTED, KEY_UNSOLVED  # noqa: E402
from learning.params import CHECK_ITEM_CONCEPTS_PER_CALL  # noqa: E402
from services.check_item_service import (  # noqa: E402
    apply_key_check,
    audit_decided,
    check_stored_keys,
    course_concept_names,
    items_to_key_check,
    key_check_passages,
    key_check_update,
)

_LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1", "0.0.0.0", "host.docker.internal"}
_SUPABASE_SUFFIX = ".supabase.co"

# Why an item is left unchecked (codes only — never item text).
_NO_PASSAGES = "no_passages"
_UNAVAILABLE = "unavailable"
_NO_VERDICT = "no_verdict"
_UNREADABLE = "unreadable"
_MC_REASON = "mc_reason"


def _project_ref() -> str:
    """The project SUPABASE_URL points at (scripts/backfill_check_items.py's rule)."""
    host = (urlparse(SUPABASE_URL).hostname or "").lower()
    if not host or host in _LOCAL_HOSTS:
        return "local"
    if host.endswith(_SUPABASE_SUFFIX):
        return host[: -len(_SUPABASE_SUFFIX)].split(".")[0]
    return host


def _passages_for(keys: list[str], passages: dict[str, list[dict]]) -> list[dict]:
    """The union of the concepts' ranked passages, de-duplicated, as an agent
    reads them ({id, text})."""
    out: list[dict] = []
    seen: set = set()
    for key in keys:
        for chunk in passages.get(key) or []:
            pkey = chunk.get("id") or ("fallback", chunk.get("doc_id"), chunk.get("chunk_index"))
            if pkey in seen:
                continue
            seen.add(pkey)
            out.append({"id": chunk.get("id"), "text": chunk.get("chunk_text") or ""})
    return out


def plan(course: str | None, *, reverify: bool) -> tuple[int, list[tuple], Counter]:
    """(rows read, [(item, KeyCheck | None, why-unchecked | None)], skipped
    counts) — reads and solves only, one course at a time."""
    rows = items_to_key_check(course, reverify=reverify)
    skipped: Counter = Counter()
    by_course: dict[str, list] = defaultdict(list)
    for row, item in rows:
        if audit_decided(item):
            skipped["audited"] += 1  # a human found its key wrong or ambiguous
            continue
        by_course[item.course_id].append((row, item))
    planned: list[tuple] = []
    for course_id, entries in sorted(by_course.items()):
        names = course_concept_names(course_id)
        passages = key_check_passages([row for row, _ in entries], names)
        by_key: dict[str, list] = defaultdict(list)
        for row, item in entries:
            if item.format == _MC_REASON and not (item.options and item.correct_option):
                planned.append((item, None, _UNREADABLE))
            elif not passages.get(item.concept_key):
                planned.append((item, None, _NO_PASSAGES))
            else:
                by_key[item.concept_key].append(item)
        keys = sorted(by_key)
        for start in range(0, len(keys), CHECK_ITEM_CONCEPTS_PER_CALL):
            batch_keys = keys[start : start + CHECK_ITEM_CONCEPTS_PER_CALL]
            items = [item for key in batch_keys for item in by_key[key]]
            checks = check_stored_keys(course_id, items, _passages_for(batch_keys, passages))
            for n, item in enumerate(items):
                if checks is None:
                    planned.append((item, None, _UNAVAILABLE))
                elif checks[n].unverified:
                    planned.append((item, None, _NO_VERDICT))
                else:
                    planned.append((item, checks[n], None))
    return len(rows), planned, skipped


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Solve-verify stored check items' answer keys (spec §13 A124)."
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

    read, planned, skipped = plan(args.course, reverify=args.reverify)
    at = datetime.now(UTC).isoformat()
    writes: list[tuple] = []
    unchecked: Counter = Counter()
    verified = 0
    held: Counter = Counter()
    recorded: Counter = Counter()  # a dispute of a key already confirmed: recorded, not held
    for item, check, why in planned:
        if check is None:
            unchecked[why] += 1
            continue
        writes.append((item, key_check_update(item, check, at=at)))
        if check.verified:
            verified += 1
        elif item.canonical_verified:
            recorded[check.flag] += 1
        else:
            held[check.flag] += 1
    print(
        f"  {read} row(s) read; {verified} verified, {sum(held.values())} to hold, "
        f"{sum(recorded.values())} dispute(s) of a confirmed key recorded, "
        f"{sum(unchecked.values())} unchecked, {skipped['audited']} skipped (audited)"
        + (" — dry run" if not args.apply else "")
    )
    for flag in (KEY_DISPUTED, KEY_UNSOLVED):
        if held[flag]:
            print(f"    hold ({flag}): {held[flag]}")
        if recorded[flag]:
            print(f"    recorded ({flag}): {recorded[flag]}")
    for why, n in sorted(unchecked.items()):
        print(f"    unchecked ({why}): {n}")
    for item, check, _ in planned:
        if check is not None and not check.verified:
            print(f"    {check.flag} {item.id}")

    failed = written = 0
    if args.apply:
        for item, update in writes:
            try:
                apply_key_check(item, update)
                written += 1
            except Exception as exc:  # noqa: BLE001 — one failed write is reported, the rest still run
                failed += 1
                print(f"  write failed for {item.id}: {type(exc).__name__}")
        print(f"Done: {written} row(s) written, {failed} failed, {sum(unchecked.values())} unchecked")
    return 1 if failed or unchecked else 0


if __name__ == "__main__":
    sys.exit(main())
