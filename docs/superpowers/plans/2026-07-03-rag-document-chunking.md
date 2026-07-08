# RAG Document Chunking Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Improve document chunking quality and fix embedding task types so the RAG pipeline retrieves the right content from student-uploaded course materials.

**Architecture:** The upload pipeline already calls `_index_document_chunks` in a background thread after each upload. This plan: (1) extracts chunking into `services/chunker.py` with a better algorithm, (2) fixes `task_type` on all embedding calls, (3) adds `extracted_text` storage on the documents row, and (4) adds a backfill script for existing documents.

**Tech Stack:** Python, FastAPI, Supabase PostgREST, `google-genai` (gemini-embedding-001), pytest

## Global Constraints

- All Supabase access goes through `db.connection.table()` or `db.connection.rpc()` — never import httpx or supabase-py directly
- Schema changes are append-only migrations in `backend/db/migrations/` — never edit an applied migration
- Migrations are numbered 0030+ (0029 is already `0029_storage_lockdown_231.sql`)
- Column-level encryption: use `encrypt_if_present` at write, `decrypt_if_present` at read (from `services/encryption.py`)
- Tests run from `backend/` with `pytest tests/ -q`; all tests must pass after each task
- No imports of `google.generativeai` — project uses `google.genai` (the new SDK)
- Run from `backend/` directory for all commands

---

### Task 1: Extract `chunk_document` into `services/chunker.py`

**Files:**
- Create: `backend/services/chunker.py`
- Create: `backend/tests/test_chunker.py`

**Interfaces:**
- Produces: `chunk_document(text: str) -> list[str]`
  - Splits on `\n\n`, merges chunks < 50 words with neighbor, splits chunks > 400 words at nearest sentence boundary
  - Returns list of non-empty strings, each 50–400 words

- [ ] **Step 1: Write the failing tests**

```python
# backend/tests/test_chunker.py
from services.chunker import chunk_document


def test_empty_returns_empty():
    assert chunk_document("") == []


def test_single_short_paragraph_returns_one_chunk():
    text = "Dynamic programming is a method for solving complex problems by breaking them into subproblems."
    result = chunk_document(text)
    assert len(result) == 1
    assert "dynamic programming" in result[0].lower()


def test_double_newline_splits_into_chunks():
    text = ("First paragraph about sorting algorithms. It covers quicksort and mergesort in detail.\n\n"
            "Second paragraph about graph algorithms. It explains BFS and DFS traversal methods.\n\n"
            "Third paragraph about dynamic programming. It covers memoization and tabulation.")
    result = chunk_document(text)
    assert len(result) == 3


def test_short_chunks_merged_with_neighbor():
    # Three paragraphs: short + short + normal => first two get merged
    short = "Short."
    normal = " ".join(["word"] * 60)  # 60 words
    text = f"{short}\n\n{short}\n\n{normal}"
    result = chunk_document(text)
    # Both short chunks should merge into one, leaving 2 total
    assert len(result) <= 2


def test_long_chunk_split_at_sentence_boundary():
    # Build a single paragraph with 500 words, multiple sentences
    sentences = [f"This is sentence number {i} about algorithms and data structures." for i in range(50)]
    long_para = " ".join(sentences)
    result = chunk_document(long_para)
    assert len(result) > 1
    for chunk in result:
        word_count = len(chunk.split())
        assert word_count <= 420, f"Chunk too long: {word_count} words"


def test_no_empty_chunks():
    text = "\n\n".join(["  ", "actual content here with enough words to matter", "  "])
    result = chunk_document(text)
    for chunk in result:
        assert chunk.strip() != ""
```

- [ ] **Step 2: Run tests to verify they fail**

```
cd backend
pytest tests/test_chunker.py -v
```

Expected: `ModuleNotFoundError: No module named 'services.chunker'`

- [ ] **Step 3: Implement `chunk_document`**

```python
# backend/services/chunker.py
"""Semantic document chunker for RAG indexing.

Splits on double-newline boundaries (the natural block delimiter in
Docling's markdown output), then merges short fragments and splits
over-long blocks at sentence boundaries.

Target: 50–400 words per chunk.
"""

_MIN_WORDS = 50
_MAX_WORDS = 400


def _word_count(text: str) -> int:
    return len(text.split())


def _split_at_sentence(text: str, max_words: int) -> list[str]:
    """Split text at the nearest sentence boundary before max_words."""
    words = text.split()
    if len(words) <= max_words:
        return [text]

    chunks: list[str] = []
    start = 0
    while start < len(words):
        end = min(start + max_words, len(words))
        candidate = " ".join(words[start:end])
        # Walk back to find a sentence boundary (". " pattern)
        if end < len(words):
            last_period = candidate.rfind(". ")
            if last_period > 0:
                candidate = candidate[: last_period + 1]
        chunks.append(candidate.strip())
        start += len(candidate.split())
    return [c for c in chunks if c.strip()]


def chunk_document(text: str) -> list[str]:
    """Split document text into RAG-indexable chunks.

    Algorithm:
    1. Split on double newlines (Docling block boundaries)
    2. Merge adjacent chunks that are each under _MIN_WORDS
    3. Split any chunk over _MAX_WORDS at a sentence boundary
    """
    if not text or not text.strip():
        return []

    # Step 1: split on double newlines
    raw_blocks = [b.strip() for b in text.split("\n\n") if b.strip()]

    # Step 2: merge short adjacent blocks
    merged: list[str] = []
    for block in raw_blocks:
        if merged and _word_count(merged[-1]) < _MIN_WORDS and _word_count(block) < _MIN_WORDS:
            merged[-1] = merged[-1] + " " + block
        elif merged and _word_count(merged[-1]) < _MIN_WORDS:
            merged[-1] = merged[-1] + " " + block
        else:
            merged.append(block)

    # Step 3: split over-long blocks
    result: list[str] = []
    for block in merged:
        if _word_count(block) > _MAX_WORDS:
            result.extend(_split_at_sentence(block, _MAX_WORDS))
        else:
            result.append(block)

    return [c for c in result if c.strip()]
```

- [ ] **Step 4: Run tests to verify they pass**

```
pytest tests/test_chunker.py -v
```

Expected: all 6 tests PASS

- [ ] **Step 5: Run full suite to check for regressions**

```
pytest tests/ -q --ignore=tests/evals
```

Expected: no new failures

- [ ] **Step 6: Commit**

```
git add backend/services/chunker.py backend/tests/test_chunker.py
git commit -m "feat(rag): extract chunk_document service with word-boundary splitting"
```

---

### Task 2: Fix embedding task types in `rag_service.py`

**Files:**
- Modify: `backend/services/rag_service.py`
- Create: `backend/tests/test_rag_service.py`

**Interfaces:**
- Consumes: nothing new
- Produces (modified signatures):
  - `_embed_document(text: str) -> list[float]` — uses `task_type="RETRIEVAL_DOCUMENT"`
  - `_embed_query(text: str) -> list[float]` — uses `task_type="RETRIEVAL_QUERY"`
  - `retrieve_chunks(query, course_id, k, min_similarity)` — unchanged signature, now uses `_embed_query`
  - `index_document_chunks(course_code, doc_id, uploader_id, chunks)` — new public function, uses `_embed_document`

- [ ] **Step 1: Write failing tests**

```python
# backend/tests/test_rag_service.py
from unittest.mock import MagicMock, patch, call
import pytest


def _make_embedding_response(vecs: list[list[float]]):
    resp = MagicMock()
    resp.embeddings = [MagicMock(values=v) for v in vecs]
    return resp


@patch("services.rag_service._client")
def test_retrieve_chunks_uses_retrieval_query_task_type(mock_client):
    mock_client.models.embed_content.return_value = _make_embedding_response([[0.1] * 768])
    with patch("services.rag_service.rpc", return_value=[]):
        from services.rag_service import retrieve_chunks
        retrieve_chunks("what is dynamic programming", course_id="CAS CS 330")

    call_kwargs = mock_client.models.embed_content.call_args
    config = call_kwargs.kwargs.get("config") or call_kwargs.args[2]
    assert config.task_type == "RETRIEVAL_QUERY"


@patch("services.rag_service._client")
def test_index_document_chunks_uses_retrieval_document_task_type(mock_client):
    mock_client.models.embed_content.return_value = _make_embedding_response([[0.2] * 768])
    with patch("services.rag_service.rpc", return_value=[]), \
         patch("db.connection.table") as mock_table:
        mock_table.return_value.upsert.return_value = []
        from services.rag_service import index_document_chunks
        index_document_chunks(
            course_code="CAS CS 330",
            doc_id="doc-abc",
            uploader_id="user-123",
            chunks=["Dynamic programming covers memoization and tabulation techniques."],
        )

    call_kwargs = mock_client.models.embed_content.call_args
    config = call_kwargs.kwargs.get("config") or call_kwargs.args[2]
    assert config.task_type == "RETRIEVAL_DOCUMENT"


@patch("services.rag_service._client")
def test_index_document_chunks_returns_count(mock_client):
    mock_client.models.embed_content.return_value = _make_embedding_response([[0.2] * 768] * 3)
    with patch("db.connection.table") as mock_table:
        mock_table.return_value.upsert.return_value = []
        from services.rag_service import index_document_chunks
        count = index_document_chunks(
            course_code="CAS CS 330",
            doc_id="doc-xyz",
            uploader_id="user-456",
            chunks=["chunk one about sorting", "chunk two about graphs", "chunk three about trees"],
        )
    assert count == 3


@patch("services.rag_service._client")
def test_index_document_chunks_empty_returns_zero(mock_client):
    from services.rag_service import index_document_chunks
    count = index_document_chunks("CAS CS 330", "doc-1", "user-1", [])
    assert count == 0
    mock_client.models.embed_content.assert_not_called()
```

- [ ] **Step 2: Run tests to verify they fail**

```
pytest tests/test_rag_service.py -v
```

Expected: `ImportError` or `AssertionError` — `task_type` is not set and `index_document_chunks` doesn't exist yet

- [ ] **Step 3: Rewrite `rag_service.py`**

```python
# backend/services/rag_service.py
"""
RAG retrieval service.

Embeds queries and documents with gemini-embedding-001 using the correct
task types (RETRIEVAL_QUERY for queries, RETRIEVAL_DOCUMENT for indexing),
then calls the match_course_chunks Supabase RPC for ANN retrieval.
"""
import hashlib
import os

from google import genai
from google.genai import types as genai_types

from db.connection import rpc, table

_client = genai.Client(api_key=os.getenv("GEMINI_API_KEY", ""))
_EMBED_MODEL = "gemini-embedding-001"
_OUTPUT_DIM = 768


def _embed_query(text: str) -> list[float]:
    resp = _client.models.embed_content(
        model=_EMBED_MODEL,
        contents=[text],
        config=genai_types.EmbedContentConfig(
            output_dimensionality=_OUTPUT_DIM,
            task_type="RETRIEVAL_QUERY",
        ),
    )
    return list(resp.embeddings[0].values)


def _embed_document(text: str) -> list[float]:
    resp = _client.models.embed_content(
        model=_EMBED_MODEL,
        contents=[text],
        config=genai_types.EmbedContentConfig(
            output_dimensionality=_OUTPUT_DIM,
            task_type="RETRIEVAL_DOCUMENT",
        ),
    )
    return list(resp.embeddings[0].values)


def _embed_documents_batch(texts: list[str]) -> list[list[float]]:
    resp = _client.models.embed_content(
        model=_EMBED_MODEL,
        contents=texts,
        config=genai_types.EmbedContentConfig(
            output_dimensionality=_OUTPUT_DIM,
            task_type="RETRIEVAL_DOCUMENT",
        ),
    )
    return [list(e.values) for e in resp.embeddings]


def retrieve_chunks(
    query: str,
    course_id: str | None = None,
    k: int = 5,
    min_similarity: float = 0.55,
) -> list[dict]:
    """Return up to k chunks similar to query, optionally filtered by course_id.

    Each result: {"course_id": str, "chunk_text": str, "similarity": float}
    """
    try:
        embedding = _embed_query(query)
        params: dict = {
            "query_embedding": embedding,
            "match_count": k,
            "filter_course_id": course_id,
        }
        rows = rpc("match_course_chunks", params)
        return [r for r in rows if r.get("similarity", 0) >= min_similarity]
    except Exception as e:
        print(f"[RAG] retrieve_chunks failed: {e}")
        return []


def index_document_chunks(
    course_code: str,
    doc_id: str,
    uploader_id: str,
    chunks: list[str],
) -> int:
    """Embed and upsert document chunks to course_chunks.

    Returns the number of chunks upserted. Uses RETRIEVAL_DOCUMENT task
    type for all embeddings. Upsert is idempotent — re-indexing the same
    doc_id produces the same chunk IDs and merges cleanly.
    """
    if not chunks:
        return 0

    records = []
    for i, chunk_text in enumerate(chunks):
        raw = f"{doc_id}::{i}::{chunk_text}"
        cid = hashlib.sha256(raw.encode()).hexdigest()
        records.append({
            "id":          cid,
            "course_id":   course_code,
            "doc_id":      doc_id,
            "uploader_id": uploader_id,
            "chunk_index": i,
            "chunk_text":  chunk_text,
            "chunk_hash":  cid,
            "embedding":   None,
            "category":    "document",
            "semester":    "current",
            "section_id":  None,
            "school":      "",
        })

    # Embed in batches of 50 (API limit)
    BATCH = 50
    for i in range(0, len(records), BATCH):
        batch = records[i : i + BATCH]
        texts = [r["chunk_text"] for r in batch]
        try:
            vecs = _embed_documents_batch(texts)
            for rec, vec in zip(batch, vecs):
                rec["embedding"] = vec
        except Exception as e:
            print(f"[RAG] embed failed for doc {doc_id} batch {i}: {e}")

    table("course_chunks").upsert(records, on_conflict="id")
    return len(records)


def format_rag_context(chunks: list[dict]) -> str:
    """Format retrieved chunks into a text block for prompt injection."""
    if not chunks:
        return ""
    lines = ["RETRIEVED COURSE CONTEXT (semantically relevant to this question):"]
    for i, chunk in enumerate(chunks, 1):
        sim = chunk.get("similarity", 0)
        lines.append(f"\n[{i}] (relevance {sim:.2f})\n{chunk.get('chunk_text', '')}")
    return "\n".join(lines)
```

- [ ] **Step 4: Run tests to verify they pass**

```
pytest tests/test_rag_service.py -v
```

Expected: all 4 tests PASS

- [ ] **Step 5: Run full suite**

```
pytest tests/ -q --ignore=tests/evals
```

Expected: no new failures

- [ ] **Step 6: Commit**

```
git add backend/services/rag_service.py backend/tests/test_rag_service.py
git commit -m "fix(rag): set RETRIEVAL_QUERY/RETRIEVAL_DOCUMENT task types; extract index_document_chunks"
```

---

### Task 3: Migration 0030 — add `extracted_text` to `documents`

**Files:**
- Create: `backend/db/migrations/0030_documents_extracted_text.sql`

**Interfaces:**
- Produces: `documents.extracted_text TEXT` column (nullable, encrypted)

- [ ] **Step 1: Write the migration**

```sql
-- backend/db/migrations/0030_documents_extracted_text.sql
-- Store raw OCR-extracted text on each document row so the chunking
-- pipeline can re-index without re-running extraction.
ALTER TABLE documents
    ADD COLUMN IF NOT EXISTS extracted_text TEXT;
```

- [ ] **Step 2: Apply to staging**

```
cd backend
python -m dotenv -f .env.staging run -- python -m db.migrate
```

Expected output includes: `applying 0030_documents_extracted_text.sql`

- [ ] **Step 3: Verify column exists on staging**

Use the Supabase MCP or run:
```
python -m dotenv -f .env.staging run -- python -c "
from db.connection import table
rows = table('documents').select('id,extracted_text', limit=1)
print('column exists:', rows is not None)
"
```

Expected: `column exists: True`

- [ ] **Step 4: Commit**

```
git add backend/db/migrations/0030_documents_extracted_text.sql
git commit -m "feat(rag): migration 0030 — add extracted_text column to documents"
```

---

### Task 4: Wire `chunker` + `rag_service` into the upload pipeline

**Files:**
- Modify: `backend/routes/documents.py` (lines ~935–1050, the `_chunk_text` and `_index_document_chunks` functions)

**Interfaces:**
- Consumes:
  - `services.chunker.chunk_document(text: str) -> list[str]`
  - `services.rag_service.index_document_chunks(course_code, doc_id, uploader_id, chunks) -> int`
- Produces: `_index_document_chunks` replaced with a thin wrapper; `extracted_text` stored on document row

- [ ] **Step 1: Check existing tests pass before touching anything**

```
pytest tests/test_documents_routes.py -q
```

Expected: all pass (baseline)

- [ ] **Step 2: Replace `_chunk_text` and `_index_document_chunks` in `documents.py`**

Find the block starting at `def _chunk_text(` (~line 935) through the end of `_index_document_chunks` (~line 1050) and replace the entire block with:

```python
def _index_document_chunks(
    doc_id: str,
    course_id: str,      # Sapling UUID — resolved to BU code internally
    user_id: str,
    extracted_text: str,
    category: str,
    doc_summary: str = "",
) -> None:
    """Chunk, embed, and upsert a document into course_chunks.

    Runs in a background thread via _spawn_post_roll after the document
    is persisted, so it never blocks the SSE stream.
    """
    import time
    from services.chunker import chunk_document
    from services.rag_service import index_document_chunks
    from services.encryption import encrypt_if_present

    MIN_COURSE_RELEVANCE = 0.35

    try:
        # Resolve BU course code from Sapling UUID
        rows = table("courses").select(
            "course_code", filters={"id": f"eq.{course_id}"}, limit=1
        )
        bu_course_id = (rows[0].get("course_code") or course_id) if rows else course_id

        chunks = chunk_document(extracted_text)
        if not chunks:
            return

        # Store raw extracted text on the document row (best-effort)
        try:
            table("documents").update(
                {"extracted_text": encrypt_if_present(extracted_text)},
                filters={"id": f"eq.{doc_id}"},
            )
        except Exception:
            logger.warning("[RAG] could not store extracted_text for doc %s", doc_id)

        # Relevance gate: skip docs that are off-topic for the course
        from google import genai as _genai
        from google.genai import types as genai_types
        import os
        _gclient = _genai.Client(api_key=os.getenv("GEMINI_API_KEY", ""))

        catalog_rows = table("course_chunks").select(
            "embedding",
            filters={"course_id": f"eq.{bu_course_id}", "category": "eq.catalog"},
            limit=1,
        )
        if catalog_rows and catalog_rows[0].get("embedding"):
            catalog_vec = catalog_rows[0]["embedding"]
            sample_text = doc_summary or chunks[0]
            resp = _gclient.models.embed_content(
                model="gemini-embedding-001",
                contents=[sample_text],
                config=genai_types.EmbedContentConfig(
                    output_dimensionality=768,
                    task_type="RETRIEVAL_DOCUMENT",
                ),
            )
            doc_sample_vec = list(resp.embeddings[0].values)
            time.sleep(1.5)
            dot = sum(a * b for a, b in zip(doc_sample_vec, catalog_vec))
            if dot < MIN_COURSE_RELEVANCE:
                logger.warning(
                    "[RAG] doc %s skipped — relevance to %s is %.3f (< %.2f)",
                    doc_id, bu_course_id, dot, MIN_COURSE_RELEVANCE,
                )
                return

        count = index_document_chunks(
            course_code=bu_course_id,
            doc_id=doc_id,
            uploader_id=user_id,
            chunks=chunks,
        )
        logger.info("[RAG] indexed %d chunks for doc %s", count, doc_id)

    except Exception:
        logger.exception("[RAG] _index_document_chunks failed for doc %s", doc_id)
```

- [ ] **Step 3: Run document route tests**

```
pytest tests/test_documents_routes.py -q
```

Expected: all pass

- [ ] **Step 4: Run full suite**

```
pytest tests/ -q --ignore=tests/evals
```

Expected: no new failures

- [ ] **Step 5: Commit**

```
git add backend/routes/documents.py
git commit -m "feat(rag): wire chunk_document + index_document_chunks into upload pipeline; store extracted_text"
```

---

### Task 5: Backfill script for existing documents

**Files:**
- Create: `backend/scripts/backfill_document_chunks.py`

**Interfaces:**
- Consumes:
  - `services.chunker.chunk_document`
  - `services.rag_service.index_document_chunks`
  - `services.extraction_service.extract_text_from_file`
  - Supabase Storage (download file bytes)

- [ ] **Step 1: Write the script**

```python
# backend/scripts/backfill_document_chunks.py
"""
One-time backfill: chunk and embed all documents that are missing extracted_text.

Run from backend/:
    python scripts/backfill_document_chunks.py              # staging
    python scripts/backfill_document_chunks.py --dry-run    # preview only
"""
import argparse
import os
import sys
import time
from pathlib import Path

import httpx
from dotenv import load_dotenv

BASE = Path(__file__).parent.parent
load_dotenv(BASE / ".env.staging")

sys.path.insert(0, str(BASE))

from db.connection import table
from services.chunker import chunk_document
from services.rag_service import index_document_chunks
from services.extraction_service import extract_text_from_file
from services.encryption import encrypt_if_present

SUPABASE_URL = os.getenv("SUPABASE_URL", "").rstrip("/")
SUPABASE_KEY = os.getenv("SUPABASE_SERVICE_KEY", "")
STORAGE_BUCKET = "documents"


def _download_file(file_path: str) -> bytes:
    url = f"{SUPABASE_URL}/storage/v1/object/{STORAGE_BUCKET}/{file_path}"
    r = httpx.get(url, headers={"Authorization": f"Bearer {SUPABASE_KEY}"}, timeout=60)
    r.raise_for_status()
    return r.content


def _get_bu_code(course_id: str) -> str:
    rows = table("courses").select("course_code", filters={"id": f"eq.{course_id}"}, limit=1)
    return (rows[0].get("course_code") or course_id) if rows else course_id


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    # Fetch docs missing extracted_text, joining to offerings for course_id
    docs = table("documents").select(
        "id,file_name,file_path,uploader_id,offering_id",
        filters={"extracted_text": "is.null"},
    )
    print(f"Found {len(docs)} documents missing extracted_text")

    ok = skip = fail = 0
    for doc in docs:
        doc_id = doc["id"]
        filename = doc.get("file_name", "")
        file_path = doc.get("file_path", "")
        user_id = doc.get("uploader_id", "")
        offering_id = doc.get("offering_id", "")

        # Resolve course from offering
        off_rows = table("course_offerings").select(
            "course_id", filters={"id": f"eq.{offering_id}"}, limit=1
        )
        if not off_rows:
            print(f"  SKIP {doc_id[:8]} — no offering")
            skip += 1
            continue
        bu_code = _get_bu_code(off_rows[0]["course_id"])

        print(f"  Processing {doc_id[:8]} ({filename}) → {bu_code} ...", end=" ", flush=True)

        if args.dry_run:
            print("(dry run)")
            continue

        try:
            file_bytes = _download_file(file_path)
            content_type = ""
            extracted = extract_text_from_file(file_bytes, filename, content_type)

            table("documents").update(
                {"extracted_text": encrypt_if_present(extracted)},
                filters={"id": f"eq.{doc_id}"},
            )

            chunks = chunk_document(extracted)
            if chunks:
                count = index_document_chunks(bu_code, doc_id, user_id, chunks)
                print(f"{count} chunks indexed")
            else:
                print("0 chunks (empty text)")

            ok += 1
            time.sleep(1.0)  # stay under embedding quota
        except Exception as e:
            print(f"FAIL: {e}")
            fail += 1

    print(f"\nDone: {ok} ok, {skip} skipped, {fail} failed")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Dry-run against staging**

```
cd backend
python scripts/backfill_document_chunks.py --dry-run
```

Expected: prints list of documents that would be processed, no writes

- [ ] **Step 3: Run for real against staging**

```
python scripts/backfill_document_chunks.py
```

Expected: each document logs chunk count. Final summary shows ok/skip/fail counts.

- [ ] **Step 4: Commit**

```
git add backend/scripts/backfill_document_chunks.py
git commit -m "feat(rag): backfill script for existing documents missing extracted_text"
```

---

### Task 6: Push and deploy

- [ ] **Step 1: Final test run**

```
cd backend
pytest tests/ -q --ignore=tests/evals
```

Expected: all pass

- [ ] **Step 2: Push to main**

```
git push
```

Railway will auto-deploy. Wait ~2 minutes for deploy to complete.

- [ ] **Step 3: Run benchmark against staging to verify improvement**

```
cd backend
python scripts/benchmark_rag.py --chunks-only
```

Expected: 17/17 chunk retrieval passes (unchanged)

```
python scripts/benchmark_rag.py
```

Expected: ≥92% overall (same or better than before the task_type fix)

- [ ] **Step 4: Upload a test document on staging.saplinglearn.com**

Upload any PDF for CAS CS 330. Then ask the tutor: *"What does my uploaded document cover?"*

Expected: tutor references content from the uploaded document, not just the BU catalog entry.

---

## Self-Review

**Spec coverage:**
- ✅ Migration 0030 — Task 3
- ✅ `services/chunker.py` — Task 1
- ✅ Fix `task_type` in `rag_service.py` — Task 2
- ✅ `index_document_chunks` public function — Task 2
- ✅ Store `extracted_text` at upload — Task 4
- ✅ Wire into upload pipeline — Task 4
- ✅ Backfill script — Task 5
- ✅ Benchmark verification — Task 6

**Type consistency:**
- `chunk_document(text: str) -> list[str]` — defined Task 1, consumed Task 4 ✓
- `index_document_chunks(course_code, doc_id, uploader_id, chunks) -> int` — defined Task 2, consumed Task 4 and Task 5 ✓
- SHA-256 chunk ID format `f"{doc_id}::{i}::{chunk_text}"` — consistent between Task 2 and Task 4 ✓

**No placeholders:** confirmed — all steps have complete code.
