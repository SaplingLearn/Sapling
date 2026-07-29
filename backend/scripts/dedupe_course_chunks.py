#!/usr/bin/env python3
"""
One-time dedupe: migrate course_chunks document rows to content-hash ids.

Chunk ids used to be sha256(doc_id::index::text), so the same lecture
slides uploaded by N students stored N copies of every chunk.
services/rag_service.py::chunk_id now scopes ids to
sha256(course_id::text); this script rewrites existing rows to that
scheme and collapses duplicates. Catalog rows (category=catalog) use
their own id scheme and are untouched.

For each group of rows sharing chunk_id(course_id, chunk_text), the
winner is the first row (id-ascending) that already has an embedding
(avoids re-embedding); its metadata (doc_id/uploader_id/chunk_index)
carries over. Which legacy row's metadata survives is arbitrary — no
timestamp is consulted — and that is fine: rag_service documents these
columns as non-load-bearing metadata (retrieval reads only course_id +
chunk_text), so the only invariant that matters is keeping an embedding.

Dry-run by default. Run from backend/:
    python scripts/dedupe_course_chunks.py            # preview
    python scripts/dedupe_course_chunks.py --apply    # rewrite rows

Reads .env; for staging run under `dotenv -f .env.staging run -- ...`.
"""
import argparse
import sys
from pathlib import Path

from dotenv import load_dotenv

BASE = Path(__file__).parent.parent
load_dotenv(BASE / ".env")
sys.path.insert(0, str(BASE))

from db.connection import table  # noqa: E402
from services.rag_service import chunk_id  # noqa: E402

PAGE_SIZE = 1000
UPSERT_BATCH = 200
DELETE_BATCH = 50

COLUMNS = (
    "id,course_id,doc_id,uploader_id,chunk_index,chunk_text,chunk_hash,"
    "embedding,category,semester,section_id,school"
)


def fetch_document_rows() -> list[dict]:
    rows: list[dict] = []
    offset = 0
    while True:
        page, total = table("course_chunks").select_with_count(
            COLUMNS,
            filters={"category": "eq.document"},
            order="id.asc",
            limit=PAGE_SIZE,
            offset=offset,
        )
        rows.extend(page)
        offset += len(page)
        if not page or offset >= total:
            return rows


def plan_migration(rows: list[dict]) -> tuple[list[dict], list[str]]:
    """Group rows by content-hash id; return (records to upsert, ids to delete)."""
    groups: dict[str, list[dict]] = {}
    for row in rows:
        groups.setdefault(chunk_id(row["course_id"], row["chunk_text"]), []).append(row)

    upserts: list[dict] = []
    deletes: list[str] = []
    for new_id, members in groups.items():
        winner = next((m for m in members if m.get("embedding")), members[0])
        if winner["id"] != new_id:
            upserts.append({**winner, "id": new_id, "chunk_hash": new_id})
        deletes.extend(m["id"] for m in members if m["id"] != new_id)
    return upserts, deletes


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Collapse duplicate course_chunks rows onto content-hash ids."
    )
    parser.add_argument("--apply", action="store_true", help="Write changes (default: preview).")
    args = parser.parse_args()

    rows = fetch_document_rows()
    upserts, deletes = plan_migration(rows)
    unique = len(rows) - len(deletes)
    print(
        f"{len(rows)} document rows -> {unique} unique chunks "
        f"({len(deletes)} duplicate/legacy-id rows to remove, {len(upserts)} rows to rewrite)."
    )

    if not args.apply:
        print("Dry run — re-run with --apply to write.")
        return

    # Upsert winners under their new ids first, then delete stale ids, so an
    # interrupted run never leaves a chunk with no surviving row.
    db = table("course_chunks")
    for i in range(0, len(upserts), UPSERT_BATCH):
        db.upsert(upserts[i : i + UPSERT_BATCH], on_conflict="id")
    for i in range(0, len(deletes), DELETE_BATCH):
        batch = deletes[i : i + DELETE_BATCH]
        db.delete(filters={"id": f"in.({','.join(batch)})"})
    print(f"Done: rewrote {len(upserts)} rows, deleted {len(deletes)}.")


if __name__ == "__main__":
    main()
