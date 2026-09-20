#!/usr/bin/env python3
"""
One-time backfill: encrypt `course_chunks.chunk_text` in place (ADR 0025, #484).

Run this IMMEDIATELY AFTER deploying the code, not before. There is no schema
change to sequence against — `chunk_text` is already TEXT — so the ordering
constraint is purely about which code is reading the column:

  * Backfilling FIRST, while the old code is live, would serve base64 straight
    into tutor and quiz prompts. That is the one genuinely bad outcome here.
  * Deploying first is safe but noisy: `decrypt_if_present` returns the raw
    value when it cannot decrypt, so every plaintext row still reads correctly
    and logs a WARNING while it does. That warning is the correct signal during
    the window, and a real alarm once this has run — which is the whole reason
    ADR 0025 encrypts catalog rows too, so "chunk_text is always ciphertext" is
    one invariant the `ciphertext` oracle can assert.

Idempotent. A row whose value already decrypts is skipped, so a second run is a
no-op and an interrupted run can simply be re-run. Ids are NOT touched: they are
content hashes over the PLAINTEXT and must stay that way (AES-GCM draws a fresh
nonce per call, so a ciphertext-derived id would change on every write).

Dry-run by default. Run from backend/:
    python scripts/backfill_encrypt_chunk_text.py            # preview
    python scripts/backfill_encrypt_chunk_text.py --apply

Reads .env; for staging/prod run under `dotenv -f .env.staging run -- ...` and
check the project ref first — this rewrites every row in the table.
"""
import argparse
import sys
from pathlib import Path

from dotenv import load_dotenv

BASE = Path(__file__).parent.parent
load_dotenv(BASE / ".env")
sys.path.insert(0, str(BASE))

from db.connection import page_all, table  # noqa: E402
from services.encryption import decrypt, encrypt  # noqa: E402

#: `merge-duplicates` updates only the columns present in the payload, and
#: `course_id` rides along because it is NOT NULL (the INSERT branch never
#: fires — every id already exists — but PostgREST validates the payload).
WRITE_BATCH = 100


def _is_ciphertext(value: str) -> bool:
    """True when `value` already decrypts.

    Uses `decrypt` rather than `decrypt_if_present` on purpose: the latter logs
    a WARNING on every failure, and over a table of thousands of
    not-yet-encrypted rows that is thousands of lines saying only "this backfill
    has work to do". A plaintext string surviving base64 decoding AND AES-GCM's
    authentication tag is not a case worth engineering around.
    """
    try:
        decrypt(value)
        return True
    except Exception:
        return False


def _rows():
    """Every row, paged through `page_all` rather than a hand-rolled loop.

    `page_all` is the repo's paging contract and it exists because three
    hand-rolled copies shared the same termination bug; a fourth here would be
    the fourth chance at it. `order="id"` is a total order (primary key), and
    encrypting `chunk_text` does not move a row's position in it, so paging by
    offset while rewriting is stable.
    """
    return page_all(
        table("course_chunks"), "id,course_id,chunk_text", order="id",
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Encrypt course_chunks.chunk_text in place (idempotent)."
    )
    parser.add_argument("--dry-run", action="store_true", default=True)
    parser.add_argument("--apply", dest="dry_run", action="store_false")
    args = parser.parse_args()

    seen = already = pending = written = 0
    todo: list[dict] = []
    for row in _rows():
        seen += 1
        text = row.get("chunk_text")
        if text is None:
            continue
        if _is_ciphertext(text):
            already += 1
            continue
        pending += 1
        todo.append({
            "id": row["id"],
            "course_id": row["course_id"],
            "chunk_text": encrypt(text),
        })
        if not args.dry_run and len(todo) >= WRITE_BATCH:
            table("course_chunks").upsert(todo[:WRITE_BATCH], on_conflict="id")
            written += len(todo[:WRITE_BATCH])
            todo = todo[WRITE_BATCH:]
            print(f"  encrypted {written:,}…", flush=True)

    if not args.dry_run and todo:
        table("course_chunks").upsert(todo, on_conflict="id")
        written += len(todo)

    print(
        f"\n{seen:,} row(s): {already:,} already ciphertext, "
        f"{pending:,} to encrypt."
    )
    if args.dry_run:
        print("(dry run — nothing written; pass --apply)")
    else:
        print(f"encrypted {written:,} row(s).")


if __name__ == "__main__":
    main()
