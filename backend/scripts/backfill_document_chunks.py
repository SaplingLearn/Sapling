"""
One-time backfill: chunk and index existing documents into course_chunks.

Architecture note (verified against the live schema before writing this
script — see .superpowers/sdd/task-5-report.md for the full grep trail):

  - The `documents` table has no `file_path` / `uploader_id` columns, and
    no Supabase Storage bucket ever holds the raw uploaded bytes. Files
    are read into memory by `POST /api/documents/upload`
    (`routes/documents.py::upload_document`), extracted synchronously via
    `services.extraction_service.extract_text_from_file`, and the raw
    bytes are discarded once the request completes. There is nothing to
    download and re-extract for documents that predate migration 0030.
  - Consequently this script does NOT re-run OCR/extraction. Its actual
    job is: chunk + index every document whose `extracted_text` column
    is already populated (encrypted) but that has no rows yet in
    `course_chunks` — e.g. documents processed before the chunker/
    index_document_chunks wiring landed (Task 4), or where the
    background indexing step previously failed or was skipped.
  - Documents with `extracted_text IS NULL` have no recoverable source
    text at all (their original file was never persisted anywhere). The
    script reports their count and skips them; the only way to backfill
    those is to have the student re-upload the file.

Run from backend/:
    python scripts/backfill_document_chunks.py              # staging
    python scripts/backfill_document_chunks.py --dry-run    # preview only
"""
import argparse
import sys
import time
from pathlib import Path

from dotenv import load_dotenv

BASE = Path(__file__).parent.parent
load_dotenv(BASE / ".env.staging")

sys.path.insert(0, str(BASE))

from db.connection import table  # noqa: E402
from services.chunker import chunk_for_category  # noqa: E402
from services.rag_service import _embed_document, index_document_chunks  # noqa: E402
from services.encryption import decrypt_if_present  # noqa: E402

MIN_COURSE_RELEVANCE = 0.35


def _get_course_code(course_id: str) -> str:
    """Resolve a Sapling course UUID to its BU course_code, used as the
    course_chunks partition key (matches routes/documents.py::_index_document_chunks).
    """
    rows = table("courses").select("course_code", filters={"id": f"eq.{course_id}"}, limit=1)
    return (rows[0].get("course_code") or course_id) if rows else course_id


def _already_indexed(doc_id: str) -> bool:
    rows = table("course_chunks").select("id", filters={"doc_id": f"eq.{doc_id}"}, limit=1)
    return bool(rows)


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Backfill course_chunks for existing documents that already have "
            "extracted_text but were never chunked/indexed. Documents missing "
            "extracted_text are reported and skipped (no source file is "
            "recoverable for them — see module docstring)."
        )
    )
    parser.add_argument("--dry-run", action="store_true", help="Preview only, no writes.")
    args = parser.parse_args()

    missing = table("documents").select(
        "id",
        filters={"extracted_text": "is.null", "deleted_at": "is.null"},
    )
    docs = table("documents").select(
        "id,file_name,user_id,offering_id,extracted_text,category",
        filters={"extracted_text": "not.is.null", "deleted_at": "is.null"},
    )

    print(f"Found {len(docs)} documents with extracted_text, {len(missing)} without.")
    if missing:
        print(
            f"  {len(missing)} document(s) have no extracted_text and no stored "
            f"source file to re-extract from (Supabase Storage holds no raw "
            f"document bytes; the original file is discarded after upload). "
            f"These cannot be backfilled here and are skipped."
        )

    ok = skip = fail = 0
    for doc in docs:
        doc_id = doc["id"]
        filename = doc.get("file_name", "")
        user_id = doc.get("user_id", "")
        offering_id = doc.get("offering_id", "")

        if _already_indexed(doc_id):
            skip += 1
            continue

        off_rows = table("course_offerings").select(
            "course_id", filters={"id": f"eq.{offering_id}"}, limit=1
        )
        if not off_rows:
            print(f"  SKIP {doc_id[:8]} — no offering {offering_id}")
            skip += 1
            continue
        course_code = _get_course_code(off_rows[0]["course_id"])

        extracted = decrypt_if_present(doc.get("extracted_text")) or ""
        print(f"  Processing {doc_id[:8]} ({filename}) -> {course_code} ...", end=" ", flush=True)

        if args.dry_run:
            print("(dry run)")
            continue

        try:
            chunks = chunk_for_category(extracted, doc.get("category") or "other")
            if not chunks:
                print("0 chunks (empty text)")
                ok += 1
                continue

            # Relevance gate: skip docs the live pipeline would have rejected
            # (see routes/documents.py::_index_document_chunks for the source
            # of truth this replicates).
            catalog_rows = table("course_chunks").select(
                "embedding",
                filters={"course_id": f"eq.{course_code}", "category": "eq.catalog"},
                limit=1,
            )
            if catalog_rows and catalog_rows[0].get("embedding"):
                catalog_vec = catalog_rows[0]["embedding"]
                doc_sample_vec = _embed_document(chunks[0])
                dot = sum(a * b for a, b in zip(doc_sample_vec, catalog_vec))
                if dot < MIN_COURSE_RELEVANCE:
                    print(f"SKIP (relevance {dot:.2f})")
                    skip += 1
                    continue

            count = index_document_chunks(course_code, doc_id, user_id, chunks)
            print(f"{count} chunks indexed")
            ok += 1
            time.sleep(1.0)  # stay under embedding quota
        except Exception as e:
            print(f"FAIL: {e}")
            fail += 1

    print(
        f"\nDone: {ok} ok, {skip} skipped (already indexed / no offering), "
        f"{fail} failed, {len(missing)} unrecoverable (no extracted_text)"
    )


if __name__ == "__main__":
    main()
