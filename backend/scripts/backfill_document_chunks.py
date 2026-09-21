"""
Re-drive documents that have not finished indexing, now (#482).

The indexing sweeper (services/index_sweeper.py) does this on its own every
few minutes, with a bounded attempt budget. This is the operator's version:
it re-drives immediately, and with `force` it also resets the budget of a
document the sweeper has given up on.

It is a thin caller of `services.document_indexing.index_document` — the same
entry point the uploads and the sweeper use — so it cannot drift from them.
It used to reimplement indexing, and drifted twice:

  - Its "already indexed?" check looked for any chunk carrying the document's
    id. On a shared chunk that id names only the LAST uploader (#629), and a
    partially indexed document looked finished. `index_status` answers this.
  - It made its own sharing decision, assuming full confidence whenever a
    shareability was stored, on the premise that a stored value had already
    been gated. It had not: the upload stores the classifier's raw label and
    the confidence floor is applied only at index time. So this script would
    re-index as SHARED a document the live upload had kept private (#630).
    The decision now happens in one place, from the stored confidence.

Documents with no extracted_text have nothing to index from — the original
file is discarded after upload, and Supabase Storage holds no document bytes.
They are reported and skipped, never counted as failures, or every run in an
environment that has any would exit 1 forever.

Run from backend/:
    python scripts/backfill_document_chunks.py              # every unfinished document
    python scripts/backfill_document_chunks.py --dry-run    # list them only
    python scripts/backfill_document_chunks.py --doc <id>   # one document, whatever its status

Loads .env.staging without overriding what is already set, so run it under
`dotenv -f .env.<env> run -- ...` for any other environment, and check the
project it prints first. It embeds, so SAPLING_MODEL_MODE must be 'real' and
GEMINI_API_KEY valid for that environment.
"""
import argparse
import sys
import time
from pathlib import Path
from urllib.parse import urlparse

from dotenv import load_dotenv

BASE = Path(__file__).parent.parent
load_dotenv(BASE / ".env.staging")

sys.path.insert(0, str(BASE))

from db.connection import REST_URL, page_all, table  # noqa: E402
from services.document_indexing import (  # noqa: E402
    FAILED,
    INDEXED,
    INDEXING,
    PARTIAL,
    PENDING,
    SKIPPED,
    index_document,
)

_UNFINISHED = (PENDING, INDEXING, PARTIAL, FAILED)


def _documents(doc: str | None, *, with_text: bool) -> list[dict]:
    filters = {
        "deleted_at": "is.null",
        # Presence is a filter, never a read of the (encrypted) text.
        "extracted_text": "not.is.null" if with_text else "is.null",
    }
    if doc:
        filters["id"] = f"eq.{doc}"
    else:
        filters["index_status"] = f"in.({','.join(_UNFINISHED)})"
    return list(page_all(
        table("documents"), "id,file_name", filters=filters, order="created_at",
    ))


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description="Re-drive documents that have not finished indexing.",
    )
    parser.add_argument("--dry-run", action="store_true", help="List only; index nothing.")
    parser.add_argument("--doc", help="Re-drive this one document, whatever its status.")
    args = parser.parse_args(argv)

    print(f"Project: {urlparse(REST_URL).hostname}")
    targets = _documents(args.doc, with_text=True)
    unrecoverable = _documents(args.doc, with_text=False)
    print(f"{len(targets)} document(s) to re-drive, "
          f"{len(unrecoverable)} unrecoverable (no extracted_text).")

    ok = skip = fail = 0
    for doc in targets:
        doc_id = doc["id"]
        print(f"  {doc_id[:8]} ({doc.get('file_name', '')}) ...", end=" ", flush=True)
        if args.dry_run:
            print("(dry run)")
            continue

        outcome = index_document(doc_id, force=True)
        if outcome.status == INDEXED:
            print(f"{outcome.chunk_count} chunks indexed")
            ok += 1
        elif outcome.status == INDEXING:
            print("SKIP — being indexed right now")
            skip += 1
        elif outcome.status == SKIPPED:
            # Indexed NOTHING: that is never an ok.
            print("FAIL: embedding is disabled — is SAPLING_MODEL_MODE still "
                  "exported from an E2E cycle? It must be 'real'.")
            fail += 1
        else:
            print(f"FAIL: {outcome.status} ({outcome.error}, "
                  f"{outcome.chunk_count} chunks landed)")
            fail += 1
        time.sleep(1.0)  # stay under the embedding quota

    print(f"\nDone: {ok} ok, {skip} skipped (being indexed), {fail} failed, "
          f"{len(unrecoverable)} unrecoverable (no extracted_text)")
    if fail:
        sys.exit(1)


if __name__ == "__main__":
    main()
