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
    - fails    → plaintext (or corrupted); encrypt and write

This is idempotent: re-running it after a successful run is a no-op
(every cell is already valid ciphertext, so every check skips).

Usage
-----
Dry run (default — counts only, no writes):
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
import sys
from typing import Any, Callable

from db.connection import table
from services.encryption import (
    decrypt,
    decrypt_json,
    encrypt,
    encrypt_if_present,
    encrypt_json,
)


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


def _is_already_encrypted_json(value: Any) -> bool:
    """Same as above but for JSON columns. After the schema migration
    these are TEXT, so a legacy JSONB row is now a JSON string."""
    if value is None or not isinstance(value, str):
        return False
    try:
        decrypt_json(value)
        return True
    except Exception:
        return False


# ── Backfill primitives ───────────────────────────────────────────────────────

def _encrypt_text_column(
    table_name: str,
    columns: list[str],
    *,
    pk: str = "id",
    apply: bool,
) -> dict[str, int]:
    """Encrypt one or more TEXT columns on a table. Returns counts."""
    rows = table(table_name).select(",".join([pk, *columns])) or []
    counts = {col: 0 for col in columns}
    counts["scanned"] = len(rows)
    for row in rows:
        update: dict[str, str] = {}
        for col in columns:
            v = row.get(col)
            if v is None:
                continue
            if _is_already_encrypted(v):
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
    rows = table(table_name).select(",".join([pk, *columns])) or []
    counts = {col: 0 for col in columns}
    counts["scanned"] = len(rows)
    for row in rows:
        update: dict[str, str] = {}
        for col in columns:
            v = row.get(col)
            if v is None or not isinstance(v, str) or v == "":
                continue
            if _is_already_encrypted(v):
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
    import json as _json

    rows = table(table_name).select(f"{pk},{column}") or []
    counts = {column: 0, "scanned": len(rows)}
    for row in rows:
        v = row.get(column)
        if v is None:
            continue
        if _is_already_encrypted_json(v):
            continue
        # Legacy row: parse the JSON text, then encrypt the parsed object
        # so the on-disk shape matches what new writes produce.
        if isinstance(v, str):
            try:
                parsed = _json.loads(v)
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
    rows = table(table_name).select(",".join([pk, *columns])) or []
    counts = {col: 0 for col in columns}
    counts["scanned"] = len(rows)
    for row in rows:
        update: dict[str, str] = {}
        for col in columns:
            v = row.get(col)
            if v is None:
                continue
            if _is_already_encrypted(v):
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
    return _encrypt_text_column(
        "users",
        ["name", "first_name", "last_name", "email", "bio", "location"],
        pk="id",
        apply=apply,
    )


def backfill_user_settings(apply: bool) -> dict:
    return _encrypt_text_column(
        "user_settings",
        ["bio", "location"],
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


RUNNERS: dict[str, Callable[[bool], dict]] = {
    "users": backfill_users,
    "user_settings": backfill_user_settings,
    "oauth_tokens": backfill_oauth_tokens,
    "assignments": backfill_assignments,
    "documents": backfill_documents,
    "sessions": backfill_sessions,
    "messages": backfill_messages,
    "room_messages": backfill_room_messages,
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

    grand_total = 0
    for name in targets:
        print(f"── {name} ──")
        try:
            counts = RUNNERS[name](apply=args.apply)
        except Exception as e:
            print(f"  FAILED: {e}")
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
    return 0


if __name__ == "__main__":
    sys.exit(main())
