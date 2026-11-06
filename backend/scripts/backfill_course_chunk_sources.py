"""
Fill course_chunk_sources from each document's own text, then withdraw the
chunks of every document that was deleted before #758.

Run AFTER `20261106055333_state_machines_audit.sql`. That migration seeds the
ledger from `course_chunks.doc_id`, which names only the LAST writer of a
deduped row, so:

  * a live document whose chunks deduped into rows another upload wrote last
    has no source row — and if that other upload is deleted, retrieval
    (correctly, by its rule) withholds text this live document still has;
  * a document deleted before #758 still has its contributor rows and, where
    nothing else holds them, its chunks.

Phase 1 (live documents) records every chunk a document's text re-derives to,
so phase 2 can tell what something else still holds. Phase 2 (deleted
documents) records theirs too, then runs the same withdrawal the delete route
now runs (`chunk_visibility.withdraw_document_chunks`). Order matters: phase 2
before phase 1 would withdraw shared text a live document still produces.

Ids are re-derived exactly as scripts/backfill_document_shareability.py does:
both chunkers (the category is user-editable and the chunker may have changed
since the row was written), both namespaces (shared, and private under the
uploader). Only ids that exist in course_chunks are recorded. No embedding, no
classification. Idempotent: the ledger upserts on its key and the withdrawal
only removes what nothing holds, so a second run changes nothing.

Dry-run by default; the dry run reads everything and writes nothing. Needs the
ENCRYPTION_KEY the database was written under (it decrypts extracted_text — a
wrong key derives ids that match nothing, which records nothing). Run from
backend/:

    python scripts/backfill_course_chunk_sources.py            # preview
    python scripts/backfill_course_chunk_sources.py --apply

For staging/prod run under `dotenv -f .env.<env> run -- ...` and check the
project it prints first.
"""
import argparse
import sys
from pathlib import Path
from urllib.parse import urlparse

from dotenv import load_dotenv

BASE = Path(__file__).parent.parent
load_dotenv(BASE / ".env")
sys.path.insert(0, str(BASE))

from db.connection import REST_URL, page_all, pg_quote_value, table  # noqa: E402
from services.academics import offering_course_id  # noqa: E402
from services.chunk_visibility import (  # noqa: E402
    PRIVATE,
    SHARED,
    record_sources,
    withdraw_document_chunks,
)
from services.chunker import chunk_document, chunk_prose  # noqa: E402
from services.encryption import decrypt  # noqa: E402
from services.rag_service import chunk_id  # noqa: E402

#: Ids per `in.(…)` filter — see chunk_visibility._ID_BATCH.
_ID_BATCH = 50

_COLUMNS = "id,user_id,offering_id,extracted_text"


def _course_code(offering_id: str | None, cache: dict) -> str | None:
    if not offering_id:
        return None
    if offering_id not in cache:
        course_id = offering_course_id(offering_id)
        code = None
        if course_id:
            rows = table("courses").select(
                "course_code", filters={"id": f"eq.{course_id}"}, limit=1,
            )
            code = (rows[0].get("course_code") or course_id) if rows else course_id
        cache[offering_id] = code
    return cache[offering_id]


def derive_ids(text: str, course_code: str, user_id: str) -> list[str]:
    """Every id this text could have been indexed under."""
    ids = set()
    for chunker in (chunk_prose, chunk_document):
        for c in chunker(text):
            ids.add(chunk_id(course_code, c, visibility=SHARED))
            if user_id:
                ids.add(chunk_id(course_code, c, visibility=PRIVATE, uploader_id=user_id))
    return sorted(ids)


def _existing(ids: list[str]) -> list[str]:
    found: list[str] = []
    for i in range(0, len(ids), _ID_BATCH):
        batch = ids[i : i + _ID_BATCH]
        rows = table("course_chunks").select(
            "id",
            filters={"id": f"in.({','.join(pg_quote_value(v) for v in batch)})",
                     "category": "neq.catalog"},
        )
        found.extend(r["id"] for r in rows or [])
    return found


def _located(doc: dict, cache: dict) -> list[str]:
    stored = doc.get("extracted_text")
    code = _course_code(doc.get("offering_id"), cache)
    if not stored or not code:
        return []
    try:
        text = decrypt(stored)
    except Exception:
        print(f"  {doc['id'][:8]} extracted_text does not decrypt under this key — skipped")
        return []
    return _existing(derive_ids(text, code, doc.get("user_id") or ""))


def _docs(*, deleted: bool):
    return page_all(
        table("documents"), _COLUMNS,
        filters={"deleted_at": "not.is.null" if deleted else "is.null"},
        order="id",
    )


def main(argv: list[str] | None = None) -> dict:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--dry-run", action="store_true", default=True)
    parser.add_argument("--apply", dest="dry_run", action="store_false")
    args = parser.parse_args(argv)

    print(f"Project: {urlparse(REST_URL).hostname}")
    cache: dict = {}
    summary = {"live_docs": 0, "live_sources": 0, "deleted_docs": 0,
               "deleted_sources": 0, "chunks_deleted": 0, "contributors_removed": 0,
               "to_private": 0, "withdraw_failed": 0}

    print("\nPhase 1 — live documents: record what each still produces")
    for doc in _docs(deleted=False):
        ids = _located(doc, cache)
        summary["live_docs"] += 1
        summary["live_sources"] += len(ids)
        if ids and not args.dry_run:
            record_sources(ids, doc["id"])

    print("\nPhase 2 — deleted documents: record, then withdraw")
    for doc in _docs(deleted=True):
        ids = _located(doc, cache)
        summary["deleted_docs"] += 1
        summary["deleted_sources"] += len(ids)
        print(f"  {doc['id'][:8]} located {len(ids)} chunk(s)")
        if args.dry_run:
            continue
        if ids:
            record_sources(ids, doc["id"])
        out = withdraw_document_chunks(doc["id"], doc.get("user_id") or "")
        if out.get("failed"):
            summary["withdraw_failed"] += 1
        for key in ("chunks_deleted", "contributors_removed", "to_private"):
            summary[key] += out.get(key, 0)

    mode = "DRY RUN — nothing written; pass --apply" if args.dry_run else "applied"
    print(f"\n{mode}: " + ", ".join(f"{k}={v}" for k, v in summary.items()))
    if summary["withdraw_failed"]:
        print("!! some withdrawals failed (see the log) — re-run; it is idempotent")
    return summary


if __name__ == "__main__":
    main()
