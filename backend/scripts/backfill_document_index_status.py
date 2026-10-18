"""
Set documents.index_status for every document that predates #482 — once, and
truthfully.

The #482 migration adds `index_status` with the default 'skipped', deliberately
inert, so the indexing sweeper cannot claim a historical row before anything
has said what is actually true of it. This script says it, from what is really
in course_chunks:

  chunks exist for the document     -> 'indexed', with index_chunk_count
  extracted_text, but no chunks     -> 'pending'  (the sweeper will index it)
  no extracted_text                 -> 'failed', 'no_extracted_text', with the
                                       attempt budget spent — visible on the
                                       admin list, never retried

No embedding and no re-classification: re-indexing a document that is already
indexed would re-run a non-deterministic classifier over a settled privacy
decision (#630), and pay for it.

It touches ONLY rows still on the migration default — `index_status='skipped'`
with `index_attempts=0`. Anything the new code has written is left alone,
including function mode's designed 'skipped', which spent an attempt and so is
told apart from the default. That also makes a second run a no-op.

One limit, inherited from the schema: a shared chunk's `doc_id` names only its
LAST writer (#629). A document whose every chunk was deduped into rows another
upload wrote last therefore counts 0 here and is marked 'pending'; the sweeper
then re-indexes it once. That costs one redundant embed, never a wrong answer.

Dry-run by default. Run from backend/:
    python scripts/backfill_document_index_status.py            # preview
    python scripts/backfill_document_index_status.py --apply

Reads .env; for staging/prod run under `dotenv -f .env.<env> run -- ...` and
check the project it prints first. Run it AFTER the migration, once per
environment. It needs no ENCRYPTION_KEY: it tests extracted_text for presence
and never reads it.
"""
import argparse
import sys
from collections import Counter
from pathlib import Path
from urllib.parse import urlparse

from dotenv import load_dotenv

BASE = Path(__file__).parent.parent
load_dotenv(BASE / ".env")
sys.path.insert(0, str(BASE))

from db.connection import REST_URL, page_all, table  # noqa: E402
from services.document_indexing import INDEX_MAX_ATTEMPTS  # noqa: E402

#: The migration's inert default. Only rows still exactly here are touched.
_UNTOUCHED = {"index_status": "eq.skipped", "index_attempts": "eq.0"}


def derive(*, has_text: bool, chunk_count: int) -> dict:
    """The columns to write for one historical document."""
    if chunk_count > 0:
        # Chunks are what retrieval serves: if they exist the document IS
        # indexed, whatever has happened to its source text since.
        return {"index_status": "indexed", "index_chunk_count": chunk_count}
    if has_text:
        return {"index_status": "pending"}
    return {
        "index_status": "failed",
        "index_error": "no_extracted_text",
        "index_attempts": INDEX_MAX_ATTEMPTS,
    }


def _doc_ids(*, with_text: bool) -> list[str]:
    # Presence is a FILTER, never a read: selecting the column to test it for
    # null would pull every document's ciphertext over the wire.
    filters = {
        **_UNTOUCHED,
        "deleted_at": "is.null",
        "extracted_text": "not.is.null" if with_text else "is.null",
    }
    return [r["id"] for r in page_all(table("documents"), "id", filters=filters, order="id")]


def _chunk_counts() -> Counter:
    rows = page_all(
        table("course_chunks"), "doc_id",
        filters={"doc_id": "not.is.null", "category": "neq.catalog"},
        order="id",
    )
    return Counter(r["doc_id"] for r in rows)


def main(argv: list[str] | None = None) -> dict:
    parser = argparse.ArgumentParser(
        description="Derive documents.index_status for rows that predate #482."
    )
    parser.add_argument("--dry-run", action="store_true", default=True)
    parser.add_argument("--apply", dest="dry_run", action="store_false")
    args = parser.parse_args(argv)

    print(f"Project: {urlparse(REST_URL).hostname}")
    counts = _chunk_counts()
    plan = [(d, True) for d in _doc_ids(with_text=True)]
    plan += [(d, False) for d in _doc_ids(with_text=False)]

    summary = {"indexed": 0, "pending": 0, "failed": 0}
    for doc_id, has_text in plan:
        data = derive(has_text=has_text, chunk_count=counts.get(doc_id, 0))
        summary[data["index_status"]] += 1
        print(f"  {doc_id[:8]} -> {data['index_status']}"
              + (f" ({data['index_chunk_count']} chunks)" if "index_chunk_count" in data else ""))
        if not args.dry_run:
            # Conditional on the default, so a status the new code wrote
            # between this read and this write is never clobbered.
            table("documents").update(
                data, filters={"id": f"eq.{doc_id}", **_UNTOUCHED},
                prefer_return_minimal=True,
            )

    mode = "DRY RUN — nothing written" if args.dry_run else "applied"
    print(f"\n{mode}: {summary['indexed']} indexed, {summary['pending']} pending, "
          f"{summary['failed']} failed (no extracted_text)")
    return summary


if __name__ == "__main__":
    main()
