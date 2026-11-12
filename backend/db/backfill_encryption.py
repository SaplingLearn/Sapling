"""One-shot backfill: re-encrypt every legacy plaintext row across the
columns wired for AES-256-GCM column-level encryption.

Why this exists
---------------
The decrypt helpers (services.encryption.decrypt_if_present /
decrypt_json / decrypt_numeric) silently fall back to the raw value when
a column hasn't been encrypted yet. That keeps the app working through
the rollout, but every legacy read logs a warning. This script walks
every encrypted column, detects which rows are still plaintext, and
rewrites them through the encrypt helpers. After it finishes once,
fallback warnings should stop.

Detection rule
--------------
For every cell, try `decrypt(value)`:
    - succeeds → already encrypted, skip
    - fails, but the value has the SHAPE of our ciphertext (base64 of at least
      a nonce and a tag) → skip and report it. That is a cell written under
      another ENCRYPTION_KEY; encrypting it again would bury it one layer
      deeper, where the read helpers hand ciphertext back as the value.
    - fails otherwise → plaintext; encrypt and write

Before anything is read, the key is checked against the database's key canary
(services/encryption_canary.py, read-only here): a script holding the wrong
key would see EVERY cell as "fails to decrypt" and stops instead.

Every table is read in pages. One unpaged select returns at most PostgREST's
1,000 rows, and a second run would then see only that already-encrypted page
and report nothing left to do.

This is idempotent: re-running it after a successful run is a no-op
(every cell is already valid ciphertext, so every check skips). The rule is
the same for every column shape, JSON included: a cell that decrypts is
encrypted, whatever the plaintext inside it turns out to be.

Usage
-----
Dry run (default — counts only, no writes). Always read its counts before
an --apply: a detection fix can make one run touch far more rows than the
last one did.
    python -m db.backfill_encryption

Apply (writes to Supabase):
    python -m db.backfill_encryption --apply

Per-table only (useful for staged rollouts):
    python -m db.backfill_encryption --apply --table users
    python -m db.backfill_encryption --apply --table assignments

Run from the `backend/` directory with the venv active so config + the
encryption module + the supabase client all resolve correctly.
"""
from __future__ import annotations

import argparse
import base64
import binascii
import json
import sys
from collections import Counter
from collections.abc import Iterator
from typing import Any, Callable

from db.connection import page_all, table
from services.encryption import (
    decrypt,
    encrypt,
    encrypt_if_present,
    encrypt_json,
)
from services.encryption_canary import EncryptionKeyMismatch, verify_encryption_key


# ── Detection ─────────────────────────────────────────────────────────────────

def _is_already_encrypted(value: Any) -> bool:
    """True if `value` is a valid base64 AES-GCM ciphertext under the
    current ENCRYPTION_KEY. False for None, non-strings, plaintext,
    or ciphertext under a different key."""
    if value is None or not isinstance(value, str):
        return False
    try:
        decrypt(value)
        return True
    except Exception:
        return False


# AES-GCM output is nonce (12 bytes) + ciphertext + tag (16 bytes).
_MIN_CIPHERTEXT_BYTES = 12 + 16

#: Cells that look like ciphertext but do not open with this key, per
#: (table, column). Never written; `main` reports them.
UNDECRYPTABLE: Counter[tuple[str, str]] = Counter()


def _looks_like_ciphertext(value: Any) -> bool:
    """True if `value` has the shape `encrypt` produces: strict base64 that
    decodes to at least a nonce and a tag. Ordinary plaintext (spaces,
    punctuation, short values) never does."""
    if not isinstance(value, str):
        return False
    try:
        raw = base64.b64decode(value, validate=True)
    except (binascii.Error, ValueError):
        return False
    return len(raw) >= _MIN_CIPHERTEXT_BYTES


def _needs_encryption(table_name: str, column: str, value: Any) -> bool:
    """Whether the backfill should encrypt this cell.

    False for a cell that already decrypts, and for one that looks like
    ciphertext under ANOTHER key: that one is counted in UNDECRYPTABLE and left
    exactly as it is.
    """
    if _is_already_encrypted(value):
        return False
    if _looks_like_ciphertext(value):
        UNDECRYPTABLE[(table_name, column)] += 1
        return False
    return True


def _rows(table_name: str, columns: str, pk: str) -> Iterator[dict]:
    """Every row of the table, paged in primary-key order. The updates this
    script makes never touch the key, so the paging stays stable under them."""
    return page_all(table(table_name), columns, order=pk)


# ── Backfill primitives ───────────────────────────────────────────────────────

def _encrypt_text_column(
    table_name: str,
    columns: list[str],
    *,
    pk: str = "id",
    apply: bool,
) -> dict[str, int]:
    """Encrypt one or more TEXT columns on a table. Returns counts."""
    counts = {col: 0 for col in columns}
    counts["scanned"] = 0
    for row in _rows(table_name, ",".join([pk, *columns]), pk):
        counts["scanned"] += 1
        update: dict[str, str] = {}
        for col in columns:
            v = row.get(col)
            if v is None:
                continue
            if not _needs_encryption(table_name, col, v):
                continue
            update[col] = encrypt_if_present(v)
            counts[col] += 1
        if update and apply:
            table(table_name).update(
                update, filters={pk: f"eq.{row[pk]}"}
            )
    return counts


def _encrypt_required_text_column(
    table_name: str,
    columns: list[str],
    *,
    pk: str,
    apply: bool,
) -> dict[str, int]:
    """Encrypt columns that store a string that must always be present
    (no None passthrough). Used for OAuth tokens."""
    counts = {col: 0 for col in columns}
    counts["scanned"] = 0
    for row in _rows(table_name, ",".join([pk, *columns]), pk):
        counts["scanned"] += 1
        update: dict[str, str] = {}
        for col in columns:
            v = row.get(col)
            if v is None or not isinstance(v, str) or v == "":
                continue
            if not _needs_encryption(table_name, col, v):
                continue
            update[col] = encrypt(v)
            counts[col] += 1
        if update and apply:
            table(table_name).update(
                update, filters={pk: f"eq.{row[pk]}"}
            )
    return counts


def _encrypt_json_column(
    table_name: str,
    column: str,
    *,
    pk: str = "id",
    apply: bool,
) -> dict[str, int]:
    """Encrypt a JSON-shaped TEXT column (was JSONB before the schema
    migration, now stores a JSON string)."""
    counts = {column: 0, "scanned": 0}
    for row in _rows(table_name, f"{pk},{column}", pk):
        counts["scanned"] += 1
        v = row.get(column)
        if v is None:
            continue
        # Decrypts = encrypted, and nothing more: do NOT also require the
        # plaintext to parse as JSON (a corrupt row is stored as encrypt(raw)
        # below, so that check would re-encrypt it on every later run), and do
        # NOT use decrypt_json (it falls back to json.loads on plaintext, so
        # every legacy JSON-text row would look encrypted and be skipped).
        if not _needs_encryption(table_name, column, v):
            continue
        # Legacy row: parse the JSON text, then encrypt the parsed object
        # so the on-disk shape matches what new writes produce.
        if isinstance(v, str):
            try:
                parsed = json.loads(v)
            except Exception:
                # Corrupt JSON; encrypt the raw string so it still
                # round-trips through decrypt_if_present.
                if apply:
                    table(table_name).update(
                        {column: encrypt(v)}, filters={pk: f"eq.{row[pk]}"}
                    )
                counts[column] += 1
                continue
        else:
            parsed = v
        if apply:
            table(table_name).update(
                {column: encrypt_json(parsed)}, filters={pk: f"eq.{row[pk]}"}
            )
        counts[column] += 1
    return counts


def _encrypt_numeric_column(
    table_name: str,
    columns: list[str],
    *,
    pk: str = "id",
    apply: bool,
) -> dict[str, int]:
    """Encrypt former-NUMERIC columns now stored as TEXT (e.g. points)."""
    counts = {col: 0 for col in columns}
    counts["scanned"] = 0
    for row in _rows(table_name, ",".join([pk, *columns]), pk):
        counts["scanned"] += 1
        update: dict[str, str] = {}
        for col in columns:
            v = row.get(col)
            if v is None:
                continue
            if not _needs_encryption(table_name, col, v):
                continue
            # Legacy plaintext — could be a float, a numeric string after
            # the ::TEXT cast, or already a stringified number.
            update[col] = encrypt(str(v))
            counts[col] += 1
        if update and apply:
            table(table_name).update(
                update, filters={pk: f"eq.{row[pk]}"}
            )
    return counts


# ── Per-table runners ─────────────────────────────────────────────────────────

def backfill_users(apply: bool) -> dict:
    # Only `email` is left on `users`: the 0024 identity split moved the
    # profile fields to `user_profiles` and dropped them here.
    return _encrypt_text_column("users", ["email"], pk="id", apply=apply)


def backfill_user_profiles(apply: bool) -> dict:
    return _encrypt_text_column(
        "user_profiles",
        ["name", "first_name", "last_name", "bio", "location"],
        pk="user_id",
        apply=apply,
    )


def backfill_oauth_tokens(apply: bool) -> dict:
    return _encrypt_required_text_column(
        "oauth_tokens",
        ["access_token", "refresh_token"],
        pk="user_id",
        apply=apply,
    )


def backfill_assignments(apply: bool) -> dict:
    text_counts = _encrypt_text_column(
        "assignments", ["notes"], pk="id", apply=apply
    )
    numeric_counts = _encrypt_numeric_column(
        "assignments", ["points_possible", "points_earned"], pk="id", apply=apply
    )
    # Merge — both helpers reported a "scanned" count for the same table;
    # they should be equal, so just keep one.
    return {
        "scanned": text_counts["scanned"],
        "notes": text_counts["notes"],
        "points_possible": numeric_counts["points_possible"],
        "points_earned": numeric_counts["points_earned"],
    }


def backfill_documents(apply: bool) -> dict:
    text = _encrypt_text_column("documents", ["summary"], pk="id", apply=apply)
    json_ = _encrypt_json_column("documents", "concept_notes", pk="id", apply=apply)
    return {
        "scanned": text["scanned"],
        "summary": text["summary"],
        "concept_notes": json_["concept_notes"],
    }


def backfill_sessions(apply: bool) -> dict:
    return _encrypt_json_column("sessions", "summary_json", pk="id", apply=apply)


def backfill_messages(apply: bool) -> dict:
    return _encrypt_text_column("messages", ["content"], pk="id", apply=apply)


def backfill_room_messages(apply: bool) -> dict:
    return _encrypt_text_column("room_messages", ["text"], pk="id", apply=apply)


def backfill_feedback(apply: bool) -> dict:
    return _encrypt_text_column("feedback", ["comment", "topic"], pk="id", apply=apply)


def backfill_issue_reports(apply: bool) -> dict:
    return _encrypt_text_column(
        "issue_reports", ["topic", "description"], pk="id", apply=apply
    )


def backfill_quiz_attempts(apply: bool) -> dict:
    q = _encrypt_json_column("quiz_attempts", "questions_json", pk="id", apply=apply)
    a = _encrypt_json_column("quiz_attempts", "answers_json", pk="id", apply=apply)
    return {
        "scanned": q["scanned"],
        "questions_json": q["questions_json"],
        "answers_json": a["answers_json"],
    }


def backfill_quiz_context(apply: bool) -> dict:
    return _encrypt_json_column("quiz_context", "context_json", pk="id", apply=apply)


def backfill_flashcards(apply: bool) -> dict:
    return _encrypt_text_column("flashcards", ["front", "back"], pk="id", apply=apply)


def backfill_study_guides(apply: bool) -> dict:
    return _encrypt_json_column("study_guides", "content", pk="id", apply=apply)


def backfill_room_summaries(apply: bool) -> dict:
    return _encrypt_text_column("room_summaries", ["summary"], pk="room_id", apply=apply)


RUNNERS: dict[str, Callable[[bool], dict]] = {
    "users": backfill_users,
    "user_profiles": backfill_user_profiles,
    "oauth_tokens": backfill_oauth_tokens,
    "assignments": backfill_assignments,
    "documents": backfill_documents,
    "sessions": backfill_sessions,
    "messages": backfill_messages,
    "room_messages": backfill_room_messages,
    "feedback": backfill_feedback,
    "issue_reports": backfill_issue_reports,
    "quiz_attempts": backfill_quiz_attempts,
    "quiz_context": backfill_quiz_context,
    "flashcards": backfill_flashcards,
    "study_guides": backfill_study_guides,
    "room_summaries": backfill_room_summaries,
}


# ── Entry point ───────────────────────────────────────────────────────────────

def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.strip().splitlines()[0])
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Actually write changes. Without this flag, prints counts only.",
    )
    parser.add_argument(
        "--table",
        choices=sorted(RUNNERS.keys()),
        action="append",
        help="Restrict to one or more tables. Repeatable. Default: all.",
    )
    args = parser.parse_args()
    targets = args.table or list(RUNNERS.keys())

    mode = "APPLY (writing)" if args.apply else "DRY RUN (no writes)"
    print(f"Backfill mode: {mode}")
    print(f"Tables: {', '.join(targets)}")
    print()

    # With the wrong key every cell fails to decrypt, which is exactly what
    # legacy plaintext looks like. seed=False: this script must never write the
    # canary itself (a wrong key would then lock the real backend out).
    try:
        if verify_encryption_key(seed=False) == "skipped":
            print("WARNING: this database has no readable key canary, so the key could not be")
            print("         confirmed. Check SUPABASE_URL and ENCRYPTION_KEY are the same environment's.")
            print()
    except EncryptionKeyMismatch as e:
        print(f"REFUSING to run: {e}")
        return 2

    UNDECRYPTABLE.clear()
    grand_total = 0
    failed: list[str] = []
    for name in targets:
        print(f"── {name} ──")
        try:
            counts = RUNNERS[name](apply=args.apply)
        except Exception as e:
            print(f"  FAILED: {e}")
            failed.append(name)
            continue
        scanned = counts.pop("scanned", 0)
        print(f"  scanned: {scanned} rows")
        for col, n in counts.items():
            label = "encrypted" if args.apply else "would encrypt"
            print(f"  {col}: {label} {n}")
            grand_total += n
        print()

    verb = "Encrypted" if args.apply else "Would encrypt"
    print(f"{verb} {grand_total} cells total.")
    if not args.apply:
        print("Re-run with --apply to write.")
    if UNDECRYPTABLE:
        print()
        print("Left untouched: cells that look like ciphertext but do not open with this key")
        print("(written under another ENCRYPTION_KEY, or damaged). Look at these by hand:")
        for (tbl, col), n in sorted(UNDECRYPTABLE.items()):
            print(f"  {tbl}.{col}: {n}")
    if failed:
        # A table that failed was not backfilled, so the run is not done: say
        # so in the exit code too. The dropped-column runners failed on every
        # run for months behind an exit 0.
        print()
        print(f"FAILED tables (not backfilled): {', '.join(failed)}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
