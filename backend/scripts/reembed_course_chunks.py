"""Re-embed every `course_chunks` row with the CURRENT embedding model.

Why this exists (ADR 0031): embeddings from two different models do not share
a vector space. After the gemini-embedding-001 -> BAAI/bge-base-en-v1.5 swap,
a row still holding its old vector is not "slightly stale" — it is noise that
`match_course_chunks` will happily rank against fresh query vectors, so
retrieval degrades SILENTLY rather than failing. Every row must be re-embedded
in one pass, or the index is mixed and untrustworthy.

Run (from backend/, with .env active, SAPLING_MODEL_MODE unset/real):

    python -m scripts.reembed_course_chunks            # all rows
    python -m scripts.reembed_course_chunks --dry-run  # count only

`chunk_text` is 🔒 column-encrypted, so this decrypts to embed and writes back
ONLY the `embedding` column — the ciphertext is never rewritten, which keeps
the content hash in `id` valid (ids hash the PLAINTEXT, and encryption happens
after embedding; see the course_chunks note in CLAUDE.md).

Idempotent: re-running recomputes the same vectors. Safe to re-run after a
partial failure.
"""
from __future__ import annotations

import argparse
import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from db.connection import table  # noqa: E402
from services.encryption import decrypt_if_present  # noqa: E402
from services.rag_service import _EMBED_MODEL, _embed_documents_batch  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger("reembed")

#: Small, because each row costs one forward pass and a PATCH round-trip; the
#: point is steady progress with resumable failure, not throughput.
_BATCH = 16


def _fetch_all() -> list[dict]:
    rows: list[dict] = []
    page = 0
    while True:
        got = table("course_chunks").select(
            "id,chunk_text",
            order="id",
            limit=500,
            offset=page * 500,
        ) or []
        rows.extend(got)
        if len(got) < 500:
            return rows
        page += 1


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="count rows, embed nothing")
    args = ap.parse_args()

    rows = _fetch_all()
    logger.info("course_chunks rows: %d", len(rows))
    if args.dry_run:
        logger.info("dry run - nothing written")
        return
    if not rows:
        return

    logger.info("re-embedding with %s", _EMBED_MODEL)
    done = skipped = 0
    for i in range(0, len(rows), _BATCH):
        batch = rows[i : i + _BATCH]
        texts, keep = [], []
        for r in batch:
            text = decrypt_if_present(r.get("chunk_text"))
            # A row whose text will not decrypt cannot be re-embedded honestly.
            # Leaving the stale vector would be worse than leaving it visible,
            # so it is reported and skipped rather than silently zeroed.
            if not text:
                logger.warning("  skip %s - empty/undecryptable chunk_text", r["id"])
                skipped += 1
                continue
            texts.append(text)
            keep.append(r["id"])
        if not texts:
            continue
        vectors = _embed_documents_batch(texts)
        for chunk_id, vec in zip(keep, vectors, strict=True):
            # return=minimal: nobody reads the result, and the default
            # representation would drag the encrypted chunk_text back over the
            # wire for every row.
            table("course_chunks").update(
                {"embedding": vec},
                filters={"id": f"eq.{chunk_id}"},
                prefer_return_minimal=True,
            )
            done += 1
        logger.info("  %d/%d", done, len(rows))

    logger.info("re-embedded %d row(s); skipped %d", done, skipped)


if __name__ == "__main__":
    main()
