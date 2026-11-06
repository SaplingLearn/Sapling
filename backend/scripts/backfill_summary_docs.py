"""
Backfill summary_docs rows from existing documents.summary (one-time, #spec
"Integration & cutover" stage 1). After this plan's upload-pipeline cutover
(Task 14), documents.summary is never written again — but documents
uploaded BEFORE this feature shipped still only have the old column, and
without this script they would appear in the Library with no summary doc
to open.

Idempotent: skips any document that already has a summary_docs row (either
from a previous run of this script, or because it was uploaded after the
cutover and already got one the normal way). Safe to re-run.

Run from backend/:
    python scripts/backfill_summary_docs.py              # backfill every eligible document
    python scripts/backfill_summary_docs.py --dry-run    # list only; write nothing

Loads .env.staging without overriding what is already set — run it under
`dotenv -f .env.<env> run -- ...` for any other environment (same
convention as scripts/backfill_document_chunks.py), and check the project
it prints first.

Not safe to run concurrently with another instance of itself: the
idempotency check (a row already exists in summary_docs) is read-then-write
with no locking, so two overlapping runs could both decide the same
document needs backfilling. create_summary_doc's own inserts
(summary_docs -> summary_doc_sources -> summary_doc_versions) aren't
atomic either — if one fails partway through, the document is left with a
summary_docs row but a FAIL is still logged. Because the idempotency check
only looks for a summary_docs row, a re-run will treat that document as
already done and will not retry it; such a document needs a manual look.
"""
import argparse
import sys
from pathlib import Path
from urllib.parse import urlparse

from dotenv import load_dotenv

BASE = Path(__file__).parent.parent
load_dotenv(BASE / ".env.staging")

sys.path.insert(0, str(BASE))

from db.connection import REST_URL, page_all, table  # noqa: E402
from services.encryption import decrypt_if_present  # noqa: E402
from services.summary_docs_service import create_summary_doc  # noqa: E402


def _documents_with_summary() -> list[dict]:
    return list(page_all(
        table("documents"), "id,user_id,summary",
        filters={"deleted_at": "is.null", "summary": "not.is.null"},
        order="created_at,id",
    ))


def _already_backfilled_document_ids() -> set[str]:
    rows = list(page_all(
        table("summary_docs"), "primary_document_id",
        filters={}, order="id",
    ))
    return {r["primary_document_id"] for r in rows}


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description="Backfill summary_docs rows from documents.summary.",
    )
    parser.add_argument("--dry-run", action="store_true", help="List only; write nothing.")
    args = parser.parse_args(argv)

    print(f"Project: {urlparse(REST_URL).hostname}")
    candidates = _documents_with_summary()
    already_done = _already_backfilled_document_ids()
    targets = [d for d in candidates if d["id"] not in already_done]
    print(f"{len(targets)} document(s) to backfill, "
          f"{len(candidates) - len(targets)} already have a summary doc.")

    ok = fail = 0
    for doc in targets:
        doc_id = doc["id"]
        print(f"  {doc_id[:8]} ...", end=" ", flush=True)
        if args.dry_run:
            print("(dry run)")
            continue
        try:
            seed_text = decrypt_if_present(doc["summary"]) or ""
            create_summary_doc(
                user_id=doc["user_id"], primary_document_id=doc_id, seed_text=seed_text,
            )
            print("ok")
            ok += 1
        except Exception as e:
            print(f"FAIL: {e}")
            fail += 1

    print(f"\nDone: {ok} ok, {fail} failed.")
    if fail:
        sys.exit(1)


if __name__ == "__main__":
    main()
