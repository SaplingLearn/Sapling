#!/usr/bin/env python3
"""
One-time backfill: fill `documents.shareability` for rows classified before #630,
and bring the visibility of their chunks in line with the answer.

Shareability has no cheaper source than the classifier. `documents.category`
cannot substitute for it — a blank problem-set handout and the same student's
worked solutions are both `category='assignment'`, and the whole point of the
field is that those two must not share a corpus. So this re-runs the classifier
over `documents.extracted_text` through the sanctioned agent seam and stores the
answer, which makes every later re-index deterministic instead of needing another
model pass.

Documents with no `extracted_text` (it is persisted inside the indexer, not in
`_persist_document` — see #482) get `personal_notes`: nothing can be read, so
nothing can be judged shareable.

Chunks are then reconciled: a document whose shareability turns out not to be
`course_material` has its chunks flipped to `visibility='private'`. The reverse
flip is NOT performed — a chunk sitting private may be private because its
uploader opted out (#629), and this script has no business overriding that.

Dry-run by default. Run from backend/:
    python scripts/backfill_document_shareability.py            # preview
    python scripts/backfill_document_shareability.py --apply

Reads .env; for staging/prod run under `dotenv -f .env.staging run -- ...`.
Needs a REAL GEMINI_API_KEY and SAPLING_MODEL_MODE unset/real — the classifier
is a live model call. Note that backend/.env.production's key is a placeholder.
"""
import argparse
import sys
from pathlib import Path

from dotenv import load_dotenv

BASE = Path(__file__).parent.parent
load_dotenv(BASE / ".env")
sys.path.insert(0, str(BASE))

from agents import WORKER_LIMITS  # noqa: E402
from agents._run import run_agent_sync  # noqa: E402
from agents.classifier import classifier_agent  # noqa: E402
from agents.deps import SaplingDeps  # noqa: E402
from db.connection import table  # noqa: E402
from services.chunk_visibility import (  # noqa: E402
    COURSE_MATERIAL, PERSONAL_NOTES, PRIVATE,
)
from services.encryption import decrypt_if_present  # noqa: E402

#: Enough text to judge. Below this the classifier invents a document (the same
#: reasoning as routes/documents.py::MIN_EXTRACTED_CHARS).
MIN_CHARS = 50


def _classify(text: str) -> str:
    deps = SaplingDeps(
        user_id="backfill", course_id=None, supabase=None, request_id="backfill",
    )
    result = run_agent_sync(
        classifier_agent.run(
            text[:20_000], deps=deps, usage_limits=WORKER_LIMITS,
        )
    )
    return result.output.shareability or PERSONAL_NOTES


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Fill documents.shareability and privatise the chunks of "
                    "anything that is not course material."
    )
    parser.add_argument("--dry-run", action="store_true", default=True)
    parser.add_argument("--apply", dest="dry_run", action="store_false")
    args = parser.parse_args()

    docs = table("documents").select(
        "id,file_name,extracted_text,category,shareability",
        filters={"shareability": "is.null", "deleted_at": "is.null"},
    )
    print(f"{len(docs)} document(s) with no stored shareability.")

    counts: dict[str, int] = {}
    privatised = 0
    for doc in docs:
        doc_id = doc["id"]
        text = decrypt_if_present(doc.get("extracted_text")) or ""
        if len(text.strip()) < MIN_CHARS:
            answer = PERSONAL_NOTES
            why = "no readable extracted_text"
        else:
            answer = _classify(text)
            why = "classified"
        counts[answer] = counts.get(answer, 0) + 1
        print(f"  {doc_id[:8]} {doc.get('file_name', '')!r:40} -> {answer} ({why})")

        if args.dry_run:
            continue

        table("documents").update(
            {"shareability": answer}, filters={"id": f"eq.{doc_id}"},
        )
        if answer != COURSE_MATERIAL:
            # Only ever tightens. A chunk already private may be private
            # because its uploader opted out (#629), and this script must not
            # reopen that.
            rows = table("course_chunks").update(
                {"visibility": PRIVATE},
                filters={"doc_id": f"eq.{doc_id}", "visibility": "eq.shared"},
            )
            privatised += len(rows or [])

    print("\nSummary:", ", ".join(f"{k}={v}" for k, v in sorted(counts.items())) or "nothing")
    if args.dry_run:
        print("(dry run — nothing written; pass --apply)")
    else:
        print(f"chunks flipped to private: {privatised}")


if __name__ == "__main__":
    main()
