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

That idempotence rests on one thing, so it is CHECKED before anything is
written: `ENCRYPTION_KEY` must be the key this database was encrypted with.
"Already ciphertext" is detected by trying to decrypt, and ciphertext written
under a DIFFERENT key fails to decrypt exactly like plaintext does — so the
wrong key turns "a second run is a no-op" into a silent double-encrypt of the
whole table, after which the live app can decrypt nothing. That is not a remote
hazard here: staging is a separate Supabase project with a different
ENCRYPTION_KEY, and this docstring tells you to point the script at it. The
guard below reads a column that is ALREADY encrypted in every environment
(`users.email`) and aborts unless this key can decrypt it.

Dry-run by default. Run from backend/:
    python scripts/backfill_encrypt_chunk_text.py            # preview
    python scripts/backfill_encrypt_chunk_text.py --apply

Reads .env; for staging/prod run under `dotenv -f .env.staging run -- ...` and
check the project ref first — this rewrites every row in the table.
"""
import argparse
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import httpx
from dotenv import load_dotenv

BASE = Path(__file__).parent.parent
load_dotenv(BASE / ".env")
sys.path.insert(0, str(BASE))

from db.connection import page_all, table  # noqa: E402
from services.encryption import decrypt, encrypt  # noqa: E402

#: Rows encrypted per round. Each row is its own PATCH (see `_write`), issued
#: concurrently across WRITE_WORKERS threads; the batch only bounds how much
#: ciphertext is held in memory and how often progress prints.
WRITE_BATCH = 25
WRITE_WORKERS = 8


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


#: A column encrypted in every environment since the 0024 identity split, used
#: purely to prove the key matches the database. Nothing is written to it.
_KEY_WITNESS = ("users", "email")


def _assert_key_matches_database() -> None:
    """Abort unless ENCRYPTION_KEY can decrypt something already encrypted here.

    Distinguishes the two states `_is_ciphertext` cannot tell apart: a column
    not yet encrypted (this script's job) versus a column encrypted under
    another key (an env mix-up, or a rotation between runs). Without this, the
    second looks exactly like the first and the script re-encrypts ciphertext.
    """
    table_name, column = _KEY_WITNESS
    rows = table(table_name).select(
        column, filters={column: "not.is.null"}, limit=20,
    )
    values = [r[column] for r in rows or [] if r.get(column)]
    if not values:
        print(
            f"  ! no {table_name}.{column} rows to verify ENCRYPTION_KEY "
            "against — proceeding, but confirm the key matches this database"
        )
        return
    if not any(_is_ciphertext(v) for v in values):
        sys.exit(
            f"REFUSING to run: none of {len(values)} {table_name}.{column} "
            "values decrypt with this ENCRYPTION_KEY, so the key does not "
            "match this database. Encrypting course_chunks now would write "
            "rows the live app cannot read, and a re-run would double-encrypt "
            "them. Check which .env is loaded against which SUPABASE_URL."
        )
    print(f"  key verified against {table_name}.{column}")


def _rows():
    """Every row, paged through `page_all` rather than a hand-rolled loop.

    `page_all` is the repo's paging contract and it exists because three
    hand-rolled copies shared the same termination bug; a fourth here would be
    the fourth chance at it. `order="id"` is a total order (primary key), and
    encrypting `chunk_text` does not move a row's position in it, so paging by
    offset while rewriting is stable.
    """
    return page_all(
        table("course_chunks"), "id,chunk_text", order="id",
    )


def _patch_one(row: dict) -> None:
    table("course_chunks").update(
        {"chunk_text": row["chunk_text"]},
        {"id": f"eq.{row['id']}"},
        prefer_return_minimal=True,
    )


def _write(batch: list[dict]) -> None:
    """Write one batch of new `chunk_text` values — UPDATE-ONLY, one row each.

    Deliberately not an upsert. An upsert is `INSERT ... ON CONFLICT DO
    UPDATE`: once its payload satisfies every NOT NULL column, a row deleted
    between this script reading it and writing it (a withdrawal by the
    shareability backfill, a re-index, the sweeper) would be INSERTED back —
    with `visibility` defaulting to 'shared', no doc, no embedding and no
    contributor rows, i.e. withdrawn student text in the class pool that no
    one can withdraw again (#630). A PATCH filtered on the id matches nothing
    for a deleted row, so it can only ever rewrite what still exists. One row
    per statement also keeps each far inside PostgREST's 8s statement_timeout
    (100-row upserts timed out on prod, where every rewritten row re-enters
    two HNSW indexes).

    On failure, exits with PostgREST's own error body — `raise_for_status`
    alone reports only the status line. Every row is independent and already-
    encrypted rows are skipped on a re-run, so a re-run resumes cleanly.
    """
    try:
        with ThreadPoolExecutor(max_workers=WRITE_WORKERS) as pool:
            list(pool.map(_patch_one, batch))
    except httpx.HTTPStatusError as exc:
        sys.exit(
            f"update failed ({exc.response.status_code}) in a batch of "
            f"{len(batch)} starting at id={batch[0]['id']!r}: "
            f"{exc.response.text[:500]}\n"
            "Rows before it are committed; re-run to resume."
        )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Encrypt course_chunks.chunk_text in place (idempotent)."
    )
    parser.add_argument("--dry-run", action="store_true", default=True)
    parser.add_argument("--apply", dest="dry_run", action="store_false")
    parser.add_argument(
        "--batch-size", type=int, default=WRITE_BATCH,
        help=f"rows per round of concurrent updates (default {WRITE_BATCH})",
    )
    args = parser.parse_args()
    batch_size = max(1, args.batch_size)

    _assert_key_matches_database()

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
        todo.append({"id": row["id"], "chunk_text": encrypt(text)})
        if not args.dry_run and len(todo) >= batch_size:
            _write(todo[:batch_size])
            written += len(todo[:batch_size])
            todo = todo[batch_size:]
            if written % 500 < batch_size:
                print(f"  encrypted {written:,}…", flush=True)

    if not args.dry_run and todo:
        _write(todo)
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
