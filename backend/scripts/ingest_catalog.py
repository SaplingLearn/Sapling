#!/usr/bin/env python3
"""
Layer 0 ingestion: bu_catalog_fall_2026.json -> course_chunks table.

Reads the scraped BU catalog JSON, builds one chunk per course
(title + description + prerequisites), embeds with the SAME local encoder
the request path uses (services/rag_service, ADR 0031), and upserts into
course_chunks.

Embedding goes through rag_service deliberately: catalog rows share the
`course_chunks` table and its ANN index with document rows, and vectors
from two different models do not share a space. A private Gemini client
here would silently poison `course_relevance` and catalog retrieval
against every bge-embedded row.

Run from repo root:
    python backend/scripts/ingest_catalog.py

Resume-safe: already-ingested chunks are skipped via upsert on_conflict=id.
"""

import hashlib
import json
import sys
import time
from pathlib import Path

from dotenv import load_dotenv

# ── Bootstrap paths ────────────────────────────────────────────────────────────
load_dotenv(Path(__file__).parent.parent / ".env")
sys.path.insert(0, str(Path(__file__).parent.parent))

from agents._providers import model_mode  # noqa: E402
from db.connection import table  # noqa: E402
from services.encryption import encrypt_if_present  # noqa: E402
from services.rag_service import (  # noqa: E402
    _EMBED_MODEL,
    _embed_documents_batch,
)

# ── Config ─────────────────────────────────────────────────────────────────────

CATALOG_FILE  = Path(__file__).parent.parent / "data" / "bu_catalog_fall_2026.json"
# Kept as a name for the log line only; the model itself is rag_service's.
EMBED_MODEL   = _EMBED_MODEL
SEMESTER_TAG  = "fall_2026"
BATCH_SIZE    = 50    # courses per Supabase upsert batch
EMBED_BATCH   = 100   # texts per local encoder forward pass
RATE_DELAY    = 0.0   # local encoder: no provider rate limit to respect

# Catalog ingestion is meaningless without real embeddings, so this CLI
# asserts real mode rather than inheriting the request path's silent
# degrade: under SAPLING_MODEL_MODE=function every _embed_* raises
# _EmbeddingDisabled, and a run that wrote NULL vectors for 20k courses
# would look like success. Fail fast with an actionable message instead
# (the shape #413 established when this was a keyless genai.Client).
def _require_real_mode_cli() -> None:
    if model_mode() != "real":
        sys.exit(
            f"SAPLING_MODEL_MODE={model_mode()!r}: ingest_catalog.py embeds with "
            "the real local encoder and has no offline mode. Unset "
            "SAPLING_MODEL_MODE (or set it to 'real') and re-run."
        )


# ── Helpers ────────────────────────────────────────────────────────────────────

def build_chunk_text(course: dict) -> str:
    """Assemble the text that gets embedded for a catalog course."""
    parts = [
        f"Course: {course['course_code']} - {course['title']}",
        f"School: {course['school'].upper()}",
    ]
    if course.get("credits"):
        parts.append(f"Credits: {course['credits']}")
    if course.get("description"):
        parts.append(f"Description: {course['description']}")
    if course.get("prerequisites"):
        parts.append(f"Prerequisites: {course['prerequisites']}")
    if course.get("instructors"):
        parts.append(f"Instructor(s): {', '.join(course['instructors'])}")
    if course.get("semester_offered"):
        parts.append(f"Offered: {', '.join(course['semester_offered'])}")
    return "\n".join(parts)


def chunk_id(course_id: str, chunk_text: str) -> str:
    """Stable SHA-256 ID — same input always produces the same ID (dedup key)."""
    raw = f"{course_id}::{chunk_text}"
    return hashlib.sha256(raw.encode()).hexdigest()


def embed_batch(texts: list[str]) -> list[list[float]]:
    """Embed up to EMBED_BATCH texts as 768-d document-side vectors.

    Delegates to rag_service so catalog rows are produced by the exact
    encoder, pooling and normalisation the retrieval path uses.
    """
    return _embed_documents_batch(texts)


# ── Main ───────────────────────────────────────────────────────────────────────

def main() -> None:
    _require_real_mode_cli()
    with open(CATALOG_FILE, encoding="utf-8") as f:
        catalog: list[dict] = json.load(f)

    print(f"Loaded {len(catalog):,} courses from {CATALOG_FILE.name}")

    # Build chunk records
    records: list[dict] = []
    for course in catalog:
        course_id  = course["course_code"]   # e.g. "CAS CS 330"
        chunk_text = build_chunk_text(course)
        cid        = chunk_id(course_id, chunk_text)
        records.append({
            "id":          cid,
            "course_id":   course_id,
            "doc_id":      None,
            "uploader_id": None,
            "chunk_index": 0,
            "chunk_text":  chunk_text,
            "chunk_hash":  cid,
            "embedding":   None,  # filled in below
            "category":    "catalog",
            "semester":    SEMESTER_TAG,
            "section_id":  None,
            "school":      course.get("school", ""),
        })

    print(f"Built {len(records):,} chunk records — embedding now...")

    # Embed in batches of EMBED_BATCH
    texts = [r["chunk_text"] for r in records]
    embeddings: list[list[float]] = []

    for i in range(0, len(texts), EMBED_BATCH):
        batch = texts[i : i + EMBED_BATCH]
        try:
            vecs = embed_batch(batch)
            embeddings.extend(vecs)
        except Exception as exc:
            exc_str = str(exc)
            # Parse retryDelay from Gemini 429 response if present
            import re as _re
            m = _re.search(r'retryDelay.*?(\d+)s', exc_str)
            wait = int(m.group(1)) + 5 if m else 35
            print(f"  Embed error at [{i}:{i+EMBED_BATCH}]: retrying in {wait}s")
            time.sleep(wait)
            try:
                vecs = embed_batch(batch)
                embeddings.extend(vecs)
            except Exception as exc2:
                print(f"  FAILED [{i}:{i+EMBED_BATCH}]: {exc2} — inserting without embedding")
                embeddings.extend([None] * len(batch))

        done = min(i + EMBED_BATCH, len(texts))
        print(f"  embedded {done:,}/{len(texts):,}", flush=True)
        time.sleep(RATE_DELAY)

    # Attach embeddings to records
    for rec, vec in zip(records, embeddings):
        rec["embedding"] = vec

    # ADR 0025 / #484: encrypt AFTER embedding (the embed pass above reads
    # `r["chunk_text"]`) and after the ids were computed on the plaintext.
    # Catalog rows are public BU course text with nothing to protect; they are
    # encrypted anyway so the invariant is "chunk_text is ALWAYS ciphertext",
    # which the `ciphertext` e2e oracle can assert. A per-category rule cannot
    # be asserted, and `decrypt_if_present` returns the raw value on failure —
    # in a mixed table that makes a genuine decrypt failure indistinguishable
    # from a legitimately-plaintext row.
    for rec in records:
        rec["chunk_text"] = encrypt_if_present(rec["chunk_text"])

    # Upsert to Supabase in batches of BATCH_SIZE
    print("\nUpserting to course_chunks...")
    db = table("course_chunks")
    inserted = 0

    for i in range(0, len(records), BATCH_SIZE):
        batch = records[i : i + BATCH_SIZE]
        try:
            db.upsert(batch, on_conflict="id")
            inserted += len(batch)
            print(f"  upserted {inserted:,}/{len(records):,}", flush=True)
        except Exception as exc:
            print(f"  Upsert error at [{i}:{i+BATCH_SIZE}]: {exc}")

    print(f"\nDone: {inserted:,} chunks upserted to course_chunks.")


if __name__ == "__main__":
    main()
