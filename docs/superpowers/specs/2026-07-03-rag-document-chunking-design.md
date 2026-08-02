# RAG Document Chunking — Design Spec
**Date:** 2026-07-03  
**Status:** Approved  

---

## Problem

The RAG pipeline currently only indexes BU catalog data (course descriptions, prerequisites, credits). Student-uploaded documents — lecture slides, readings, notes, syllabi — are processed for summaries and concept graphs but are never chunked, embedded, or made retrievable. When a student asks "explain the master theorem from my slides", the tutor has no access to that content.

---

## Goal

When any student uploads a document for course X, chunk it into semantically coherent units, embed each chunk, and store them in `course_chunks`. All students in course X — across all sections and semesters — immediately benefit from that document in their tutor sessions, quiz generation, and study guides.

---

## Architecture

### Data flow

```
Upload → extract_text_from_file()
       → store extracted_text on documents row  (new)
       → _process_document() → classify/summarize (existing, unchanged)
       → chunk_document(extracted_text)          (new)
       → embed each chunk (RETRIEVAL_DOCUMENT)   (new + bug fix)
       → upsert to course_chunks                 (new)
```

Retrieval is unchanged — `retrieve_chunks(query, course_id=bu_code)` already returns all chunks for a course regardless of category.

---

## Components

### 1. Migration 0029 — `documents.extracted_text`

Add `extracted_text TEXT` to the `documents` table, encrypted with the same column-level encryption used on `documents.summary`. Populated at upload time from the output of `extract_text_from_file()`.

Existing documents will be backfilled via a one-time script (`scripts/backfill_document_chunks.py`) that re-runs extraction and chunking for all documents missing `extracted_text`.

### 2. `services/chunker.py` — document chunker

Single public function:

```python
def chunk_document(text: str) -> list[str]:
    ...
```

**Algorithm:**
1. Split on `\n\n` (double newlines) — Docling's markdown output uses these as logical block boundaries regardless of document type (slides, prose, tables, lists)
2. Merge any chunk under 50 words with its neighbor
3. Split any chunk over 400 words at the nearest sentence boundary (`. ` or `\n`)
4. Return list of chunk strings

Target per chunk: 50–400 words. No document-type detection, no keyword patterns.

### 3. `services/rag_service.py` — embedding task type fix + index function

**Bug fix:** `gemini-embedding-001` has distinct task types that measurably improve retrieval quality:
- `RETRIEVAL_DOCUMENT` — used when embedding chunks at index time
- `RETRIEVAL_QUERY` — used when embedding the student's question at retrieval time

Currently neither is set. Fix both.

**New function:**

```python
def index_document_chunks(
    course_code: str,
    doc_id: str,
    uploader_id: str,
    chunks: list[str],
) -> int:
    """Embed and upsert chunks to course_chunks. Returns count upserted."""
```

Each chunk gets:
- `id` — SHA-256 of `f"{doc_id}:{chunk_index}"`
- `course_id` — BU course code (e.g. `"CAS CS 330"`)
- `category` — `"document"`
- `chunk_text` — raw chunk text
- `embedding` — 768-dim vector via `gemini-embedding-001`
- `doc_id` — foreign key to documents row
- `uploader_id` — for attribution

Upserted with `resolution=merge-duplicates` — re-uploading the same document is idempotent.

### 4. `routes/documents.py` — hook into upload pipeline

In `upload_document` (POST `/api/documents/upload`), after text extraction:

```python
extracted_text = extract_text_from_file(file_bytes, filename, content_type)

# Store raw text on the document row
table("documents").update({"extracted_text": encrypt_if_present(extracted_text)}, ...)

# Chunk and index after classification (bu_code resolved from offering)
chunks = chunk_document(extracted_text)
index_document_chunks(bu_code, doc_id, user_id, chunks)
```

`bu_code` is resolved via `offering_course_id(offering_id)` → `_get_course_info()` — the same chain used in the chat route.

`_process_document` is **not changed** — it still truncates to 12,000 chars for its classify/summarize call. Chunking uses the full `extracted_text`.

---

## Retrieval — no changes needed

`retrieve_chunks(query, course_id=bu_code, k=5)` filters by `course_id`. Once document chunks are in `course_chunks` with the correct `course_id`, they are returned alongside catalog chunks automatically. The `min_similarity=0.55` threshold applies to both.

The `_get_catalog_chunk` path (always-injected course info) is unchanged.

---

## Sharing scope

Chunks are stored with `course_id = bu_code` (e.g. `"CAS CS 330"`), not by offering or section. Any student enrolled in any section of CAS CS 330 benefits from documents uploaded by any other CAS CS 330 student — across all tutor sessions, quiz generation, and study guides.

---

## Backfill script

`scripts/backfill_document_chunks.py`:
- Queries all documents missing `extracted_text`
- Re-downloads file bytes from Supabase Storage
- Runs `extract_text_from_file()`, stores `extracted_text`
- Runs `chunk_document()` + `index_document_chunks()`
- Logs per-document success/failure

Run once against staging, then production, after migration 0029 is applied.

---

## Benchmark additions

Add document-retrieval test cases to `scripts/benchmark_rag.py`:
- Upload a known test document to a staging course
- Assert that specific content from the document is retrieved for relevant queries
- Measure retrieval accuracy before/after the `task_type` fix

---

## What this does NOT include (future work)

- **Description enhancement for sparse slides** — generating a Gemini description for slides with < 80 words. Benchmarks will show if this is needed.
- **Parent-child chunking** — storing both a small child chunk (for embedding precision) and a larger parent chunk (for LLM context). Worth revisiting if retrieval precision is low.
- **Query rewriting / HyDE** — rewriting the student's question into a hypothetical answer before embedding. Measurably improves recall for conversational queries.

---

## Files changed

| File | Change |
|---|---|
| `backend/db/migrations/0029_documents_extracted_text.sql` | New — add `extracted_text` column |
| `backend/services/chunker.py` | New — `chunk_document()` |
| `backend/services/rag_service.py` | Modify — fix `task_type`, add `index_document_chunks()` |
| `backend/routes/documents.py` | Modify — store `extracted_text`, call chunker at upload |
| `backend/scripts/backfill_document_chunks.py` | New — one-time backfill |
| `backend/scripts/benchmark_rag.py` | Modify — add document retrieval test cases |
