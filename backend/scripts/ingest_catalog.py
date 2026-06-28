#!/usr/bin/env python3
"""
Layer 0 ingestion: bu_catalog_fall_2026.json -> course_chunks table.

Reads the scraped BU catalog JSON, builds one chunk per course
(title + description + prerequisites), embeds with Gemini
text-embedding-004, and upserts into course_chunks.

Run from repo root:
    python backend/scripts/ingest_catalog.py

Resume-safe: already-ingested chunks are skipped via upsert on_conflict=id.
"""

import hashlib
import json
import os
import sys
import time
from pathlib import Path

from dotenv import load_dotenv
from google import genai
from google.genai import types as genai_types

# ── Bootstrap paths ────────────────────────────────────────────────────────────
load_dotenv(Path(__file__).parent.parent / ".env")
sys.path.insert(0, str(Path(__file__).parent.parent))

from db.connection import table

# ── Config ─────────────────────────────────────────────────────────────────────

CATALOG_FILE  = Path(__file__).parent.parent / "data" / "bu_catalog_fall_2026.json"
EMBED_MODEL   = "gemini-embedding-001"
SEMESTER_TAG  = "fall_2026"
BATCH_SIZE    = 50    # courses per Supabase upsert batch
EMBED_BATCH   = 100   # texts per Gemini embed_content call
RATE_DELAY    = 3.0   # 100 texts / 3s = ~2,000 texts/min (limit is 3,000/min)

_gemini = genai.Client(api_key=os.getenv("GEMINI_API_KEY", ""))

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
    """Embed up to EMBED_BATCH texts in one Gemini call, truncated to 768-dim."""
    response = _gemini.models.embed_content(
        model=EMBED_MODEL,
        contents=texts,
        config=genai_types.EmbedContentConfig(output_dimensionality=768),
    )
    return [list(e.values) for e in response.embeddings]


# ── Main ───────────────────────────────────────────────────────────────────────

def main() -> None:
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

    # Upsert to Supabase in batches of BATCH_SIZE
    print(f"\nUpserting to course_chunks...")
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
